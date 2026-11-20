// The working page (TD4): loads the tasks, renders them, and on each change
// (add on submit, toggle on a checkbox) saves them and renders again.
// The page's markup is docs/markup.md's; every path is relative, so the page
// works under a sub-path such as /todo-demo/ on GitHub Pages.

import { addTask, toggleTask, loadTasks, saveTasks } from './todos.js';
import { renderTasks } from './view.js';

// localStorage itself can throw (storage blocked, some private modes); the page
// then still works, for this visit only.
function browserStorage() {
  try {
    const storage = window.localStorage;
    if (storage) return storage;
  } catch {
    // fall through
  }
  const items = new Map();
  return { getItem: (key) => (items.has(key) ? items.get(key) : null), setItem: (key, value) => items.set(key, String(value)) };
}

const storage = browserStorage();
const form = document.querySelector('.todo-form');
const field = document.querySelector('.todo-form-input');
const container = document.querySelector('.todo-tasks');

let tasks = loadTasks(storage);

function render() {
  container.innerHTML = renderTasks(tasks);
}

function checkboxFor(id) {
  return [...container.querySelectorAll('.todo-item-check')].find((box) => box.dataset.id === id) ?? null;
}

function change(next) {
  tasks = next;
  try {
    saveTasks(storage, tasks);
  } catch {
    // A full or blocked storage keeps the change on the page for this visit.
  }
  render();
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const next = addTask(tasks, field.value);
  if (next !== tasks) {
    change(next);
    field.value = '';
  }
  field.focus();
});

container.addEventListener('change', (event) => {
  const box = event.target;
  if (!(box instanceof HTMLInputElement) || !box.classList.contains('todo-item-check')) return;
  const id = box.dataset.id;
  change(toggleTask(tasks, id));
  // Rendering replaces the checkbox; keep keyboard focus on the same task.
  checkboxFor(id)?.focus();
});

render();
