// #1685: one controller by a lease on #394, hunters that provision themselves or say why
// in one line, and a dry run of a whole hunt on a fake GitHub and a fake hunter set.
// Synthetic only: the fake gh in fixtures/gh-switch.mjs, local Git repositories, no network.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, symlinkSync, rmSync, existsSync, accessSync, constants } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { projectSettings } from './fixtures/project-settings.mjs';
import { spawnSync, execFileSync } from 'node:child_process';

const here = dirname(fileURLToPath(import.meta.url));
const settings = projectSettings();
const lease = join(here, 'lease.mjs');
const hunters = join(here, 'hunters.mjs');
const provision = join(here, 'provision.sh');
const MIN = 60000;
const at = minutes => new Date(Math.floor(Date.now() / 1000) * 1000 + minutes * MIN).toISOString().replace(/\.\d{3}Z$/, 'Z');
const claimLine = run => `huntr lease: claim ${run} for 45m`;

function world(comments = [], extra = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'huntr-controller-'));
  mkdirSync(join(dir, 'bin'));
  mkdirSync(join(dir, 'docs/agents'), {recursive: true});
  // A fake gh that cannot run would let the real one answer: refuse before any call.
  accessSync(join(here, 'fixtures/gh-switch.mjs'), constants.X_OK);
  symlinkSync(join(here, 'fixtures/gh-switch.mjs'), join(dir, 'bin/gh'));
  // The lease reads the switch issue from the project's huntr settings, as the gate does.
  writeFileSync(join(dir, 'docs/agents/huntr.md'), readFileSync(settings, 'utf8'));
  const env = {...process.env, GH_REPO: 'synthetic/project', PATH: join(dir, 'bin') + ':' + process.env.PATH,
    HUNTR_FAKE_STATE: join(dir, 'state.json'), HUNTR_FAKE_LOG: join(dir, 'log'), HUNTR_FAKE_ORIGIN: join(dir, 'origin.git')};
  for (const k of ['GH_TOKEN', 'GITHUB_TOKEN', 'GH_HOST', 'GH_ENTERPRISE_TOKEN', 'ROOM_THREAD_ID', 'CODEX_THREAD_ID']) delete env[k];
  const w = {
    dir, env,
    state: {comments: comments.map((c, i) => ({id: 100 + i, ...c})), ...extra},
    run(file, args) {
      writeFileSync(env.HUNTR_FAKE_STATE, JSON.stringify(w.state));
      const r = spawnSync(file.endsWith('.sh') ? 'sh' : process.execPath, [file, ...args], {cwd: dir, env, encoding: 'utf8'});
      assert.ifError(r.error);
      w.state = JSON.parse(readFileSync(env.HUNTR_FAKE_STATE, 'utf8'));
      return r;
    },
    calls: () => existsSync(env.HUNTR_FAKE_LOG) ? readFileSync(env.HUNTR_FAKE_LOG, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : [],
    posts: () => w.calls().filter(c => c[0] === 'issue'),
    file(name, text) { writeFileSync(join(dir, name), text); return join(dir, name); },
    close: () => rmSync(dir, {recursive: true, force: true}),
    // Let `minutes` pass: every recorded comment time moves into the past, the local clock stays real.
    advance(minutes) {
      for (const c of w.state.comments) c.created_at = new Date(Date.parse(c.created_at) - minutes * MIN).toISOString().replace(/\.\d{3}Z$/, 'Z');
    },
  };
  return w;
}
const scenario = (name, fn) => test(name, () => { const w = world(); try { fn(w); } finally { w.close(); } });
const on = {created_at: at(-120), body: 'huntr: on'};

