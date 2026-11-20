#!/usr/bin/env node
// Read-only slice evidence. The controller persists stdout in its durable hunt record.
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';

const fail = reason => { throw new Error(reason); };
const kinds = ['source', 'test', 'policy'];
const hash = value => typeof value === 'string' && /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(value);
const text = value => typeof value === 'string' && value.trim().length > 0;
const sha256 = value => createHash('sha256').update(value).digest('hex');
const digest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const checker = sha256(readFileSync(new URL(import.meta.url)));
function exact(value, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      !isDeepStrictEqual(Object.keys(value).sort(), [...keys].sort())) fail('invalid record shape');
}
const read = path => json(readFileSync(path, 'utf8'));
function json(raw) {
  const value = JSON.parse(raw);
  // Same duplicate-key rejection as the approval gate; JSON.parse checks grammar first.
  const stack = [];
  for (const token of raw.match(/"(?:[^"\\]|\\.)*"|[{}\[\],:]|[^\s{}\[\],:]+/g) ?? []) {
    if (token === '{') stack.push({keys: new Set(), key: true});
    else if (token === '[') stack.push(null);
    else if (token === '}' || token === ']') stack.pop();
    else if (token === ',') { if (stack.at(-1)) stack.at(-1).key = true; }
    else if (token === ':') { if (stack.at(-1)) stack.at(-1).key = false; }
    else if (token.startsWith('"') && stack.at(-1)?.key) {
      const key = JSON.parse(token), frame = stack.at(-1);
      if (frame.keys.has(key)) fail('duplicate JSON key');
      frame.keys.add(key);
    }
  }
  return value;
}
function plan(value) {
  exact(value, ['slice', 'source_only', 'questions', 'paths']);
  if (!text(value.slice) || !text(value.questions) || typeof value.source_only !== 'boolean') fail('invalid slice plan');
  exact(value.paths, kinds);
  for (const kind of kinds) {
    const paths = value.paths[kind];
    if (!Array.isArray(paths) || !paths.length || new Set(paths).size !== paths.length) fail('invalid input paths');
    for (const path of paths) {
      if (typeof path !== 'string' || !/^[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*\/?$/.test(path) ||
          path.replace(/\/$/, '').split('/').some(p => p === '.' || p === '..')) fail('invalid input path');
    }
  }
}
function result(value) {
  exact(value, ['status', 'findings', 'gaps']);
  if (!['PASS', 'ISSUES', 'BLOCKED'].includes(value.status) ||
      !Array.isArray(value.findings) || !value.findings.every(text) ||
      !Array.isArray(value.gaps) || !value.gaps.every(text)) fail('invalid slice result');
}
function record(value) {
  exact(value, ['version', 'checker', 'base', 'plan', 'files_sha256', 'result']);
  if (value.version !== 2 || !hash(value.base) || !hash(value.checker) || !digest(value.files_sha256)) fail('invalid manifest version/hash');
  plan(value.plan);
  if (value.result !== null) result(value.result);
}
function git(...args) {
  return execFileSync('git', ['--no-optional-locks', ...args], {encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
    maxBuffer: 64 * 1024 * 1024, timeout: 60000});
}
function snapshot(input) {
  plan(input);
  if (git('rev-parse', '--show-prefix').trim()) fail('run from the consuming repository root');
  const base = git('rev-parse', '--verify', 'HEAD^{commit}').trim();
  if (git('status', '--porcelain=v1', '--untracked-files=all', '--ignore-submodules=none').length) fail('dirty checkout');
  const tree = git('ls-tree', '-rz', '--full-tree', base).split('\0').filter(Boolean).map(line => {
    const tab = line.indexOf('\t');
    const [mode, type, blob] = line.slice(0, tab).split(' ');
    if (tab < 0 || !hash(blob)) fail('unreadable Git tree');
    return {mode, type, blob, path: line.slice(tab + 1)};
  });
  const files = [];
  for (const kind of kinds) {
    const selected = new Map();
    for (const path of input.paths[kind]) {
      const indexed = git('ls-files', '-v', '-z', '--', path).split('\0').filter(Boolean);
      if (indexed.some(entry => !entry.startsWith('H '))) fail('input has nonstandard Git index flags');
      if (path.endsWith('/') && git('ls-files', '-o', '-i', '--exclude-standard', '-z', '--', path).length)
        fail('ignored input file');
      const matches = tree.filter(f => path.endsWith('/') ? f.path.startsWith(path) : f.path === path);
      if (!matches.length) fail('missing input path');
      for (const file of matches) {
        if (file.type !== 'blob' || !['100644', '100755'].includes(file.mode)) fail('input is not a regular file');
        selected.set(file.path, {kind, path: file.path, blob: file.blob, mode: file.mode});
      }
    }
    files.push(...[...selected.values()].sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  }
  // Canonical UTF-8 JSON: source/test/policy order, paths sorted within each kind,
  // entry keys in kind/path/blob/mode order, no extra whitespace.
  return {version: 2, checker, base, plan: input, files_sha256: sha256(JSON.stringify(files)), result: null};
}
function check(input, previousPath) {
  try {
    const current = snapshot(input), previous = read(previousPath);
    record(previous);
    if (!current.plan.source_only || !previous.plan.source_only) return {decision: 'run', reason: 'dynamic slice'};
    if (previous.result?.status !== 'PASS' || previous.result.findings.length || previous.result.gaps.length)
      return {decision: 'run', reason: 'no completed clean PASS'};
    if (current.checker !== previous.checker || !isDeepStrictEqual(current.plan, previous.plan) ||
        current.files_sha256 !== previous.files_sha256) return {decision: 'run', reason: 'changed manifest'};
    return {decision: 'skip', reason: 'unchanged clean PASS'};
  } catch {
    return {decision: 'run', reason: 'unreadable manifest or checkout; record the gap'};
  }
}
// Prepare bounded issue comments without writing to GitHub. Base64 keeps each
// part ASCII and preserves Unicode, quotes and JSON boundaries across parts.
function pack(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail('hunt record must be an object');
  const raw = JSON.stringify(value), sum = sha256(raw);
  const chunks = Buffer.from(raw).toString('base64').match(/.{1,60000}/g);
  const comments = chunks.map((data, i) => {
    const part = i + 1, total = chunks.length;
    const body = `Hunt record part ${part}/${total}\n\n\`\`\`json\n` +
      JSON.stringify({version: 1, sha256: sum, part, total, data}) + '\n```';
    if (Buffer.byteLength(body) > 65536) fail('record part exceeds comment capacity');
    return body;
  });
  return {sha256: sum, comments};
}
function unpack(bodies, expected) {
  if (!digest(expected) || !Array.isArray(bodies) || !bodies.length) fail('missing read-back or expected digest');
  const parts = new Map();
  for (const body of bodies) {
    if (typeof body !== 'string' || Buffer.byteLength(body) > 65536) fail('invalid read-back body');
    const match = body.match(/^Hunt record part ([1-9][0-9]*)\/([1-9][0-9]*)\n\n```json\n([^\n]+)\n```$/);
    if (!match) fail('unreadable record part');
    const value = json(match[3]);
    exact(value, ['version', 'sha256', 'part', 'total', 'data']);
    if (value.version !== 1 || value.sha256 !== expected || value.total !== bodies.length ||
        !Number.isSafeInteger(value.part) || value.part < 1 || value.part > value.total ||
        String(value.part) !== match[1] || String(value.total) !== match[2] || parts.has(value.part) ||
        typeof value.data !== 'string' || !value.data.length ||
        Buffer.from(value.data, 'base64').toString('base64') !== value.data) fail('incomplete or inconsistent record parts');
    parts.set(value.part, value.data);
  }
  const data = [...parts.entries()].sort((a, b) => a[0] - b[0]).map(([, value]) => value).join('');
  const raw = Buffer.from(data, 'base64');
  if (raw.toString('base64') !== data || sha256(raw) !== expected) fail('record read-back digest mismatch');
  return json(raw.toString('utf8'));
}
try {
  const [command, first, second, ...extra] = process.argv.slice(2);
  if (extra.length || !first || !['snapshot', 'complete', 'check', 'pack', 'unpack'].includes(command) ||
      (['snapshot', 'pack'].includes(command) ? second !== undefined : !second))
    fail('usage: manifest.mjs snapshot PLAN | complete SNAPSHOT RESULT | check PLAN PREVIOUS | pack RECORD | unpack READBACK EXPECTED-SHA256');
  let output;
  if (command === 'snapshot') output = snapshot(read(first));
  if (command === 'complete') {
    const initial = read(first), final = read(second);
    record(initial); result(final);
    if (initial.result !== null || !isDeepStrictEqual(initial, snapshot(initial.plan))) fail('slice inputs/base changed; rerun before completing');
    output = {...initial, result: final};
  }
  if (command === 'check') output = check(read(first), second);
  if (command === 'pack') output = pack(read(first));
  if (command === 'unpack') output = unpack(read(first), second);
  process.stdout.write(JSON.stringify(output) + '\n');
} catch (error) {
  process.stderr.write(`huntr manifest: ${error.message}\n`);
  process.exitCode = 2;
}
