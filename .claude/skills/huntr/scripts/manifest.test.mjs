import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, existsSync, chmodSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync, spawnSync } from 'node:child_process';

const here = dirname(fileURLToPath(import.meta.url));
const script = join(here, 'manifest.mjs');
function fixture(fn) {
  const dir = mkdtempSync(join(tmpdir(), 'huntr-manifest-'));
  const repo = join(dir, 'repo');
  mkdirSync(repo);
  const git = (...args) => execFileSync('git', ['-c', 'core.hooksPath=/dev/null',
    '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', ...args],
  {cwd: repo, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']}).trim();
  const write = (path, text) => {
    mkdirSync(dirname(join(repo, path)), {recursive: true});
    writeFileSync(join(repo, path), text);
  };
  const commit = () => { git('add', '.'); git('commit', '-qm', 'synthetic fixture'); };
  const plan = {slice: 'core/correctness', source_only: true, questions: 'Check synthetic bounds with fixture tests.',
    paths: {source: ['src/'], test: ['tests/'], policy: ['AGENTS.md']}};
  function run(command, ...values) {
    const paths = values.map((v, i) => {
      const path = join(dir, `input-${i}.json`);
      writeFileSync(path, typeof v === 'string' ? v : JSON.stringify(v));
      return path;
    });
    const r = spawnSync(process.execPath, [script, command, ...paths], {cwd: repo, encoding: 'utf8'});
    assert.ifError(r.error);
    return r;
  }
  const ok = (command, ...values) => {
    const r = run(command, ...values);
    assert.equal(r.status, 0, r.stderr);
    return JSON.parse(r.stdout);
  };
  const pass = {status: 'PASS', findings: [], gaps: []};
  try {
    git('init', '-q', '--object-format=sha1');
    write('src/ops.rs', 'synthetic source\n');
    write('tests/ops.rs', 'synthetic test\n');
    write('AGENTS.md', 'synthetic policy\n');
    commit();
    fn({dir, repo, git, write, commit, plan, run, ok, pass});
  } finally { rmSync(dir, {recursive: true, force: true}); }
}

test('unchanged completed clean PASS skips, including after an unrelated commit', () => fixture(f => {
  const snapshot = f.ok('snapshot', f.plan);
  assert.equal(snapshot.base, f.git('rev-parse', 'HEAD'));
  // Worked independently from the three literal Git blob payloads and canonical JSON.
  assert.equal(snapshot.files_sha256, '683b15dfd02fcb8a0ba6708d2e7ebfb6d71fef5b15459d6086e3f5f4813f511d');
  const previous = f.ok('complete', snapshot, f.pass);
  assert.deepEqual(previous.result, f.pass);
  assert.equal(f.ok('check', f.plan, previous).decision, 'skip');
  f.write('unrelated.md', 'unrelated\n'); f.commit();
  assert.equal(f.ok('check', f.plan, previous).decision, 'skip');
  assert.equal(f.git('status', '--porcelain'), '', 'checks must not write state');
}));

test('a different checker version runs again', () => fixture(f => {
  const previous = f.ok('complete', f.ok('snapshot', f.plan), f.pass);
  assert.equal(f.ok('check', f.plan, previous).decision, 'skip');
  // Flip only the first hex digit: still a valid 64-hex digest, never the stored one.
  const other = (previous.checker[0] === 'a' ? 'b' : 'a') + previous.checker.slice(1);
  assert.match(other, /^[a-f0-9]{64}$/); assert.notEqual(other, previous.checker);
  assert.equal(f.ok('check', f.plan, {...previous, checker: other}).decision, 'run');
}));

for (const path of ['src/ops.rs', 'tests/ops.rs', 'AGENTS.md']) {
  test(`a changed manifested file runs again: ${path}`, () => fixture(f => {
    const previous = f.ok('complete', f.ok('snapshot', f.plan), f.pass);
    f.write(path, 'changed synthetic input\n'); f.commit();
    assert.equal(f.ok('check', f.plan, previous).decision, 'run');
  }));
}
test('R1 thousands of files keep a complete durable manifest compact', () => fixture(f => {
  for (let i = 0; i < 2000; i++) f.write(`src/synthetic_module_${i}.rs`, `synthetic ${i}\n`);
  f.commit();
  const previous = f.ok('complete', f.ok('snapshot', f.plan), f.pass);
  const bytes = Buffer.byteLength(JSON.stringify(previous));
  assert.ok(bytes < 4096, `durable manifest is ${bytes} bytes; it must not grow with the file list`);
  assert.equal(Object.hasOwn(previous, 'files'), false);
  assert.match(previous.files_sha256, /^[a-f0-9]{64}$/);
  assert.equal(f.ok('check', f.plan, previous).decision, 'skip');
  f.write('src/synthetic_module_1999.rs', 'changed\n'); f.commit();
  assert.equal(f.ok('check', f.plan, previous).decision, 'run');
}));
test('an executable-mode change runs again even when its blob is identical', () => fixture(f => {
  const previous = f.ok('complete', f.ok('snapshot', f.plan), f.pass);
  const blob = f.git('rev-parse', 'HEAD:src/ops.rs');
  chmodSync(join(f.repo, 'src/ops.rs'), 0o755); f.commit();
  assert.equal(f.git('rev-parse', 'HEAD:src/ops.rs'), blob);
  assert.equal(f.ok('check', f.plan, previous).decision, 'run');
}));
for (const mutation of ['add', 'delete', 'scope', 'questions', 'slice']) {
  test(`changed coverage runs again: ${mutation}`, () => fixture(f => {
    const previous = f.ok('complete', f.ok('snapshot', f.plan), f.pass);
    if (mutation === 'add') { f.write('src/new.rs', 'new\n'); f.commit(); }
    if (mutation === 'delete') { rmSync(join(f.repo, 'src/ops.rs')); f.commit(); }
    if (mutation === 'scope') f.plan.paths.source = ['src/ops.rs'];
    if (mutation === 'questions') f.plan.questions = 'Check different bounds.';
    if (mutation === 'slice') f.plan.slice = 'core/size';
    assert.equal(f.ok('check', f.plan, previous).decision, 'run');
  }));
}
for (const result of [null, {status: 'ISSUES', findings: ['synthetic defect'], gaps: []},
  {status: 'BLOCKED', findings: [], gaps: ['unreadable source']},
  {status: 'PASS', findings: ['unresolved candidate'], gaps: []},
  {status: 'PASS', findings: [], gaps: ['missing test read']}]) {
  test(`only a clean completed PASS skips: ${JSON.stringify(result)}`, () => fixture(f => {
    const snapshot = f.ok('snapshot', f.plan);
    const previous = result ? f.ok('complete', snapshot, result) : snapshot;
    assert.equal(f.ok('check', f.plan, previous).decision, 'run');
  }));
}
test('dynamic monitoring is recorded but never skipped', () => fixture(f => {
  f.plan.source_only = false;
  const previous = f.ok('complete', f.ok('snapshot', f.plan), f.pass);
  assert.equal(f.ok('check', f.plan, previous).decision, 'run');
}));
test('dirty tracked and untracked inputs cannot complete or skip', () => fixture(f => {
  const snapshot = f.ok('snapshot', f.plan);
  const previous = f.ok('complete', snapshot, f.pass);
  for (const path of ['src/ops.rs', 'src/new.rs']) {
    f.write(path, 'dirty\n');
    assert.equal(f.ok('check', f.plan, previous).decision, 'run');
    const r = f.run('complete', snapshot, f.pass);
    assert.equal(r.status, 2); assert.equal(r.stdout, ''); assert.match(r.stderr, /dirty/);
    f.git('restore', 'src/ops.rs');
  }
}));
function refusesHiddenInputs(f, snapshot, previous, reason) {
  assert.equal(f.git('status', '--porcelain'), '', 'ordinary status misses the hidden input');
  assert.deepEqual(f.ok('check', f.plan, previous),
    {decision: 'run', reason: 'unreadable manifest or checkout; record the gap'});
  for (const [command, values] of [['snapshot', [f.plan]], ['complete', [snapshot, f.pass]]]) {
    const r = f.run(command, ...values);
    assert.equal(r.status, 2, `${command} must refuse hidden inputs`);
    assert.equal(r.stdout, ''); assert.match(r.stderr, reason);
  }
}
for (const flags of [['--skip-worktree'], ['--assume-unchanged'], ['--skip-worktree', '--assume-unchanged']]) {
  for (const path of ['src/ops.rs', 'tests/ops.rs', 'AGENTS.md']) {
    for (const changed of [false, true]) {
      test(`index flags refuse reuse: ${flags.join(' ')} ${path}, changed=${changed}`, () => fixture(f => {
        const snapshot = f.ok('snapshot', f.plan);
        const previous = f.ok('complete', snapshot, f.pass);
        for (const flag of flags) f.git('update-index', flag, '--', path);
        if (changed) f.write(path, 'hidden synthetic change\n');
        refusesHiddenInputs(f, snapshot, previous, /index flags/);
      }));
    }
  }
}
for (const path of ['src/generated.rs', 'src/cache/deep/generated.rs', 'tests/generated.rs', 'rules/generated.md']) {
  test(`ignored directory inputs refuse reuse: ${path}`, () => fixture(f => {
    f.write('rules/policy.md', 'synthetic directory policy\n');
    f.plan.paths.policy = ['rules/'];
    f.write('.gitignore', path.includes('/cache/') ? 'src/cache/\n' : `${path}\n`);
    f.commit();
    const snapshot = f.ok('snapshot', f.plan);
    const previous = f.ok('complete', snapshot, f.pass);
    f.write(path, 'ignored synthetic input\n');
    refusesHiddenInputs(f, snapshot, previous, /ignored input/);
  }));
}
test('hidden files outside the named inputs do not prevent reuse', () => fixture(f => {
  f.plan.paths.source = ['src/ops.rs'];
  f.write('src/outside.rs', 'synthetic sibling\n');
  f.write('.gitignore', 'src/generated.rs\noutside/\n');
  f.commit();
  const snapshot = f.ok('snapshot', f.plan);
  const previous = f.ok('complete', snapshot, f.pass);
  f.git('update-index', '--skip-worktree', '--', 'src/outside.rs');
  f.write('src/outside.rs', 'hidden unrelated change\n');
  f.write('src/generated.rs', 'ignored sibling of an exact file input\n');
  f.write('outside/generated.rs', 'ignored unrelated input\n');
  assert.equal(f.git('status', '--porcelain'), '');
  assert.deepEqual(f.ok('snapshot', f.plan), snapshot);
  assert.deepEqual(f.ok('complete', snapshot, f.pass), previous);
  assert.equal(f.ok('check', f.plan, previous).decision, 'skip');
}));
test('completion refuses a changed base instead of caching unread changes', () => fixture(f => {
  const snapshot = f.ok('snapshot', f.plan);
  f.write('src/ops.rs', 'changed\n'); f.commit();
  const r = f.run('complete', snapshot, f.pass);
  assert.equal(r.status, 2); assert.equal(r.stdout, ''); assert.match(r.stderr, /changed/);
}));
test('missing, malformed, duplicate-key and incomplete previous records run again', () => fixture(f => {
  const previous = f.ok('complete', f.ok('snapshot', f.plan), f.pass);
  const broken = structuredClone(previous); delete broken.files_sha256;
  for (const value of ['{', 'null', '[]', '{"version":1,"version":1}', broken,
    JSON.stringify(previous).replace('"status":"PASS"', '"status":"ISSUES","status":"PASS"'),
    {...previous, version: 99}, {...previous, files_sha256: '0'.repeat(64)},
    {...previous, files_sha256: '0'.repeat(40)}, {...previous, files_sha256: {sha256: '0'.repeat(64)}},
    {...previous, result: {status: {PASS: null}, findings: [], gaps: []}}]) {
    assert.equal(f.ok('check', f.plan, value).decision, 'run');
  }
  const r = spawnSync(process.execPath, [script, 'check', join(f.dir, 'input-0.json'), join(f.dir, 'missing.json')],
    {cwd: f.repo, encoding: 'utf8'});
  assert.equal(r.status, 0, r.stderr); assert.equal(JSON.parse(r.stdout).decision, 'run');
}));
test('invalid plans and non-files never become reusable coverage', () => fixture(f => {
  for (const source of [[], ['../AGENTS.md'], ['/tmp/source'], ['src//ops.rs'], ['src/*'], ['missing.rs'],
    ['src/ops.rs', 'src/ops.rs']]) {
    const plan = structuredClone(f.plan); plan.paths.source = source;
    const r = f.run('snapshot', plan);
    assert.equal(r.status, 2, JSON.stringify(source)); assert.equal(r.stdout, '');
  }
  f.git('update-index', '--add', '--cacheinfo', '120000', f.git('hash-object', 'AGENTS.md'), 'src/link');
  f.git('commit', '-qm', 'synthetic link');
  // A selected symlink is refused even on a clean checkout.
  f.git('checkout-index', '-f', '--', 'src/link');
  assert.equal(f.run('snapshot', f.plan).status, 2);
  assert.equal(existsSync(join(f.repo, 'manifest.json')), false);
}));
test('finish instructions persist and read back #394 before archiving the controller', () => {
  const skill = readFileSync(join(here, '../SKILL.md'), 'utf8');
  const finish = skill.split('## 5. Record the result and finish this hunt\n')[1]?.split('\n## ')[0] ?? '';
  assert.match(finish, /#394/);
  assert.match(finish, /read back/i);
  assert.match(finish, /room-cli thread archive --self/);
  assert.match(finish, /off.*paused.*blocked/i);
  assert.ok(finish.indexOf('#394') < finish.indexOf('room-cli thread archive --self'));
});