// The controller lease (item 1): post, read back, expire; never a thread listing.
scenario('L1 a claim posts one lease comment, reads it back and holds the lease for 45 minutes', w => {
  w.state.comments = [{id: 100, ...on}];
  const r = w.run(lease, ['claim', 'night-r1']);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(w.posts().length, 1);
  const mine = w.state.comments.at(-1);
  assert.equal(mine.body, claimLine('night-r1'));
  const out = JSON.parse(r.stdout);
  assert.deepEqual(out, {holder: {run: 'night-r1', since: mine.created_at,
    expires: new Date(Date.parse(mine.created_at) + 45 * MIN).toISOString().replace(/\.\d{3}Z$/, 'Z'), comment: mine.id}});
  assert.ok(!w.calls().some(c => c.includes('thread')), 'no thread listing');
});
scenario('L2 a live lease refuses a second controller before it posts anything', w => {
  w.state.comments = [{id: 100, ...on}, {id: 101, created_at: at(-10), body: claimLine('night-r1')}];
  const r = w.run(lease, ['claim', 'night-r2']);
  assert.equal(r.status, 2);
  assert.equal(r.stdout, '');
  assert.match(r.stderr, /held by night-r1 until /);
  assert.deepEqual(w.posts(), []);
});
scenario('L3 two claims posted together: the earlier comment holds, the later controller exits 2', w => {
  w.state.comments = [{id: 100, ...on}];
  w.state.race = claimLine('night-r9');
  const r = w.run(lease, ['claim', 'night-r2']);
  assert.equal(r.status, 2);
  assert.equal(r.stdout, '');
  assert.match(r.stderr, /lost to night-r9/);
  assert.equal(JSON.parse(w.run(lease, ['status']).stdout).holder.run, 'night-r9');
});
scenario('L4 a lease not renewed for 45 minutes expires and the next controller takes it', w => {
  w.state.comments = [{id: 100, ...on}, {id: 101, created_at: at(-50), body: claimLine('night-r1')}];
  assert.equal(JSON.parse(w.run(lease, ['status']).stdout).holder, null);
  const r = w.run(lease, ['claim', 'night-r2']);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(JSON.parse(r.stdout).holder.run, 'night-r2');
});
scenario('L5 a renewal posts the lease line first, then the result, and extends the lease', w => {
  w.state.comments = [{id: 100, ...on}, {id: 101, created_at: at(-50), body: claimLine('night-r1')}];
  const renewAt = at(-20);
  w.state.clock = renewAt;
  const result = w.file('checkpoint.md', 'partial result: found 0, approved 0, proposed 0, skipped 0\n');
  const r = w.run(lease, ['renew', 'night-r1', result]);
  // The precheck runs on the local clock: the claim at -50 expired at -5 and nothing may post.
  assert.equal(r.status, 2);
  assert.deepEqual(w.posts(), []);
  w.state.comments[1].created_at = at(-40);
  const ok = w.run(lease, ['renew', 'night-r1', result]);
  assert.equal(ok.status, 0, ok.stderr);
  assert.equal(w.state.comments.at(-1).body,
    'huntr lease: renew night-r1 for 45m\n\npartial result: found 0, approved 0, proposed 0, skipped 0\n');
  // Derived from the renewal's own time, never a second clock read.
  assert.equal(JSON.parse(ok.stdout).holder.expires, new Date(Date.parse(renewAt) + 45 * MIN).toISOString().replace(/\.\d{3}Z$/, 'Z'));
  delete w.state.clock;
  assert.equal(w.run(lease, ['claim', 'night-r2']).status, 2);
});
scenario('L6 a controller that lost the lease can neither renew nor release, and posts nothing', w => {
  w.state.comments = [{id: 100, ...on}, {id: 101, created_at: at(-10), body: claimLine('night-r9')}];
  const body = w.file('result.md', 'final result\n');
  for (const args of [['renew', 'night-r1', body], ['release', 'night-r1', body]]) {
    const r = w.run(lease, args);
    assert.equal(r.status, 2, args[0]);
    assert.match(r.stderr, /held by night-r9/);
  }
  assert.deepEqual(w.posts(), []);
});
scenario('L7 a release frees the lease at once for the next controller', w => {
  w.state.comments = [{id: 100, ...on}, {id: 101, created_at: at(-10), body: claimLine('night-r1')}];
  const r = w.run(lease, ['release', 'night-r1', w.file('final.md', 'final result\n')]);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(w.state.comments.at(-1).body, 'huntr lease: release night-r1\n\nfinal result\n');
  assert.equal(JSON.parse(r.stdout).holder, null);
  assert.equal(w.run(lease, ['claim', 'night-r2']).status, 0);
});
scenario('L8 the lease is read across every comment page, and a failed read refuses', w => {
  const filler = Array.from({length: 150}, (_, i) => ({id: 100 + i, created_at: at(-200), body: `synthetic note ${i}`}));
  filler[120] = {id: 220, created_at: at(-5), body: claimLine('night-r1')};
  w.state.comments = filler;
  assert.equal(JSON.parse(w.run(lease, ['status']).stdout).holder.run, 'night-r1');
  w.state.readFailure = true;
  const r = w.run(lease, ['claim', 'night-r2']);
  assert.equal(r.status, 2);
  assert.match(r.stderr, /read failed/);
  assert.deepEqual(w.posts(), []);
});
scenario('L9 malformed lease lines and arguments are refused, never read as a lease', w => {
  w.state.comments = [{id: 100, ...on}, {id: 101, created_at: at(-5), body: 'huntr lease: claim night-r1 thread thr_synx for 9999m'},
    {id: 102, created_at: at(-4), body: 'note\nhuntr lease: claim night-r3 thread thr_syny for 45m'}];
  assert.equal(JSON.parse(w.run(lease, ['status']).stdout).holder, null);
  for (const args of [['claim', 'bad run'], ['claim', 'thr_synnotarun'], ['renew', 'night-r2'], ['take']]) {
    assert.equal(w.run(lease, args).status, 2, args.join(' '));
  }
  assert.deepEqual(w.posts(), []);
});

// Hunter provisioning (item 2): the pin in the brief, fetched by the hunter, one-line failures.
function origin(w) {
  const git = (cwd, ...args) => execFileSync('git', args, {cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], env: {...w.env, GIT_AUTHOR_NAME: 's', GIT_AUTHOR_EMAIL: 's@example.invalid', GIT_COMMITTER_NAME: 's', GIT_COMMITTER_EMAIL: 's@example.invalid'}}).trim();
  git(w.dir, 'init', '-q', '--bare', '-b', 'main', 'origin.git');
  git(w.dir, 'clone', '-q', 'origin.git', 'author');
  const author = join(w.dir, 'author');
  git(author, 'commit', '-q', '--allow-empty', '-m', 'one');
  git(author, 'push', '-q', 'origin', 'HEAD:main');
  git(w.dir, 'clone', '-q', 'origin.git', 'stale');
  git(author, 'commit', '-q', '--allow-empty', '-m', 'two');
  git(author, 'push', '-q', 'origin', 'HEAD:main');
  return {pin: git(author, 'rev-parse', 'HEAD'), head: dir => git(dir, 'rev-parse', 'HEAD')};
}
scenario('P1 a stale project copy fetches the pin itself and reports ready in one line', w => {
  const o = origin(w);
  assert.notEqual(o.head(join(w.dir, 'stale')), o.pin);
  const r = w.run(provision, ['synthetic/project', o.pin, join(w.dir, 'stale'), 'core/correctness']);
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(r.stdout, `huntr hunter: ready core/correctness at ${o.pin}\n`);
  assert.equal(r.stderr, '');
  assert.equal(o.head(join(w.dir, 'stale')), o.pin);
});
scenario('P2 a missing project copy is cloned with the sandbox\'s own GitHub login', w => {
  const o = origin(w);
  const r = w.run(provision, ['synthetic/project', o.pin, join(w.dir, 'fresh'), 'core/correctness']);
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(o.head(join(w.dir, 'fresh')), o.pin);
  assert.deepEqual(w.calls().map(c => c.slice(0, 2).join(' ')), ['auth status', 'auth setup-git', 'repo clone']);
});
scenario('P3 a sandbox without its own GitHub login reports BLOCKED in exactly one line', w => {
  const o = origin(w);
  w.state.auth = 'fail';
  const r = w.run(provision, ['synthetic/project', o.pin, join(w.dir, 'stale'), 'core/correctness']);
  assert.equal(r.status, 3);
  assert.equal(r.stdout, 'huntr hunter: BLOCKED core/correctness at auth: gh is not signed in in this sandbox\n');
  assert.equal(r.stderr, '');
});
scenario('P4 a pin missing from origin reports BLOCKED at fetch in one line', w => {
  origin(w);
  const r = w.run(provision, ['synthetic/project', 'f'.repeat(40), join(w.dir, 'stale'), 'core/correctness']);
  assert.equal(r.status, 3);
  assert.equal(r.stdout, `huntr hunter: BLOCKED core/correctness at fetch: could not fetch ${'f'.repeat(40)} from origin\n`);
  assert.equal(r.stderr, '');
});
scenario('P5 malformed provisioning arguments exit 2 and run nothing', w => {
  for (const args of [['synthetic/project', 'abc', '/tmp/x', 's'], ['bad repo', 'a'.repeat(40), '/tmp/x', 's'], ['synthetic/project', 'a'.repeat(40), '/tmp/x', 'bad slice']]) {
    assert.equal(w.run(provision, args).status, 2, args.join(' '));
  }
  assert.deepEqual(w.calls(), []);
});

