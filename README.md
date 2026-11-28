# todo-demo

Part of [OpenWiz](https://openwiz.dev), the open source agent factory.

A to-do app built end to end by an [OpenWiz](https://github.com/openwizdev/OpenWiz) fleet, using [WizSkills](https://github.com/openwizdev/WizSkills) 0.2.0: a short grill, a spec with its narrated video, small tickets, builders and other-family reviewers.

**Live app:** https://openwizdev.github.io/todo-demo/

- `app/`: the app, plain HTML, CSS and JavaScript. Every merge to `main` deploys it to GitHub Pages.
- `tests/`: `npm test` (Node 24, no dependencies); CI runs it on every pull request.
- `docs/agents/`: the fleet's settings. `.claude/`: the installed skills.
