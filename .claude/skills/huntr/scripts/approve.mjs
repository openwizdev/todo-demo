#!/usr/bin/env node
// huntr's only approval writer. GitHub reads are untrusted; never execute proof text.
import { readFileSync, writeFileSync, mkdtempSync, rmSync, lstatSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';

const fail = reason => { throw new Error(reason); };
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const integer = x => Number.isSafeInteger(x) && x >= 0;
function json(text) {
  // JSON.parse checks grammar; scan its valid tokens to reject repeated object keys.
  const value = JSON.parse(text);
  const stack = [];
  for (const token of text.match(/"(?:[^"\\]|\\.)*"|[{}\[\],:]|[^\s{}\[\],:]+/g) ?? []) {
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
function exact(value, keys, what) {
  if (!object(value) || Object.keys(value).sort().join('\n') !== [...keys].sort().join('\n')) fail(`unreadable ${what}`);
}
function connection(value, what, paginated = false) {
  exact(value, paginated ? ['totalCount','pageInfo','nodes'] : ['totalCount','nodes'], what);
  if (!integer(value.totalCount) || !Array.isArray(value.nodes)) fail(`unreadable ${what}`);
  if (paginated) {
    exact(value.pageInfo, ['hasNextPage','endCursor'], what);
    if (typeof value.pageInfo.hasNextPage !== 'boolean' || !(value.pageInfo.endCursor === null || typeof value.pageInfo.endCursor === 'string')) fail(`unreadable ${what}`);
  } else if (value.totalCount !== value.nodes.length) fail(`incomplete ${what}`);
  return value.nodes;
}
function comments(value) {
  const nodes = connection(value, 'comments');
  const ids = new Set();
  for (const c of nodes) {
    exact(c, ['databaseId','body'], 'comment');
    if (!integer(c.databaseId) || c.databaseId === 0 || ids.has(c.databaseId) || typeof c.body !== 'string') fail('unreadable or duplicate comments');
    ids.add(c.databaseId);
  }
  return [...nodes].sort((a,b) => a.databaseId - b.databaseId);
}
function issue(value) {
  exact(value, ['number','state','body','labels','comments','parent','subIssuesSummary'], 'issue');
  if (!integer(value.number) || value.number === 0 || value.state !== 'OPEN' || typeof value.body !== 'string') fail('unreadable issue');
  const labels = connection(value.labels, 'labels');
  for (const l of labels) { exact(l,['name'],'label'); if (typeof l.name !== 'string') fail('unreadable label'); }
  if (new Set(labels.map(l=>l.name)).size !== labels.length) fail('duplicate label');
  comments(value.comments);
  exact(value.subIssuesSummary, ['total'], 'subissue count');
  if (!integer(value.subIssuesSummary.total)) fail('unreadable subissue count');
  if (value.parent !== null) {
    exact(value.parent, ['number','comments'], 'parent');
    if (!integer(value.parent.number) || value.parent.number === 0) fail('unreadable parent');
    comments(value.parent.comments);
  }
  return value;
}
// Each connection owns its cursor. gh's automatic pagination cannot advance
// the outer issue list and several independent nested connections together.
const PAGE_FIELDS = 'totalCount pageInfo { hasNextPage endCursor }';
const COMMENT_FIELDS = `${PAGE_FIELDS} nodes { databaseId body }`;
const LABEL_FIELDS = `${PAGE_FIELDS} nodes { name }`;
const QUERY = `query HuntrGate($owner:String!, $name:String!, $endCursor:String, $switch:Int!) {
 repository(owner:$owner,name:$name) {
  switch: issue(number:$switch) { number comments(first:100) { ${COMMENT_FIELDS} } }
  issues(states:OPEN,first:100,after:$endCursor,orderBy:{field:CREATED_AT,direction:ASC}) {
   ${PAGE_FIELDS} nodes {
    number state body subIssuesSummary { total }
    labels(first:100) { ${LABEL_FIELDS} }
    comments(first:100) { ${COMMENT_FIELDS} }
    parent { number comments(first:100) { ${COMMENT_FIELDS} } }
   }
  }
 }
}`;
function gh(args, what) {
  try { return execFileSync('gh', args, {encoding:'utf8',stdio:['ignore','pipe','pipe'],maxBuffer:64*1024*1024,timeout:60000}); }
  catch { fail(what); }
}
function graphql(repo, query, fields) {
  const args=['api','graphql','-f',`owner=${repo.split('/')[0]}`,'-f',`name=${repo.split('/')[1]}`,'-f',`query=${query}`];
  for (const [key,value] of Object.entries(fields)) args.push(typeof value === 'number' ? '-F' : '-f',`${key}=${value}`);
  let p;
  try { p=json(gh(args,'GitHub read failed')); }
  catch (e) { if (e instanceof SyntaxError) fail('unreadable GitHub JSON'); throw e; }
  if (!object(p) || (p.errors !== undefined && (!Array.isArray(p.errors) || p.errors.length))) fail('GitHub error');
  exact(p, p.errors === undefined ? ['data'] : ['data','errors'], 'GitHub envelope');
  exact(p.data, ['repository'], 'GitHub data');
  return p.data.repository;
}
function readConnection(repo, number, field, first) {
  if (!integer(number) || number === 0) fail('unreadable issue number');
  const nodes=[], cursors=new Set();
  let page=first, total;
  for (;;) {
    const batch=connection(page,field,true);
    total ??= page.totalCount;
    if (total !== page.totalCount || batch.length !== Math.min(100,total-nodes.length)) fail(`incomplete ${field} count`);
    nodes.push(...batch);
    if (page.pageInfo.hasNextPage !== (nodes.length < total)) fail(`incomplete ${field} pages`);
    if (!page.pageInfo.hasNextPage) return {totalCount:total,nodes};
    const cursor=page.pageInfo.endCursor;
    if (!cursor || cursors.has(cursor)) fail(`incomplete or duplicate ${field} cursor`);
    cursors.add(cursor);
    const query=`query HuntrConnection($owner:String!, $name:String!, $number:Int!, $after:String!) {
 repository(owner:$owner,name:$name) { issue(number:$number) {
  number ${field}(first:100,after:$after) { ${field === 'comments' ? COMMENT_FIELDS : LABEL_FIELDS} }
 } }
}`;
    const r=graphql(repo,query,{number,after:cursor});
    exact(r,['issue'],'connection repository');
    exact(r.issue,['number',field],`issue ${field}`);
    if (r.issue.number !== number) fail(`inconsistent ${field} issue number`);
    page=r.issue[field];
  }
}
function readWorld(repo, switchNumber) {
  let total, switchState, after;
  const issues = [], ids = new Set(), cursors = new Set();
  for (;;) {
    const r=graphql(repo,QUERY,{switch:switchNumber,...(after === undefined ? {} : {endCursor:after})});
    exact(r, ['switch','issues'], 'repository');
    exact(r.switch,['number','comments'],'switch');
    if (r.switch.number !== switchNumber) fail('unreadable switch number');
    const state=comments(readConnection(repo,switchNumber,'comments',r.switch.comments));
    if (switchState && JSON.stringify(switchState) !== JSON.stringify(state)) fail('switch changed during read');
    switchState=state;
    const nodes=connection(r.issues,'issues',true);
    if (total !== undefined && total !== r.issues.totalCount) fail('incomplete issues: changed during read');
    total=r.issues.totalCount;
    for (const node of nodes) {
      exact(node,['number','state','body','labels','comments','parent','subIssuesSummary'],'issue');
      if(ids.has(node.number)) fail('duplicate issue');
      ids.add(node.number);
      node.labels=readConnection(repo,node.number,'labels',node.labels);
      node.comments=readConnection(repo,node.number,'comments',node.comments);
      if (node.parent !== null) {
        exact(node.parent,['number','comments'],'parent');
        node.parent.comments=readConnection(repo,node.parent.number,'comments',node.parent.comments);
      }
      issue(node);issues.push(node);
    }
    if (!r.issues.pageInfo.hasNextPage) break;
    if (!nodes.length || issues.length >= total) fail('incomplete issues pages');
    after=r.issues.pageInfo.endCursor;
    if (!after || cursors.has(after)) fail('incomplete or duplicate issue cursor');
    cursors.add(after);
  }
  if (total !== issues.length) fail('incomplete issues count');
  return {issues, switchState};
}
function section(text, heading) {
  const lines=text.replaceAll('\r\n','\n').split('\n');
  let fence = null;
  const active = lines.map(line => {
    const mark = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if (mark) {
      if (!fence) fence = mark[1];
      else if (mark[1][0] === fence[0] && mark[1].length >= fence.length && !mark[2].trim()) fence = null;
      return false;
    }
    return fence === null;
  });
  if (fence) fail('unreadable issue: unclosed fence');
  const starts=lines.flatMap((line,i) => active[i] && line === `## ${heading}` ? [i] : []);
  if (starts.length !== 1) fail(`missing or duplicate ${heading.toLowerCase()}`);
  const from=starts[0]+1, end=lines.findIndex((line,i) => i>=from && active[i] && /^#{1,2} /.test(line));
  return lines.slice(from,end<0?undefined:end).join('\n').trim();
}

function policy() {
  try {
    const source=readFileSync('docs/agents/huntr.md','utf8');
    const blocks=[...source.matchAll(/^```json\n([\s\S]*?)\n```$/gm)];
    if (blocks.length !== 1) fail('one settings JSON block is required');
    const p=json(blocks[0][1]);
    exact(p,['version','label','switch_issue','max_changed_lines','open_cap','max_tier','tiers','groups','never_prefixes','never_names','never_name_prefixes','never_components','never_suffixes'],'settings');
    if (p.version !== 2 || p.label !== 'huntr' || !integer(p.switch_issue) || !p.switch_issue ||
        p.max_changed_lines !== 200 || !integer(p.open_cap) || !p.open_cap || !integer(p.max_tier) || p.max_tier > 3) fail('invalid settings constants');
    exact(p.tiers,['0','1','2','3'],'settings tiers');
    exact(p.groups,['code','tests','docs'],'settings groups');
    const strings = xs => Array.isArray(xs) && xs.every(x => typeof x === 'string' && x.length > 0) && new Set(xs).size === xs.length;
    for (const name of Object.keys(p.groups)) {
      const g=p.groups[name];exact(g,['prefixes','suffixes','root_suffixes'],'settings group');
      if (![g.prefixes,g.suffixes,g.root_suffixes].every(strings) || g.prefixes.some(x=>!x.endsWith('/'))) fail('invalid settings group');
    }
    for (const names of Object.values(p.tiers)) if (!strings(names) || names.some(x=>!Object.hasOwn(p.groups,x))) fail('invalid settings tier');
    for (const key of ['never_prefixes','never_names','never_name_prefixes','never_components','never_suffixes'])
      if (!strings(p[key]) || !p[key].length) fail('invalid settings never-list');
    return p;
  } catch (e) { fail(`unreadable settings: ${e.message}`); }
}
function validPath(path, folder = false) {
  const file = folder && path.endsWith('/') ? path.slice(0,-1) : path;
  return /^[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*$/.test(file) &&
    file.split('/').every(x => x !== '.' && x !== '..');
}
function never(path,p) {
  const parts=path.split('/');
  return p.never_prefixes.some(x=>path.startsWith(x)) ||
    parts.some(x=>p.never_names.includes(x) || p.never_name_prefixes.some(pre=>x.startsWith(pre)) || p.never_components.includes(x)) ||
    p.never_suffixes.some(x=>path.endsWith(x));
}
function allowed(path,tier,p) {
  return p.tiers[tier].some(name=> {
    const group=p.groups[name];
    return (group.prefixes.some(x=>path.startsWith(x)) && (!group.suffixes.length || group.suffixes.some(x=>path.endsWith(x)))) ||
      (!path.includes('/') && group.root_suffixes.some(x=>path.endsWith(x)));
  });
}
function exactFile(path) {
  // Check the consuming checkout where available, including symlink ancestors.
  let current='';
  for (const [i,part] of path.split('/').entries()) {
    current += (i ? '/' : '')+part;
    try {
      const st=lstatSync(current);
      if (st.isSymbolicLink() || (current === path && !st.isFile())) fail('owned paths must be exact files, not directories or links');
    } catch (e) {
      if (e.code === 'ENOENT') return; // A declared new file is allowed.
      throw e;
    }
  }
}
function intent(candidate,p) {
  if (!candidate.labels.nodes.some(x=>x.name === p.label)) fail('candidate needs huntr label');
  if (candidate.parent || candidate.subIssuesSummary.total) fail('candidate must be standalone, not a spec or graph ticket');
  if (comments(candidate.comments).some(c=>/^\s*\*\*Approved on its own by /.test(c.body))) fail('candidate already approved; reconcile instead of repeating');
  const tierText=section(candidate.body,'Tier');
  if (!/^[0-3]$/.test(tierText)) fail('unknown or missing tier');
  const tier=Number(tierText);
  if (tier > p.max_tier) fail('tier above the setting');
  const kind=section(candidate.body,'Kind');
  if (!/^[A-Za-z][A-Za-z0-9 -]*$/.test(kind)) fail('unknown or missing kind');
  if (section(candidate.body,'Product promises') !== 'No new features, contracts or dependencies.') fail('product promises require a proposal');
  const proofClass=['report','coverage-or-docs','unchanged-existing-tests','failing-test-first'][tier];
  if (section(candidate.body,'Proof class') !== proofClass) fail('proof class must match the tier');
  const problem=section(candidate.body,'Problem');
  if (!problem || /\n\s*\n/.test(problem)) fail('problem must declare one problem in one paragraph');
  proofCommand(section(candidate.body,'Proof'),'proof');
  const speed=section(candidate.body,'Speed proof');
  if (speed !== 'none') {
    if (tier !== 2 || !/^Machine: [^\n]*\S[^\n]*\nBefore: [^\n]*\S[^\n]*\nAfter: [^\n]*\S[^\n]*\n\n/.test(speed)) fail('speed proof needs same-machine before and after measurements');
    proofCommand(speed.slice(speed.indexOf('\n\n')+2),'speed proof');
  }
  const security=section(candidate.body,'Security fix');
  if (security !== 'no') fail('security fixes are proposals until the merge loop requires two exact-head approvals');
  const size=section(candidate.body,'Size').match(/^(0|[1-9][0-9]*) \/ 200 changed lines \(added \+ deleted\)$/);
  if (!size || !Number.isSafeInteger(Number(size[1])) || Number(size[1]) > p.max_changed_lines) fail('size must declare at most 200 added + deleted lines');
  if (section(candidate.body,'Never-list') !== 'The never-list in docs/agents/huntr.md applies in full.') fail('missing full never-list declaration');
  const scope=section(candidate.body,'Owned paths');
  const lines=tier === 0 && scope === 'none' ? [] : scope.split('\n');
  const paths=lines.map(line=>line.match(/^- `([^`]+)`$/)?.[1]);
  if ((tier !== 0 && !paths.length) || paths.some(path=>!path || !validPath(path)) || new Set(paths).size !== paths.length) fail('owned paths must list exact, unique repository files');
  const allPaths=[...new Set([...paths,...comments(candidate.comments).flatMap(c=>protectedPaths(c.body).paths)])];
  if (allPaths.some(path=>!validPath(path))) fail('candidate owned paths must be exact files');
  if (tier === 0 && (allPaths.length || Number(size[1]) !== 0)) fail('tier 0 is report only: no changed files or lines');
  for (const path of allPaths) {
    if (never(path,p)) fail(`never-list path: ${path}`);
    exactFile(path);
    if (!path.includes('/') && !path.includes('.')) fail('owned paths must be exact files');
    if (!allowed(path,tier,p)) fail(`path outside tier ${tier}: ${path}`);
  }
  return {kind,tier,paths:allPaths};
}
function protectedPaths(text,legacyBody=false) {
  const chunks=[];
  let owned=-1, hint=-1, fence=null;
  for (const raw of text.replaceAll('\r\n','\n').split('\n')) {
    const mark=raw.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    const quoted=fence !== null;
    if (mark) {
      if (!fence) fence=mark[1];
      else if (mark[1][0] === fence[0] && mark[1].length >= fence.length && !mark[2].trim()) fence=null;
    }
    if (!quoted && !mark && /^#{1,2} /.test(raw)) {
      owned=-1;hint=-1;
      if (/^## Owned paths\s*$/i.test(raw)) {
        chunks.push({text:'',strict:true,bare:true});owned=chunks.length-1;
        continue;
      }
    }
    if (quoted || mark) { hint=-1; continue; }
    if (owned >= 0) { chunks[owned].text+=raw+'\n'; continue; }
    if (!raw.trim()) { hint=-1; continue; }
    const line=raw.trim().replace(/^[-*+]\s+/, '');
    const plain=line.replaceAll('**','');
    if (/\b(owned paths|scope)\b/i.test(plain)) {
      const question=/\?\s*$/.test(plain) || /:\s*(?:should|could|would|can|may|shall|do|does|is|are)\b/i.test(plain);
      const strict=/^Owned paths\s*:/i.test(plain) && !question;
      chunks.push({text:line,strict,bare:strict});hint=chunks.length-1;
    } else if (hint >= 0) {
      if (/^\s*(?:[-*+]|[0-9]+[.)])\s+/.test(raw)) chunks[hint].text+='\n'+raw;
      else hint=-1;
    }
  }
  if (legacyBody && !chunks.some(c=>c.strict)) chunks.push({text,strict:false,bare:true,legacy:true});
  const paths=[];
  for (const chunk of chunks) {
    if (chunk.strict && /^none(?:\s*\(a person's ticket\))?\.?$/i.test(chunk.text.trim())) continue;
    const quoted=[...chunk.text.matchAll(/`([^`]+)`/g)].map(x=>x[1]);
    const bare=chunk.text.replace(/`[^`]+`/g,'');
    // Formal declarations and legacy bodies also protect obvious unformatted paths.
    const unquoted=chunk.bare ? [...bare.matchAll(/(?:[A-Za-z0-9_.*-]+\/)+[A-Za-z0-9_.*\/-]*|\b[A-Za-z0-9_-]+\.[A-Za-z0-9_.*-]+\b/g)].map(x=>x[0]) : [];
    const tokens=[...quoted,...unquoted].filter(x=>validPath(x.replaceAll('*','x'),true));
    const first=chunk.text.split('\n',1)[0].replaceAll('**','');
    // Recognize an ownership assertion after explicit attribution/approval,
    // while keeping conditional prose about a possible widening as a hint.
    const assertion=first.replace(/^#{1,6}\s+/, '')
      .replace(/^(?:orchestrator|builder|reviewer):\s*/i, '')
      .replace(/^(?:yes,?\s+)?approved\b[.!:]?\s*/i, '');
    const widening=!chunk.legacy && !/\?\s*$/.test(first) && assertion.match(/^(?:Q[0-9]+:\s*)?(?:(?:the|your|its)\s+)?(?:owned paths|scope)\s+(?:(is|are|has been|have been)\s+)?(?:added|widened|expanded|now (?:also )?include[sd]?)\b(.*)$/i);
    // Only generic is/are policy wording gets this exception; completed
    // declarations still need paths. Named paths always add protection.
    const conditionalPolicy=widening && /^(?:is|are)$/i.test(widening[1] ?? '') && /^\s+only\s+(?:if|after)\b/i.test(widening[2]);
    if (!tokens.length && (chunk.strict || (widening && !conditionalPolicy))) fail('approved ticket has unreadable owned paths declaration');
    paths.push(...tokens);
  }
  return {paths:[...new Set(paths)],declared:chunks.some(c=>c.strict)};
}
function overlaps(owned,path) {
  const star=owned.indexOf('*');
  if (star >= 0) {
    const slash=owned.lastIndexOf('/',star);
    return slash < 0 ? path.split('/').some(part=>part.startsWith(owned.slice(0,star))) : path.startsWith(owned.slice(0,slash+1));
  }
  if (owned.endsWith('/')) return path.startsWith(owned);
  if (!owned.includes('/')) return path === owned || path.endsWith('/'+owned);
  return path === owned || path.startsWith(owned+'/');
}
function switchOn(records) {
  const lines=records.map(c=>c.body.split(/\r?\n/,1)[0]);
  const latest=lines.filter(line=>line.startsWith('huntr:')).at(-1);
  return latest?.match(/^huntr: (on|off)(?:\s+[—–-]\s.*)?$/)?.[1] === 'on';
}
function proofCommand(text,what) {
  const proof=text.match(/^```sh\n([\s\S]*?)\n```(?:\n[\s\S]*)?$/);
  if (!proof || !proof[1].split('\n').some(line=>line.trim() && !line.trim().startsWith('#'))) fail(`${what} needs a named evidence command`);
}
function beingBuilt(ticket) {
  // Match the fleet's first-nonblank-line records. Approval or a branch alone
  // is not evidence that a builder started. An unresolved starting claim may
  // already have spawned one, so it reserves files until reconciled.
  return comments(ticket.comments).some(c=> {
    const line=c.body.split(/\r?\n/).find(x=>x.trim())?.trim() ?? '';
    return /^launch-fleet:\s*(starting|started|start checked)\b/.test(line);
  });
}
function evaluate(world,number,p) {
  if (!switchOn(world.switchState)) fail('switch is off or has no readable on record');
  const candidate=world.issues.find(x=>x.number === number);
  if (!candidate || number === p.switch_issue) fail('candidate is not an open work issue');
  const plan=intent(candidate,p);
  if (world.issues.filter(x=>x.number !== number && x.number !== p.switch_issue && x.labels.nodes.some(l=>l.name === p.label)).length >= p.open_cap) fail(`open cap: ${p.open_cap} other huntr issues are open`);
  for (const ticket of world.issues) {
    if (ticket.number === number || ticket.number === p.switch_issue || !beingBuilt(ticket)) continue;
    let scopes;
    try { scopes=[protectedPaths(ticket.body,true), ...comments(ticket.comments).map(c=>protectedPaths(c.body))]; }
    catch (e) { fail(`being-built ticket #${ticket.number}: ${e.message}`); }
    if (!scopes.some(s=>s.declared || s.paths.length)) fail(`being-built ticket #${ticket.number} has unreadable owned paths`);
    const scope=scopes.flatMap(s=>s.paths);
    if (scope.some(owned=>plan.paths.some(path=>overlaps(owned,path)))) fail(`owned paths overlap being-built ticket #${ticket.number}`);
  }
  return plan;
}
function main() {
  const arg=process.argv.slice(2);
  if (arg.length !== 1 || !/^[1-9][0-9]*$/.test(arg[0]) || !Number.isSafeInteger(Number(arg[0]))) fail('usage: approve.mjs ISSUE_NUMBER');
  const pointer=process.env.HUNTR_PRIVATE_RECORD;
  if (!/^https:\/\/github\.com\/jparker2006\/ClosedWiz\/(issues|pull)\/[1-9][0-9]*#issuecomment-[1-9][0-9]*$/.test(pointer ?? '')) fail('HUNTR_PRIVATE_RECORD must point to the private standing approval comment');
  const p=policy();
  let repo=process.env.GH_REPO;
  if (!repo) {
    const record=json(gh(['repo','view','--json','nameWithOwner'],'GitHub repository read failed'));
    exact(record,['nameWithOwner'],'repository selector');repo=record.nameWithOwner;
  }
  if (typeof repo !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9-]*\/[A-Za-z0-9_][A-Za-z0-9_.-]*$/.test(repo)) fail('unreadable repository selector');
  process.env.GH_REPO=repo;
  const first=readWorld(repo,p.switch_issue);
  evaluate(first,Number(arg[0]),p);
  const second=readWorld(repo,p.switch_issue);
  const plan=evaluate(second,Number(arg[0]),p);
  if (JSON.stringify(first.issues.find(x=>x.number === Number(arg[0]))) !== JSON.stringify(second.issues.find(x=>x.number === Number(arg[0])))) fail('candidate changed during approval checks');
  const commentId=pointer.match(/#issuecomment-([1-9][0-9]*)$/)[1];
  let record;
  try { record=json(gh(['api',`repos/jparker2006/ClosedWiz/issues/comments/${commentId}`], 'private standing approval could not be read')); }
  catch { fail('private standing approval could not be read'); }
  if (!object(record) || record.html_url !== pointer || String(record.id) !== commentId || typeof record.body !== 'string' || !record.body.trim()) fail('private standing approval pointer does not resolve to that comment');
  const approval=`**Approved on its own by huntr, ${new Date().toISOString().slice(0,10)}, tier ${plan.tier}, kind ${plan.kind}:** under Jake's standing approval (ADR 0014).\nPrivate record: ${pointer}`;
  const tmp=mkdtempSync(join(tmpdir(),'huntr-approval-'));
  try {
    const file=join(tmp,'comment.md');writeFileSync(file,approval,{mode:0o600});
    const result=gh(['issue','comment',arg[0],'--body-file',file],'approval write failed or is unconfirmed; read back before retrying');
    process.stdout.write(result);
  } finally { rmSync(tmp,{recursive:true,force:true}); }
}
try { main(); }
catch (e) { process.stderr.write(`huntr: ${e.message}\n`); process.exitCode=2; }