// R2 of #1693: a project copy with changes is never reported ready at the pin, and its edits are kept.
for (const [name, change, line] of [
  ['P6 an edited tracked file', dir => writeFileSync(join(dir, 'source.txt'), 'dirty copied source\n'), ' M source.txt'],
  ['P7 an untracked file', dir => writeFileSync(join(dir, 'extra.txt'), 'untracked copied source\n'), '?? extra.txt'],
  ['P8 a staged change', dir => { writeFileSync(join(dir, 'source.txt'), 'staged copied source\n'); execFileSync('git', ['-C', dir, 'add', 'source.txt']); }, 'M  source.txt'],
]) {
  scenario(`${name} in the project copy reports BLOCKED at source and keeps the edit`, w => {
    const git = (cwd, ...args) => execFileSync('git', args, {cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], env: {...w.env, GIT_AUTHOR_NAME: 's', GIT_AUTHOR_EMAIL: 's@example.invalid', GIT_COMMITTER_NAME: 's', GIT_COMMITTER_EMAIL: 's@example.invalid'}}).trim();
    git(w.dir, 'init', '-q', '--bare', '-b', 'main', 'origin.git');
    git(w.dir, 'clone', '-q', 'origin.git', 'copy');
    const copy = join(w.dir, 'copy');
    writeFileSync(join(copy, 'source.txt'), 'committed\n');
    git(copy, 'add', 'source.txt');
    git(copy, 'commit', '-qm', 'pin');
    git(copy, 'push', '-q', 'origin', 'HEAD:main');
    const pin = git(copy, 'rev-parse', 'HEAD');
    change(copy);
    const before = readFileSync(join(copy, line.slice(3)), 'utf8');
    const r = w.run(provision, ['synthetic/project', pin, copy, 'core/correctness']);
    assert.equal(r.status, 3, r.stdout);
    assert.equal(r.stdout, `huntr hunter: BLOCKED core/correctness at source: ${copy} has uncommitted changes\n`);
    assert.equal(r.stderr, '');
    // Untrimmed: a porcelain line's leading space is part of its status.
    assert.equal(execFileSync('git', ['-C', copy, 'status', '--porcelain', '--untracked-files=all'], {encoding: 'utf8'}), line + '\n');
    assert.equal(readFileSync(join(copy, line.slice(3)), 'utf8'), before);
  });
}

const plan = {slice: 'core/correctness', source_only: true, questions: 'Check synthetic bounds; run the named fixture proof.',
  paths: {source: ['crates/core/src/'], test: ['tests/proof/'], policy: ['AGENTS.md']}};
scenario('H1 the brief carries the pin, the provisioning script and the one-line rule', w => {
  const pin = 'a'.repeat(40);
  const r = w.run(hunters, ['brief', w.file('plan.json', JSON.stringify(plan)), 'synthetic/project', pin]);
  assert.equal(r.status, 0, r.stderr);
  const brief = r.stdout;
  assert.ok(brief.includes(`sh -s -- synthetic/project ${pin} "$PWD" core/correctness <<'HUNTR_PROVISION'\n${readFileSync(provision, 'utf8')}HUNTR_PROVISION\n`));
  assert.match(brief, /If it prints a `huntr hunter: BLOCKED` line, reply with exactly that line and nothing else, then stop\./);
  assert.ok(brief.includes(`huntr hunter: report core/correctness at ${pin}`));
  assert.ok(brief.includes(plan.questions));
  assert.match(brief, /no shared edits, commits, pushes, GitHub writes, approvals, builders or agents/);
  for (const bad of [['brief', w.file('bad.json', '{}'), 'synthetic/project', pin], ['brief', w.file('plan.json', JSON.stringify(plan)), 'synthetic/project', 'HEAD']]) {
    assert.equal(w.run(hunters, bad).status, 2);
  }
});
scenario('H2 collect counts only reports at the pin; blocked, stale and empty slices are gaps', w => {
  const pin = 'a'.repeat(40);
  const r = w.run(hunters, ['collect', pin,
    `core/correctness=${w.file('a.txt', `huntr hunter: report core/correctness at ${pin}\nfindings: none\n`)}`,
    `core/speed=${w.file('b.txt', 'huntr hunter: BLOCKED core/speed at auth: gh is not signed in in this sandbox\n')}`,
    `core/tests=${w.file('c.txt', `huntr hunter: report core/tests at ${'b'.repeat(40)}\n`)}`,
    `core/docs=${w.file('d.txt', '')}`,
    `core/size=${w.file('e.txt', `huntr hunter: BLOCKED core/speed at auth: wrong slice\n`)}`]);
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(JSON.parse(r.stdout), {pin, reported: ['core/correctness'], blocked: [
    {slice: 'core/speed', step: 'auth', reason: 'gh is not signed in in this sandbox'},
    {slice: 'core/tests', step: 'source-pin', reason: `reported ${'b'.repeat(40)}`},
    {slice: 'core/docs', step: 'report', reason: 'no report line'},
    {slice: 'core/size', step: 'report', reason: 'no report line'},
  ]});
});

