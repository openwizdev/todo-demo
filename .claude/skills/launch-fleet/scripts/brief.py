#!/usr/bin/env python3
"""Print one brief the fleet sends, literally (WS8, #1181). Send its output unchanged.

  brief.py builder N
  brief.py reviewer P COMMIT
  brief.py re-check P COMMIT OLD_HEAD IDS ANSWER     IDS: R1,R2 or none; ANSWER: the builder's comment link or none
  brief.py fresh N P BRANCH COMMIT
  brief.py diagnose
  brief.py fleet S OWNER/NAME                       the fleet thread's first wake
  brief.py wake S OWNER/NAME                        a spec's fleet loop
  brief.py tick OWNER/NAME ORCHESTRATOR_THREAD      the project's safety-net loop
  brief.py wakes OWNER/NAME ORCHESTRATOR_THREAD     the project's webhook loop

A loop prompt is private routing: it may name the orchestrator's thread, which
never goes into a public record.

Exit 2 and print nothing for an unknown kind or a malformed target. The
skill-file lookup belongs to the recipient, so it is printed unexpanded.
"""
import re
import sys

LOOKUP = ("Read 'skills/{s}/SKILL.md' if present, otherwise find '*/skills/{s}/SKILL.md' only inside your own "
          "harness's configured plugin cache: Codex uses CODEX_HOME/plugins/cache (default HOME/.codex/plugins/cache); "
          "Claude uses CLAUDE_CODE_PLUGIN_CACHE_DIR/cache when set, otherwise CLAUDE_CONFIG_DIR/plugins/cache (default "
          "HOME/.claude/plugins/cache); for another harness use its installation metadata. Prefer active installation "
          "metadata over cache scanning when available. During cache scans exclude other harness caches, source "
          "checkouts, orphaned versions marked .orphaned_at, and targets outside the selected cache. Follow symlinks "
          "and deduplicate real paths. Verify .claude-plugin/plugin.json manifest name openwiz and entry "
          "./skills/{s}; report missing, unreadable or ambiguous matches, otherwise read the unique matching file and "
          "follow it")
N = r'[1-9][0-9]{0,8}'
SHA = r'[0-9a-f]{40}'
FORMS = {
    'builder': ([N], 'You are the builder for #{0}. Use the build-ticket skill. {b}.'),
    'reviewer': ([N, SHA], 'You are the reviewer for pull request #{0} at {1}. Use the review-ticket skill. {r}.'),
    're-check': ([N, SHA, SHA, r'none|R[0-9]+(,R[0-9]+)*', r'none|https://github\.com/[A-Za-z0-9_./#-]+'],
                 "Re-check pull request #{0} at {1}: use the review-ticket skill. {r}, Re-checks. Open findings: {3}. "
                 "Changed since {2}: git diff {2} {1}; the builder's answer: {4}."),
    'fresh': ([N, N, r'room/[A-Za-z0-9._/-]+', SHA],
              'You are the fresh builder for #{0}: one fresh round on pull request #{1}, on its branch {2}, after '
              'the report at {3}. Use the build-ticket skill. {b}, its fresh round.'),
    'diagnose': ([], 'Use the diagnose skill. {d} for the finding.'),
    'fleet': ([N, r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+'],
              'You are the fleet thread for spec #{0} of {1}. Use the launch-fleet skill. {f}; do its Fleet threads '
              'section, first wake.'),
    'wake': ([N, r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+'],
             'Fleet wake for {1} spec #{0}. Use the launch-fleet skill. {f}; do its Fleet threads section, Each wake.'),
    'tick': ([r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+', r'thr_[A-Za-z0-9_-]+'],
             "You are a launch-fleet tick for {0}. Use the launch-fleet skill. {f}; do its Each wake section for the "
             "due lines below. The orchestrator's thread is {1}."),
    'wakes': ([r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+', r'thr_[A-Za-z0-9_-]+'],
              "You are a launch-fleet tick for {0}, woken by GitHub's messages. Use the launch-fleet skill. {f}; do its "
              "Each wake section for the messages below. The orchestrator's thread is {1}."),
}


def main(argv):
    form = FORMS.get(argv[0]) if argv else None
    if form is None or len(argv) - 1 != len(form[0]) \
            or not all(re.fullmatch(p, a) for p, a in zip(form[0], argv[1:])):
        return 2
    print(form[1].format(*argv[1:], **{k: LOOKUP.format(s=s) for k, s in
                                       (('b', 'build-ticket'), ('r', 'review-ticket'), ('d', 'diagnose'),
                                        ('f', 'launch-fleet'))}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
