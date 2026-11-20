// The working page (TD4): loads the tasks, renders them, and on each change
// (add on submit, toggle on a checkbox) saves them and renders again.
// The page's markup is docs/markup.md's; every path is relative, so the page
// works under a sub-path such as /todo-demo/ on GitHub Pages.
//
// Storage is the source of truth: each change is applied to the latest saved
// list (another tab may have changed it), and the page shows a change only
// once it is saved. Tabs take turns: each read-change-write holds one lock
// (the Web Locks API); a browser without it saves again a task another tab
// wrote over.

import { addTask, toggleTask, loadTasks, saveTasks, STORAGE_KEY } from './todos.js';
import { renderTasks } from './view.js';

const NOT_SAVED = 'Your change was not saved: this browser’s storage is full or blocked.';
const THIS_VISIT = 'Storage is blocked: tasks are kept for this visit only';

// The latest saved list, or null when storage can't be read right now (never
// mistaken for an empty list, which would then be saved over the real one).
function latest(storage) {
  try {
    storage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
  return loadTasks(storage);
}

// One lock for every read-change-write of the stored tasks, shared by the
// origin's tabs (the Web Locks API), so two tabs' changes never interleave.
const LOCK_NAME = 'todo-demo.tasks';

function hasLocks(locks) {
  return typeof locks?.request === 'function';
}

// Applies one action to the latest saved list and saves it, all at once.
function applyToLatest(storage, action) {
  const before = latest(storage);
  if (before === null) return { saved: false, tasks: null };
  const next = action(before);
  if (next !== before) {
    try {
      saveTasks(storage, next);
    } catch {
      return { saved: false, tasks: before };
    }
  }
  return { saved: true, tasks: next };
}

// Applies one action to the latest saved list and saves it, holding the tabs'
// lock from the read to the write when the browser has the Locks API. Resolves
// to { saved, tasks }: saved is true once saved (or when nothing changed);
// tasks is the list to show, or null when storage can't be read (show what is
// shown).
export async function saveChange(storage, locks, action) {
  if (!hasLocks(locks)) return applyToLatest(storage, action);
  let ran = false;
  try {
    return await locks.request(LOCK_NAME, () => {
      ran = true;
      return applyToLatest(storage, action);
    });
  } catch (error) {
    // The lock itself was refused (some sandboxed pages): change without it.
    if (ran) throw error;
    return applyToLatest(storage, action);
  }
}

// The list with every task of shown it lacks added back at the end, with its
// done state. Tasks are never deleted, so a task this tab showed that is not
// in the list (same id and text) was written over by another tab. One that
// lost its id to another tab's task comes back under a fresh id.
function withMissing(list, shown) {
  let next = list;
  for (const task of shown) {
    if (next.some((t) => t.id === task.id && t.text === task.text)) continue;
    const added = addTask(next, task.text);
    if (added === next) continue;
    next = task.done ? toggleTask(added, added[added.length - 1].id) : added;
  }
  return next;
}

// Another tab saved. Resolves to the list to show, or null to keep what is shown.
// With the Locks API no tab writes over another's change, so this only reads.
// Without it two tabs' saves can still overlap, so a task this tab showed that
// the other tab wrote over is saved again.
export async function afterOtherTabSaved(storage, locks, shown) {
  if (hasLocks(locks)) return latest(storage);
  return (await saveChange(storage, locks, (list) => withMissing(list, shown))).tasks;
}

// localStorage itself can throw (storage blocked, some private modes); the page
// then still works, for this visit only, and says so.
function browserStorage() {
  try {
    const storage = window.localStorage;
    if (storage) return { storage, kept: true };
  } catch {
    // fall through
  }
  const items = new Map();
  return {
    storage: { getItem: (key) => (items.has(key) ? items.get(key) : null), setItem: (key, value) => items.set(key, String(value)) },
    kept: false,
  };
}

function start() {
  const { storage, kept } = browserStorage();
  const locks = navigator.locks;
  const form = document.querySelector('.todo-form');
  const field = document.querySelector('.todo-form-input');
  const container = document.querySelector('.todo-tasks');

  // The messages use the fields' own validation messages, so the page needs no
  // markup beyond docs/markup.md; the form is submitted by script, not blocked by them.
  form.noValidate = true;
  if (!kept) field.placeholder = THIS_VISIT;

  let tasks = latest(storage) ?? [];

  function checkboxFor(id) {
    return [...container.querySelectorAll('.todo-item-check')].find((box) => box.dataset.id === id) ?? null;
  }

  // Renders the tasks; a checkbox that had keyboard focus keeps it.
  function render() {
    const active = document.activeElement;
    const focusedId = active instanceof HTMLInputElement && container.contains(active) ? active.dataset.id : null;
    container.innerHTML = renderTasks(tasks);
    if (focusedId !== null) checkboxFor(focusedId)?.focus();
  }

  // Saves one change, then shows the result; resolves to whether it was saved.
  async function commit(action) {
    const { saved, tasks: shown } = await saveChange(storage, locks, action);
    if (shown !== null) tasks = shown;
    render();
    return saved;
  }

  function tell(element, message) {
    element.setCustomValidity(message);
    element.reportValidity();
  }

  field.addEventListener('input', () => field.setCustomValidity(''));

  // A save waits for the tabs' lock, so a second submit (a held Enter) can come
  // before the first is saved; it would add the same text again, so it is ignored.
  let adding = false;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (adding) return;
    adding = true;
    field.setCustomValidity('');
    const text = field.value;
    let saved;
    try {
      saved = await commit((list) => addTask(list, text));
    } finally {
      adding = false;
    }
    if (saved) {
      // Clear only the text that was added, not anything typed since.
      if (text.trim() !== '' && field.value === text) field.value = '';
      field.focus();
    } else {
      field.focus();
      tell(field, NOT_SAVED);
    }
  });

  container.addEventListener('change', async (event) => {
    const box = event.target;
    if (!(box instanceof HTMLInputElement) || !box.classList.contains('todo-item-check')) return;
    const id = box.dataset.id;
    const saved = await commit((list) => toggleTask(list, id));
    const again = checkboxFor(id);
    again?.focus();
    if (!saved && again) tell(again, NOT_SAVED);
  });

  // Another tab saved: show its list.
  window.addEventListener('storage', async (event) => {
    if (event.key !== STORAGE_KEY && event.key !== null) return;
    const list = await afterOtherTabSaved(storage, locks, tasks);
    if (list === null) return;
    tasks = list;
    render();
  });

  render();
}

// The page starts in a browser; the tests import the functions above in Node.
if (typeof document !== 'undefined') start();