// Item 4: a whole hunt, dry: lease, provisioning failure reporting, a partial result, a final result.
scenario('D1 dry run: one controller, three fake hunters, a partial result at 30 minutes and a final result', w => {
  const o = origin(w);
  const generated = w.run(lease, ['id']);
  assert.equal(generated.status, 0, generated.stderr);
  const run = generated.stdout.trim();
  const rivalRun = w.run(lease, ['id']).stdout.trim();
  assert.notEqual(run, rivalRun);
  assert.match(run, /^huntr-\d{8}T\d{6}Z-[0-9a-f]{24}$/);
  assert.deepEqual(w.calls(), [], 'identity generation needs no endpoint or GitHub read');
  w.state.comments = [{id: 100, ...on}];
  const slices = ['core/correctness', 'core/speed', 'core/tests'];
  const log = [];
  // 1. Claim the lease (and a rival wake is refused).
  w.state.clock = at(-40);
  assert.equal(w.run(lease, ['claim', run]).status, 0);
  delete w.state.clock;
  const rival = w.run(lease, ['claim', rivalRun]);
  assert.equal(rival.status, 2);
  log.push(`lease: ${run} holds; rival wake refused: ${rival.stderr.trim()}`);
  // 2. Dispatch: each fake hunter gets its brief and runs the provisioning it carries.
  const reports = {};
  for (const slice of slices) {
    const brief = w.run(hunters, ['brief', w.file('plan.json', JSON.stringify({...plan, slice})), 'synthetic/project', o.pin]);
    assert.equal(brief.status, 0, brief.stderr);
    const script = brief.stdout.match(/```sh\n([\s\S]*?)```/)[1];
    const sandbox = join(w.dir, slice.replace('/', '-'));
    // Each sandbox starts from a stale project copy, one commit behind the pin.
    execFileSync('git', ['clone', '-q', join(w.dir, 'origin.git'), sandbox], {stdio: 'ignore'});
    execFileSync('git', ['-C', sandbox, 'reset', '-q', '--hard', 'HEAD~1'], {stdio: 'ignore'});
    w.state.auth = slice === 'core/speed' ? 'fail' : 'ok';
    writeFileSync(w.env.HUNTR_FAKE_STATE, JSON.stringify(w.state));
    const ran = spawnSync('sh', ['-c', script], {cwd: sandbox, env: w.env, encoding: 'utf8'});
    const first = ran.stdout.split('\n')[0];
    reports[slice] = first.startsWith('huntr hunter: BLOCKED') ? first + '\n' : `huntr hunter: report ${slice} at ${o.pin}\nfindings: none\n`;
    log.push(`hunter ${slice}: ${first}`);
  }
  const collect = names => JSON.parse(w.run(hunters, ['collect', o.pin, ...names.map(s => `${s}=${w.file(s.replace('/', '-') + '.txt', reports[s])}`)]).stdout);
  // 3. Wake 1, 30 minutes in: two reports are back; post the partial result with the renewal.
  const partial = collect(['core/correctness', 'core/speed']);
  assert.deepEqual(partial.blocked, [{slice: 'core/speed', step: 'auth', reason: 'gh is not signed in in this sandbox'}]);
  w.state.clock = at(-10);
  const checkpoint = w.file('checkpoint.md', `partial result ${run}: found 0, approved 0, proposed 0, skipped 0; reported ${partial.reported.join(', ')}; blocked ${partial.blocked.map(b => `${b.slice} at ${b.step}: ${b.reason}`).join('; ')}; running core/tests\n`);
  assert.equal(w.run(lease, ['renew', run, checkpoint]).status, 0);
  log.push(`wake 1: ${w.state.comments.at(-1).body.replace(/\n+/g, ' | ').trim()}`);
  // 4. Wake 2: the last hunter reports; post the final result and release the lease.
  const final = collect(slices);
  w.state.clock = at(0);
  const result = w.file('final.md', `final result ${run}: found 0, approved 0, proposed 0, skipped 0; reported ${final.reported.join(', ')}; blocked ${final.blocked.map(b => `${b.slice} at ${b.step}: ${b.reason}`).join('; ')}\n`);
  assert.equal(w.run(lease, ['release', run, result]).status, 0);
  log.push(`wake 2: ${w.state.comments.at(-1).body.replace(/\n+/g, ' | ').trim()}`);
  delete w.state.clock;
  // 5. The next scheduled wake can take the lease at once.
  assert.equal(w.run(lease, ['claim', 'night-next']).status, 0);
  log.push('next wake: night-next holds');
  w.advance(46);
  assert.equal(JSON.parse(w.run(lease, ['status']).stdout).holder, null);
  assert.equal(w.run(lease, ['claim', rivalRun]).status, 0);
  assert.equal(w.run(lease, ['renew', 'night-next', checkpoint]).status, 2);
  assert.equal(w.run(lease, ['release', 'night-next', result]).status, 2);
  assert.equal(w.run(lease, ['release', rivalRun, result]).status, 0);
  log.push('expiry: next lease expired; generated rival holds, stale holder refused; release frees it');

  const bodies = w.state.comments.slice(1, 5).map(c => c.body.split('\n')[0]);
  assert.deepEqual(bodies, [claimLine(run), `huntr lease: renew ${run} for 45m`,
    `huntr lease: release ${run}`, claimLine('night-next')]);
  assert.match(w.state.comments[2].body, /partial result .*: .*blocked core\/speed at auth: gh is not signed in in this sandbox; running core\/tests/);
  assert.match(w.state.comments[3].body, /final result .*: .*reported core\/correctness, core\/tests; blocked core\/speed at auth/);
  // No live writes: every call went to the fake gh for the synthetic repository, and nothing listed threads.
  for (const c of w.calls()) assert.ok(['api', 'issue', 'auth', 'repo'].includes(c[0]), JSON.stringify(c));
  for (const line of log) console.log(line);
});

