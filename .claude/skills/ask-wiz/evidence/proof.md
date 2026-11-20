# #1095 proof plan

Contract: #1095 and the full confirmed `2026-11-05-skill-ask` grill on PR #1094, as confirmed there on 2026-11-05. No parent spec is set on the ticket.

| Claim | Evidence class and seam |
| --- | --- |
| ask-wiz installs with the existing skill set, both links and plugin registration | Fixture/static test: `skills::the_skills_folder_passes_the_static_check`, with ask-wiz in the exact list |
| Only ask-wiz may require explicit user invocation in both harnesses | Fixture test: `skills::ask_wiz_user_started_policy`; existing `skills::a_user_only_flag_fails` stays in force for other skills |
| It routes every OpenWiz skill, reads before recommending, waits for yes, discovers installed skills and searches external skills with risk checks | Text test: `skills::ask_wiz_contract`, plus builder comparison with the confirmed grill; no live behavior claimed |
| The reference explains CloudRoom phase boundaries and respects the existing handoff role | Text test: `skills::ask_wiz_phase_boundaries`, plus builder comparison with `skills/handoff/SKILL.md` |
| No new dependency or executable behavior | Diff check; this is Markdown instructions, registration and static proofs only |

Red tests and logs are committed before implementation. Only affected skill checks, format and clippy for the changed test crate run locally under the scoped-check policy. CI is responsible for the full set. Runtime skill selection, external discovery and installation are unverified; no live task or external skill is executed here.

Historical command logs use `<checkout>/` in place of the original absolute checkout path; commands, results and failure reasons are unchanged.
