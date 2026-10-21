> **Historical (2026-10-21).** This describes ModPilot's own agent, LLM layer, app or legacy tools, deleted in restructure M6 (`1e18e56`). Code paths, commands and test counts here no longer exist; domain notes may still hold. Current docs: [README](../../README.md), [restructure record](../../docs/dev/restructure.md).

# Move Log & `query_history` — Runtime Walkthrough

Concrete walkthrough of what the move log does at runtime. Implementation: `app/agent/history.py`.

**File:** `~/.modpilot/sessions/{session_id}/moves.jsonl` — one JSON object per line, append-only, UTF-8. Never rewritten in place.

*Moved here from the repo root (`Context_mng.md`) on 2026-08-06.*

---

## What gets written, and when

Every move passes through `RouterLoop._log_move()` — `PhaseLoop._log_move()` is a one-line
forward to it, so the router owns the single writer regardless of which phase emitted the move.
Trigger points:

| Trigger | Logged as | Example payload |
|---|---|---|
| `step()` entry, normal user typing | `{kind: "user", phase, content, ts, turn}` | `content` = the typed message |
| `step()` entry, message starts with `[CONFIRMED_CLASSIFICATIONS]` / `[CONFIRMED_MATERIAL_MAPPING]` | `{kind: "widget", ...}` | Same shape, different `kind` |
| `step()` entry, `state == ERROR_HANDLING` | `{kind: "error_choice", ...}` | `content` = `"retry"` / `"skip"` / `"ask"` |
| `step()` after dispatch returns | `{kind: "assistant", phase, content, ...}` | `content` = the agent's reply |
| `_execute_tool_call` after any tool returns | `{kind: "tool", phase, name, args, result_summary, success, ...}` | One entry per call |
| `_execute_tool_call` after a phase-advancing tool succeeds (extra entry, in addition to the tool one) | `{kind: "phase_advance", phase, to_phase, ...}` | `phase` = just-completed, `to_phase` = next or `null` |
| `interrupt()` is called | `{kind: "interrupt", phase, ...}` | Empty payload otherwise |

`ts` (epoch seconds) and `turn` (monotonic 1-indexed counter) are auto-injected if the caller omits them. `turn` resumes from the file's existing line count on construction — survives backend restart.

---

## How `query_history` reads it

The meta-tool is part of every phase's tool subset (`PhaseLoop`) and is routed in `_execute_tool_call()` next to `sync_phase_state`. When the LLM calls it:

```
LLM → query_history(phase="phase_4a", kind="tool")
      │
      ▼
_execute_tool_call sees tool_name == "query_history"
      │
      ▼
self._move_log.read(phase="phase_4a", kind="tool", name=None, last_n=None)
      │
      ▼
Open file → for each line → json.loads → AND-filter by phase/kind/name → last_n trim
      │
      ▼
Return JSON-encoded list of matching move dicts as the tool_result
```

Filters are ANDed, `last_n` applied **after** filtering, malformed lines silently skipped (so one corrupted write doesn't brick the log).

---

## Concrete shape, mid-session

After running `setup_validate`, `setup_infer`, `setup_import`, `phase_1`, then user says `"continue"`, `moves.jsonl` looks roughly like:

```jsonl
{"kind":"user","phase":"setup_import_source","content":"start","ts":1.0,"turn":1}
{"kind":"tool","phase":"setup_import_source","name":"setup_import_source","args":{"file_path":"C:/x.fbx"},"result_summary":"imported","success":true,"ts":1.1,"turn":2}
{"kind":"phase_advance","phase":"setup_import_source","to_phase":"setup_validate","ts":1.1,"turn":3}
{"kind":"assistant","phase":"setup_validate","content":"Source imported. Continue?","ts":1.2,"turn":4}
{"kind":"user","phase":"setup_validate","content":"continue","ts":2.0,"turn":5}
{"kind":"tool","phase":"setup_validate","name":"setup_validate_scene","args":{},"result_summary":"ok","success":true,"ts":2.1,"turn":6}
{"kind":"phase_advance","phase":"setup_validate","to_phase":"setup_infer","ts":2.1,"turn":7}
... etc
```

---

## How it ties to phase isolation

> **Superseded (issue #20, PR6):** this doc originally described a *compaction* pass that
> rewrote `_global_history` into `[compacted] Phase 4A done…` summaries. That machinery
> (`compact_phase_range`, `COMPACT_MARKER`, `_just_completed_phase`) was **deleted** when the
> hierarchical loop split landed — per-phase history isolation solves the same problem more
> cleanly. See [refactor_hierarchical_loop.md](refactor_hierarchical_loop.md).

The move log and what the LLM actually sees are **independent channels**:

- **Each `PhaseLoop` holds its own `_phase_history`**, seeded from that phase's brief. Nothing from
  a previous phase's turns is carried into it — so the prompt starts near-empty at every boundary,
  with no summarization step needed.
- **The move log** writes to disk and is never rewritten.

So `phase_4a`'s tool detail simply never enters `phase_5`'s prompt, while the same detail sits
verbatim in `moves.jsonl` — and that's exactly what `query_history` pulls back when the LLM asks.
Recovery is always possible; it just costs a tool call.

---

## One subtle thing worth knowing

The on-disk `turn` counter and any single loop's history length are **not** the same number. The
log records ~7 moves per phase (user, tool, phase_advance, assistant, then 3 from the next phase)
across the whole session, whereas each `PhaseLoop` only ever holds its own phase's slice.
`RouterLoop._global_history` still appends every user/assistant message, but it is a flat debug log —
no LLM call reads it (its deletion is deferred only because ~30 tests assert on it).

So when you read `moves.jsonl` you're getting the **unabridged** record, not a copy of what's in the prompt.
