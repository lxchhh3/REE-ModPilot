# AGENTS.md

Baseline guide for AI agents and contributors working on REE-ModPilot (kevin's fork).

Overview: [README.md](README.md). Why the code is shaped this way:
[docs/dev/restructure.md](docs/dev/restructure.md). Claude Code notes: [CLAUDE.md](CLAUDE.md).

---

## Project at a glance

- **What:** MH Wilds character-mod steps that run inside Blender, called one at a time by an agent
  (Claude Code) or a test.
- **Stack:** Python 3.11+ (Blender 5.2.2's own Python for `modpilot`), numpy, uv, pytest, ruff.
- **Depends on:** the Modding-Toolkit, Modder_Batch_Tool, RE Mesh Editor, RE Chain Editor and
  blender-mcp add-ons at the versions pinned in `tools-5.2/pins.toml`.

---

## Common commands

Run these from `ModPilot/`. `uv run pytest` fails here (trampoline error, lesson #45); call the
venv's Python.

```bash
uv sync                                                    # host environment
uv pip install --target .bldeps --python-version 3.11 pytest   # pytest for Blender's Python (T1)

.venv/Scripts/python.exe -m pytest tests/core              # T0: bpy-free, seconds
.venv/Scripts/python.exe -m modpilot_host.bpytest tests/bl/test_physics.py   # T1: one file in headless Blender
.venv/Scripts/python.exe -m pytest                         # T0 + every T1 file (~6 min)
.venv/Scripts/python.exe -m pytest -m live                 # read-only doctor in kevin's Blender (9876/9877)

.venv/Scripts/ruff check src tests
.venv/Scripts/ruff format src tests
```

T1 logs: `tools-5.2/runtime/logs/bpytest/5.2.2/`.

---

## Hard rules

1. **A step is a function** decorated `@step("name", ParamsDataclass)` in `src/modpilot/steps/`. Its
   params are a frozen dataclass. Unknown keys and wrong types are refused before the step runs.
2. **Every failure raises `StepError`** with a category (`params`, `precondition`, `operator`,
   `postcondition`, `environment`). No `except: pass`, no "non-fatal" branches, no fallback that
   guesses. A skip happens only when the params opt in, and it goes in the report's `skipped`.
3. **Operators run through `modpilot.core.ops.run`**, which requires `{'FINISHED'}` and turns an
   add-on error popup into a `StepError`. Give context-dependent operators an explicit override
   (`modpilot.bl.context`) and check the result afterwards.
4. **Scene names come from `SceneConfig`** (`scene["modpilot_config"]`), never from a literal in a step.
5. **The bpy-free parts stay bpy-free:** `core.params`, `core.errors`, `core.report`, `core.step`,
   `core.config`, `presets`, `datafiles`, `physics`, `colliders` and the `formats`, `geom` and
   `mods` packages. An AST test (`tests/core/test_bpy_free.py`) enforces it.
6. **No bpy classes registered by `modpilot`.** The package is reloaded in place; a registered class
   would break that.
7. **Tests run real code.** A step's test (T1) builds a synthetic scene (`modpilot.testing`) and
   calls the step in headless Blender. Don't mock Blender.
8. **Never commit `Ref/`** (Dimi's files, ~900 MB, private). The fork is public.

---

## Code style

- **Type hints** on function signatures.
- **Imports:** Ruff's isort order. Inside `modpilot`, import `bpy` within functions in modules
  the host also imports.
- **Comments:** English only, and only where the *why* isn't obvious from the code.
- **Docstrings:** each step module's docstring records what changed on purpose from the legacy tool.

| Category | Style | Example |
|---|---|---|
| Files, functions, variables | `snake_case` | `vertex_groups.py`, `bake_mix()` |
| Classes | `PascalCase` | `StepError`, `VertexGroupsParams` |
| Constants | `UPPER_SNAKE_CASE` | `CATEGORIES` |
| Step names | the legacy tool names | `physics_chains` |

---

## Workflow

1. **TDD:** write the T0/T1 test first and watch it fail, then write the code.
2. **Run the suites before committing:** T0 always; T1 for the files you touched; tools-5.2 L3
   when a step's behaviour changes.
3. **Commit messages:** Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`).
4. **Branches:** work goes on `restructure` (or a branch from it) in the fork. Never push to `upstream`.

---

## Status badges

| Symbol | Meaning |
|---|---|
| 🟢 | Done / decided / passing |
| 🟡 | In progress / partial |
| ⚪ | Not started |
| 🔴 | Blocked / failing / decision required |
