# REE-ModPilot

> MH Wilds character-mod steps that run inside Blender, as a Python library.
>
> 面向 MH Wilds 人物 Mod 的 Blender 步骤库（在 Blender 内运行）。

This is kevin's fork ([lxchhh3/REE-ModPilot](https://github.com/lxchhh3/REE-ModPilot), branch
`restructure`) of [Dimcirui/REE-ModPilot](https://github.com/Dimcirui/REE-ModPilot). Dimi's
original, an AI agent with its own LLM loop, FastAPI backend and React/Tauri app, is still in
Dimi's repo and in this fork's history before `1e18e56`.

---

## Status

| | |
|---|---|
| Restructure (2026-10-19 → 10-21) | 🟢 M0–M3, M5–M7 done; M4 (builds as recipe files) dropped. Record: [docs/dev/restructure.md](docs/dev/restructure.md) |
| Who drives it | Claude Code, in kevin's Blender 5.2.2 or in headless Blender. ModPilot has no agent or UI of its own any more |
| Verified | Three builds passed in game with ModPilot's tools (claude_run1, GG, Marette). Every step is tested in a real headless Blender 5.2.2 |
| Next | Group B (physics defaults) and group C (materials), ported from the recipes that passed in game |
| Blender | 5.2.2 only. 4.3 has been out of scope since 2026-10-20 |

---

## How it works

`ModPilot/src/modpilot` is a plain Python package that Blender imports. It registers no bpy
classes. One call runs one step:

```python
import modpilot
report = modpilot.call("vertex_groups", {"mesh_objects": ["Body"], "x_preset": "VRChat"})
```

- **Report:** `{ok, step, params, data, warnings, skipped, scene_diff, popups, seconds, code, blender}`.
  It is also printed as one `MODPILOT_REPORT=<json>` line, so a channel that returns only stdout
  still carries it.
- **Failure:** every failure raises `StepError(category, message, step, operator, details,
  partial)`, printed as `MODPILOT_ERROR=<json>`. The category is one of `params`, `precondition`,
  `operator`, `postcondition`, `environment` or `internal`. Nothing fails silently.
- **Params:** each step takes a strict frozen dataclass. Unknown keys and wrong types are refused.
- **Reload:** before each call, ModPilot re-imports any of its modules whose source changed.
  The report's `code.reloaded` says so.
- **Help:** `modpilot.steps()` lists the steps, and `modpilot.describe(name)` gives one step's
  params and docstring.

### Three ways to reach a Blender

| Channel | Where | Use it for |
|---|---|---|
| Blender Lab MCP, port 9877 | kevin's Blender, through Claude Code's MCP tools (`modpilot_host.transport.LabTransport` from Python) | short steps and looking at the scene; its server gives up after 300 s |
| Community blender-mcp bridge, port 9876 | kevin's Blender (`modpilot_host.transport.BridgeTransport`) | long steps: `physics_chains`, `material_generate`, `batch_export` |
| Headless session, free port | a private `blender -b` with the pinned add-ons (`modpilot_host.session.HeadlessSession`) | tests, replays and anything that must not touch the live scene |

Every channel sends the same two lines: `import modpilot` and `modpilot.call(step, params)`.

### Steps

| Module | Steps |
|---|---|
| `setup` | `setup_import_source`, `setup_validate_scene`, `setup_infer_model_type`, `setup_preset_supplement_write`, `setup_preset_custom_write`, `setup_import_mhwilds` |
| `pose` | `pose_correction`, `skeleton_align` |
| `vertex_groups` | `vertex_groups` |
| `physics` | `physics_transplant`, `physics_classification`, `physics_chains`, `physics_adjust` |
| `colliders` | `collider_create`, `collider_apply` |
| `materials` | `material_setup`, `material_generate`, `material_inspect`, `material_consolidate` |
| `export` | `batch_export` |
| `garments` | `mute_shape_keys`, `rebind_rigid_garments`, `restore_leaf_bones` |
| `query` | `list_objects`, `scene_info`, `get_bone_info`, `list_collections`, `get_mesh_info`, `get_material_info`, `get_object_props`, `inspect_material_nodes`, `physics_read`, `list_mdf_presets` |
| `doctor`, `fingerprint` | `doctor` (add-ons and versions), `scene_fingerprint` (a comparable digest of the scene) |

---

## Layout

```
ModPilot/src/
├── modpilot/          runs inside Blender
│   ├── core/          call(), @step registry, params, StepError, report, SceneConfig, snapshot, ops.run, popups
│   ├── steps/         the steps above
│   ├── bl/            Blender helpers: context overrides, joins, fits, chains, source fixes
│   ├── formats/       bpy-free file code: chain2, jcns, mdf, mesh patch, key rows, unitypackage
│   ├── geom/          bpy-free numpy: similarity fit, cones, legs, weights, GPU cloth grid
│   ├── mods/          whole-mod edits: relocate, colour_fix
│   ├── testing/       synthetic scenes and rigs for the tests
│   └── data/          physics_presets.json, clsp_body_bits.json, full_body.clsp.3, armor_sets.json
└── modpilot_host/     runs on the host, no bpy
    ├── transport.py   LabTransport (9877), BridgeTransport (9876)
    ├── session.py     HeadlessSession
    ├── bpytest.py     pytest inside headless Blender
    └── tools52.py     finds tools-5.2 (pinned add-ons, isolated profiles)
```

ModPilot leans on **tools-5.2** (`Blender-MHWilds/tools-5.2`, beside this checkout; set
`MODPILOT_TOOLS52` to point elsewhere). tools-5.2 pins the Blender builds and add-on versions,
builds the isolated profiles, and its L0/L3 suites replay ModPilot's steps.

---

## Setup

1. **Add-ons in kevin's Blender:** in tools-5.2, run `uv run python -m compat.install_live`. It
   installs the pinned Modding-Toolkit, Modder_Batch_Tool, RE Mesh Editor, RE Chain Editor and
   blender-mcp, plus Blender Lab MCP. The set is listed in `tools-5.2/pins.toml`.
2. **The package:** make a directory junction
   `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\modules\modpilot` → `ModPilot\src\modpilot`.
   `addons/modules` is on Blender's `sys.path`; `scripts/modules` is not (Blender-MHWilds
   lesson #98). Headless sessions link it themselves.
3. **Host tools:** `cd ModPilot && uv sync`.
4. **Pytest for Blender's Python:** `uv pip install --target .bldeps --python-version 3.11 pytest`.

## Tests

Run these from `ModPilot/`. `uv run pytest` fails here with a trampoline error (lesson #45), so
call the venv's Python.

| Tier | What | Command |
|---|---|---|
| T0 | bpy-free code: formats, geom, params, transport, presets; an AST test bans `bpy` there | `.venv/Scripts/python.exe -m pytest tests/core` |
| T1 | real steps on synthetic scenes in headless Blender 5.2.2, one Blender per file | `.venv/Scripts/python.exe -m modpilot_host.bpytest tests/bl/test_*.py` |
| all host | T0 plus `tests/blender`, which runs every T1 file (344 tests, ~6 min) | `.venv/Scripts/python.exe -m pytest` |
| live | `doctor` over 9876 and 9877 in kevin's Blender (read-only) | `.venv/Scripts/python.exe -m pytest -m live` |
| L0/L3 | tools-5.2: the operators ModPilot calls exist; the claude_run1 replay; the group-A fixes | in tools-5.2: `.venv/Scripts/python.exe -m pytest tests/test_l0_*.py tests/test_l3_*.py -k "not 4.3.0"` |

[docs/dev/restructure_test_mapping.md](docs/dev/restructure_test_mapping.md) maps each deleted
mocked test to the test that covers it now.

---

## References

| Doc | Purpose |
|---|---|
| [lesson.md](lesson.md) | Session primer and lesson log, read first |
| [CLAUDE.md](CLAUDE.md) | Working notes for Claude Code |
| [AGENTS.md](AGENTS.md) | Rules, commands and style |
| [docs/dev/restructure.md](docs/dev/restructure.md) | Why and how the fork was restructured, and which old decisions it replaced |
| [docs/dev/design.md](docs/dev/design.md) | Dimi's A–E decisions (many replaced; see restructure.md) |
| [docs/dev/plugin_api.md](docs/dev/plugin_api.md) | Modding-Toolkit operator reference |
| [docs/user/plan.md](docs/user/plan.md) | The 7-video mod-making walkthrough (human reference) |
| [CHANGELOG.md](CHANGELOG.md) | Dated history |

Docs under `docs/` that open with a "Historical" banner describe the app deleted in M6.
