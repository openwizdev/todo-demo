import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { renderTasks } from '../app/view.js';

// The list example in docs/markup.md, read from the contract itself, so the
// view and the contract can never drift apart unnoticed.
async function contractListExample() {
  const doc = await readFile(new URL('../docs/markup.md', import.meta.url), 'utf8');
  const section = doc.split('## The list, as `renderTasks(tasks)` returns it')[1];
  assert.ok(section, 'docs/markup.md has the list section');
  const blocks = [...section.matchAll(/```html\n([\s\S]*?)```/g)].map((m) => m[1].trim());
  assert.equal(blocks.length, 2, 'the list section has the list example and the empty state');
  return { list: blocks[0], empty: blocks[1] };
}

// P4. The view marks completed tasks done, checks their box and escapes text.

test('P4: renders the contract example exactly: in order, one item each, done marked and checked', async () => {
  const { list } = await contractListExample();
  const tasks = [
    { id: 't1', text: 'Buy milk', done: false },
    { id: 't2', text: 'Walk the dog', done: true },
  ];
  assert.equal(renderTasks(tasks).trim(), list);
});

test('P4: every task gets one item, in the list order, and only done tasks are marked and checked', () => {
  const tasks = [
    { id: 'c', text: 'third added first', done: true },
    { id: 'a', text: 'open one', done: false },
    { id: 'b', text: 'done one', done: true },
    { id: 'd', text: 'open two', done: false },
  ];
  const html = renderTasks(tasks);
  const items = [...html.matchAll(/<li class="([^"]*)" data-id="([^"]*)">\s*<input ([^>]*)>\s*<label class="todo-item-text" for="([^"]*)">([^<]*)<\/label>\s*<\/li>/g)];
  assert.equal(items.length, 4, 'exactly one item per task');
  assert.equal((html.match(/<li\b/g) || []).length, 4);
  assert.equal((html.match(/<ul class="todo-list">/g) || []).length, 1, 'one list');
  assert.deepEqual(items.map((m) => m[2]), ['c', 'a', 'b', 'd'], 'the list order');
  assert.deepEqual(items.map((m) => m[5]), ['third added first', 'open one', 'done one', 'open two']);
  assert.deepEqual(items.map((m) => m[1]), ['todo-item done', 'todo-item', 'todo-item done', 'todo-item']);
  for (const [i, m] of items.entries()) {
    const id = tasks[i].id;
    const input = m[3];
    assert.match(input, /^class="todo-item-check" type="checkbox"/);
    assert.ok(input.includes(` id="todo-task-${id}"`), `checkbox id for ${id}`);
    assert.ok(input.includes(` data-id="${id}"`), `checkbox data-id for ${id}`);
    assert.equal(m[4], `todo-task-${id}`, `label tied to the checkbox of ${id}`);
    assert.equal(/\bchecked\b/.test(input), tasks[i].done, `checked exactly when ${id} is done`);
  }
});

test('P4: text with <, >, &, and quotes renders as text, never as markup', () => {
  const html = renderTasks([{ id: 't1', text: `<img src=x onerror="alert('x')"> & </label></li>`, done: false }]);
  assert.ok(
    html.includes('>&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt; &amp; &lt;/label&gt;&lt;/li&gt;</label>'),
    html,
  );
  assert.ok(!html.includes('<img'), 'no element from the text');
  assert.equal((html.match(/<\/label>/g) || []).length, 1);
  assert.equal((html.match(/<\/li>/g) || []).length, 1);
});

test('P4: an id with quotes or markup is escaped in every attribute', () => {
  const html = renderTasks([{ id: `x" onclick="a()'<&>`, text: 'one', done: true }]);
  const escaped = 'x&quot; onclick=&quot;a()&#39;&lt;&amp;&gt;';
  assert.ok(html.includes(`<li class="todo-item done" data-id="${escaped}">`), html);
  assert.ok(html.includes(` id="todo-task-${escaped}" data-id="${escaped}" checked>`), html);
  assert.ok(html.includes(`<label class="todo-item-text" for="todo-task-${escaped}">one</label>`), html);
  assert.ok(!html.includes(' onclick="'), 'no attribute injected');
});

test('an empty list renders the empty state from docs/markup.md', async () => {
  const { empty } = await contractListExample();
  assert.equal(empty, '<p class="todo-empty">No tasks yet.</p>');
  assert.equal(renderTasks([]).trim(), empty);
  assert.ok(!renderTasks([]).includes('<ul'), 'no list when there are no tasks');
});

test('renderTasks does not change the tasks it is given', () => {
  const tasks = [{ id: 't1', text: '<b>', done: true }];
  renderTasks(tasks);
  assert.deepEqual(tasks, [{ id: 't1', text: '<b>', done: true }]);
});
