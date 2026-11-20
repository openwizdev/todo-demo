import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, symlinkSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { projectSettings } from './fixtures/project-settings.mjs';
import { spawnSync } from 'node:child_process';
const here = dirname(fileURLToPath(import.meta.url));
const gate = join(here, 'approve.mjs');
const settings = projectSettings();
const conn = nodes => ({totalCount: nodes.length, nodes, pageInfo: {hasNextPage:false,endCursor:null}});
const paged = nodes => ({...conn(nodes), pageInfo: {hasNextPage:false,endCursor:null}});
const comment = (body, id = 1) => ({databaseId: id, body});
function body(kind = 'bug fix', paths = ['crates/core/src/ops.rs', 'tests/proof/p01_list.rs'], tier = ['missing test','stale docs'].includes(kind) ? 1 : 3) {
  return `## Tier\n\n${tier}\n\n## Kind\n\n${kind}\n\n## Product promises\n\nNo new features, contracts or dependencies.\n\n## Proof class\n\n${["report","coverage-or-docs","unchanged-existing-tests","failing-test-first"][tier] ?? "unknown"}\n\n## Problem\n\nOne synthetic ordering defect.\n\n## Proof\n\n\`\`\`sh\nsynthetic-repro --fixture ordering\n\`\`\`\n\n## Speed proof\n\nnone\n\n## Security fix\n\nno\n\n## Owned paths\n\n${paths.map(p => '- \`' + p + '\`').join('\n')}\n\n## Size\n\n120 / 200 changed lines (added + deleted)\n\n## Never-list\n\nThe never-list in docs/agents/huntr.md applies in full.\n`;
}
function issue(number = 700, changes = {}) {
  return {number, state: 'OPEN', body: body(), labels: conn([{name: 'huntr'}]), comments: conn([]), parent: null, subIssuesSummary: {total: 0}, ...changes};
}
function world() {
  return {pages: [{data: {repository: {
    switch: {number: 394, comments: conn([comment('huntr: on', 1)])},
    issues: paged([issue()]),
  }}}]};
}
function run(w, changeSettings) {
  const tmp = mkdtempSync(join(tmpdir(), 'huntr-gate-'));
  try {
    mkdirSync(join(tmp, 'bin')); mkdirSync(join(tmp, 'docs/agents'), {recursive: true});
    symlinkSync(join(here, 'fixtures/gh.mjs'), join(tmp, 'bin/gh'));
    // Before settings exist, still exercise the missing gate for the HU1 red run.
    const text = existsSync(settings) ? readFileSync(settings, 'utf8') : '';
    writeFileSync(join(tmp, 'docs/agents/huntr.md'), changeSettings ? changeSettings(text) : text);
    writeFileSync(join(tmp, 'world.json'), JSON.stringify(w));
    for (const [path,kind] of Object.entries(w.checkout ?? {})) {
      mkdirSync(dirname(join(tmp,path)),{recursive:true});
      if (kind === 'directory') mkdirSync(join(tmp,path));
      else if (kind === 'symlink') symlinkSync('/tmp',join(tmp,path));
      else writeFileSync(join(tmp,path),'synthetic');
    }
    const r = spawnSync(process.execPath, [gate, '700'], {cwd: tmp, encoding: 'utf8', env: {...process.env,
      GH_REPO: 'synthetic/project', PATH: join(tmp, 'bin') + ':' + process.env.PATH,
      HUNTR_PRIVATE_RECORD: w.pointer ?? 'https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001', HUNTR_FAKE_STATE: join(tmp, 'world.json'), HUNTR_FAKE_POSTS: join(tmp, 'posts'), HUNTR_FAKE_READS:join(tmp,'reads')}});
    assert.ifError(r.error);
    const posts = existsSync(join(tmp, 'posts')) ? readFileSync(join(tmp, 'posts'), 'utf8').trim().split('\n').map(JSON.parse) : [];
    return {...r, posts};
  } finally { rmSync(tmp, {recursive: true, force: true}); }
}
function refuse(name, change, reason) {
  test(name, () => {
    const w = world(); change(w, w.pages[0].data.repository, w.pages[0].data.repository.issues.nodes[0]);
    const r = run(w);
    assert.equal(r.status, 2, r.stderr);
    assert.deepEqual(r.posts, [], r.stdout);
    assert.match(r.stderr, reason);
    assert.equal(r.stdout, '');
  });
}
for (const [kind, paths] of [
  ['bug fix', ['crates/core/src/ops.rs', 'tests/proof/p01_list.rs']],
  ['flaky test', ['apps/web/test/browser/synthetic.mjs', 'apps/web/src/viewer.ts']],
  ['missing test', ['tests/proof/new_case.rs']],
  ['stale docs', ['docs/fleets.md', 'README.md']],
]) test(`HU1 approves ${kind} once`, () => {
  const w = world(); w.pages[0].data.repository.issues.nodes[0].body = body(kind, paths);
  const r = run(w); assert.equal(r.status, 0, r.stderr); assert.equal(r.posts.length, 1);
  assert.equal(r.posts[0].number, '700');
  assert.equal(r.posts[0].body.split('\n')[1], 'Private record: https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001');
  assert.doesNotMatch(r.posts[0].body, /\bthr_[A-Za-z0-9]|["“”]/);
  assert.match(r.posts[0].body.split('\n')[0], new RegExp('^\\*\\*Approved on its own by huntr, \\d{4}-\\d{2}-\\d{2}, tier ' + (['missing test','stale docs'].includes(kind) ? 1 : 3) + ', kind ' + kind + ':\\*\\* under Jake\'s standing approval \\(ADR 0014\\)\\.$'));
});
refuse('HU1 needs huntr label', (_w, _r, t) => {t.labels = conn([]);}, /huntr label/);
refuse('HU1 ready label alone approves nothing', (_w, _r, t) => {t.labels = conn([{name:'ready-for-agent'}]);}, /huntr label/);
refuse('HU1 missing descriptive kind', (_w,_r,t)=>{t.body=body('');}, /kind/);
for (const paths of [[], ['tests/'], ['tests'], ['tests/*'], ['tests/../README.md'], ['/tests/a.rs'], ['tests//a.rs'], ['tests/a.rs', 'tests/a.rs'], ['tests/é.rs'], ['tests/a.rs\nREADME.md']])
  refuse(`HU1 exact paths ${JSON.stringify(paths)}`, (_w, _r, t) => {t.body = body('bug fix', paths);}, /owned paths/);
for (const [kind, path] of [['missing test', 'crates/core/src/ops.rs'], ['missing test', 'apps/web/src/viewer.ts'], ['stale docs', 'apps/web/src/viewer.ts']])
  refuse(`HU1 ${kind} refuses ${path}`, (_w, _r, t) => {t.body = body(kind, [path]);}, /kind|tier/);
refuse('HU1 duplicate operative kind', (_w, _r, t) => {t.body += '\n## Kind\n\nbug fix\n';}, /kind|tier/);
refuse('HU1 missing problem', (_w, _r, t) => {t.body = t.body.replace('One synthetic ordering defect.', '');}, /problem/);
refuse('HU1 missing failing command', (_w, _r, t) => {t.body = t.body.replace('synthetic-repro --fixture ordering', '');}, /proof/);
refuse('HU1 over 200 declared lines', (_w, _r, t) => {t.body = t.body.replace('120 / 200', '201 / 200');}, /200/);
refuse('HU1 missing never-list', (_w, _r, t) => {t.body = t.body.replace('The never-list in docs/agents/huntr.md applies in full.', '');}, /never-list/);
refuse('HU1 refuses spec child', (_w, _r, t) => {t.parent = {number: 600, comments: conn([])};}, /standalone/);
refuse('HU1 refuses parent spec', (_w, _r, t) => {t.subIssuesSummary.total = 1;}, /standalone/);
const never = [
  'crates/adapters/cloudroom/src/allowlist.rs', 'crates/core/src/limits.rs',
  'release/openwiz/README.md', 'contracts/inventory.v1.schema.json', 'Cargo.toml', 'Cargo.lock',
  'crates/core/Cargo.toml', 'apps/web/package.json', 'apps/web/package-lock.json',
  'rust-toolchain.toml', '.github/workflows/ci.yml', '.github/actions/docs-only/test.sh',
  'ci/runner/cache.sh', 'skills/huntr/SKILL.md', 'docs/agents/huntr.md', 'docs/adr/0013.md',
  'docs/grills/new.md', 'AGENTS.md', 'apps/web/AGENTS.md', '.claude-plugin/plugin.json',
  '.githooks/pre-push', 'tests/new/Cargo.toml', 'tests/package.json', 'tests/new.schema.json',
];
for (const path of never) refuse(`HU2 never-list ${path}`, (_w, _r, t) => {t.body = body('bug fix', [path]);}, /never-list/);
function add(r, t, started = true) {
  // Old scope-parser regressions model work with an actual started builder.
  if (started && (t.parent || t.comments.nodes.some(c=>c.body.startsWith('**Approved on its own by '))))
    t.comments = conn([...t.comments.nodes, comment('launch-fleet: started, thread thr_synthetic', 999)]);
  r.issues.nodes.push(t); r.issues.totalCount++;
}
for (const owner of ['Jake', 'huntr']) for (const path of ['crates/core/src/ops.rs', 'crates/core/src/'])
  refuse(`HU2 overlaps ${owner} ${path}`, (_w, r) => {add(r, issue(701, {body:`## Owned paths\n\n\`${path}\``, comments:conn([comment(`**Approved on its own by ${owner}, 2026-11-01:** recorded`)]), labels:conn([])}));}, /overlap/);
refuse('HU2 overlap widened in a comment', (_w, r) => {add(r, issue(701, {body:'## Owned paths\n\n`tests/another.rs`', comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'), comment('Owned paths added: `crates/core/src/ops.rs`', 2)])}));}, /overlap/);
refuse('HU2 overlaps approved graph ticket', (_w, r) => {add(r, issue(701, {body:'## Owned paths\n\n`crates/core/src/`', labels: conn([]), parent:{number:600, comments:conn([comment('**Plan graph approved by Jake, 2026-11-01, revision 1:** yes\n\n| #701 | Synthetic | none | ready-for-agent |')])}}));}, /overlap/);
refuse('HU2 unreadable approved scope', (_w, r) => {add(r, issue(701, {body:'No scope', comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes')])}));}, /owned paths/);
test('HC1 policy sets the open cap to 50', () => {
  const policy = JSON.parse(readFileSync(settings, 'utf8').match(/^```json\n([\s\S]*?)\n```$/m)[1]);
  assert.equal(policy.open_cap, 50);
});
refuse('HU2 fiftieth other open ticket refuses the fifty-first', (_w, r) => {for(let i=0;i<50;i++) add(r, issue(800+i));}, /open cap: 50 other huntr issues are open/);
for (const others of [20, 49]) test(`HC1 allows work ticket ${others + 1}, candidate and switch excluded`, () => {
  const w=world(), r=w.pages[0].data.repository;
  for(let i=0;i<others;i++) add(r, issue(800+i));
  add(r, issue(394));
  const result=run(w); assert.equal(result.status, 0, result.stderr); assert.equal(result.posts.length,1);
});
test('HC1 gate reads the open cap from policy JSON', () => {
  const w=world(), r=w.pages[0].data.repository;
  for(let i=0;i<20;i++) add(r, issue(800+i));
  const result=run(w, text=>text.replace(/"open_cap": \d+/, '"open_cap": 20'));
  assert.equal(result.status,2,result.stderr); assert.deepEqual(result.posts,[]);
  assert.match(result.stderr,/open cap: 20 other huntr issues are open/);
});
for (const cap of ['0', '-1', '1.5', '"50"', 'null']) test(`HC1 invalid open cap ${cap} fails closed`, () => {
  const result=run(world(), text=>text.replace(/"open_cap": \d+/, `"open_cap": ${cap}`));
  assert.equal(result.status,2,result.stderr); assert.deepEqual(result.posts,[]);
  assert.match(result.stderr,/settings/);
});
refuse('HC1 reaching 50 other tickets before posting refuses approval', w => {
  const second=structuredClone(w.pages), r=second[0].data.repository;
  for(let i=0;i<50;i++) add(r, issue(800+i));
  w.sequence=[w.pages,second];
}, /open cap: 50 other huntr issues are open/);
refuse('HU2 switch off', (_w, r) => {r.switch.comments=conn([comment('huntr: on',1),comment('huntr: off',2)]);}, /switch.*off/);
refuse('HU2 missing switch state', (_w,r) => {r.switch.comments=conn([]);}, /switch.*off/);
refuse('HU2 absent switch', (_w,r) => {r.switch=null;}, /switch/);
refuse('HU2 missing candidate', (_w,r) => {r.issues=paged([]);}, /candidate/);
refuse('HU2 unreadable API', w => {w.readFailure=true;}, /GitHub read/);
refuse('HU2 GraphQL errors', w => {w.pages[0].errors=[{message:'synthetic'}];}, /GitHub/);
refuse('HU2 null repository', w => {w.pages[0].data.repository=null;}, /repository/);
refuse('HU2 malformed JSON', w => {w.raw='{';}, /JSON/);
refuse('HU2 duplicate JSON keys', w => {w.raw='{"data":null,"data":{}}';}, /duplicate/);
refuse('HU2 no pages', w => {w.pages=[];}, /GitHub/);
refuse('HU2 truncated issues', (_w,r) => {r.issues.totalCount++;}, /incomplete/);
refuse('HU2 missing last page', (_w,r) => {r.issues.pageInfo.hasNextPage=true;r.issues.pageInfo.endCursor='next';}, /incomplete/);
refuse('HU2 duplicate issue', (_w,r,t) => {add(r,t);}, /duplicate/);
refuse('HU2 truncated labels', (_w,_r,t) => {t.labels.totalCount++;}, /incomplete/);
refuse('HU2 truncated comments', (_w,_r,t) => {t.comments.totalCount++;}, /incomplete/);
refuse('HU2 unknown label shape', (_w,_r,t) => {t.labels.nodes[0].name=3;}, /label/);
refuse('HU2 unreadable parent comments', (_w,r) => {add(r, issue(701,{parent:{number:600, comments:{}}}));}, /comments/);
refuse('HU2 no double approval', (_w,_r,t) => {t.comments=conn([comment('**Approved on its own by huntr, 2026-11-01, kind bug fix:** under Jake\'s standing approval (ADR 0013).')]);}, /already approved/);
refuse('HU2 failed comment write', w => {w.postFailure=true;}, /approval write/);
test('HU2 reads all issue pages', () => {
  const w=world(), r=w.pages[0].data.repository;
  r.issues.totalCount=2; r.issues.pageInfo={hasNextPage:true,endCursor:'next'};
  const page=structuredClone(w.pages[0]); page.data.repository.issues.nodes=[issue(701,{labels:conn([])})];page.data.repository.issues.pageInfo={hasNextPage:false,endCursor:null};
  w.pages.push(page); const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
});
test('HU2 settings unreadable fails closed', () => {
  const result=run(world(), () => 'not a settings contract');assert.equal(result.status,2);assert.match(result.stderr,/settings/);assert.deepEqual(result.posts,[]);
});

// Boundaries found while checking the gate's untrusted-input and scope guards.
refuse('HU2 unknown GraphQL envelope key', w=>{w.pages[0].unexpected=true;}, /GitHub/);
refuse('HU2 duplicate label entry', (_w,_r,t)=>{t.labels=conn([{name:'huntr'},{name:'huntr'}]);}, /label/);
refuse('HU2 candidate scope addition on never-list', (_w,_r,t)=>{t.comments=conn([comment('Owned paths added: `crates/core/src/limits.rs`')]);}, /never-list/);
refuse('HU2 candidate comment scope addition outside kind', (_w,_r,t)=>{t.body=body('missing test',['tests/new.rs']);t.comments=conn([comment('Owned paths added: `crates/core/src/ops.rs`')]);}, /kind|tier/);
refuse('HU2 bullet scope addition on approved ticket', (_w,r)=>{add(r,issue(701,{body:'## Owned paths\n\n`tests/another.rs`',comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment('- **Owned paths:** `crates/core/src/ops.rs`',2)])}));}, /overlap/);
refuse('HU2 ambiguous ownership addition', (_w,r)=>{add(r,issue(701,{body:'## Owned paths\n\n`tests/another.rs`',comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment('**Owned paths:** whatever this needs',2)])}));}, /owned paths/);
for (const path of ['tests/existing.rs','tests/linked'])
  refuse(`HU1 refuses checkout directory or link ${path}`, (w,_r,t)=>{t.body=body('missing test',[path]);w.checkout={[path]:path.endsWith('.rs')?'directory':'symlink'};}, /owned paths/);
test('HU2 approval can record scope in its comment alone',()=>{
  const w=world(), r=w.pages[0].data.repository;
  add(r,issue(701,{body:'One already approved problem.',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes\n\n**Owned paths:** `tests/separate.rs`')])}));
  const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
});
test('HU2 proposals do not consume slots; 200 lines allowed',()=>{
  const w=world(),r=w.pages[0].data.repository;r.issues.nodes[0].body=body().replace('120 / 200','200 / 200');
  for(let i=0;i<15;i++)add(r,issue(800+i,{labels:conn([{name:'needs-triage'}])}));
  const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
});
test('HU2 newest switch record wins, unrelated comments ignored',()=>{
  const w=world();w.pages[0].data.repository.switch.comments=conn([comment('huntr: on — resumed',3),comment('huntr: off',1),comment('ordinary note',4)]);
  const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
});
for (const [name,mutate,reason] of [
  ['switch turned off',r=>{r.switch.comments=conn([comment('huntr: off')]);},/switch/],
  ['candidate edited',r=>{r.issues.nodes[0].body=body('missing test',['tests/new.rs']);},/candidate changed/],
  ['overlap appeared',r=>{add(r,issue(701,{comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes')])}));},/overlap/],
]) refuse(`HU2 recheck before posting: ${name}`,(w)=>{
  const second=structuredClone(w.pages);mutate(second[0].data.repository);w.sequence=[w.pages,second];
},reason);

refuse('HU2 free-form recorded path expansion cannot be missed',(_w,r)=>{
  add(r,issue(701,{body:'## Owned paths\n\n`tests/another.rs`',comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment('I added `crates/core/src/ops.rs` to the owned paths.',2)])}));
},/overlap/);
refuse('HU2 unreadable recorded ownership expansion refuses',(_w,r)=>{
  add(r,issue(701,{body:'## Owned paths\n\n`tests/another.rs`',comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment('**Owned paths:** the rest of the component',2)])}));
},/owned paths/);
refuse('HU1 quoted kind in an indented fence is not operative',(_w,_r,t)=>{
  t.body=t.body.replace('## Kind\n\nbug fix\n\n','')+'\n## Notes\n\n   ```text\n## Kind\n\nbug fix\n\n## Ignored\nSynthetic quoted metadata.\n   ```\n';
},/kind|tier/);
refuse('HU2 mixed formatted and bare approved paths protect the overlap',(_w,r)=>{
  add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`\ncrates/core/src/ops.rs',comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes')])}));
},/owned paths/);
refuse('HU2 a scope expansion without owned-path wording is protected',(_w,r)=>{
  add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment('Scope expanded to include `crates/core/src/ops.rs`',2)])}));
},/overlap/);
refuse('HU2 approved directory without a trailing slash protects its children',(w,r)=>{
  w.checkout={'crates/core/src':'directory'};
  add(r,issue(701,{body:'## Owned paths\n\n`crates/core/src`',comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes')])}));
},/owned paths/);
refuse('HU1 comment-only proof is not a declared command',(_w,_r,t)=>{
  t.body=t.body.replace('synthetic-repro --fixture ordering','# no command');
},/proof/);

// PR #439 R1: real ticket prose, expressed entirely with synthetic paths/content.
const reviewScopes = [
  ['annotated folder', '## Owned paths\n\n`tests/proof/` (new: `synthetic.rs`, `helpers/` with its fixtures).', 'tests/proof/new_case.rs'],
  ['glob', '## Owned paths\n\n`tests/fleet/b2_*.rs` (the proof cases).', 'tests/fleet/other_case.rs'],
  ['bare filename', '## Owned paths\n\nThe one line in `Fleets.tsx`.', 'apps/web/src/components/Fleets.tsx'],
];
for (const [name,scope,overlap] of reviewScopes) {
  test(`R1 ${name}: non-overlapping work is approved`,()=>{
    const w=world(),r=w.pages[0].data.repository;
    r.issues.nodes[0].body=body('bug fix',['crates/core/src/zz_huntr_review_fixture.rs']);
    add(r,issue(701,{body:scope,labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes')])}));
    const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
  });
  refuse(`R1 ${name}: overlap is protected`,(_w,r,t)=>{
    t.body=body('bug fix',[overlap]);
    add(r,issue(701,{body:scope,labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes')])}));
  },/overlap/);
}
for (const note of [
  'Builder question: should owned paths now include `crates/*/src/`? Recommend checking the `bug fix` kind.',
  'launch-fleet: the builder asks whether its scope now includes `crates/*/src/`; waiting for the orchestrator.',
]) test('R1 incidental scope mention permits unrelated work: '+note.split(':')[0],()=>{
  const w=world(),r=w.pages[0].data.repository;
  r.issues.nodes[0].body=body('bug fix',['apps/web/src/viewer.ts']);
  add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note,2)])}));
  const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
});
test('R1 own-ticket style annotations do not block unrelated work',()=>{
  const w=world(),r=w.pages[0].data.repository;
  add(r,issue(701,{body:'## Owned paths\n\n`skills/huntr/` (new: `SKILL.md`, `agents/openai.yaml`, `scripts/` with the gate and fixtures), `docs/agents/huntr.md` (new), `tests/checks/skills.rs` (the skill list).',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes')])}));
  const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
});
for (const command of ['huntr: on hold until Monday','huntr: one more note, stay off','huntr: paused','huntr: ON','huntr: on-call'])
  refuse('R2 invalid switch command stays off: '+command,(_w,r)=>{
    r.switch.comments=conn([comment('huntr: on',1),comment('huntr: off',2),comment(command,3)]);
  },/switch/);
refuse('R2 an unknown huntr record overrides a previous on',(_w,r)=>{
  r.switch.comments=conn([comment('huntr: on',1),comment('huntr: pause',2)]);
},/switch/);
for (const command of ['huntr: on\nTechnical note below the command.', 'huntr: on — resumed', 'huntr: on - resumed', 'huntr: on – resumed'])
  test('R2 exact first-line command permits an explicit resume: '+command,()=>{
    const w=world();w.pages[0].data.repository.switch.comments=conn([comment('huntr: off',1),comment(command,2)]);
    const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
  });
for (const overlap of [false,true]) test('R1 legacy standalone body without a scope heading: '+(overlap?'overlap':'unrelated'),()=>{
  const w=world(),r=w.pages[0].data.repository;
  r.issues.nodes[0].body=body('bug fix',[overlap?'tests/support/review_scope.rs':'crates/core/src/zz_huntr_review_fixture.rs']);
  add(r,issue(701,{body:'A small repair belongs in `tests/support/review_scope.rs` and `Helper.ts`.',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes')])}));
  const result=run(w);assert.equal(result.status,overlap?2:0,result.stderr);assert.equal(result.posts.length,overlap?0:1);
  if(overlap)assert.match(result.stderr,/overlap/);
});
test('R1 a person ticket with explicit no owned files does not block work',()=>{
  const w=world(),r=w.pages[0].data.repository;
  add(r,issue(701,{body:"## Owned paths\n\nnone (a person's ticket)\n\n## Proof\n\nObserved by a person.",labels:conn([]),parent:{number:600,comments:conn([comment('**Plan graph approved by Jake, 2026-11-01, revision 1:** yes\n\n| #701 | Synthetic acceptance | none | ready-for-human |')])}}));
  const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
});
for (const question of ['Owned paths: should we include `crates/core/src/ops.rs`?', 'Owned paths: could we include `crates/core/src/ops.rs`. Please advise.'])
  test('R1 a field-like question permits unrelated work: '+question,()=>{
    const w=world(),r=w.pages[0].data.repository;
    r.issues.nodes[0].body=body('bug fix',['crates/core/src/zz_huntr_review_fixture.rs']);
    add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(question,2)])}));
    const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
  });

// PR #439 R3: authoritative widenings are not limited to a fixed line prefix.
const widenedScopes = [
  ['inline answer', '**Q1: owned paths widened** to the synthetic files: `crates/core/src/fleet/synthetic_mod.rs`, `tests/fake-room-cli/synthetic_main.rs`, `tests/messaging/synthetic_allowlist.rs`.', ['crates/core/src/fleet/synthetic_mod.rs','tests/fake-room-cli/synthetic_main.rs','tests/messaging/synthetic_allowlist.rs']],
  ['list after prose', 'Orchestrator: **yes, approved.** Your owned paths now also include:\n- `crates/server/src/synthetic_api.rs`\n- `crates/server/src/synthetic_main.rs`', ['crates/server/src/synthetic_api.rs','crates/server/src/synthetic_main.rs']],
];
for (const [name,note,paths] of widenedScopes) {
  for (const path of paths) refuse(`R3 ${name} protects ${path}`,(_w,r,t)=>{
    t.body=body('bug fix',[path]);
    add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note,2)])}));
  },/overlap being-built ticket #701/);
  test(`R3 ${name} permits unrelated work`,()=>{
    const w=world(),r=w.pages[0].data.repository;r.issues.nodes[0].body=body('bug fix',['apps/web/src/viewer.ts']);
    add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note,2)])}));
    const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
  });
}
refuse('R3 scope hints in questions conservatively protect named files',(_w,r,t)=>{
  t.body=body('bug fix',['apps/web/src/viewer.ts']);
  add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment('Should its scope also cover `apps/web/src/viewer.ts`?',2)])}));
},/overlap/);
for (const note of ['Status: no scope decision yet.', 'Could the owned paths be widened?', 'launch-fleet: scope is being checked.'])
  test('R3 pathless informal note never refuses: '+note,()=>{
    const w=world(),r=w.pages[0].data.repository;
    add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note,2)])}));
    const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
  });

for (const note of [
  'Its scope may also include:\n- `tests/separate.rs`\n\n- `apps/web/src/viewer.ts`',
  '```text\nIts owned paths now include:\n- `apps/web/src/viewer.ts`\n```',
  '**Owned paths:** should these change?',
]) test('R3 scope hints respect blank lines, fences and pathless questions: '+note.split('\n')[0],()=>{
  const w=world(),r=w.pages[0].data.repository;r.issues.nodes[0].body=body('bug fix',['apps/web/src/viewer.ts']);
  add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note,2)])}));
  const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
});
for (const overlap of [false,true]) test('R3 a bare filename glob protects its basename prefix: '+(overlap?'matching':'unrelated'),()=>{
  const w=world(),r=w.pages[0].data.repository;r.issues.nodes[0].body=body('bug fix',[overlap?'tests/proof/c3_synthetic.rs':'apps/web/src/viewer.ts']);
  add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment('Its owned paths also include the `c3_*` proofs.',2)])}));
  const result=run(w);assert.equal(result.status,overlap?2:0,result.stderr);assert.equal(result.posts.length,overlap?0:1);
  if(overlap)assert.match(result.stderr,/overlap/);
});

refuse('R3 a bare glob directory also protects descendant files',(_w,r,t)=>{
  t.body=body('bug fix',['tests/proof/c3_cases/new_case.rs']);
  add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment('Its scope now includes `c3_*/`.',2)])}));
},/overlap/);
for (const note of [
  '## Scope widened: `apps/web/src/viewer.ts`',
  '## Scope widened\n- `apps/web/src/viewer.ts`',
  'Your scope now includes:\n1. `apps/web/src/viewer.ts`',
]) refuse('R3 headings and ordered widening lists protect files: '+note.split('\n')[0],(_w,r,t)=>{
  t.body=body('bug fix',['apps/web/src/viewer.ts']);
  add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note,2)])}));
},/overlap/);
for (const [scope,note] of [
  ['## Owned paths\n\n`tests/separate.rs`','The scope may change later.\nAn unrelated explanation interrupts the list.\n- `apps/web/src/viewer.ts`'],
  ['## Owned paths\n\n`tests/separate.rs`\n```text\n`apps/web/src/viewer.ts`\n```','A status note.'],
]) test('R3 non-list prose and fenced formal examples do not widen scope: '+scope.split('\n').length,()=>{
  const w=world(),r=w.pages[0].data.repository;r.issues.nodes[0].body=body('bug fix',['apps/web/src/viewer.ts']);
  add(r,issue(701,{body:scope,labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note,2)])}));
  const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
});

// PR #439 R4: an asserted widening needs readable paths, even outside a formal field.
for (const note of [
  'Owned paths added: whatever this needs',
  'Owned paths widened to include the rest of the component',
  '**Q1: owned paths widened** to include the rest of the fleet module',
  'The scope expanded to the rest of the component',
  'Your owned paths now include the rest of the component',
  'Your owned paths now also includes the rest of the component',
]) refuse('R4 unreadable widening refuses: '+note,(_w,r,t)=>{
  t.body=body('bug fix',['crates/core/src/fleet/ops.rs']);
  add(r,issue(701,{body:'## Owned paths\n\n`crates/core/src/fleet/starts.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note,2)])}));
},/owned paths/);
refuse('R4 unreadable candidate widening refuses',(_w,_r,t)=>{
  t.comments=conn([comment('Scope expanded to the rest of the component')]);
},/owned paths/);
for (const note of [
  'Could the owned paths be widened?',
  '**Owned paths added:** should this include the rest of the component?',
  'Status: no scope decision yet.',
]) test('R4 pathless questions and status notes remain hints: '+note,()=>{
  const w=world(),r=w.pages[0].data.repository;
  add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note,2)])}));
  const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
});

