# The list's markup

The contract between the view (`app/view.js`), the page (`app/index.html`, `app/main.js`) and the styles (`app/style.css`). Every element and class the app uses is named here; the styles select only these, and the view and the page produce exactly these.

## The page

```html
<body>
  <main class="todo-app">
    <h1 class="todo-title">To-do</h1>

    <form class="todo-form">
      <label class="todo-form-label" for="todo-new">New task</label>
      <input class="todo-form-input" id="todo-new" name="text" type="text" autocomplete="off">
      <button class="todo-form-add" type="submit">Add</button>
    </form>

    <div class="todo-tasks"><!-- renderTasks(tasks) goes here --></div>
  </main>
</body>
```

| Element | Class | What it is |
| --- | --- | --- |
| `main` | `todo-app` | The page's single column |
| `h1` | `todo-title` | The page heading |
| `form` | `todo-form` | The add form; submitting it adds the field's text |
| `label` | `todo-form-label` | The text field's label, tied to it by `for="todo-new"` |
| `input type="text"` | `todo-form-input` | The text field, `id="todo-new"` |
| `button type="submit"` | `todo-form-add` | The Add button |
| `div` | `todo-tasks` | The container the page fills with `renderTasks(tasks)` |

## The list, as `renderTasks(tasks)` returns it

With one or more tasks, one `ul` with one `li` per task, in the list's order:

```html
<ul class="todo-list">
  <li class="todo-item" data-id="t1">
    <input class="todo-item-check" type="checkbox" id="todo-task-t1" data-id="t1">
    <label class="todo-item-text" for="todo-task-t1">Buy milk</label>
  </li>
  <li class="todo-item done" data-id="t2">
    <input class="todo-item-check" type="checkbox" id="todo-task-t2" data-id="t2" checked>
    <label class="todo-item-text" for="todo-task-t2">Walk the dog</label>
  </li>
</ul>
```

| Element | Class | What it is |
| --- | --- | --- |
| `ul` | `todo-list` | The list of tasks |
| `li` | `todo-item` | One task; `data-id` is the task's `id` |
| `li` | `todo-item done` | **The `done` state:** a completed task's item also has the class `done` |
| `input type="checkbox"` | `todo-item-check` | The task's checkbox: `checked` exactly when the task is done; `id="todo-task-<id>"`, `data-id` is the task's `id` |
| `label` | `todo-item-text` | The task's text, tied to its checkbox by `for="todo-task-<id>"` |

With no tasks, the empty state instead of the list:

```html
<p class="todo-empty">No tasks yet.</p>
```

| Element | Class | What it is |
| --- | --- | --- |
| `p` | `todo-empty` | The empty state, with the text `No tasks yet.` |

## Rules

- The task's text and its `id` are escaped wherever they appear (`&`, `<`, `>`, `"` and `'`), so a task always renders as text, never as markup.
- A change on a `todo-item-check` checkbox toggles the task named by its `data-id`.
- No other classes: a new one is added here first.
