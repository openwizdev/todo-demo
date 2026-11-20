# Domain docs

Where this project keeps its words and its decisions, and how every skill reads them.

## Before exploring, read these

- **`GLOSSARY.md`** at the root: the project's words, each defined once. (Optional: in a repository with several separate packages, a **`GLOSSARY-MAP.md`** at the root, when present, points at one `GLOSSARY.md` per package instead; read each one that bears on the work. When it is absent, there is no map to read.)
- **`docs/adr/`**: one short file per hard-to-reverse decision. Read the ones that touch the area you are about to work in.
- **`docs/grills/` in the private checkout**: one file per grill, with every question and exact answer. Run the grill index there and read its current private PR head when not merged. Read the grill that fed the spec; never create or copy its file into the public checkout.

If the glossary or ADRs do not exist yet, carry on without them. Missing private storage or unread privacy is a stop before writing private material, never permission to put it in a public tree. The `grill` skill creates them as terms and decisions get settled.

## Private storage

The repository routing is in `issue-tracker.md`. Resolve the private checkout by its verified remote, never by a guessed current directory; verify private visibility before writing. Grills (including their branches, PRs and decision requests) use `docs/grills/` there. The handoff page is `<handoff page>` and all orchestrator state stays under `<private state folder>`, the locations recorded here for that private checkout; never assume a default. Authorized agents read those private sources directly; a public source names a decision and a private-comment pointer, never its exact replies or thread ids. If a source is not available, report the gap.

## Layout

```
/
├── GLOSSARY.md
├── docs/
│   └── adr/
│       └── 0001-<decision>.md
└── ...

<private checkout>/
├── docs/grills/
│   ├── README.md
│   └── <date>-<topic>.md
└── <private state folder>/
    └── <handoff page>
```

## Use the glossary's words

When your output names something the glossary defines (in an issue title, a ticket, a test name, a review), use the glossary's word. Avoid the words it lists under _Avoid_.

If what you need to name is not in the glossary yet, either you are inventing language the project doesn't use (think again), or there is a real gap: note it for the next grill.

Public ADR sources use `<decider>, <YYYY-MM-DD>: <decision in plain words> ([private record](<full private-comment URL>)).` Save and read back the exact words in that private comment first; a link to a grill file is not a pointer. The public glossary and ADRs stay in the development checkout.

## Flag ADR conflicts

If your output contradicts an ADR, say so plainly instead of quietly overriding it:

> _Contradicts ADR 0004 (<its title>), but worth reopening because…_
