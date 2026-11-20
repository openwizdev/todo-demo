# Skills

One folder for each skill: `skills/<name>/SKILL.md`, its `agents/openai.yaml`, and its own scripts, tests and resources. `python3 check/run.py` checks the rules below, then the standalone check and every skill's own suites.

| Skill |
| --- |
| [`ask-wiz`](ask-wiz/SKILL.md) |
| [`build-ticket`](build-ticket/SKILL.md) |
| [`diagnose`](diagnose/SKILL.md) |
| [`grill`](grill/SKILL.md) |
| [`handoff`](handoff/SKILL.md) |
| [`hill-climb`](hill-climb/SKILL.md) |
| [`huntr`](huntr/SKILL.md) |
| [`image`](image/SKILL.md) |
| [`install`](install/SKILL.md) |
| [`launch-fleet`](launch-fleet/SKILL.md) |
| [`research`](research/SKILL.md) |
| [`review-ticket`](review-ticket/SKILL.md) |
| [`setup`](setup/SKILL.md) |
| [`to-spec`](to-spec/SKILL.md) |
| [`to-tickets`](to-tickets/SKILL.md) |
| [`triage`](triage/SKILL.md) |
| [`wayfind`](wayfind/SKILL.md) |
| [`where-are-we`](where-are-we/SKILL.md) |

## Rules

- **Layout:** `skills/` holds only this file and skill folders, each named in lowercase and hyphens and holding its `SKILL.md`.
- **Frontmatter:** `name` (the folder's name), `description` and `version` (semver), one line each, and no other key; only `ask-wiz` also requires `disable-model-invocation: true`.
- **Codex:** `agents/openai.yaml` holds only `interface.display_name` and `interface.short_description`; only `ask-wiz` also has `policy.allow_implicit_invocation: false`.
- **Notice:** a skill listed in `SOURCE_LINES` in `check/run.py` carries its source line exactly, on a line of its own, and never Matt Pocock's notice; every other skill keeps his copyright and MIT notice word for word in its sibling `NOTICE.md`, and its `SKILL.md` ends with a credit line linking that file.
- **Links:** every relative Markdown link resolves inside the package, and there are no symlinks inside `skills/`: plugin installs may drop them.
- **Manifest:** `.claude-plugin/plugin.json` lists exactly these skills, sorted by name; `.claude-plugin/marketplace.json` holds one `openwiz` plugin with source `./`.
- **Standalone:** every relative link, script path, import and file read in a skill resolves to a file inside the package (`check/standalone.py`).