// #554: risk-tier gate contract, through the public CLI and fake GitHub only.
for (const [tier,kind,paths] of [
  [0,'audit',[]], [1,'missing docs',['docs/synthetic.md']],
  [2,'cleanup',['crates/core/src/ops.rs']], [3,'accessibility fix',['apps/web/src/viewer.ts']],
]) test(`HT approves tier ${tier} with named proof`,()=>{
  const w=world(),t=w.pages[0].data.repository.issues.nodes[0];
  t.body=body(kind,paths,tier).replace('120 / 200',tier===0?'0 / 200':'120 / 200');
  if(tier===0)t.body=t.body.replace('## Owned paths\n\n\n','## Owned paths\n\nnone\n');
  const r=run(w);assert.equal(r.status,0,r.stderr);assert.equal(r.posts.length,1);
  assert.match(r.posts[0].body,new RegExp(`tier ${tier}, kind ${kind}:`));
});
for(const tier of ['4','-1','01','3.0','unknown',''])
  refuse(`HT refuses invalid tier ${JSON.stringify(tier)}`,(_w,_r,t)=>{t.body=t.body.replace('## Tier\n\n3','## Tier\n\n'+tier);},/tier/);
test('HT maximum tier is a setting',()=>{
  const r=run(world(),s=>s.replace('"max_tier": 3','"max_tier": 2'));
  assert.equal(r.status,2);assert.deepEqual(r.posts,[]);assert.match(r.stderr,/above.*setting/);
});
for(const tier of [0,1,2,3]) refuse(`HT tier ${tier} needs a proof`,(_w,_r,t)=>{
  t.body=body('audit',['tests/synthetic.rs'],tier).replace('synthetic-repro --fixture ordering','');
},/proof/);
refuse('HT tier zero cannot change files',(_w,_r,t)=>{t.body=body('audit',['tests/synthetic.rs'],0);},/report only/);
refuse('HT tier one cannot change product code',(_w,_r,t)=>{t.body=body('cleanup',['crates/core/src/ops.rs'],1);},/tier/);
refuse('HT tier two needs unchanged existing tests',(_w,_r,t)=>{
  t.body=body('cleanup',['crates/core/src/ops.rs'],2).replace('## Proof','## Evidence');
},/proof/);
refuse('HT speed claim needs same-machine before and after',(_w,_r,t)=>{
  t.body=body('speed-up',['crates/core/src/ops.rs'],2).replace('## Speed proof\n\nnone','## Speed proof\n\nbefore: fast');
},/speed proof/);
for (const field of ['Machine', 'Before', 'After']) for (const value of ['', '  ', '\t ', '\u00a0 '])
  refuse(`HT speed proof refuses blank ${field} ${JSON.stringify(value)}`,(_w,_r,t)=>{
    const measurements = {Machine: 'synthetic-bench', Before: '12 s', After: '8 s'};
    measurements[field] = value;
    t.body=body('speed-up',['tests/synthetic.rs'],2).replace('## Speed proof\n\nnone',
      `## Speed proof\n\nMachine: ${measurements.Machine}\nBefore: ${measurements.Before}\nAfter: ${measurements.After}\n\n\`\`\`sh\nsynthetic-bench --same-machine\n\`\`\``);
  },/speed proof/);