// R1 of #1693: every scheduled `huntr wake:` posts a result; a hunter's wake posts only when one is overdue.
scenario('L10 due: a scheduled wake always checkpoints, a hunter wake only after 30 minutes, a non-holder never', w => {
  w.state.comments = [{id: 100, ...on}, {id: 101, created_at: at(-26), body: claimLine('night-r1')}];
  const due = kind => w.run(lease, ['due', 'night-r1', kind]);
  assert.equal(JSON.parse(due('hunter').stdout).checkpoint, false);
  assert.equal(JSON.parse(due('scheduled').stdout).checkpoint, true);
  w.advance(5);
  assert.equal(JSON.parse(due('hunter').stdout).checkpoint, true);
  const other = w.run(lease, ['due', 'night-r2', 'scheduled']);
  assert.equal(other.status, 2);
  assert.match(other.stderr, /held by night-r1/);
  assert.equal(w.run(lease, ['due', 'night-r1', 'later']).status, 2);
  assert.deepEqual(w.posts(), [], 'due writes nothing');
});
scenario('D2 dry run: a hunter wake at 26 minutes cannot push the 30-minute result to 60', w => {
  w.state.comments = [{id: 100, ...on}];
  assert.equal(w.run(lease, ['claim', 'night-dry']).status, 0);
  const results = [];
  const wake = (minutes, kind) => {
    w.advance(minutes);
    const d = w.run(lease, ['due', 'night-dry', kind]);
    assert.equal(d.status, 0, d.stderr);
    if (!JSON.parse(d.stdout).checkpoint) return;
    const r = w.run(lease, ['renew', 'night-dry', w.file('checkpoint.md', `partial result after a ${kind} wake\n`)]);
    assert.equal(r.status, 0, r.stderr);
    results.push(w.state.comments.at(-1).id);
  };
  // The reviewer's interleaving: hunters finish at 26 and 56, the scheduled wakes come at 30 and 60.
  wake(26, 'hunter'); wake(4, 'scheduled'); wake(26, 'hunter'); wake(4, 'scheduled');
  const minutes = id => (Date.now() - Date.parse(w.state.comments.find(c => c.id === id).created_at)) / MIN;
  const claim = w.state.comments[1].id;
  const times = [claim, ...results].map(minutes).map(Math.round);
  assert.deepEqual(times, [60, 30, 0], 'claim at t0, results at t30 and t60: no gap over 30 minutes');
  // A lost scheduled wake: the next hunter wake past 30 minutes posts the overdue result.
  wake(31, 'hunter');
  assert.equal(results.length, 3);
  for (const line of w.state.comments.slice(1).map(c => c.body.split('\n')[0])) console.log(`D2: ${line}`);
});

// R3 of #1693: an outcome without its own live lease still finalizes its record.
scenario('D3 dry run: an off switch posts its final record without a lease, and release stays refused', w => {
  w.state.comments = [{id: 100, created_at: at(-60), body: 'huntr: off'}];
  const index = w.file('index.md', 'final result night-off: off; found 0, approved 0, proposed 0, skipped 0\n');
  const release = w.run(lease, ['release', 'night-off', index]);
  assert.equal(release.status, 2);
  assert.deepEqual(w.posts(), []);
  const r = w.run(lease, ['record', 'night-off', index]);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(w.posts().length, 1);
  assert.equal(w.state.comments.at(-1).body, readFileSync(index, 'utf8'));
  assert.deepEqual(JSON.parse(r.stdout), {holder: null, comment: w.state.comments.at(-1).id});
  // A record body can never forge a lease line or flip the switch.
  for (const first of ['huntr: on', 'huntr lease: claim night-off thread thr_synx for 45m']) {
    assert.equal(w.run(lease, ['record', 'night-off', w.file('bad.md', `${first}\nbody\n`)]).status, 2, first);
  }
  assert.equal(w.posts().length, 1);
  console.log(`D3: release refused (${release.stderr.trim()}); record posted: ${w.state.comments.at(-1).body.trim()}`);
});
scenario('D4 a controller that lost its lease records its handoff while the new holder keeps the lease', w => {
  w.state.comments = [{id: 100, ...on}, {id: 101, created_at: at(-10), body: claimLine('night-r9')}];
  const r = w.run(lease, ['record', 'night-r1', w.file('handoff.md', 'handoff night-r1: unfiled candidates for the holder\n')]);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(JSON.parse(r.stdout).holder.run, 'night-r9');
});

scenario('L11 legacy thread-bearing lease remains held by its run until release or expiry', w => {
  w.state.comments = [{id: 100, ...on}, {id: 101, created_at: at(-10),
    body: 'huntr lease: claim legacy-run thread thr_synthetic for 45m'}];
  assert.equal(JSON.parse(w.run(lease, ['status']).stdout).holder.run, 'legacy-run');
  assert.equal(w.run(lease, ['claim', 'new-run']).status, 2);
  const index = w.file('legacy.md', 'final result legacy-run\n');
  assert.equal(w.run(lease, ['renew', 'legacy-run', index]).status, 0);
  assert.equal(w.run(lease, ['release', 'legacy-run', index]).status, 0);
  assert.equal(w.run(lease, ['claim', 'new-run']).status, 0);
});

// WS12: whether to hunt (switch, kind approvals and pace) and the durable record's posting.
scenario('S1 switch: the newest huntr: first line decides, unknown commands are off, kind approvals are listed', w => {
  const filler = Array.from({length: 120}, (_, i) => ({created_at: at(-200 + i), body: `note ${i}`}));
  w.state.comments = [{created_at: at(-300), body: 'huntr: off'}, ...filler,
    {created_at: at(-50), body: 'huntr kind approved: docs typo sweeps, tier 1\nPrivate record: synthetic'},
    {created_at: at(-40), body: 'huntr: on — resumed'}, {created_at: at(-30), body: claimLine('night-r1')},
    {created_at: at(-20), body: 'a note\nhuntr: off'}].map((c, i) => ({id: 100 + i, ...c}));
  const read = () => { const r = w.run(lease, ['switch']); assert.equal(r.status, 0, r.stderr); return JSON.parse(r.stdout); };
  assert.deepEqual(read(), {switch: 'on', line: 'huntr: on — resumed',
    kinds: [{comment: 221, line: 'huntr kind approved: docs typo sweeps, tier 1'}]});
  w.state.comments.push({id: 300, created_at: at(-10), body: 'huntr: on hold until Monday'});
  assert.equal(read().switch, 'off');
  w.state.comments = [{id: 100, created_at: at(-10), body: 'ordinary note'}];
  assert.deepEqual(read(), {switch: 'off', line: null, kinds: []});
  assert.deepEqual(w.posts(), [], 'switch writes nothing');
});
scenario('S2 switch: an unreadable switch issue is a refusal, never on', w => {
  w.state.comments = [{id: 100, ...on}];
  w.state.readFailure = true;
  const r = w.run(lease, ['switch']);
  assert.equal(r.status, 2);
  assert.equal(r.stdout, '');
  assert.match(r.stderr, /switch issue read failed/);
});

