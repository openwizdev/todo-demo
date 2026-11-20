# #2218 (OB7a), synthetic: test.sh's check.json changed by its LIB helpers.
# #13's older contract hold (1301, for #23) is resolved by spec #10's newer
# approval (1002, revision 2); a newer manual hold (1302) on the same ticket is
# unresolved. `held` is still on and both ready roles are off, so the reader
# must offer no release and no ready label may come back.
merge12 | contract23 | issue(13; .labels = ["held"]) | held_at(13; "10:59")
| say(13; 1301; "11:00"; "launch-fleet: held for #23: contract changed, re-approve. contracts/widget.v1.md changed in #23.")
| approve(10; 1002; "11:30"; 2; [11, 12, 13, 14])
| say(13; 1302; "11:40"; "launch-fleet: held manual: owner decision required")
