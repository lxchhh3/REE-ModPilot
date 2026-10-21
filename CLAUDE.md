# CLAUDE.md

**Always read [lesson.md](lesson.md) at the start of every conversation in this project.** It holds
the primer, the run commands, the step rules and the trimmed lesson log.

Working notes for Claude Code in this repo.

---

## Read these first (in order)

1. [lesson.md](lesson.md): primer and lesson log. Read it first, every session.
2. [README.md](README.md): status, how a step is called, the three channels, layout, setup, tests.
3. [AGENTS.md](AGENTS.md): rules, commands, style.

Open everything else on demand: `docs/dev/lessons-detail.md` by lesson ID,
`docs/dev/restructure.md` for why the code looks the way it does, `docs/dev/plugin_api.md` for a
Toolkit operator, `docs/dev/restructure_test_mapping.md` for where an old test's intent went.

## Doc weight (2026-08-06)

- **lesson.md**: one trimmed bullet per lesson, at most 3 lines / 300 chars, a stable `#NN`, newest
  at top. Depth goes to [docs/dev/lessons-detail.md](docs/dev/lessons-detail.md) under the same
  ID with a `(→detail)` marker. A `PreToolUse` hook (`~/.claude/hooks/lesson_format_check.py`)
  enforces the limit. It matches on the `**#NN**` prefix, so a bullet without an ID slips past it.
- **README.md**: pointers and skeletons, not prose. Dated history goes in `CHANGELOG.md`.
- **What happened / what shipped** goes to the context-manager board, not into these files.

## Current stage (2026-10-21)

The restructure is done (M0–M3, M5–M7; M4 dropped). ModPilot is a library: `src/modpilot` runs
inside Blender, `src/modpilot_host` on the host. Claude Code is the agent. It calls steps in
kevin's Blender 5.2.2 over Blender Lab MCP (9877) or the bridge (9876), or in a headless session.
Next: groups B (physics defaults) and C (materials). Record:
[docs/dev/restructure.md](docs/dev/restructure.md).

---

## Driving kevin's Blender

- **Calling a step.** Through Lab MCP's execute tool, send
  `import modpilot; print(modpilot.call("doctor", {}))`. A step that may run past 300 s
  (`physics_chains`, `material_generate`, `batch_export`) goes over 9876 with
  `modpilot_host.transport.BridgeTransport(timeout=...)` instead.
- **Edits reach live Blender without a restart.** `modpilot.call` re-imports changed modules first.
  Check the report's `code.reloaded` and `code.sha` to see which code ran.
- **The live scene is unsaved work.** Use a headless session (`HeadlessSession`) for anything
  experimental, and touch the live scene only when kevin asks.
- **The bridge's wire protocol** (9876): one raw JSON object each way, no newline and no length
  prefix. `{"type": "execute_code", "params": {"code": ...}}` goes in;
  `{"status": "success", "result": {"result": <stdout>}}` or `{"status": "error", "message": ...}`
  comes back. Read until the buffer parses as JSON. `transport.py` already does this, and finds the
  report by its `MODPILOT_REPORT=` line among the add-ons' own prints.

## Project rules

- **Platform:** Windows 11, Blender **5.2.2 only**. 4.3 has been out of scope since 2026-10-20. In
  tools-5.2, run L3 with `-k "not 4.3.0 and not test_new_blender_builds_the_same_mod_as_old and
  not test_new_blender_returns"`.
- **The fork is public.** `Ref/` (Dimi's BHS_fixed, ~900 MB) must never be committed. Scan diffs
  for secrets before pushing. Push to `fork` only; `upstream` (Dimi's repo) has its push URL disabled.
- **Working rules:** kevin's global `~/.claude/CLAUDE.md` governs work here: TDD, ask when an
  instruction is unclear, follow his decisions and discuss before changing one. Reply in English.
  The rules Dimi set at the project's start (cf872ef, 2026-05-09: reply in 中文, plan-then-code,
  strict scope) were dropped on 2026-10-16, when kevin took the project over.