// A fixed-offset zone whose local hour now satisfies `want`: Etc/GMT-14 to Etc/GMT+12 cover every hour.
function zone(want) {
  const now = Date.now();
  for (let offset = -12; offset <= 14; offset++) {
    const local = new Date(now + offset * 3600000);
    if (want(local.getUTCHours() + local.getUTCMinutes() / 60))
      return {tz: offset === 0 ? 'Etc/GMT' : `Etc/GMT${offset > 0 ? '-' : '+'}${Math.abs(offset)}`, local};
  }
  throw new Error('no zone');
}
const nextDay = local => new Date(Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate() + 1)).toISOString().slice(0, 10);
scenario('PC1 pace: two empty hunts pause until the next calendar day in the project timezone', w => {
  const pace = (...args) => w.run(lease, ['pace', ...args]);
  const midday = zone(h => h >= 6 && h < 18), earlyMorning = zone(h => h >= 0.25 && h < 2.5);
  const hourAgo = new Date(Date.now() - 3600000).toISOString(), threeHoursAgo = new Date(Date.now() - 3 * 3600000).toISOString();
  assert.deepEqual(JSON.parse(pace(midday.tz, '1', hourAgo).stdout), {hunt: true});
  assert.deepEqual(JSON.parse(pace(midday.tz, '2', hourAgo).stdout), {hunt: false, until: nextDay(midday.local)});
  assert.deepEqual(JSON.parse(pace(midday.tz, '3', hourAgo).stdout), {hunt: false, until: nextDay(midday.local)});
  // The same instant was yesterday in another zone, so its pause is over.
  assert.deepEqual(JSON.parse(pace(earlyMorning.tz, '2', threeHoursAgo).stdout), {hunt: true});
  assert.deepEqual(w.calls(), [], 'pace reads no GitHub');
});
scenario('PC2 pace: an unknown timezone, streak or time asks instead of hunting', w => {
  const now = new Date().toISOString();
  for (const args of [['Mars/Olympus', '2', now], ['', '2', now], ['Etc/GMT', 'two', now], ['Etc/GMT', '-1', now],
    ['Etc/GMT', '2', 'yesterday']]) {
    const r = w.run(lease, ['pace', ...args]);
    assert.equal(r.status, 2, JSON.stringify(args));
    assert.equal(r.stdout, '');
    assert.match(r.stderr, /unknown (timezone|empty-hunt streak|last empty hunt time): ask on the tracking issue/);
  }
});

const manifest = join(here, 'manifest.mjs');
function publish(w, record, run = record.run) {
  const index = join(w.dir, 'index.md');
  rmSync(index, {force: true});
  const r = w.run(lease, ['publish', run, w.file('record.json', JSON.stringify(record)), index]);
  return {r, index: existsSync(index) ? readFileSync(index, 'utf8') : null};
}
const unpackPosted = (w, bodies, sha) => {
  const r = spawnSync(process.execPath, [manifest, 'unpack', w.file('readback.json', JSON.stringify(bodies)), sha], {encoding: 'utf8'});
  assert.equal(r.status, 0, r.stderr);
  return JSON.parse(r.stdout);
};
const bigRecord = {run: 'night-big', slices: [], gaps: [], note: 'quoted "text"\nλ😺'.repeat(10000)};
scenario('PB1 publish posts every numbered part, reads them back and writes the index that links them', w => {
  w.state.comments = [{id: 100, ...on}];
  const {r, index} = publish(w, bigRecord);
  assert.equal(r.status, 0, r.stderr);
  const out = JSON.parse(r.stdout);
  const parts = w.state.comments.slice(1);
  assert.equal(parts.length, 6);
  assert.deepEqual(out, {sha256: out.sha256, parts: 6, index: join(w.dir, 'index.md')});
  assert.deepEqual(unpackPosted(w, parts.map(c => c.body), out.sha256), bigRecord);
  assert.equal(index.split('\n')[0], `Hunt record index for night-big: 6 parts, sha256 ${out.sha256}`);
  for (const [i, c] of parts.entries())
    assert.ok(index.includes(`- part ${i + 1}/6: https://github.com/synthetic/project/issues/394#issuecomment-${c.id}`), `part ${i + 1}`);
  // The index posts as a plain record: its first line never reads as a switch or lease line.
  assert.equal(w.run(lease, ['record', 'night-big', join(w.dir, 'index.md')]).status, 0);
});
scenario('PB2 publish after a lost response reuses the part already posted, never a duplicate', w => {
  w.state.comments = [{id: 100, ...on}];
  const packed = JSON.parse(spawnSync(process.execPath, [manifest, 'pack', w.file('r.json', JSON.stringify(bigRecord))], {encoding: 'utf8'}).stdout);
  w.state.comments.push({id: 101, created_at: at(-5), body: packed.comments[0]}, {id: 102, created_at: at(-4), body: packed.comments[1]});
  const {r} = publish(w, bigRecord);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(w.posts().length, 4);
  assert.equal(w.state.comments.length, 7);
});
scenario('PB3 publish refuses another run\'s record and an unconfirmed post leaves no index', w => {
  w.state.comments = [{id: 100, ...on}];
  const wrong = publish(w, {run: 'night-other', slices: []}, 'night-mine');
  assert.equal(wrong.r.status, 2);
  assert.match(wrong.r.stderr, /run/);
  assert.deepEqual(w.posts(), []);
  w.state.postFailure = true;
  const lost = publish(w, {run: 'night-mine', slices: []});
  assert.equal(lost.r.status, 2);
  assert.match(lost.r.stderr, /rerun publish/);
  assert.equal(lost.index, null);
});