for (const padding of ['', ' \t']) test(`HT speed proof names machine, before, after and a command ${JSON.stringify(padding)}`,()=>{
  const w=world(),t=w.pages[0].data.repository.issues.nodes[0];
  t.body=body('speed-up',['tests/synthetic.rs'],2).replace('## Speed proof\n\nnone',
    `## Speed proof\n\nMachine: ${padding}synthetic-bench${padding}\nBefore: ${padding}12 s${padding}\nAfter: ${padding}8 s${padding}\n\n\`\`\`sh\nsynthetic-bench --same-machine\n\`\`\``);
  const r=run(w);assert.equal(r.status,0,r.stderr);assert.equal(r.posts.length,1);
});
refuse('HT security fix needs quiet filing and two reviewers',(_w,_r,t)=>{
  t.body=t.body.replace('## Security fix\n\nno','## Security fix\n\nyes');
},/security/);
refuse('R2 security fix stays a proposal until two-reviewer merge enforcement',(_w,_r,t)=>{
  t.body=t.body.replace('## Security fix\n\nno','## Security fix\n\nyes; two reviewers; exploit details withheld until merge');
},/security fixes are proposals/);
for(const record of [null,'launch-fleet: start refused: capacity','launch-fleet: start failed: absent','launch-fleet: start withdrawn'])
  test('HT unstarted approved scope permits work: '+record,()=>{
    const w=world(),r=w.pages[0].data.repository;
    add(r,issue(701,{comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),...(record?[comment(record,2)]:[])])}),false);
    const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
  });
