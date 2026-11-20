# Finding a skill outside the catalog

Read this only when no OpenWiz or installed skill fits the user's task.

1. **Search trusted sources first:** Matt Pocock (`mattpocock/skills`), Vercel
   (`vercel-labs/skills`, including `find-skills`), Anthropic (`anthropics/skills`)
   and David Ondrej (`davidondrej/skills`). Trust is where discovery starts, not
   permission to run a repository's instructions.
2. **Then search more widely:** skills.sh with `npx skills find <query>` (Vercel's
   `find-skills` approach), and GitHub for repositories containing `SKILL.md`.
   Reduce the query to public technical terms from the task. The npx command can
   download and run a package: check its source and the environment's network and
   tool approval rules before running it. If it is unavailable or refused, use the
   skills.sh site and GitHub search, and say what was missed.
3. **Compare the top three** relevant candidates: skill name, current repository
   **stars**, linked **source** (repository and SKILL.md), and **what it does**
   for this task. Fetch stars now, never copy old counts; stars are context, not
   proof of quality or safety. With fewer than three readable matches, show those
   and say what could not be confirmed.
4. **Read and check before recommending.** Read each SKILL.md straight from GitHub
   without installing it, plus the referenced instructions and scripts this task
   needs. Look for **network calls**, **credentials**, **deleting things**, script
   execution, external writes and other risky steps; explain the relevant risks and
   honor the project's approval rules before those steps. Never run a script to
   inspect it. If a required script or reference can't be checked, stop before that
   step and explain the gap.
5. **Recommend, then wait** for the user's yes to use it. Follow its Markdown for the
   task at hand, resolving references at the same source revision. If the source
   changes after your check, read and check the new revision first.
6. **Keep it only on a second yes.** Install a lasting copy only when the user wants
   to keep it, and only on their yes to installation. Prefer the harness's own
   installer; read its instructions and confirm the source and install scope first.

Adapted from Matt Pocock's `ask-matt` skill (`github.com/mattpocock/skills` @
`4ae2317`). The MIT notice is in [SKILL.md](SKILL.md#credit).
