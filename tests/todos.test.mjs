import { test } from 'node:test';
import assert from 'node:assert/strict';
import { addTask, toggleTask, loadTasks, saveTasks, STORAGE_KEY } from '../app/todos.js';

// An in-memory stand-in for localStorage: only getItem and setItem.
function memoryStorage(initial = {}) {
  const items = new Map(Object.entries(initial));
  return {
    getItem: (key) => (items.has(key) ? items.get(key) : null),
    setItem: (key, value) => { items.set(key, String(value)); },
    raw: items,
  };
}

// P1. Adding a task appends it; blank text adds nothing.

test('P1: addTask appends a trimmed, not-done task at the end', () => {
  const before = [{ id: 'a', text: 'Buy milk', done: true }];
  const after = addTask(before, '  Walk the dog \n');
  assert.equal(after.length, 2);
  assert.deepEqual(after[0], { id: 'a', text: 'Buy milk', done: true });
  assert.equal(after[1].text, 'Walk the dog');
  assert.equal(after[1].done, false);
  assert.deepEqual(Object.keys(after[1]).sort(), ['done', 'id', 'text']);
  assert.notEqual(after, before, 'a new array');
  assert.equal(before.length, 1, 'the input list is not changed');
});

test('P1: addTask gives every task an id unique in the list', () => {
  let tasks = [];
  for (const text of ['one', 'two', 'three', 'four']) tasks = addTask(tasks, text);
  // Ids that look like ones the list could generate must not be reused.
  tasks = addTask([{ id: 't1', text: 'x', done: false }, { id: 't2', text: 'y', done: false }], 'z');
  assert.equal(new Set(tasks.map((t) => t.id)).size, 3);
  let many = [];
  for (let i = 0; i < 50; i++) many = addTask(many, `task ${i}`);
  assert.equal(new Set(many.map((t) => t.id)).size, 50);
  assert.deepEqual(many.map((t) => t.text), Array.from({ length: 50 }, (_, i) => `task ${i}`));
});

test('P1: blank or whitespace text returns the same list unchanged', () => {
  const before = [{ id: 'a', text: 'Buy milk', done: false }];
  for (const blank of ['', ' ', '   ', '\t\n ']) {
    assert.equal(addTask(before, blank), before, JSON.stringify(blank));
  }
  assert.deepEqual(before, [{ id: 'a', text: 'Buy milk', done: false }]);
});

// P2. Toggling flips one task's done and nothing else.

test('P2: toggleTask flips only the named task, both ways', () => {
  const before = [
    { id: 'a', text: 'one', done: false },
    { id: 'b', text: 'two', done: true },
    { id: 'c', text: 'three', done: false },
  ];
  const ticked = toggleTask(before, 'a');
  assert.deepEqual(ticked, [
    { id: 'a', text: 'one', done: true },
    { id: 'b', text: 'two', done: true },
    { id: 'c', text: 'three', done: false },
  ]);
  const unticked = toggleTask(ticked, 'b');
  assert.deepEqual(unticked, [
    { id: 'a', text: 'one', done: true },
    { id: 'b', text: 'two', done: false },
    { id: 'c', text: 'three', done: false },
  ]);
  assert.notEqual(ticked, before, 'a new array');
  assert.deepEqual(before[0], { id: 'a', text: 'one', done: false }, 'the input task is not changed');
});

test('P2: toggleTask with an unknown id changes nothing', () => {
  const before = [{ id: 'a', text: 'one', done: false }, { id: 'b', text: 'two', done: true }];
  const after = toggleTask(before, 'zzz');
  assert.deepEqual(after, [{ id: 'a', text: 'one', done: false }, { id: 'b', text: 'two', done: true }]);
  assert.deepEqual(toggleTask([], 'a'), []);
});

// P3. Tasks saved are the tasks loaded; a missing or broken value loads as empty.

test('P3: saveTasks then loadTasks gives the same tasks, under the one key', () => {
  const storage = memoryStorage();
  const tasks = [
    { id: 'a', text: 'Buy milk', done: false },
    { id: 'b', text: 'Say "hi" <b>&</b>', done: true },
  ];
  saveTasks(storage, tasks);
  assert.equal(STORAGE_KEY, 'todo-demo.tasks.v1');
  assert.deepEqual([...storage.raw.keys()], ['todo-demo.tasks.v1']);
  assert.deepEqual(JSON.parse(storage.raw.get('todo-demo.tasks.v1')), tasks);
  assert.deepEqual(loadTasks(storage), tasks);
  saveTasks(storage, []);
  assert.deepEqual(loadTasks(storage), []);
});

test('P3: a missing, broken or wrongly shaped value loads as []', () => {
  const cases = {
    missing: undefined,
    'empty string': '',
    'broken JSON': '[{"id":"a",',
    'not JSON': 'hello',
    null: 'null',
    object: '{"id":"a","text":"x","done":false}',
    number: '42',
    string: '"[]"',
    'item not an object': '["a"]',
    'item null': '[null]',
    'item an array': '[["a","x",false]]',
    'id missing': '[{"text":"x","done":false}]',
    'id a number': '[{"id":1,"text":"x","done":false}]',
    'id empty': '[{"id":"","text":"x","done":false}]',
    'text missing': '[{"id":"a","done":false}]',
    'text a number': '[{"id":"a","text":5,"done":false}]',
    'done a string': '[{"id":"a","text":"x","done":"false"}]',
    'done missing': '[{"id":"a","text":"x"}]',
    'extra key': '[{"id":"a","text":"x","done":false,"due":"today"}]',
    'duplicate ids': '[{"id":"a","text":"x","done":false},{"id":"a","text":"y","done":true}]',
    'one bad item among good': '[{"id":"a","text":"x","done":false},{"id":"b","text":"y"}]',
  };
  for (const [name, value] of Object.entries(cases)) {
    const storage = memoryStorage(value === undefined ? {} : { 'todo-demo.tasks.v1': value });
    assert.deepEqual(loadTasks(storage), [], name);
  }
});

test('P3: a storage that throws on read loads as []', () => {
  const storage = { getItem() { throw new Error('denied'); }, setItem() {} };
  assert.deepEqual(loadTasks(storage), []);
});

test('P3: loadTasks reads only its own key', () => {
  const storage = memoryStorage({ 'other.key': '[{"id":"a","text":"x","done":false}]' });
  assert.deepEqual(loadTasks(storage), []);
});