for(const record of ['launch-fleet: starting','launch-fleet: started, thread thr_synthetic','\n  launch-fleet: start checked, thread thr_synthetic, branch room/701-synthetic'])
  refuse('HT actual started builder reserves paths: '+record,(_w,r)=>{
    add(r,issue(701,{labels:conn([]),comments:conn([comment(record)])}),false);
  },/overlap.*built ticket/);
refuse('HT builder starts between reads',w=>{
  const r=w.pages[0].data.repository;
  add(r,issue(701,{comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes')])}),false);
  const second=structuredClone(w.pages);
  second[0].data.repository.issues.nodes[1].comments=conn([comment('launch-fleet: started, thread thr_synthetic')]);
  w.sequence=[w.pages,second];
},/overlap/);

// Tier approval must not fall back to a blacklist of kind names.
test('HT descriptive kind does not decide permission',()=>{
  const w=world(),t=w.pages[0].data.repository.issues.nodes[0];
  t.body=body('contract bug fix',['tests/synthetic.rs'],3);
  const r=run(w);assert.equal(r.status,0,r.stderr);assert.equal(r.posts.length,1);
});
for(const value of ['', 'new feature', 'dependencies', 'unchanged except a contract'])
  refuse('HT product promise declaration fails closed: '+JSON.stringify(value),(_w,_r,t)=>{
    t.body=t.body.replace('## Product promises\n\nNo new features, contracts or dependencies.', '## Product promises\n\n'+value);
  },/product promises/);
refuse('HT proof class must match the tier',(_w,_r,t)=>{
  t.body=t.body.replace('## Proof class\n\nfailing-test-first','## Proof class\n\nreport');
},/proof class/);

refuse('R1 starting claim appears between reads',w=>{
  const r=w.pages[0].data.repository;
  add(r,issue(701,{comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes')])}),false);
  const second=structuredClone(w.pages);
  second[0].data.repository.issues.nodes[1].comments=conn([comment('launch-fleet: starting')]);
  w.sequence=[w.pages,second];
},/overlap/);
test('R1 starting claim permits unrelated files',()=>{
  const w=world(),r=w.pages[0].data.repository;
  add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('launch-fleet: starting')])}),false);
  const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
});

// #900: conditional prose is not a declaration that ownership changed.
for (const note of [
  'launch-fleet: stay inside the ticket unless scope is explicitly widened.',
  'Status: owned paths may be expanded after a separate approval.',
  'No files are added unless the owned paths are widened.',
  'The builder will ask whether scope now includes more files.',
  'Orchestrator: stay inside the ticket unless scope is explicitly widened.',
  'Orchestrator: **yes, approved.** Stay inside the ticket unless scope is explicitly widened.',
]) for (const candidate of [false,true]) test(`#900 pathless prose permits approval (${candidate?'candidate':'started ticket'}): ${note}`,()=>{
  const w=world(),r=w.pages[0].data.repository;
  if (candidate) r.issues.nodes[0].comments=conn([comment(note)]);
  else add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note,2)])}));
  const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
  assert.equal(result.posts[0].number,'700');
});

