#!/usr/bin/env node
// A synthetic GitHub for the controller lease and hunter provisioning (#1685): no network.
// State: comments [{id, created_at, body}], clock (ISO time of the next post, else now),
// race (a rival body posted just before ours), readFailure, readFailures (fail only the next N
// reads), postFailure, auth ('fail').
import { readFileSync, writeFileSync, appendFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
const file = process.env.HUNTR_FAKE_STATE;
const w = JSON.parse(readFileSync(file, 'utf8'));
const a = process.argv.slice(2);
appendFileSync(process.env.HUNTR_FAKE_LOG, JSON.stringify(a) + '\n');
const stamp = () => w.clock ?? new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
const add = body => {
  const id = Math.max(99, ...w.comments.map(c => c.id)) + 1;
  w.comments.push({id, created_at: stamp(), body});
  return id;
};
const repo = process.env.GH_REPO;
if (a.join(' ') === `api --paginate --slurp repos/${repo}/issues/394/comments?per_page=100`) {
  const failing = w.readFailure || w.readFailures > 0;
  if (w.readFailures > 0) { w.readFailures--; writeFileSync(file, JSON.stringify(w)); }
  if (failing) { process.stderr.write('synthetic read failure\n'); process.exit(1); }
  const pages = [];
  for (let i = 0; i < w.comments.length || !pages.length; i += 100) pages.push(w.comments.slice(i, i + 100));
  process.stdout.write(JSON.stringify(pages));
} else if (a[0] === 'issue' && a[1] === 'comment' && a[2] === '394' && a[3] === '--body-file' && a.length === 5) {
  if (w.postFailure) { process.stderr.write('synthetic post failure\n'); process.exit(1); }
  if (w.race) { add(w.race); delete w.race; }
  const id = add(readFileSync(a[4], 'utf8'));
  writeFileSync(file, JSON.stringify(w));
  process.stdout.write(`https://github.com/${repo}/issues/394#issuecomment-${id}\n`);
} else if (a.join(' ') === 'auth status' || a.join(' ') === 'auth setup-git') {
  if (w.auth === 'fail') { process.stderr.write('synthetic: not logged in\n'); process.exit(1); }
} else if (a[0] === 'repo' && a[1] === 'clone' && a[2] === repo && a.length >= 4) {
  execFileSync('git', ['clone', '-q', process.env.HUNTR_FAKE_ORIGIN, a[3]], {stdio: 'ignore'});
} else { process.stderr.write('unexpected fake gh command: ' + JSON.stringify(a) + '\n'); process.exit(1); }
