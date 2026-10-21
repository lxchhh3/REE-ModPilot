> **Historical (2026-10-21).** This describes ModPilot's own agent, LLM layer, app or legacy tools, deleted in restructure M6 (`1e18e56`). Code paths, commands and test counts here no longer exist; domain notes may still hold. Current docs: [README](../../README.md), [restructure record](../../docs/dev/restructure.md).

# ModPilot — Hierarchical Agent Loop Refactor (Router + PhaseLoop)

> **Status:** 🟢 shipped. PRs 1-6 landed and pushed as commit `283bec8` (issue #20, 2026-05-24).
> All decision-locked goals achieved. Historical record — kept for the rationale and the
> deferred-work list at the bottom, which is still accurate.
>
> *Moved here from the repo root (`Context_Improvement_Plan.md`) on 2026-08-06.*

## Context

`AgentLoop` in `ModPilot/app/agent/loop.py` had grown into a single 1500+ line state machine that:

- Concatenated every phase's workflow text into one ~22.5k-token system prompt on every LLM call
- Exposed 30 tools to the LLM on every turn regardless of which 1-2 were valid at the current phase
- Hosted five `LoopState` modes and three pause-rails interleaved through one `_run_react_turn`

Per-request floor before the refactor: ~30.6k tokens (22.5k system + 8.1k tool schemas) before any conversation history.

## Goal (achieved)

`AgentLoop` is now a thin passthrough façade over:

- `RouterLoop` — owns `_phase_idx`, MoveLog, SSE event sink, mechanical phase advance, deferred widget slot
- 13 per-phase `PhaseLoop` instances — each owns one phase's isolated `_phase_history`, its scoped tool subset, and its scoped system prompt

A typed handoff dataclass at each phase boundary is in place (shells today; per-boundary fields added as future consumers materialize).

Decision-locked from prior discussion:

| # | Decision | Status |
|---|----------|--------|
| 1 | Per-phase chat threads on FE (backend supports both today and after; FE refactor is separate) | backend: done |
| 2 | Dumb router — mechanical phase advance, no LLM router call | done |
| 3 | Typed handoff dataclass per phase boundary | shells done; per-boundary fields incremental |
| 4 | Single model — clean context is the win, not multi-model | done |
| 5 | Staged migration (6 PRs), local-only until final push | done |

## Architecture (as built through PR6)

```
RouterLoop                                (owns: _phase_idx, MoveLog, session_id, event sink,
                                                 _global_history (append-only debug log),
                                                 _pending_widget (Issue #3 deferred emit slot))
  ├─ system prompt: build_system_prompt() — kept as backward-compat field; not used by any LLM call
  ├─ tools: none
  └─ step(user_msg):
        ├─ _select_active_phase_loop()   ← refreshes _phase_loop pointer
        ├─ append user msg to _global_history + emit + log_move
        ├─ _dispatch(user_msg)
        │   ├─ if DONE: return short-circuit message
        │   └─ else: delegate to _phase_loop.dispatch(user_msg)
        ├─ append assistant reply to _global_history + emit + log_move
        └─ finally: self.flush_pending_widget()  (Issue #3)

PhaseLoop (one per phase, lazily built + cached in RouterLoop._per_phase_loops)
  ├─ system prompt: scoped to ONE workflow section via include_section_keys={section_key}
  ├─ tools: PHASE_TOOL_SUBSETS[phase_name] + query tools + sync_phase_state + query_history
  ├─ history: isolated _phase_history (seeded with phase brief on first entry)
  └─ dispatch(user_msg):
        ├─ mirror user_msg into _phase_history (so the LLM sees it under isolation)
        ├─ runs by internal state (RUNNING / AWAIT_CONFIRM / ERROR_HANDLING / ASK_MODE)
        ├─ _run_react_turn loop calls LLM, executes tools, signals Router on advance
        └─ mirror assistant reply into _phase_history (keeps next turn's history balanced)
```

## Staging (6 PRs, all local — DONE)

| PR | Status | Scope | Result |
|----|--------|-------|--------|
| 1 | done | Extract `RouterLoop` + `PhaseLoop` classes. `AgentLoop` becomes 459-line passthrough façade. Define handoff dataclass shells. Zero behavior change. | Façade architecture in place; 601 passing / 13 pre-existing failing tests |
| 2 | done | Migrate Setup phases (4) onto per-phase `PhaseLoop` with isolated histories | Setup prompts dropped to ~12k tokens |
| 3 | done | Migrate Phase 1-3. Centralize compaction in `Router.step` (later removed in PR6) | Phase 1-3 prompts dropped to ~11.6k tokens |
| 4 | done | Migrate Phase 3.5 + 4A + 4B + 4C. Retarget `_annotate_chains` proxy to phase_4a loop. Move `_pending_widget` to Router (so phase-advancing inspector tools don't lose the slot after the active loop swap). Mirror user/assistant messages into isolated `_phase_history` so widget-protocol payloads reach the LLM. | Physics-block phases ~3-4.3k words = 3.9-5.6k tokens each |
| 5 | done | Migrate Phase 5 + 6. Retarget `_suggest_texture_mapping` proxy to phase_5 loop. | All phases now isolated; generic loop became dead code |
| 6 | done | Delete `_generic_phase_loop`, `compact_phase_range`, `COMPACT_MARKER`, `compact_completed_phase_if_pending`, `_just_completed_phase`, `_phase_start_idx_global`. Simplify `_hydrate_from_move_log` to restore `_phase_idx` only. Extract `build_full_tool_catalog` module-level function for façade's global-tool-view proxies. Update tests that asserted on compaction / synthetic hydration. | Net -150 lines across `router.py`/`phase_loop.py`/`history.py`; tests: 589 passing + same 13 pre-existing failures |

## Final per-phase token floor (words; tokens ≈ words × 1.3)

| Phase | Prompt | Tools | Tool words | **Floor (words)** |
|-------|-------:|------:|-----------:|------------------:|
| setup_import_source | 2881 | 13 | 1124 | **4005** |
| setup_validate | 2881 | 13 | 1093 | **3974** |
| setup_infer | 2881 | 15 | 1513 | **4394** |
| setup_import | 2881 | 13 | 1113 | **3994** |
| phase_1 | 2617 | 13 | 1174 | **3791** |
| phase_2 | 2617 | 13 | 1135 | **3752** |
| phase_3 | 2617 | 13 | 1135 | **3752** |
| **phase_35** | 1938 | 13 | 1122 | **3060** ← smallest |
| phase_4a | 2610 | 13 | 1089 | **3699** |
| phase_4b | 2878 | 14 | 1451 | **4329** |
| phase_4c | 2392 | 14 | 1225 | **3617** |
| **phase_5** | 3800 | 16 | 1911 | **5711** ← biggest |
| phase_6 | 2581 | 13 | 1264 | **3845** |

Pre-refactor floor (every phase): **~30.6k tokens** (22.5k system + 8.1k tool schemas).
Post-refactor: per-phase floors range from ~4k (phase_35) to ~7.5k (phase_5) tokens. **~75-85% reduction** across the pipeline.

## Module sizes after PR6

| File | Lines | Role |
|------|------:|------|
| `app/agent/handoff.py` | 108 | Per-boundary `PhaseHandoff` dataclasses |
| `app/agent/state.py` | 160 | Shared types: `LoopState`, `_PHASE_SEQUENCE`, `PHASE_TOOL_SUBSETS`, addendums |
| `app/agent/history.py` | 230 | `MoveLog` + `query_history` schema (compaction logic deleted in PR6) |
| `app/agent/loop.py` | 459 | `AgentLoop` passthrough façade |
| `app/agent/router.py` | 473 | `RouterLoop` (session-wide state + dispatch + widget flush) |
| `app/agent/phase_loop.py` | 1302 | `PhaseLoop` + `build_full_tool_catalog` (per-phase reasoning + tool registry) |

Total: 2732 lines (was 1600+ as a monolith — net growth is from explicit Router/PhaseLoop separation + handoff dataclasses; per-method cyclomatic complexity is much lower).

---

## Non-obvious decisions worth remembering

### PR3: Compaction moved from `PhaseLoop._run_react_turn` to `Router.step`

Originally, compaction lived at the top of `_run_react_turn`. After PR2 added isolation, the call site no longer ran for the shared `_global_history` at the right moment — isolated loops have their own `_run_react_turn` operating on their isolated history. Moving to `Router.step` (AFTER user-message append, BEFORE `_dispatch`) made compaction loop-agnostic. PR6 then removed compaction entirely.

### PR4: `_pending_widget` moved from `PhaseLoop` to `Router`

`physics_classification` is `advances_phase=True` AND emits a widget. The advance triggers `_select_active_phase_loop` which swaps `_phase_loop` to the next phase's loop. Router.step's `finally` then read `_pending_widget` from the **wrong** loop. Moving the slot to Router (one per session-step, immune to mid-step loop swaps) fixed it.

### PR4: Mirror user/assistant messages into isolated `_phase_history`

Under isolation, Router appends user messages to `_global_history` only — but each phase's LLM call reads `_phase_history`. For mechanical phases (setup, phase_1-3) this happened to not matter because the LLM had session_config + the phase brief seed; but widget-protocol phases (`[CONFIRMED_CLASSIFICATIONS]` for phase_4a, `[CONFIRMED_MATERIAL_MAPPING]` for phase_5) need the user message verbatim. The fix in `PhaseLoop.dispatch`: at top, append user_msg to `_phase_history` (unless NEGOTIATING which has its own append); at exit, append the assistant reply too so the next turn starts on a balanced alternating history.

### PR4: Façade proxies for `_annotate_chains` / `_suggest_texture_mapping` target the per-phase loop via `_get_or_build_phase_loop`

Tests do `patch.object(loop, "_annotate_chains", side_effect=fake)` BEFORE calling `step`. The active loop at patch time may not yet be phase_4a (typically it's the setup loop on cold start). Routing the proxy through `_get_or_build_phase_loop("phase_4a")` gives a stable instance: the patch lands on the same loop that `step()` will later activate via `_select_active_phase_loop`.

### PR5: "Wrong phase_slot" rejection message changed semantics

Pre-PR5, all tools were registered on the generic loop, so calling a tool from the wrong slot was rejected by the `phase_slot != _PHASE_SEQUENCE[_phase_idx]` guard ("phase_6" appears in message). Post-PR5, each per-phase loop only exposes its subset, so a wrong-slot call is rejected upstream by "tool not available". Test `test_wrong_phase_slot_tool_is_rejected_without_advancing` was loosened to accept either rejection — the load-bearing invariants (`_phase_idx` not bumped, no `phase_completed` event) hold in both paths.

### PR6: `_hydrate_from_move_log` simplified to phase_idx restore only

Before: rebuilt a synthetic phase-granular `_global_history` for the LLM to read on resume. Now: restores `_phase_idx` from the MoveLog's `phase_advance` count and leaves `_global_history` empty. Per-phase loops build their own histories from their phase prompts on first activation; the LLM uses `query_history` to recall older detail. Hydration is ~25 lines instead of ~70.

---

## Deferred (not done in PR6)

Three items from the original PR6 plan were deliberately deferred because they require disproportionate test rewrites for negligible runtime benefit:

- **Delete `_global_history`.** Production code no longer reads it (every LLM call uses an isolated `_phase_history`), but Router.step still appends user/asst messages to it as a flat debug log. `~30` tests read `loop._global_history` for assertions; rewriting them is mechanical but large. Current state: harmless append-only log, reset on completed-session hydrate.

- **Delete pause rails.** `_phase_just_advanced` and `_last_tool_requires_pause` are NOT dead — Issue #15's "phase-advancing tool pauses for user wrap-up" logic in `_run_react_turn` depends on them. They live on each per-phase loop and work identically pre/post-refactor.

- **Delete `AgentLoop` façade.** ~100 tests construct `AgentLoop(...)` and reach into proxied attributes. Deleting the façade requires either updating every test to use `RouterLoop` directly, or accepting a one-shot mechanical rewrite. The façade adds zero runtime overhead — proxies forward calls. Suggested as a follow-up clean-up PR after the next push lands and the architecture is stable.

---

## Verification (run after each PR)

```powershell
# Full unit suite. Baseline: 589 passing + 13 pre-existing failures (TestPhysicsChains x11,
# test_phase_transition x1, test_query_tools x1). No new regressions.
& "D:/2files/models/vrc/CC/Blender-MHWilds/REE-ModPilot/ModPilot/.venv/Scripts/python.exe" `
    -m pytest -m unit --tb=no -q

# SSE event ordering — strictest assertions
& "D:/2files/models/vrc/CC/Blender-MHWilds/REE-ModPilot/ModPilot/.venv/Scripts/python.exe" `
    -m pytest -m unit tests/unit/test_agent_loop_events.py -v

# Widget protocol + context-management flow + interrupt
& "D:/2files/models/vrc/CC/Blender-MHWilds/REE-ModPilot/ModPilot/.venv/Scripts/python.exe" `
    -m pytest -m unit tests/unit/test_agent_loop_history.py tests/unit/test_context_management_flow.py tests/unit/test_widget_routes.py tests/unit/test_agent_interrupt.py -v
```

---

## Critical files

| File | Why |
|------|-----|
| `ModPilot/app/agent/router.py` | RouterLoop — entry point for every turn, owns `_select_active_phase_loop` and `_pending_widget` |
| `ModPilot/app/agent/phase_loop.py` | PhaseLoop — `_run_react_turn`, widget protocol, ASK mode; also `build_full_tool_catalog` module-level |
| `ModPilot/app/agent/state.py` | `PHASE_TOOL_SUBSETS` — the single map controlling per-phase tool scoping |
| `ModPilot/app/agent/prompts.py` | `PHASE_TO_SECTION_KEY` + `build_system_prompt(include_section_keys=...)` |
| `ModPilot/app/agent/loop.py` | Façade — proxies; deferred deletion |
| `ModPilot/app/agent/history.py` | `MoveLog` + `query_history` schema (compaction deleted in PR6) |
| `ModPilot/app/agent/handoff.py` | `PhaseHandoff` dataclasses (shells; per-boundary fields incremental) |
| `ModPilot/app/main.py:298-333` | `AgentLoop` instantiation site — façade keeps it working |