// WS23 (#1608): the recorded last-empty time is an instant with Z or an offset, so the host's
// timezone can never decide whether a hunt starts. Each case runs under two host zones.
scenario('PC3 pace: an offset-free time is refused and an offset-bearing instant decides the same in every host zone', w => {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.parse(today) - 86400000).toISOString().slice(0, 10);
  const pace = (host, when, project = 'UTC') => {
    const saved = w.env.TZ;
    w.env.TZ = host;
    try { return w.run(lease, ['pace', project, '2', when]); }
    finally { if (saved === undefined) delete w.env.TZ; else w.env.TZ = saved; }
  };
  for (const host of ['UTC', 'America/Los_Angeles']) {
    for (const when of [`${yesterday}T23:00:00`, `${yesterday}T23:00`, `${yesterday}T23:00:00.000`]) {
      const r = pace(host, when);
      assert.equal(r.status, 2, `${host} ${when}: ${r.stdout}`);
      assert.equal(r.stdout, '');
      assert.match(r.stderr, /last empty hunt time needs Z or an offset .*: ask on the tracking issue/);
    }
    // One instant written three ways: yesterday in the project's zone, so the pause is over.
    for (const when of [`${yesterday}T23:00:00Z`, `${yesterday}T15:00:00-08:00`, `${today}T07:00:00.000+08:00`])
      assert.deepEqual(JSON.parse(pace(host, when).stdout), {hunt: true}, `${host} ${when}`);
    // An hour ago, at midday in the project's zone: paused until its next day, whatever the host zone.
    const midday = zone(h => h >= 6 && h < 18), hourAgo = new Date(Date.now() - 3600000).toISOString();
    assert.deepEqual(JSON.parse(pace(host, hourAgo, midday.tz).stdout), {hunt: false, until: nextDay(midday.local)}, host);
  }
  assert.deepEqual(w.calls(), [], 'pace reads no GitHub');
});

// WS23 (#1569): a run that still holds its lease finishes with release, never the lease-less record,
// so the next scheduled controller is never refused by a finished hunt's live lease.
scenario('D5 a controller paused after claiming cannot record past its live lease; release frees it for the next controller', w => {
  w.state.comments = [{id: 100, ...on}];
  assert.equal(w.run(lease, ['claim', 'synthetic-final']).status, 0);
  const {r: published} = publish(w, {run: 'synthetic-final', slices: [], gaps: [], next: 'paused until tomorrow'});
  assert.equal(published.status, 0, published.stderr);
  const index = join(w.dir, 'index.md'), posts = w.posts().length;
  const record = w.run(lease, ['record', 'synthetic-final', index]);
  assert.equal(record.status, 2, record.stdout);
  assert.match(record.stderr, /synthetic-final holds the live lease: post its final index with release/);
  assert.equal(w.posts().length, posts, 'a refused record posts nothing');
  const release = w.run(lease, ['release', 'synthetic-final', index]);
  assert.equal(release.status, 0, release.stderr);
  const next = w.run(lease, ['claim', 'synthetic-next']);
  assert.equal(next.status, 0, next.stderr);
});

