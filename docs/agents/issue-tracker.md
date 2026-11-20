# Issue tracker: GitHub

This project's versions, specs and tickets live in its GitHub repository. Use the `gh` CLI (2.94 or later, for sub-issues and "blocked by" links) for everything. Inside a clone, `gh` finds the repository from `git remote -v`.

## Where things live

| Thing | On GitHub |
| --- | --- |
| Version | A milestone, named after the version |
| Spec | An issue in that milestone; its body is the spec |
| Ticket | A sub-issue of its spec, with "blocked by" links to the tickets it waits for |
| A ticket's work | Its pull request |
| The user's approval of a spec or a plan graph | A public-form comment on the spec issue: the decision, date and private-comment pointer, naming the revision approved |

A ticket is ready when it has the `ready-for-agent` label and every ticket blocking it has a verified merge: a closed blocker alone is not enough. A ticket closes only on a verified merge, a spec only when all its tickets are closed, and a version only when its milestone is done and its live check has passed.

## Repositories

- **Development tracker:** `openwizdev/todo-demo`.
- **Private records:** `jparker2006/ClosedWiz`.

## Private records and approval forms

Read the repositories above before any write; `gh` defaults to this clone's remote, so explicitly target the private repository for private comments and PRs. Verify its private visibility first. Grills and their requests, exact replies, handoff and orchestrator state stay there. Public spec/plan requests stay on the development tracker.

Save and read back the exact confirmation/approval in a private issue/PR comment before posting its public decision. Use a comment on the private subject when already there; otherwise use the private issue titled exactly `Private record: todo-demo #<N>` (created on first use). The pointer must name that existing comment: `https://github.com/jparker2006/ClosedWiz/issues/<N>#issuecomment-<C>` or `/pull/<N>#issuecomment-<C>`.

Writers use only the public forms: keep the `Spec confirmed by`, `Plan graph approved by` or `Approved on its own by` opening; add the date and decision in plain words, with `Private record: <pointer>` as the very next line. No quoted exact words or thread ids appear in a public comment.

## Commands

- **Create an issue:** `gh issue create --title "..." --body-file <file>`.
- **Put it in a version:** add `--milestone "<version>"`.
- **Make a ticket a sub-issue of its spec:** `gh issue create --parent <spec> ...`.
- **Blocking:** `gh issue create --blocked-by <n>,<n> ...`, or afterwards `gh issue edit <ticket> --add-blocked-by <blocker>`.
- **Read an issue:** `gh issue view <n> --json number,title,body,labels,comments,milestone,parent,blockedBy`.
- **Comment:** `gh issue comment <n> --body-file <file>`.
- **Labels:** `gh issue edit <n> --add-label "..."` and `--remove-label "..."`.

File product issues only in `openwizdev/todo-demo`. Private-record issues and comments target `--repo jparker2006/ClosedWiz`.

## Pull requests as triage input

**Outside pull requests count as requests: no.**