// #900 R1: explicit attribution/approval prefixes do not hide declarations.
for (const note of [
  'Orchestrator: **yes, approved.** Your owned paths now also include the rest of the component.',
  'Orchestrator: Your owned paths now also include the rest of the component.',
  'Approved: Scope expanded to the rest of the component.',
  'Builder: **approved.** Owned paths widened to include the rest of the component.',
]) for (const candidate of [false,true]) refuse(`#900 R1 attributed assertion refuses (${candidate?'candidate':'started ticket'}): ${note}`,(_w,r,t)=>{
  if (candidate) t.comments=conn([comment(note)]);
  else add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note,2)])}));
},/unreadable owned paths declaration/);

// #900 R2: an explicit policy condition does not assert a scope change.
const conditionalScopes = [
  'Orchestrator: Scope is widened only if separate approval is granted; otherwise stay inside the ticket.',
  'Orchestrator: Scope is widened only after separate approval.',
];
for (const note of conditionalScopes) for (const candidate of [false,true]) {
  test(`#900 R2 conditional policy permits approval (${candidate?'candidate':'started ticket'}): ${note}`,()=>{
    const w=world(),r=w.pages[0].data.repository;
    if (candidate) r.issues.nodes[0].comments=conn([comment(note)]);
    else add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note,2)])}));
    const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
    assert.equal(result.posts[0].number,'700');
  });
  refuse(`#900 R2 conditional policy still protects named paths (${candidate?'candidate':'started ticket'}): ${note}`,(_w,r,t)=>{
    if (candidate) t.comments=conn([comment(note+' Consider `docs/agents/huntr.md`.')]);
    else add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note+' Consider `crates/core/src/ops.rs`.',2)])}));
  },candidate?/never-list/:/overlap/);
}
for (const candidate of [false,true]) refuse(`#900 R2 later policy text does not hide an assertion (${candidate?'candidate':'started ticket'})`,(_w,r,t)=>{
  const note='Orchestrator: Scope is widened to the rest of the component; only after this, build.';
  if (candidate) t.comments=conn([comment(note)]);
  else add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note,2)])}));
},/unreadable owned paths declaration/);

