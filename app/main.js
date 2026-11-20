// The working page (TD4): loads the tasks, renders them, and on each change
// (add on submit, toggle on a checkbox) saves them and renders again.
// The page's markup is docs/markup.md's; every path is relative, so the page
// works under a sub-path such as /todo-demo/ on GitHub Pages.
//
// Storage is the source of truth: each change is applied to the latest saved
// list (another tab may have changed it), and the page shows a change only
// once it is saved.

import { addTask, toggleTask, loadTasks, saveTasks, STORAGE_KEY } from './todos.js';
import { renderTasks } from './view.js';

const NOT_SAVED = 'Your change was not saved: this browser’s storage is full or blocked.';
const THIS_VISIT = 'Storage is blocked: tasks are kept for this visit only';

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

const { storage, kept } = browserStorage();
const form = document.querySelector('.todo-form');
const field = document.querySelector('.todo-form-input');
const container = document.querySelector('.todo-tasks');

// The messages use the fields' own validation messages, so the page needs no
// markup beyond docs/markup.md; the form is submitted by script, not blocked by them.
form.noValidate = true;
if (!kept) field.placeholder = THIS_VISIT;

// The latest saved list, or null when storage can't be read right now (never
// mistaken for an empty list, which would then be saved over the real one).
function latest() {
  try {
    storage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
  return loadTasks(storage);
}

let tasks = latest() ?? [];

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

// Applies one action to the latest saved list and saves it. Shows the result
// and returns true once saved (or when nothing changed); otherwise shows the
// saved list unchanged and returns false.
function commit(action) {
  const before = latest();
  if (before === null) {
    render();
    return false;
  }
  const next = action(before);
  if (next !== before) {
    try {
      saveTasks(storage, next);
    } catch {
      tasks = before;
      render();
      return false;
    }
  }
  tasks = next;
  render();
  return true;
}

function tell(element, message) {
  element.setCustomValidity(message);
  element.reportValidity();
}

field.addEventListener('input', () => field.setCustomValidity(''));

form.addEventListener('submit', (event) => {
  event.preventDefault();
  field.setCustomValidity('');
  const text = field.value;
  if (commit((list) => addTask(list, text))) {
    if (text.trim() !== '') field.value = '';
    field.focus();
  } else {
    field.focus();
    tell(field, NOT_SAVED);
  }
});

container.addEventListener('change', (event) => {
  const box = event.target;
  if (!(box instanceof HTMLInputElement) || !box.classList.contains('todo-item-check')) return;
  const id = box.dataset.id;
  const saved = commit((list) => toggleTask(list, id));
  const again = checkboxFor(id);
  again?.focus();
  if (!saved && again) tell(again, NOT_SAVED);
});

// Another tab saved: show its list.
window.addEventListener('storage', (event) => {
  if (event.key !== STORAGE_KEY && event.key !== null) return;
  const list = latest();
  if (list === null) return;
  tasks = list;
  render();
});

render();
