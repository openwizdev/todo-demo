---
name: diagnose
description: Diagnose a hard bug, unexplained test failure, flaky CI test or performance regression, starting from a command that goes red on it. Use for a stuck builder or the orchestrator's optional diagnosis inside a decision on a parked finding; not for planned work (build-ticket) or hunting unreported problems (huntr).
version: 0.2.0
---

# Diagnose

**No theory without a loop.** First run one command that goes red on the
reported bug. Then minimise it, rank hypotheses, test one prediction at a
time, and fix with a regression test. Skip a later phase only with a stated
reason; the red loop cannot be skipped.

Read the project's `AGENTS.md` or `CLAUDE.md`, its glossary and the ADRs for
the area. Run the helper as `python3 -I <this skill's folder>/scripts/loop.py`.

## Guards

- **Scope:** keep the caller's role, owned paths, approval gates and the
  1 + 1 review limit. Diagnosis grants no permission to edit elsewhere, run
  against a live system, merge or start agents. The orchestrator's diagnosis
  only supplies a cause and direction for its decision; it never resets 1 + 1.
- **Privacy:** replace every secret with `<REDACTED>` before showing commands,
  outputs or artifacts. Keep credentials in environment variables, never in
  arguments. Quote only diagnostic lines; headers can be secrets. Public
  records carry synthetic reproducers and technical facts: no thread ids,
  exact user words, real identifiers or links into private files. Keep private
  captures in the configured private repository. Record a user decision in
  your own words with its date and the open-development private-record
  pointer. If redaction removes the signal, say so and ask; never expose it.

## 1. Build the red loop

Reading code to build a reproducer is fine; explaining the cause first is
not. Prefer, in order: a failing test at the seam that reaches the bug; an
HTTP script; a CLI run on fixture input against a known-good snapshot; a
headless browser assertion; a redacted trace replayed through the isolated
path; a throwaway harness; a seeded fuzz loop; `git bisect run` in an
isolated copy; or old against new on the same input. Assert the exact
symptom, pin time and seeds, isolate files and network, and aim for seconds.

**Last resort, a human loop:** `bash <this skill's folder>/scripts/hitl-loop.template.sh
'<step>' '<symptom question>'`. Exit 1 means the symptom is present, 0 absent,
2 inconclusive; map 2 to 125 under `git bisect run`. The human signs in
themselves and answers only y or n. Without a terminal they can answer, ask;
never invent the answer.

**Flaky:** set the effort first (the ticket's budget, if given), then amplify
with repeats, stress or injected delays until `loop.py rate --runs N
[--timeout S] -- <command>` shows a high failure rate. Record its line, the
seed and configuration before and after amplification. A lucky pass proves
nothing; never retry until green.

**Done when** you have run one fast, agent-runnable command on the real bug
path and can show its redacted red output and the symptom it asserts. If you
cannot build it, stop and ask for the missing environment, a redacted capture
or permission for temporary instrumentation: on the ticket with
`build-ticket`'s needs-info procedure, otherwise to the caller. Do not
hypothesise or instrument production while waiting.

## 2. Minimise

Confirm the loop catches the reported failure, not a nearby one. Cut inputs,
callers, configuration, data and steps one at a time, rerunning after each.
**Done when** removing any remaining element loses the failure.

## 3. Rank hypotheses

Write 3–5 ranked hypotheses, each with a prediction: "if X, changing Y removes
it." Discard any you cannot falsify. Show the ranking on the ticket (or to the
caller) and carry on without waiting.

## 4. Probe one prediction at a time

Change one variable per run and update the ranking. Prefer a debugger, then
boundary logs tagged with one prefix from `loop.py tag`; never log everything
and look for a story. For a performance regression, measure a baseline with a
timer, profiler or query plan, then bisect; logs are not a measurement.
**Done when** one probe has distinguished the cause.

## 5. Fix with a regression test

1. Turn the minimised loop into a test at a seam that exercises the real
   call pattern. No correct seam: record that gap and ask; an untested fix
   is not done.
2. Run it red. If red needed a mutation, diff against a pristine copy.
3. Apply the smallest fix for the established cause, and run the test green.
4. Rerun the original loop. For a flake, rerun `loop.py rate` with the same
   command and runs; retries never erase failures.

Follow the project's proof-first commits and state the cause in the commit
or pull request. Fixture tests prove fixture behaviour, never live behaviour.

## 6. Clean up and report

`loop.py clean '<prefix>'` must print `clean:`; remove every leftover it
names and any throwaway harness. Then leave a diagnosis comment on the ticket
or issue: the loop command, symptom and redacted red output; the cause and
the probe that showed it, or "unsolved"; the regression test and original
loop results; any `rate` lines and effort spent; and every open gap. If the
effort ran out unsolved, list what you tried and ask for the next step.

Credit: adapted from Matt Pocock's skills under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