// #900 R3: completed declarations require readable paths despite a condition.
for (const note of [
  'Scope has been widened only after separate approval was granted, to include the rest of the component.',
  'Orchestrator: Owned paths have been expanded only after separate approval was granted, to include the rest of the component.',
  'Approved: Scope widened only after separate approval was granted, to include the rest of the component.',
]) for (const candidate of [false,true]) {
  refuse(`#900 R3 completed declaration refuses (${candidate?'candidate':'started ticket'}): ${note}`,(_w,r,t)=>{
    if (candidate) t.comments=conn([comment(note)]);
    else add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note,2)])}));
  },/unreadable owned paths declaration/);
  refuse(`#900 R3 completed declaration protects named paths (${candidate?'candidate':'started ticket'}): ${note}`,(_w,r,t)=>{
    if (candidate) t.comments=conn([comment(note+' Added `docs/agents/huntr.md`.')]);
    else add(r,issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([]),comments:conn([comment('**Approved on its own by Jake, 2026-11-01:** yes'),comment(note+' Added `crates/core/src/ops.rs`.',2)])}));
  },candidate?/never-list/:/overlap/);
}

for (const pointer of ['', 'https://github.com/example/public/issues/1#issuecomment-1', 'https://github.com/jparker2006/ClosedWiz/issues/01#issuecomment-2']) {
  refuse('#1273 malformed private pointer ' + pointer, w => {w.pointer=pointer;}, /private standing approval comment/);
}
refuse('#1273 missing private record refuses approval', w => {w.pointerMissing=true;}, /private standing approval could not be read/);

