#!/usr/bin/env node
import { readFileSync, appendFileSync, existsSync, writeFileSync } from 'node:fs';
const w = JSON.parse(readFileSync(process.env.HUNTR_FAKE_STATE, 'utf8'));
const a = process.argv.slice(2);
if (a[0] === 'api' && /^repos\/jparker2006\/ClosedWiz\/issues\/comments\/[1-9][0-9]*$/.test(a[1])) {
  if (w.pointerMissing) process.exit(1);
  process.stdout.write(JSON.stringify({id:9000000001,html_url:'https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001',body:'Synthetic standing approval record.'}));
} else if (a[0] === 'api' && a[1] === 'graphql') {
  const param = name => a.find(x=>x.startsWith(name+'='))?.slice(name.length+1);
  const query=param('query') ?? '';
  const reads=existsSync(process.env.HUNTR_FAKE_READS)?Number(readFileSync(process.env.HUNTR_FAKE_READS,'utf8')):0;
  if(query.includes('query HuntrConnection')) {
    const number=Number(param('number')),field=query.includes('labels(')?'labels':'comments';
    const connections=w.connectionSequence?.[Math.min(reads-1,w.connectionSequence.length-1)] ?? w.connections;
    const page=connections?.[`${number}:${field}`]?.find(p=>p.after===param('after'));
    if(!page || page.failure) {process.stderr.write('synthetic page failure\n');process.exit(1);}
    process.stdout.write(page.raw ?? JSON.stringify(page.envelope ?? {data:{repository:{issue:{number,[field]:page.value}}}}));
    process.exit(0);
  }
  const after=param('endCursor');
  const readIndex=after?reads-1:reads;
  if(!after) writeFileSync(process.env.HUNTR_FAKE_READS,String(reads+1));
  if (w.readFailure) { process.stderr.write('synthetic read failure\n'); process.exit(1); }
  if (w.raw) process.stdout.write(w.raw);
  else {
    const pages=w.sequence ? w.sequence[Math.min(readIndex,w.sequence.length-1)] : w.pages;
    if(a.includes('--slurp')) {
      // Project the old query's nested selections for its failing-first run.
      for(const p of pages) {
        const r=p.data?.repository;
        if(r?.switch?.comments) delete r.switch.comments.pageInfo;
        for(const t of r?.issues?.nodes ?? []) {
          if(t.labels) delete t.labels.pageInfo;
          if(t.comments) delete t.comments.pageInfo;
          if(t.parent?.comments) delete t.parent.comments.pageInfo;
        }
      }
      process.stdout.write(JSON.stringify(pages));
    } else {
      const index=after?pages.findIndex(p=>p.data?.repository?.issues?.pageInfo?.endCursor===after)+1:0;
      if(after && index===0) process.exit(1);
      process.stdout.write(JSON.stringify(pages[index] ?? {errors:[{message:'synthetic missing page'}]}));
    }
  }
} else if (a[0] === 'issue' && a[1] === 'comment' && a[3] === '--body-file' && a.length === 5) {
  if (w.postFailure) { process.stderr.write('synthetic post failure\n'); process.exit(1); }
  appendFileSync(process.env.HUNTR_FAKE_POSTS, JSON.stringify({number: a[2], body: readFileSync(a[4], 'utf8')}) + '\n');
  process.stdout.write('https://example.invalid/approval\n');
} else { process.stderr.write('unexpected fake gh command: ' + JSON.stringify(a)); process.exit(1); }
