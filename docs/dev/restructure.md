# Restructure 2026-10: ModPilot as a library that runs inside Blender

Design record for kevin's fork (`lxchhh3/REE-ModPilot`, branch `restructure`). Decided by kevin
on 2026-10-19 (board entry 0bc904f3, which supersedes 4fe90e97) and done 2026-10-19 → 10-21.
The full plan with its milestones was `~/.claude/plans/fuzzy-dazzling-milner.md`. This file
keeps what still matters once the work is done: why it happened, what was decided, and which
decisions in [design.md](design.md) it replaced.

## Why

kevin took ModPilot over from Dimi on 2026-10-16. On 10-19 the group-A work fixed ten tool
defects that the three builds that passed in game (claude_run1, GG, Marette) had each patched
around with agent scripts. It also showed why such defects had lived for months:

- **Blender logic travelled as f-string source.** The tools sent 53 round trips of Python as text
  (`physics_bones.py` had about 730 lines of it) and read results back from printed lines.
  That code could not be imported, linted or run in a test. Two scans looked up an RE Chain
  Editor type and property that don't exist and returned nothing for months (lesson #55).
- **The tests checked text, not behaviour.** 35 of 39 unit-test files mocked Blender and
  asserted on the generated code and call order (design.md B5). All 697 passed while the join,
  the `_End` bones, SHARED settings, the clsp and emission were broken. Four tests pinned the
  20-bit clsp bug.
- **Failures were silent by design:** `except Exception: pass`, "non-fatal" steps, and
  fallbacks that gave every chain the first type.
- **Half the code served a use that was gone.** About 14.5k lines (agent loop, LLM layer, app
  routes, React/Tauri) existed for ModPilot's own DeepSeek agent. Since 10-12 Claude Code is the
  agent, and Dimi had paused ModPilot as "a workflow, not an agent".

## Decisions (kevin)

| Date | Decision |
|---|---|
| 10-19 | Restructure ModPilot, reversing the 10-12 "not redesigned" clause |
| 10-19 | Work in our own public fork; Dimi's repo is `upstream` and is never pushed to. `Ref/` (Dimi's BHS_fixed, ~900 MB) is gitignored and must never be committed |
| 10-19 | Claude Code stays the agent, ModPilot is its library, Blender Lab MCP (9877) its eyes |
| 10-19 | The agent loop, LLM layer and React/Tauri app are deleted once the new core replaces them |
| 10-19 | Generic recipes from `Known_Good_mod_test/scripts` move into the library; outfit-specific build drivers stay there |
| 10-19 | Groups B (physics defaults) and C (materials) wait until the restructure is done |
| 10-19 | Keep `solve_repeated_uvs` |
| 10-20 | Blender 4.3 is out of scope; build and test on 5.2.2 only |
| 10-20 | M4 (builds as TOML recipes with a runner) dropped |

Defaults I chose, accepted with the plan: steps keep the old tool names, so the call logs and
tools-5.2's checks still work; `.blend` checkpoints go to `tools-5.2/runtime/cache`, never into git.

## What was built

- **`modpilot`, a package Blender imports.** It registers no bpy classes, so reloading it is safe.
  `modpilot.call(step, params)` parses the params strictly, snapshots the scene, runs the step
  with add-on popups captured, snapshots again and returns the report. See the README for the
  report and `StepError`.
- **No silent paths.** Operators run through `core.ops.run`, which requires `{'FINISHED'}` and
  turns an error popup into a `StepError`. A step skips something only when its params opt in,
  and the report lists it under `skipped`.
- **Scene names come from `SceneConfig`,** stored in `scene["modpilot_config"]` so they survive
  a `.blend` save. `setup_import_mhwilds` writes the names it actually created.
- **One calling line for every channel:** Lab MCP 9877, the bridge 9876 and headless sessions.
- **Tests run real code.** T0 covers the bpy-free packages on the host. T1 runs real steps on
  synthetic scenes in headless Blender (`modpilot_host.bpytest`, one Blender per file, isolated
  profiles from tools-5.2). tools-5.2's L3 replays claude_run1's own ModPilot calls through
  `modpilot.call` in headless Blender.

