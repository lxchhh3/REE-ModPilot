# CLAUDE.md

**Always read [lesson.md](lesson.md) at the start of every conversation in this project** — orientation primer, run commands, hard rules, and the trimmed lesson log. Read it before anything else.

Working notes specific to Claude Code / Claude API agents in this repo.

---

## Read These First (in order)

1. [lesson.md](lesson.md) — Primer + lesson log. Hard requirement: read first, every session.
2. [README.md](README.md) — Status, architecture, layout, prerequisites.
3. [AGENTS.md](AGENTS.md) — Hard rules + commands + style + workflow.

Everything else is opened **on demand**, not up front: `docs/dev/lessons-detail.md` by lesson ID,
`docs/dev/design.md` for a decision's rationale, `docs/dev/backlog.md` for open work,
`docs/dev/plugin_api.md` for an operator signature, `docs/user/plan.md` for the video workflow.

## Doc-weight discipline (2026-08-06)

`lesson.md` had grown to ~8.5k tokens and README to ~5.5k — both loaded every session. Keep them thin:

- **lesson.md** = ONE trimmed bullet per fix, ≤3 lines / ≤300 chars, stable `#NN`, newest at top.
  Depth goes to [docs/dev/lessons-detail.md](docs/dev/lessons-detail.md) under the same ID with a
  `(→detail)` marker. A `PreToolUse` hook (`~/.claude/hooks/lesson_format_check.py`) enforces the
  limit — it matches on the `**#NN**` prefix, so an ID-less bullet silently bypasses the gate.
- **README.md** = pointers and skeletons, not prose. Release-time detail lives in
  `docs/dev/desktop_build.md`; dated history in `CHANGELOG.md`.
- **Episodic "what happened / what shipped"** goes to the **context-manager**, not into these files —
  it is indexed, drillable by `entry_id`, and doesn't tax every future session's context.

## Current Stage

**MVP shipped**; current work is post-MVP polish (P1 → P3 in the backlog). 672 unit tests green,
70+ Playwright checks, L3 acceptance against MMD/VRC models. Architecture: FastAPI + hand-rolled
ReAct (`RouterLoop` + 13 `PhaseLoop`s, 30-tool catalog) + React 19/Vite SPA + optional Tauri v2 shell.

Latest milestone — **2026-08-06, first full export through the agent path** (Maya Ver1.02.2 →
`ModPilot/artifacts/e2e_mod_out`), not yet autonomous and not yet L3-verified. Blockers and
diagnostics are lessons `#33`/`#34`/`#35`. For dated history see [CHANGELOG.md](CHANGELOG.md); for
live status see the context-manager board injected at session start.

---

## blender-mcp Wire Protocol (footgun-prone — read carefully)

Read `addon.py` directly from wherever blender-mcp is installed — it is **not vendored here** (see Prerequisites in [README.md](README.md); typically `%APPDATA%\Blender Foundation\Blender\4.3\scripts\addons\blender-mcp\addon.py` or your clone of [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp)). Do **not** trust that repo's README — it describes `server.py`'s MCP wrapper, not the raw socket protocol.

- **Request**: pure JSON object, **no newline / no length prefix**.

  ```json
  {"type": "execute_code", "params": {"code": "..."}}
  ```

- **Response**: pure JSON object, also no separator.

  ```json
  {"status": "success", "result": {"executed": true, "result": "<stdout>"}}
  ```

  Errors: `{"status": "error", "message": "..."}`.
- **`execute_code` returns stdout only** — `exec(code)`'s last expression is **not** auto-returned. Always `print(...)` to get values back.
- **Reading the socket**: loop `recv()` accumulating buffer, retry `json.loads` each iteration; success = full response. **Don't read by line. Don't read by fixed length.**
- **Operator stdout pollution**: Modding-Toolkit operators may `print` their own debug output, which interleaves with our `print(...)`. Use a **sentinel string** to bracket our own output and slice from there. (Pattern in [verify_blender_mcp.py](verify_blender_mcp.py): `SENTINEL = "===STAGE0_OUT==="`.)
- Built-in handlers (addon.py:206-216): `get_scene_info` / `get_object_info` / `get_viewport_screenshot` / `execute_code`.

---

## Memory Files

Persistent context for Claude (in `~/.claude/projects/.../memory/`):

| File | Type | Summary |
|------|------|---------|
| `MEMORY.md` | index | One-line pointers to each memory below |
| `feedback_english_to_kevin.md` | feedback | The 中文 policy governs the runtime agent, not Claude Code — reply to kevin in English |
| `feedback_planning_first.md` | feedback | Don't jump from tech-validation to implementation; use design docs |
| `feedback_discuss_alternatives.md` | feedback | Discuss unsuitable options too — user uses this project as a learning vehicle |
| `project_python_over_llm.md` | project | LLM only at phase-internal classification points; deterministic Python everywhere else |
| `project_state_2026_08.md` | project | kevin drives this solo since ~July 2026; Aug-6 first-export milestone + working runtime setup |
| `project_may_leftovers.md` | project | What the archived May-19 session logs / eval report are; both bugs they exposed are fixed at HEAD |
| `recall_as_template.md` | reference | Project structure (README/CLAUDE/AGENTS/backlog) borrows from YoungZ2357/Recall |

---

## Project-Specific Quirks & Rules

- **User Platform**: Windows 11 and Blender 4.3.2.
- **Working rules**: kevin's global `~/.claude/CLAUDE.md` governs work here (TDD; ask when an instruction
  is unclear; follow his decisions and discuss before changing one). The language, interaction and
  workflow rules Dimi set at the project's start (cf872ef, 2026-05-09: reply in 中文, plan-then-code,
  strict scope) were dropped on 2026-10-16, when kevin took the project over.
