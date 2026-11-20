# OB6 inbox fixtures (#1481)

Synthetic only. `limits.conf` holds the five TL1 goals at their defaults;
`limits-bad.conf` is missing one, so the TL1 reader refuses it. The missed-goal
proofs also read `stage-waits-bench.json`, a byte-for-byte copy of TL2's own
sanitized stage bench.

Run the owning proofs:

```sh
python3 -I skills/launch-fleet/scripts/test-inbox.py
```

The review relay's side of the inbox, its page and its own proof, live with
the relay, outside this skill.
