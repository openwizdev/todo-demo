// The task list: pure functions every other part of the app builds on.
// A task is { id, text, done }: id a non-empty string unique in the list,
// text a string, done a boolean. Functions never change the list they are given.

export const STORAGE_KEY = 'todo-demo.tasks.v1';

// Returns a new list with the trimmed text added at the end as a not-done task,
// or the same list when the text is blank.
export function addTask(tasks, text) {
  const trimmed = String(text).trim();
  if (trimmed === '') return tasks;
  return [...tasks, { id: nextId(tasks), text: trimmed, done: false }];
}

// Returns a new list with the named task's done flipped; every other task,
// and every task when the id is unknown, is unchanged.
export function toggleTask(tasks, id) {
  return tasks.map((task) => (task.id === id ? { ...task, done: !task.done } : task));
}

// Reads the tasks from a getItem/setItem storage. A missing, unreadable or
// wrongly shaped value loads as an empty list.
export function loadTasks(storage) {
  let value;
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (typeof raw !== 'string') return [];
    value = JSON.parse(raw);
  } catch {
    return [];
  }
  return isTaskList(value) ? value.map(({ id, text, done }) => ({ id, text, done })) : [];
}

// Writes the tasks to the storage under the one key, as JSON.
export function saveTasks(storage, tasks) {
  storage.setItem(STORAGE_KEY, JSON.stringify(tasks.map(({ id, text, done }) => ({ id, text, done }))));
}

// The first id of the form t<n>, counting up from the list's length + 1,
// that no task in the list already has.
function nextId(tasks) {
  const used = new Set(tasks.map((task) => task.id));
  let n = tasks.length + 1;
  while (used.has(`t${n}`)) n += 1;
  return `t${n}`;
}

const TASK_KEYS = ['done', 'id', 'text'];

function isTaskList(value) {
  if (!Array.isArray(value)) return false;
  const ids = new Set();
  for (const task of value) {
    if (task === null || typeof task !== 'object' || Array.isArray(task)) return false;
    const keys = Object.keys(task).sort();
    if (keys.length !== TASK_KEYS.length || keys.some((key, i) => key !== TASK_KEYS[i])) return false;
    if (typeof task.id !== 'string' || task.id === '' || ids.has(task.id)) return false;
    if (typeof task.text !== 'string' || typeof task.done !== 'boolean') return false;
    ids.add(task.id);
  }
  return true;
}
