# Golden call logs

The ModPilot calls of the three builds that passed in game, frozen at the start of the
restructure (2026-10-19). One JSON object per line: `{tool, params, success, state_diff, error,
seconds}`, as `Known_Good_mod_test/scripts/gg/mp_session.py` (and claude_run1's `mp.py`) logged
them. Agent code steps between the calls are not in these logs.

| File | Build | Source |
|---|---|---|
| `claude_run1.jsonl` | Maya + Bunny Heart Sailor (pl024), passed in game 2026-10-12 | `Known_Good_mod_test/Output/claude_run1/modpilot_calls.jsonl` |
| `gg_mp4.jsonl` | Maya in GG, ModPilot staging run 4 (gg13 onward) | `Known_Good_mod_test/work/gg/mp4/modpilot_calls.jsonl` |
| `marette.jsonl` | Maya in Marette, ModPilot staging (marette2 onward) | `Known_Good_mod_test/work/marette/modpilot/modpilot_calls.jsonl` |

They are inputs, not expectations: the new core must accept every params dict in them (M1), and
tools-5.2 replays claude_run1 from its log as an acceptance test. Never edit them.
