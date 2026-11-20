import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { projectSettings } from './fixtures/project-settings.mjs';
import { spawnSync } from 'node:child_process';

const here = dirname(fileURLToPath(import.meta.url));
const settings = projectSettings();
function run(command, value, digest) {
  const dir = mkdtempSync(join(tmpdir(), 'huntr-record-'));
  try {
    const input = join(dir, 'record.json');
    writeFileSync(input, JSON.stringify(value));
    const r = spawnSync(process.execPath, [join(here, 'manifest.mjs'), command, input,
      ...(digest === undefined ? [] : [digest])], {encoding: 'utf8'});
    assert.ifError(r.error);
    return r;
  } finally { rmSync(dir, {recursive: true, force: true}); }
}
function ok(command, value, digest) {
  const r = run(command, value, digest);
  assert.equal(r.status, 0, r.stderr);
  return JSON.parse(r.stdout);
}
const small = {run: 'synthetic-r1', slices: [], gaps: []};
const large = {...small, note: 'quoted "text"\nλ😺'.repeat(10000)};

test('R1 one small record uses one bounded part and a large record round-trips all numbered parts', () => {
  assert.equal(ok('pack', small).comments.length, 1);
  const packed = ok('pack', large);
  assert.equal(packed.comments.length, 6);
  assert.match(packed.sha256, /^[a-f0-9]{64}$/);
  for (const [i, body] of packed.comments.entries()) {
    assert.ok(Buffer.byteLength(body) <= 65536);
    assert.ok(body.startsWith(`Hunt record part ${i + 1}/6\n`));
  }
  // Transport read-back may arrive in a different order; every numbered part is required.
  assert.deepEqual(ok('unpack', packed.comments.toReversed(), packed.sha256), large);
});
function changePart(body, edit) {
  return body.replace(/\n(\{.*\})\n```$/, (_match, raw) => '\n' + JSON.stringify(edit(JSON.parse(raw))) + '\n```');
}
for (const problem of ['missing', 'duplicate', 'truncated', 'changed', 'wrong-root', 'bad-number', 'extra-key']) {
  test(`R1 read-back refuses ${problem} parts`, () => {
    const packed = ok('pack', large), parts = [...packed.comments];
    let expected = packed.sha256;
    if (problem === 'missing') parts.pop();
    if (problem === 'duplicate') parts[1] = parts[0];
    if (problem === 'truncated') parts[0] = parts[0].slice(0, -1);
    if (problem === 'changed') parts[0] = changePart(parts[0], p => {
      // Preserve valid JSON and all transport metadata: only the digest can catch this edit.
      const data = Buffer.from(p.data, 'base64');
      data.write('synthetic-r2', data.indexOf('synthetic-r1'));
      return {...p, data: data.toString('base64')};
    });
    if (problem === 'wrong-root') expected = '0'.repeat(64);
    if (problem === 'bad-number') parts[0] = changePart(parts[0], p => ({...p, part: 2}));
    if (problem === 'extra-key') parts[0] = changePart(parts[0], p => ({...p, extra: true}));
    const r = run('unpack', parts, expected);
    assert.equal(r.status, 2, problem); assert.equal(r.stdout, '', problem);
  });
}
test('R1 the operative handoff requires bounded indexed parts and read-back before archival', () => {
  const section = readFileSync(settings, 'utf8').split('## Slice manifests (#696)\n')[1]?.split('\n## ')[0] ?? '';
  assert.match(section, /65,536/);
  assert.match(section, /pack .*run-record\.json/);
  assert.match(section, /unpack .*readback\.json/);
  assert.match(section, /index.*links/i);
  const finish = readFileSync(join(here, '../SKILL.md'), 'utf8').split('## 5. Record the result and finish this hunt\n')[1];
  assert.match(finish, /read back.*every.*part/i);
});

// #959, corrected by #1740: the verified #394 record is the only report channel.
// Verify every part and index before delivery is complete and the controller archives.
function finishRecord(finish) {
  const sentences = finish.split(/(?<=\.)\s+/);
  const summary = sentences.find(s => s.startsWith('Include **found, approved, proposed, skipped**'));
  assert.match(summary ?? '', /each with counts and tracker links/, 'record includes counts and links');
  const readBack = sentences.findIndex(s => /read back\*\* every #394 part and index/i.test(s));
  assert.match(sentences[readBack] ?? '', /use `unpack` with the planned digest to verify all numbered parts/,
    'read-back verifies all numbered parts with the planned digest');
  const delivery = sentences.findIndex(s => s.startsWith('Once that record is verified, delivery is complete: **#394 is the only report channel** to the orchestrator'));
  assert.ok(delivery >= 0, '#394 alone completes delivery after verification');
  assert.match(finish, /Do not send direct thread messages or attempt a second delivery/,
    'direct messages and second delivery are forbidden');
  assert.doesNotMatch(finish, /send the orchestrator a short note|room-cli thread tell/i,
    'no direct orchestrator delivery');
  const archive = sentences.findIndex(s => s.includes('room-cli thread archive --self'));
  assert.ok(readBack >= 0 && archive >= 0, 'read-back and archive sentences present');
  assert.ok(readBack < delivery && delivery < archive, 'verification precedes delivery completion and archival');
}
const step5 = () => readFileSync(join(here, '../SKILL.md'), 'utf8')
  .split('## 5. Record the result and finish this hunt\n')[1].split('\n**Night setting:**')[0];
test('#959 step 5 sends its report only through the verified #394 record before archival', () => {
  finishRecord(step5());
});
const summaryLine = 'Include **found, approved, proposed, skipped**, each with counts and tracker links.';
const readBackLine = 'Then **read back** every #394 part and index, use `unpack` with the planned digest to verify all numbered parts.';
const deliveryLine = 'Once that record is verified, delivery is complete: **#394 is the only report channel** to the orchestrator, including partial results, final results, tier-0 audits, proposals and blockers.';
const noDirectLine = 'Do not send direct thread messages or attempt a second delivery.';
const archiveLine = 'Run `room-cli thread archive --self` as the final action.';
const validPolicy = `${summaryLine} ${readBackLine} ${deliveryLine} ${noDirectLine} ${archiveLine}`;
for (const [name, text, reason] of [
  ['direct note instead of #394-only delivery', `${summaryLine} ${readBackLine} Send the orchestrator a short note naming the verified #394 record. ${noDirectLine} ${archiveLine}`,
    '#394 alone completes delivery after verification'],
  ['direct thread command added', `${validPolicy} Run \`room-cli thread tell synthetic-orchestrator report\`.`,
    'no direct orchestrator delivery'],
  ['direct note added', `${validPolicy} Send the orchestrator a short note naming the verified #394 record.`,
    'no direct orchestrator delivery'],
  ['archival before verification', `${summaryLine} ${archiveLine} ${readBackLine} ${deliveryLine} ${noDirectLine}`,
    'verification precedes delivery completion and archival'],
  ['delivery before read-back', `${summaryLine} ${deliveryLine} ${readBackLine} ${noDirectLine} ${archiveLine}`,
    'verification precedes delivery completion and archival'],
  ['read-back without digest verification', validPolicy.replace(', use `unpack` with the planned digest to verify all numbered parts', ''),
    'read-back verifies all numbered parts with the planned digest'],
  ['record without counts', validPolicy.replace('counts and ', ''),
    'record includes counts and links'],
]) {
  test(`#959 the record check refuses ${name}`, () => {
    assert.throws(() => finishRecord(text), error => error.code === 'ERR_ASSERTION' && error.message.startsWith(reason));
  });
}
test('#959 the record check accepts #394-only delivery after verification and before archival', () => {
  finishRecord(validPolicy);
});