## Milestones

| | What | Commits |
|---|---|---|
| M0 | Fork, `Ref/` ignored, the 10-19 working tree as the first commit, golden call logs | `8a859dd`, `7540700` |
| M1 | Core, host transport, test runner, Lab MCP transport, live smoke test | `4479c98`, `fe0512e` |
| M2 | Every legacy tool ported to a step, each through T1 → T2 (legacy vs new on the same scene) → L3 | `7507484` … `2695fcb`, `f00f8e1` |
| M3 | Generic recipes absorbed: `geom`, `formats`, `bl` helpers, garment steps, `mods` | `369e107` … `b8234c7` |
| M4 | Builds as recipe files | dropped (kevin, 10-20) |
| M5 | tools-5.2 tests the fork: `pins.toml [modpilot] src_dir`; L3 replays run `modpilot.call` in headless Blender; `extract_ops` walks the AST so the operator inventory sees the new code | tools-5.2 (not a git repo); board 3eebe509 |
| M6 | Deleted the agent, LLM, app, frontend, legacy tools and the mocked tests, after [restructure_test_mapping.md](restructure_test_mapping.md) mapped each test's intent | `f118449`, `1e18e56` |
| M7 | These docs | |

Results at the end: the ModPilot host suite is 344 passed. tools-5.2 on 5.2.2 passes everything
outside the L1/L2 file round-trips (284). L1/L2 has 297 failures that predate M5: SKS corpus files
added on 10-14 and 10-16 that `baselines/l1_bytes.json` (recorded 10-13) does not have yet.

## Changed on purpose

Where a legacy tool was silent, the step now fails. Each change is noted in its step module's
docstring and in the mapping table. Examples:
- An unknown chain group in `collider_apply` fails, and every entry is checked before any is written.
- A material mapping with a bad slot changes nothing and fails.
- A failed `_End` cascade or chain-header tune fails `physics_chains`.
- `batch_export` has no built-in fallback for mesh cleanup.

## Decisions in design.md this replaces

| design.md | Then | Now |
|---|---|---|
| A1, B6 | ModPilot's LLM picks phases and classifies; phase tools in the middle | Claude Code is the agent; ModPilot is a library of steps |
| B5 | A mockable socket and a state cache, tested with mocks | Steps run in Blender; tests run them in real headless Blender |
| B7 | Errors as `Result`; no `.blend` snapshots | `StepError` with a category; scene snapshots in every report |
| C9, C10, C11 | Hand-rolled ReAct, provider-agnostic LLM client, workflow doc in the prompt | Deleted |
| C13 | FastAPI and the LLM SDKs | numpy only (pytest and ruff for dev) |
| C25 | React 19 + Tauri | Deleted |
| D14 | `tests/unit` mocked, `tests/integration`, `tests/e2e` | `tests/core` (T0), `tests/bl` (T1), `tests/blender`, `tests/live` |
| E16, E18 | `PhaseResult`; a sync `BlenderClient` under FastAPI | The report dict; `modpilot_host.transport` |

Still valid: A4's acceptance bar (the mod runs in game), E19 (physics presets as JSON data).

## Open after the restructure

- **The MMD and Endfield T-pose conversions** (`pose_correction` for the `MMD` and `arknights`
  presets) fail outside a UI Blender: the Toolkit calls `object.select_grouped`, whose poll fails
  headless even with a 3D View lent through `temp_override` (lesson #58). Their T1 test is a
  strict xfail. No build has used these presets yet.
- **tools-5.2's L1 baseline** needs re-recording for the SKS corpus files.
- **tools-5.2's `compat/legacy_baseline.py`** still calls its checkpoints "legacy", but it replays the new steps now.
- **Groups B and C** come next, each ported from a recipe that passed in game, with T1 tests and
  kevin's in-game checks.
