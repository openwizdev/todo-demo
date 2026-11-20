// The list view: turns tasks into the list's markup, as docs/markup.md says.
// A task is { id, text, done } (app/todos.js). Dependency-free; never changes
// the tasks it is given.

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

// Escapes &, <, >, " and ' so a value renders as text, in an element or an attribute.
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ESCAPES[ch]);
}

function renderItem({ id, text, done }) {
  const safeId = escapeHtml(id);
  const checkId = `todo-task-${safeId}`;
  return [
    `  <li class="todo-item${done ? ' done' : ''}" data-id="${safeId}">`,
    `    <input class="todo-item-check" type="checkbox" id="${checkId}" data-id="${safeId}"${done ? ' checked' : ''}>`,
    `    <label class="todo-item-text" for="${checkId}">${escapeHtml(text)}</label>`,
    '  </li>',
  ].join('\n');
}

// Returns the markup for the container `.todo-tasks`: one `ul.todo-list` with one
// `li.todo-item` per task in the list's order, or the empty state when there are none.
export function renderTasks(tasks) {
  if (tasks.length === 0) return '<p class="todo-empty">No tasks yet.</p>';
  return ['<ul class="todo-list">', ...tasks.map(renderItem), '</ul>'].join('\n');
}