// #1244: the public CLI must use every page before making its approval decision.
// All values and cursors below are synthetic; no live approval command is run.
function paginate(w, target, number, field, nodes) {
  const pages=[];
  for (let i=0;i<nodes.length;i+=100) pages.push({totalCount:nodes.length,
    nodes:nodes.slice(i,i+100), pageInfo:{hasNextPage:i+100<nodes.length,endCursor:`synthetic-${i+100}`}});
  target[field]=pages[0];
  w.connections ??= {};
  w.connections[`${number}:${field}`]=pages.slice(1).map((value,i)=>({after:pages[i].pageInfo.endCursor,value}));
  return pages;
}
const notes = count => Array.from({length:count},(_,i)=>comment('Synthetic note.',i+1));
const labels = count => Array.from({length:count},(_,i)=>({name:`synthetic-${i}`}));
for (const count of [100,117,150,200,530]) for (const location of ['candidate','other','parent','switch'])
  test(`#1244 reads all ${count} ${location} comments before approving once`,()=>{
    const w=world(),r=w.pages[0].data.repository;
    let target=r.issues.nodes[0];
    if(location==='other') {target=issue(701,{labels:conn([])});add(r,target,false);}
    if(location==='parent') {target={number:600};add(r,issue(701,{labels:conn([]),parent:target}),false);}
    if(location==='switch') target=r.switch;
    const records=notes(count);
    if(location==='switch') records.at(-1).body='huntr: on';
    paginate(w,target,target.number,'comments',records);
    const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
  });
