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

- **Development tracker:** <verified owner/repository; retain the current tracker until any separately gated cut-over>.
- **Public development, if different:** <verified owner/repository and its activation gate>.
- **Private records:** <verified private owner/repository; for OpenWiz, jparker2006/ClosedWiz>.

## Private records and approval forms

Read the repositories above before any write; `gh` defaults to this clone's remote, so explicitly target the private repository for private comments and PRs. Verify its private visibility first. Grills and their requests, exact replies, handoff and orchestrator state stay there. Public spec/plan requests stay on the development tracker; this is routing for writers, not proof of two-repository cockpit discovery.

Save and read back the exact confirmation/approval in a private issue/PR comment before posting its public decision. Use a comment on the private subject when already there; otherwise use the private issue titled exactly `Private record: OpenWiz #<N>` (created on first use). An approval with no issue/PR uses `Private record: standing approvals`. The pointer must name that existing comment: `https://github.com/jparker2006/ClosedWiz/issues/<N>#issuecomment-<C>` or `/pull/<N>#issuecomment-<C>`, positive numbers without leading zeroes.

Writers use only the public forms on either repository: keep the `Spec confirmed by`, `Plan graph approved by` or `Approved on its own by` opening; add the date and decision in plain words, with `Private record: <pointer>` as the very next line. Keep a plan's revision, table and fingerprint. Standing approvals are named in the decision and point to the private comment where they were given. No quoted exact words or thread ids appear in the public comment. Readers accept historical quoting records only after positively identifying a private repository; unknown visibility uses the public rules.

## Commands

- **Create an issue:** `gh issue create --title "..." --body "..."`. Use a heredoc for a body of more than one line.
- **Put it in a version:** add `--milestone "<version>"`. List the versions with `gh api 'repos/{owner}/{repo}/milestones' --jq '.[] | {number, title, state}'`; create one with `gh api --method POST 'repos/{owner}/{repo}/milestones' -f title="<version>"`.
- **Make a ticket a sub-issue of its spec:** `gh issue create --parent <spec> ...`, or afterwards `gh issue edit <spec> --add-sub-issue <ticket>`.
- **Blocking:** GitHub's own "blocked by" links, which show on the issue page. Add them with `gh issue create --blocked-by <n>,<n> ...`, or afterwards `gh issue edit <ticket> --add-blocked-by <blocker>`.
- **List a ticket's blockers:** `gh issue view <n> --json blockedBy --jq '.blockedBy.nodes[] | {number, state}'`. A closed blocker still needs its verified merge before the ticket is ready.
- **Read an issue:** `gh issue view <n> --json number,title,body,labels,comments,milestone,parent,blockedBy`.
- **List issues:** `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`, with `--label`, `--milestone` and `--state` filters as needed.
- **Comment:** `gh issue comment <n> --body "..."`.
- **Labels:** `gh issue edit <n> --add-label "..."` and `--remove-label "..."`.
- **Close:** post the reason with `gh issue comment <n> --body "..."`, then `gh issue close <n>`. On an issue that is already closed, `gh issue close --comment` drops the comment and still exits 0.

File product issues only in the configured development repository. Private-record issues and comments explicitly target the configured private repository with `--repo <private-owner/repo>`. A fork can make `gh` default to its parent, so before the first `gh issue create` of a session, check the target with `gh repo view --json nameWithOwner`.

## Pull requests as triage input

**Outside pull requests count as requests: no.** _(Set to `yes` if this project treats pull requests from outside contributors as feature requests; the `triage` skill reads this.)_

When it is `yes`, those pull requests get the same labels and states as issues, with the `gh pr` commands: `gh pr view <n>`, `gh pr view <n> --comments`, `gh pr diff <n>`, `gh pr comment`, `gh pr edit --add-label` and `--remove-label`, and `gh pr close`. Issues and pull requests share one set of numbers, so for a bare `#42` try `gh pr view 42`, then `gh issue view 42`.

## When a skill says

- **"Publish to the issue tracker":** create a GitHub issue.
- **"Fetch the ticket":** read it as in **Read an issue** above.