// WS23 (#1569): the controller's own steps. The last hunter wake (all slices reported or blocked)
// and a pause after claiming end through step 5's publish and release; record is for no lease.
test('W1 the last wake and a pause after claiming finish with release; record only without a live lease', () => {
  const skill = readFileSync(join(here, '../SKILL.md'), 'utf8');
  const section = heading => skill.split(`\n${heading}\n`)[1].split('\n## ')[0].replace(/\s+/g, ' ');
  assert.match(section('## On every wake'), /every slice is reported or blocked[^.]*\bfinish the hunt \(step 5\)/i);
  assert.match(section('## 1. Check whether to hunt'), /`hunt: false` ends the hunt as paused: finish it \(step 5\)/);
  assert.match(section('## 5. Record the result and finish this hunt'), /to finish the hunt, `lease\.mjs finish <run> <index>`/);
  assert.doesNotMatch(section('## 5. Record the result and finish this hunt'), /`record` \(off, paused, blocked/);
});

// WS23 review R1 (#1656): a wake that cannot read the switch issue does not know whether its lease
// is lost, so `due` keeps that apart (exit 3) from a lease that is really gone or taken (exit 2).
scenario('D6 due: an unreadable switch issue exits 3, never the lost-lease exit 2; after it recovers the holder releases', w => {
  w.state.comments = [{id: 100, ...on}];
  assert.equal(w.run(lease, ['claim', 'synthetic-final']).status, 0);
  w.state.readFailure = true;
  const unread = w.run(lease, ['due', 'synthetic-final', 'hunter']);
  assert.equal(unread.status, 3, unread.stderr);
  assert.equal(unread.stdout, '');
  assert.match(unread.stderr, /switch issue read failed: the lease is unknown, so file nothing this wake/);
  w.state.readFailure = false;
  assert.equal(JSON.parse(w.run(lease, ['due', 'synthetic-final', 'hunter']).stdout).holder.run, 'synthetic-final');
  const {r: published} = publish(w, {run: 'synthetic-final', slices: [], gaps: []});
  assert.equal(published.status, 0, published.stderr);
  assert.equal(w.run(lease, ['release', 'synthetic-final', join(w.dir, 'index.md')]).status, 0);
  assert.equal(w.run(lease, ['claim', 'synthetic-next']).status, 0);
  // A lease that is really gone or taken is still exit 2: the wake's lost-lease route.
  const taken = w.run(lease, ['due', 'synthetic-final', 'scheduled']);
  assert.equal(taken.status, 2); assert.match(taken.stderr, /held by synthetic-next/);
  w.advance(46);
  const expired = w.run(lease, ['due', 'synthetic-next', 'scheduled']);
  assert.equal(expired.status, 2); assert.match(expired.stderr, /no live lease/);
});

// WS23 review R1 and R2 (#1656): the steps a controller follows on an unknown lease and when
// dispatch leaves no hunter running or queued.
test('W2 an unreadable wake retries instead of recording, and a dispatch with nothing running finishes at once', () => {
  const skill = readFileSync(join(here, '../SKILL.md'), 'utf8');
  const section = heading => skill.split(`\n${heading}\n`)[1].split('\n## ')[0].replace(/\s+/g, ' ');
  const wake = section('## On every wake');
  assert.match(wake, /Exit 2 \(the lease is lost or taken\): file nothing more, put unfiled candidates in the record and finish the hunt \(step 5\)\./);
  assert.match(wake, /Exit 3 \(unreadable\): file nothing and dispatch no queued slice this wake; collect reports \(step 3\), then end the turn while hunters are still running, or else finish the hunt \(step 5\) with any queued slice recorded as a gap\./);
  assert.match(section('## 2. Plan and dispatch hunters'),
    /If no slice is running or queued \(every slice blocked\), finish the hunt now \(step 5\)\. Otherwise end the turn\./);
  const finish = section('## 5. Record the result and finish this hunt');
  assert.match(finish, /Exit 3 means nothing was confirmed posted: finalization is pending\. Keep the record and index in resumable state, stay open and rerun `finish` on the next wake; it reuses an index already posted\./);
  assert.match(finish, /If no wake comes, the lease expires 45 minutes after its last renewal and the next scheduled controller resumes from the latest verified record\./);
});

// WS23 planner's call on review R1 (#1656): the terminal write needs no wake after it. `finish` reads
// the lease a bounded number of times, releases while this run holds it, records after a confirmed
// loss, and when the lease stays unreadable still posts the index under a release line: a release
// line frees only its own run's lease, so it is safe whoever holds the lease.
const readsOf = w => w.calls().filter(c => c[0] === 'api').length;
function finalWorld(w, comments = [{id: 100, ...on}]) {
  w.env.HUNTR_LEASE_RETRY_MS = '0';
  w.state.comments = comments;
  const {r} = publish(w, {run: 'synthetic-final', slices: [], gaps: []});
  assert.equal(r.status, 0, r.stderr);
  return {file: join(w.dir, 'index.md'), text: readFileSync(join(w.dir, 'index.md'), 'utf8')};
}
const finish = w => w.run(lease, ['finish', 'synthetic-final', join(w.dir, 'index.md')]);
scenario('F1 finish after a brief read failure on the last wake releases the held lease and posts the final index', w => {
  w.state.comments = [{id: 100, ...on}];
  assert.equal(w.run(lease, ['claim', 'synthetic-final']).status, 0);
  const {text} = finalWorld(w, w.state.comments);
  w.state.readFailures = 2;
  const r = finish(w);
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(JSON.parse(r.stdout), {finished: 'release', verified: true, comment: w.state.comments.at(-1).id, holder: null});
  assert.equal(w.state.comments.at(-1).body, `huntr lease: release synthetic-final\n\n${text}`);
  assert.equal(w.run(lease, ['claim', 'synthetic-next']).status, 0);
});
scenario('F2 finish while the lease stays unreadable reads it a bounded four times, posts under a release line and frees only its own lease', w => {
  for (const [holder, after] of [['synthetic-final', null], ['synthetic-other', 'synthetic-other']]) {
    w.state = {comments: [{id: 100, ...on}]};
    rmSync(w.env.HUNTR_FAKE_LOG, {force: true});
    assert.equal(w.run(lease, ['claim', holder]).status, 0);
    const {text} = finalWorld(w, w.state.comments);
    w.state.readFailure = true;
    const reads = readsOf(w);
    const r = finish(w);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(readsOf(w) - reads, 4, 'four reads, then it stops reading');
    assert.deepEqual(JSON.parse(r.stdout), {finished: 'release', verified: false, comment: w.state.comments.at(-1).id});
    assert.equal(w.state.comments.at(-1).body, `huntr lease: release synthetic-final\n\n${text}`);
    w.state.readFailure = false;
    assert.equal(JSON.parse(w.run(lease, ['status']).stdout).holder?.run ?? null, after, holder);
  }
});
scenario('F3 finish after a confirmed loss records the index without a lease line', w => {
  const {text} = finalWorld(w, [{id: 100, ...on}, {id: 101, created_at: at(-10), body: claimLine('synthetic-other')}]);
  const r = finish(w);
  assert.equal(r.status, 0, r.stderr);
  const out = JSON.parse(r.stdout);
  assert.equal(out.finished, 'record');
  assert.equal(out.holder.run, 'synthetic-other');
  assert.equal(w.state.comments.at(-1).body, text);
});
scenario('F4 finish with GitHub down keeps finalization pending, and a rerun reuses an index already posted', w => {
  w.state.comments = [{id: 100, ...on}];
  assert.equal(w.run(lease, ['claim', 'synthetic-final']).status, 0);
  finalWorld(w, w.state.comments);
  Object.assign(w.state, {readFailure: true, postFailure: true});
  const posts = w.posts().length;
  const down = finish(w);
  assert.equal(down.status, 3);
  assert.equal(down.stdout, '');
  assert.match(down.stderr, /finalization pending: nothing was confirmed posted; keep the index and rerun finish/);
  Object.assign(w.state, {readFailure: false, postFailure: false});
  const up = finish(w);
  assert.equal(up.status, 0, up.stderr);
  assert.equal(JSON.parse(up.stdout).finished, 'release');
  const again = finish(w);
  assert.equal(again.status, 0, again.stderr);
  assert.deepEqual(JSON.parse(again.stdout), {finished: 'already', verified: true, comment: JSON.parse(up.stdout).comment, holder: null});
  assert.equal(w.posts().length, posts + 2, 'one failed post, one release, no duplicate');
  assert.equal(w.run(lease, ['claim', 'synthetic-next']).status, 0);
});

// WS23 review R4 (#1656, planner's call): an old controller whose wake cannot read the lease may
// collect and finish, but never dispatch: a new controller may already hold the hunt.
scenario('W3 two controllers: after a new claim, the old controller\'s unreadable wake dispatches no queued slice', w => {
  w.state.comments = [{id: 100, ...on}];
  assert.equal(w.run(lease, ['claim', 'synthetic-old']).status, 0);
  w.advance(46);
  assert.equal(w.run(lease, ['claim', 'synthetic-new']).status, 0);
  w.state.readFailure = true;
  const late = w.run(lease, ['due', 'synthetic-old', 'hunter']);
  assert.equal(late.status, 3, late.stderr);
  w.state.readFailure = false;
  assert.equal(JSON.parse(w.run(lease, ['status']).stdout).holder.run, 'synthetic-new');
  // So the exit-3 route the old controller follows must start no hunter.
  const skill = readFileSync(join(here, '../SKILL.md'), 'utf8');
  const wake = skill.split('\n## On every wake\n')[1].split('\n## ')[0].replace(/\s+/g, ' ');
  assert.match(wake, /Exit 3 \(unreadable\): file nothing and dispatch no queued slice this wake;/);
  assert.match(wake, /dispatch queued slices only after `due` exited 0\./);
  assert.doesNotMatch(wake, /Archive those hunters; dispatch queued slices\./);
});
