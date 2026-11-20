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

// R1: two tabs on one list. Both tabs share one origin, so one localStorage and
// one lock manager. The storage stand-in can run another tab's change just
// before this tab writes the list it read: the overlap a handler paused before
// its save (as the review did with a breakpoint) gives in a browser.
import { saveChange, afterOtherTabSaved } from '../app/main.js';
import { STORAGE_KEY, loadTasks, saveTasks, addTask, toggleTask } from '../app/todos.js';

function sharedStorage() {
  const items = new Map();
  let onWrite = null;
  let onRead = null;
  return {
    getItem(key) {
      const value = items.has(key) ? items.get(key) : null;
      const hook = onRead;
      onRead = null;
      hook?.();
      return value;
    },
    setItem(key, value) {
      const hook = onWrite;
      onWrite = null;
      hook?.();
      items.set(key, String(value));
    },
    // Runs once, just before the next write lands.
    beforeNextWrite(hook) {
      onWrite = hook;
    },
    // Runs once, as the next read returns.
    onNextRead(hook) {
      onRead = hook;
    },
  };
}

// The Web Locks API's exclusive mode, for one origin: a request runs its
// callback once every earlier request for the same name has settled, and
// resolves with the callback's result.
function lockManager() {
  const tails = new Map();
  return {
    request(name, callback) {
      const run = (tails.get(name) ?? Promise.resolve()).then(() => callback({ name, mode: 'exclusive' }));
      tails.set(name, run.catch(() => {}));
      return run;
    },
  };
}

const texts = (list) => list.map((t) => `${t.text}${t.done ? ' (done)' : ''}`);

test('two tabs whose changes overlap both stay saved (Locks API)', async () => {
  const storage = sharedStorage();
  const locks = lockManager();
  saveTasks(storage, [{ id: 't1', text: 'Buy milk', done: false }]);
  let tabB;
  // Tab A ticks Buy milk; just before A's write lands, tab B adds Pay rent.
  storage.beforeNextWrite(() => {
    tabB = saveChange(storage, locks, (list) => addTask(list, 'Pay rent'));
  });
  const tabA = await saveChange(storage, locks, (list) => toggleTask(list, 't1'));
  const b = await tabB;
  assert.deepEqual([tabA.saved, b.saved], [true, true]);
  assert.deepEqual(texts(loadTasks(storage)), ['Buy milk (done)', 'Pay rent']);
  assert.deepEqual(texts(b.tasks), ['Buy milk (done)', 'Pay rent'], 'tab B shows both');
});

test('a tab reads the list only once it holds the lock (Locks API)', async () => {
  const storage = sharedStorage();
  const locks = lockManager();
  saveTasks(storage, [{ id: 't1', text: 'Buy milk', done: false }]);
  let tabB;
  // Tab B asks to add Pay rent as soon as tab A first reads the list.
  storage.onNextRead(() => {
    tabB = saveChange(storage, locks, (list) => addTask(list, 'Pay rent'));
  });
  await saveChange(storage, locks, (list) => toggleTask(list, 't1'));
  await tabB;
  assert.deepEqual(texts(loadTasks(storage)), ['Buy milk (done)', 'Pay rent']);
});

test('without the Locks API, a task another tab overwrote is saved again by the tab that added it', async () => {
  const storage = sharedStorage();
  saveTasks(storage, [{ id: 't1', text: 'Buy milk', done: false }]);
  let tabB;
  storage.beforeNextWrite(() => {
    tabB = saveChange(storage, undefined, (list) => addTask(list, 'Pay rent'));
  });
  await saveChange(storage, undefined, (list) => toggleTask(list, 't1'));
  const b = await tabB;
  // Tab A wrote its stale list over Pay rent; tab B hears of it as a storage event.
  assert.deepEqual(texts(loadTasks(storage)), ['Buy milk (done)']);
  const shown = await afterOtherTabSaved(storage, undefined, b.tasks);
  assert.deepEqual(texts(loadTasks(storage)), ['Buy milk (done)', 'Pay rent']);
  assert.deepEqual(texts(shown), ['Buy milk (done)', 'Pay rent']);
});

test('without the Locks API, a task that lost its id to another tab is saved again under a fresh id', async () => {
  const storage = sharedStorage();
  saveTasks(storage, [{ id: 't1', text: 'Buy milk', done: false }]);
  // Both tabs add a task from the same list, so both pick id t2; A's write lands last.
  saveTasks(storage, [{ id: 't1', text: 'Buy milk', done: false }, { id: 't2', text: 'Call the bank', done: false }]);
  const shownInB = [{ id: 't1', text: 'Buy milk', done: false }, { id: 't2', text: 'Pay rent', done: true }];
  const shown = await afterOtherTabSaved(storage, undefined, shownInB);
  const saved = loadTasks(storage);
  assert.deepEqual(texts(saved), ['Buy milk', 'Call the bank', 'Pay rent (done)']);
  assert.equal(new Set(saved.map((t) => t.id)).size, 3, 'ids stay unique');
  assert.deepEqual(shown, saved);
});

test('with the Locks API, another tab saving just shows its list, and writes nothing', async () => {
  const storage = sharedStorage();
  const list = [{ id: 't1', text: 'Buy milk', done: true }];
  saveTasks(storage, list);
  const raw = storage.getItem(STORAGE_KEY);
  let writes = 0;
  const setItem = storage.setItem;
  storage.setItem = (...args) => {
    writes += 1;
    setItem(...args);
  };
  const shown = await afterOtherTabSaved(storage, lockManager(), [{ id: 't1', text: 'Buy milk', done: false }, { id: 't9', text: 'Old', done: false }]);
  assert.deepEqual(shown, list);
  assert.equal(writes, 0);
  assert.equal(storage.getItem(STORAGE_KEY), raw);
});
