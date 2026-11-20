import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, access } from 'node:fs/promises';

const APP = new URL('../app/', import.meta.url);

async function page() {
  return readFile(new URL('index.html', APP), 'utf8');
}

// Every start tag in the page, with its attributes. The page is our own plain
// HTML, so a start tag is `<name attr="value" flag>`; a value is always double-quoted.
function tags(html) {
  return [...html.replace(/<!--[\s\S]*?-->/g, '').matchAll(/<([a-zA-Z][a-zA-Z0-9-]*)((?:\s+[^\s=>]+(?:="[^"]*")?)*)\s*\/?>/g)].map(
    ([, name, rest]) => ({
      name: name.toLowerCase(),
      attrs: Object.fromEntries([...rest.matchAll(/([^\s=>]+)(?:="([^"]*)")?/g)].map(([, k, v]) => [k.toLowerCase(), v ?? ''])),
    }),
  );
}

// The page's assets as a browser would fetch them when GitHub Pages serves
// app/ under the sub-path /todo-demo/.
const SITE = 'https://synthetic-owner.github.io/todo-demo/';

function underSubPath(path) {
  const url = new URL(path, SITE);
  return url.origin === new URL(SITE).origin && url.pathname.startsWith('/todo-demo/') ? url.pathname.slice('/todo-demo/'.length) : null;
}

async function exists(name) {
  try {
    await access(new URL(name, APP));
    return true;
  } catch {
    return false;
  }
}

// The page itself, as docs/markup.md fixes it.
async function contractPage() {
  const doc = await readFile(new URL('../docs/markup.md', import.meta.url), 'utf8');
  const section = doc.split('## The page')[1]?.split('\n## ')[0];
  assert.ok(section, 'docs/markup.md has the page section');
  const blocks = [...section.matchAll(/```html\n([\s\S]*?)```/g)].map((m) => m[1]);
  assert.equal(blocks.length, 1, 'the page section has one example');
  return blocks[0];
}

const squash = (html) => html.replace(/\s+/g, ' ').replace(/> </g, '><').trim();

test('the page links style.css and loads main.js as a module, and nothing else', async () => {
  const all = tags(await page());
  const assets = all.filter((t) => 'src' in t.attrs || 'href' in t.attrs);
  assert.deepEqual(
    assets.map((t) => [t.name, t.attrs.rel ?? t.attrs.type, t.attrs.href ?? t.attrs.src]),
    [
      ['link', 'stylesheet', 'style.css'],
      ['script', 'module', 'main.js'],
    ],
  );
});

test('every asset path in the page is relative, so it loads under the /todo-demo/ sub-path', async () => {
  const assets = tags(await page()).flatMap((t) => ['src', 'href'].filter((k) => k in t.attrs).map((k) => t.attrs[k]));
  assert.ok(assets.length > 0, 'the page has assets');
  for (const path of assets) {
    assert.doesNotMatch(path, /^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|\/)/, `${path} is relative (no scheme, no leading /)`);
    const file = underSubPath(path);
    assert.ok(file, `${path} resolves under /todo-demo/`);
    assert.ok(await exists(file), `${path} is a file in app/`);
  }
});

test('main.js imports only relative modules that exist in app/', async () => {
  const main = await readFile(new URL('main.js', APP), 'utf8');
  const specifiers = [...main.matchAll(/^\s*import\s[^;]*?from\s+'([^']+)'/gm)].map((m) => m[1]);
  assert.deepEqual(specifiers.sort(), ['./todos.js', './view.js']);
  for (const spec of specifiers) assert.ok(await exists(underSubPath(spec)), `${spec} is a file in app/`);
});

test('the page has a title, a language and a labelled text field', async () => {
  const html = await page();
  const all = tags(html);
  assert.match(html, /<title>\s*To-do\s*<\/title>/);
  const root = all.filter((t) => t.name === 'html');
  assert.equal(root.length, 1);
  assert.equal(root[0].attrs.lang, 'en');
  const fields = all.filter((t) => t.name === 'input' && t.attrs.type === 'text');
  assert.equal(fields.length, 1, 'one text field');
  assert.ok(fields[0].attrs.id, 'the text field has an id');
  const labels = all.filter((t) => t.name === 'label' && t.attrs.for === fields[0].attrs.id);
  assert.equal(labels.length, 1, 'one label tied to the text field');
  assert.match(html, /<label [^>]*>\s*New task\s*<\/label>/);
  const viewport = all.filter((t) => t.name === 'meta' && t.attrs.name === 'viewport');
  assert.equal(viewport.length, 1, 'a viewport, so it fits a phone');
});

test('the page body is exactly the page in docs/markup.md', async () => {
  const body = (await page()).match(/<body>[\s\S]*<\/body>/);
  assert.ok(body, 'the page has a body');
  assert.equal(squash(body[0]), squash(await contractPage()));
});