test('#1244 reads huntr label on the second label page',()=>{
  const w=world(),t=w.pages[0].data.repository.issues.nodes[0];
  paginate(w,t,t.number,'labels',[...labels(149),{name:'huntr'}]);
  const r=run(w);assert.equal(r.status,0,r.stderr);assert.equal(r.posts.length,1);
});
refuse('#1244 latest switch off on page six refuses', (w,r)=>{
  const records=notes(530);records[0].body='huntr: on';records.at(-1).body='huntr: off';
  paginate(w,r.switch,r.switch.number,'comments',records);
},/switch.*off/);
refuse('#1244 prior candidate approval on page two refuses',(w,_r,t)=>{
  const records=notes(117);records.at(-1).body='**Approved on its own by huntr, 2026-01-01:** synthetic approval';
  paginate(w,t,t.number,'comments',records);
},/already approved/);
refuse('#1244 builder scope on page two protects overlap',(w,r)=>{
  const other=issue(701,{body:'## Owned paths\n\n`tests/separate.rs`',labels:conn([])});
  add(r,other,false);
  const records=notes(117);records[0].body='launch-fleet: starting';
  records.at(-1).body='Owned paths added: `crates/core/src/ops.rs`';
  paginate(w,other,701,'comments',records);
},/overlap/);
refuse('#1244 open cap includes huntr label on page two',(w,r)=>{
  for(let i=0;i<49;i++) add(r,issue(800+i));
  const other=issue(900);add(r,other,false);
  paginate(w,other,900,'labels',[...labels(149),{name:'huntr'}]);
},/open cap/);
for(const field of ['comments','labels']) for(const [name,change,reason] of [
  ['short last page',p=>{p[1].nodes.pop();},/incomplete/],
  ['count changes',p=>{p[1].totalCount++;},/incomplete/],
  ['too many nodes',p=>{p[1].nodes.push(p[1].nodes[0]);},/incomplete/],
  ['missing last page',p=>{p[1].pageInfo.hasNextPage=true;},/incomplete/],
  ['early end',p=>{p[0].pageInfo.hasNextPage=false;},/incomplete/],
  ['missing cursor',p=>{p[0].pageInfo.endCursor=null;},/cursor/],
  ['duplicate entry',p=>{p[1].nodes[0]=p[0].nodes[0];},/duplicate/],
]) refuse(`#1244 ${field} ${name} refuses`,(w,_r,t)=>{
  const pages=paginate(w,t,t.number,field,field==='comments'?notes(117):[...labels(116),{name:'huntr'}]);
  change(pages);
},reason);
for(const field of ['comments','labels']) {
  refuse(`#1244 ${field} failed second page refuses`,(w,_r,t)=>{
    paginate(w,t,t.number,field,field==='comments'?notes(117):labels(117));
    w.connections[`${t.number}:${field}`][0].failure=true;
  },/GitHub read/);
  refuse(`#1244 ${field} duplicate cursor refuses`,(w,_r,t)=>{
    const pages=paginate(w,t,t.number,field,field==='comments'?notes(530):labels(530));
    pages[1].pageInfo.endCursor=pages[0].pageInfo.endCursor;
  },/cursor/);
}
refuse('#1244 malformed last parent comment refuses',(w,r)=>{
  const parent={number:600};add(r,issue(701,{labels:conn([]),parent}),false);
  const records=notes(117);records.at(-1).body=null;
  paginate(w,parent,600,'comments',records);
},/comments/);
for(const field of ['comments','labels']) for(const [name,change,reason] of [
  ['short intermediate page',p=>{p.value.nodes.pop();},/incomplete/],
  ['GraphQL error',p=>{p.envelope={errors:[{message:'Synthetic error.'}],data:null};},/GitHub/],
  ['invalid JSON',p=>{p.raw='{';},/JSON/],
  ['duplicate JSON key',p=>{p.raw='{"data":null,"data":null}';},/duplicate/],
  ['wrong issue',p=>{p.envelope={data:{repository:{issue:{number:701}}}};p.envelope.data.repository.issue[field]=p.value;},/inconsistent/],
  ['missing page info',p=>{delete p.value.pageInfo;},/unreadable/],
  ['invalid next flag',p=>{p.value.pageInfo.hasNextPage='false';},/unreadable/],
]) refuse(`#1244 ${field} ${name} refuses`,(w,_r,t)=>{
  paginate(w,t,t.number,field,field==='comments'?notes(530):labels(530));
  change(w.connections[`${t.number}:${field}`][0]);
},reason);
refuse('#1244 failed page in second approval read refuses',(w,_r,t)=>{
  paginate(w,t,t.number,'comments',notes(117));
  const failed=structuredClone(w.connections);failed['700:comments'][0].failure=true;
  w.connectionSequence=[w.connections,failed];
},/GitHub read/);
refuse('#1244 later candidate page changes between approval reads',(w,_r,t)=>{
  paginate(w,t,t.number,'comments',notes(117));
  const changed=structuredClone(w.connections);changed['700:comments'][0].value.nodes.at(-1).body='Synthetic edit.';
  w.connectionSequence=[w.connections,changed];
},/candidate changed/);
test('#1244 nested cursors stay independent across outer issue pages',()=>{
  const w=world(),r=w.pages[0].data.repository,t=r.issues.nodes[0];
  paginate(w,t,700,'comments',notes(117));
  paginate(w,t,700,'labels',[...labels(149),{name:'huntr'}]);
  const records=notes(530);records.at(-1).body='huntr: on';
  paginate(w,r.switch,394,'comments',records);
  for(let i=0;i<99;i++) add(r,issue(800+i,{labels:conn([])}),false);
  const last=structuredClone(w.pages[0]);
  r.issues.totalCount=102;r.issues.pageInfo={hasNextPage:true,endCursor:'synthetic-issues'};
  last.data.repository.issues=paged([issue(899,{labels:conn([])}),issue(900,{labels:conn([])})]);
  last.data.repository.issues.totalCount=102;
  const parent={number:600};last.data.repository.issues.nodes[0].parent=parent;
  paginate(w,parent,600,'comments',notes(150));
  w.pages.push(last);
  const result=run(w);assert.equal(result.status,0,result.stderr);assert.equal(result.posts.length,1);
});
