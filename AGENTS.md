# Agents

This repository is a to-do app built end to end by an OpenWiz fleet: the demo behind [openwiz.dev](https://openwiz.dev).

- Skills: WizSkills 0.2.0, installed with its `install.sh --version 0.2.0` and copied whole into `.claude/` (`.claude/skills/`, `.claude/contracts/`, `.claude/.claude-plugin/`); `.agents/skills/` links each skill folder for Codex. When told to use a skill, such as `build-ticket`, read `.claude/skills/<skill>/SKILL.md` and follow it.
- Settings for the fleet are in `docs/agents/`.
- The app is plain HTML, CSS and JavaScript in `app/`, with no build step and no dependencies. `npm test` runs the tests in `tests/`.
