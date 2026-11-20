# #2112 (OB7), synthetic: test.sh's check.json changed by its LIB helpers.
# #13's contract hold (1301, for #23) is answered by spec #10's newer approval
# (1002, revision 2), with `held` on and both ready roles off. Alone, the tick
# offers its release; each OB7 case adds one race the release must not pass.
merge12 | contract23 | issue(13; .labels = ["held"]) | held_at(13; "10:59")
| say(13; 1301; "11:00"; "launch-fleet: held for #23: contract changed, re-approve. contracts/widget.v1.md changed in #23.")
| approve(10; 1002; "11:30"; 2; [11, 12, 13, 14])
