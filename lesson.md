# REE-ModPilot — Session Primer

> Read this at the start of every session: orientation up top, lesson log at the bottom.
>
> **Keep it thin.** Each lesson is ONE trimmed bullet (≤3 lines / ≤300 chars) carrying a stable
> `#NN`. IDs are never renumbered or reused — cross-refs point here. Depth for the deep ones
> (`→detail`) lives in [docs/dev/lessons-detail.md](docs/dev/lessons-detail.md); open it **by ID**,
> never wholesale. Highest ID so far = **#59**; the next new lesson is #60.
> Episodic "what happened / what shipped" narrative belongs in the context-manager, not here.

---

## What this project is

kevin's fork of Dimi's ModPilot, restructured 2026-10-19 → 10-21 ([docs/dev/restructure.md](docs/dev/restructure.md)).
`ModPilot/src/modpilot` is a library of MH Wilds character-mod steps that runs **inside Blender
5.2.2**: `import modpilot; modpilot.call("vertex_groups", {...})` returns a report or raises
`StepError`. Claude Code is the agent. It calls steps in kevin's Blender over Blender Lab MCP (9877)
or the blender-mcp bridge (9876), or in a headless session. ModPilot has no LLM, agent loop or UI
of its own any more; the app was deleted in M6 (`1e18e56`).

## Where to look

| Need | File |
|------|------|
| Status, calling a step, the three channels, layout, setup, tests | [README.md](README.md) |
| Driving kevin's Blender, project rules | [CLAUDE.md](CLAUDE.md), **always read** |
| Step rules, commands, style | [AGENTS.md](AGENTS.md) |
| Why the code is shaped this way; which old decisions it replaced | [docs/dev/restructure.md](docs/dev/restructure.md) |
| Where a deleted mocked test's intent went | [docs/dev/restructure_test_mapping.md](docs/dev/restructure_test_mapping.md) |
| Modding-Toolkit operator reference | [docs/dev/plugin_api.md](docs/dev/plugin_api.md) |
| Lesson depth, by ID | [docs/dev/lessons-detail.md](docs/dev/lessons-detail.md) |

## How to run

From `ModPilot/`. `uv run pytest` dies with a trampoline error here (#45), so call the venv's Python.

```bash
uv sync
.venv/Scripts/python.exe -m pytest tests/core                  # T0, bpy-free, seconds
.venv/Scripts/python.exe -m modpilot_host.bpytest tests/bl/test_physics.py   # T1, headless Blender 5.2.2
.venv/Scripts/python.exe -m pytest                             # T0 + every T1 file, ~6 min
.venv/Scripts/python.exe -m pytest -m live                     # doctor in kevin's Blender, read-only
```

In live Blender: `import modpilot; print(modpilot.call("doctor", {}))`. The package reaches it
through the junction `%APPDATA%/Blender Foundation/Blender/5.2/scripts/addons/modules/modpilot`.

## Step rules

1. A step takes a strict frozen params dataclass; unknown keys and wrong types are refused.
2. Every failure raises `StepError` with a category. No silent paths: no `except: pass`, no guessing
   fallback. A skip needs an opt-in param and is listed under `skipped`.
3. Operators go through `core.ops.run` (`{'FINISHED'}` required; an error popup fails the step).
4. Scene names come from `SceneConfig`, not literals.
5. Test steps in real headless Blender on synthetic scenes (T1), never against a mocked Blender.

## Project quirks

- Windows 11 + Blender **5.2.2 only** (4.3 out of scope since 2026-10-20). PowerShell ≠ Bash syntax.
- The add-ons (Toolkit, MBT, RE Mesh / Chain Editor, blender-mcp) are pinned and installed by
  tools-5.2 (`pins.toml`, `compat.install_live`), not vendored here.
- Lessons #1–#33 are mostly about the app deleted in M6; they stay as history.

---

# Lesson Log

<!-- ONE trimmed bullet per fix: what went wrong / what's non-obvious + the known fix.
     ≤3 lines, ≤300 chars, stable #NN, newest at top. Depth → docs/dev/lessons-detail.md by ID.
     A PreToolUse hook gates this format on every Edit/Write. -->

- **#59** `modpilot.reload()` re-imports `modpilot.core.errors`, so a `StepError` imported before it is a stale class: `pytest.raises(StepError)` misses the new one and the test fails. Import `errors` inside the test, or check `e.category`, not the class.
- **#58** pose_correction's MMD / Endfield T-pose conversion fails headless: the Toolkit's `core/pose_ops._apply_and_rebind` calls `object.select_grouped`, whose poll fails in 5.2 even with the Layout 3D View lent via `temp_override` (cf. #43). T1 keeps it a strict xfail.
- **#57** The legacy tools' scene diff (objects_added / removed / count) is built on blender-mcp `get_scene_info`, which lists only the FIRST 10 objects: past 10 objects it reports adds and removes that never happened. The new core snapshots every object; compare scenes by fingerprint.
- **#56** Blender 4 renamed Principled 'Emission' to 'Emission Color' and defaults Emission Strength to 0, which the Toolkit's generator reads as not emissive: material_setup skipped every emission map. Look slots up by alias; turn a zero strength on.
- **#55** RE Chain Editor has no 'RE_CHAIN_CHAINNODE' type, node `parent_bone` or group `chainSetting`; SHARED mode and collider_create used them and got nothing back (every chain the first type, every head ''). Head = first RE_CHAIN_NODE child's BoneName; settings = parent.
- **#54** Hips poke through a hanging skirt's back: Dimi pre-rotates the limit CONES of the back/side strands 13° (frame rotation = angleLimitDirection) and cone-limits their top joints (15/30/45/60). Only front strands get Free tops. Sampling 2 front strands to copy all 12 broke it.
- **#53** Sleeves hit the sailor collar: pre-rotate the collar's side strips outward (~6° about their top joint) with mesh AND bones together. Dimi tilted only the mesh, so physics never got the room and his bones sat 6.7 cm below the cloth.
- **#52** Legs pierce a simulated skirt front. Dimi's fix needs no colliders: leave the front strands (F, 1, 2) unweighted and skin that cloth to L/R_Thigh + Hip_HJ_00, with physics only on the sides and back. ModPilot weights every strand to its chain.
- **#51** Back collar misbehaved in game: physics_chains starts a flap chain at its root bone (C_Cloak), so the next joint simulates, and full_body.clsp's Spine_2 capsule (r 0.13) held the flap's joints 1-12 mm deep at rest. Start at `.005`, shrink to 0.094; check rest clearance.
- **#50** CORRECTED: a clspFlags mask indexes the part's OWN clsp. BHS's 8634368 has bit 23 inert (no such capsule there); ours is full_body.clsp's 0.2 m hip capsule, which held 41/53 skirt joints inside at rest. Never copy masks; match the colliders hit (thighs r 0.08).
- **#49** physics_transplant (smart_graft) adds `<leaf>_End` only for leaves weighted in meshes still on the SOURCE rig; vertex_groups already moved them, so a rig without `_end` bones got none and auto_create_chains skipped all 34 one-bone chains. Add the `_End`s first.
- **#48** vertex_groups' join keeps ONE value per shape key (the active object's): the BHS FBX lost shoes `High heeled`=1 (soles 4.3 cm into the floor) and `Big breasts` 0.5. Bake each object's own mix before joining, or rebuild per vertex after.
- **#47** collider_create bound full_body.clsp to the ACTIVE object; after 4B the avatar + MHWs armatures exist, so re_clsp.importfile cancelled ("More than one armature"). Now binds `target_armature` (default MHWs). batch_export still never binds clsp, so the colliders don't reach the mod.
- **#46** Blender 5 moved pose-mode selection to `PoseBone.select`; `Bone.select` is gone, so `pb.bone.select = True` killed physics_chains (merge/clear). Use `pb.select` if `hasattr(pb,'select')` else `pb.bone.select`. Found by tools-5.2 L3 replay.
- **#45** `uv run pytest` dies here with "uv trampoline failed to canonicalize script path"; `uv run python -m pytest` works. A test that seeds X_PRESETS before `TestClient(app)` is silently overwritten by the lifespan fallback — seed inside the `with`.
- **#44** `getattr(bpy.ops.ns, 'op', None)` is never None: bpy.ops returns a stub for ANY name and only the call fails ("could not be found"). Check `'op' in dir(bpy.ops.ns)`. ModPilot's old MISSING_OP branch was dead code because of this.
- **#43** Blender 5.x breaks scripted ops in two ways: `object.select_grouped` needs a 3D View (headless and MCP timer contexts fail), and GN modifier `mod["Socket_N"]` is gone (use `mod.properties.inputs.Socket_N.value`). Hits MBT T-pose + RE Chain Editor. (→detail)
- **#42** Modding-Toolkit 2.8.5 renamed presets to ASCII stems (怪猎荒野→`mhws`, 终末地→`arknights`) and `tpose_direction`→`mmd_a_to_tpose`. Enum values are FILE names, so stale literals TypeError at runtime. tools-5.2 L0 checks both in live Blender.
- **#41** MDF flag bits are adjacent: killing alpha-test by ASSIGNING 134217880 also cleared `BaseTwoSideEnable`. Real defect (both working mods use 134217883 on cloth) and fixed to ...881 — but it did NOT restore the skirt, so wrong culprit. Flip single bits, never assign whole ints. (→detail)
- **#40** fbxskel family-clustering fooled us: ModPilot fits avatar→template rig, so near-vanilla fbxskel is CORRECT here (RigForge re-proportions skeleton→avatar — donor/BHS deviate hugely). In-game: fine overall, legs slightly off (L_Shin flip, minor). Don't cross-judge strategies. (→detail)
- **#39** MHWs armor physics kit: working mods kill vanilla physics on ALL 5 parts (16B empty CLSP + 128B chain2 stubs); model part ships real chain2(+clsp). Engine reads chain2 .13 AND .14 (.14 shadows); Aug-4 TU re-exported only touched assets. defAttr 0x100A0 is vanilla-normal. (→detail)
- **#38** VRChat-avatar MDF pitfalls: cloth ALBD alpha = outfit TOGGLES → BaseAlphaTestEnable OFF on cloth (else skirt vanishes) but ON for hair (strand cutout); the deprecated hair master's defaults render white hair dark — put anime hair on Base_Equip with a color+alpha ALBD. (→detail)
- **#37** CORRECTED 2026-10-11: `create_full_body_clsp` was never an RE Chain Editor op — only the uninstalled MHWilds_Chain_Editor fork had it. Phase 4C now imports bundled full_body.clsp.3 via `re_clsp.importfile`. Flags-only fallback still BROKEN (#39).
- **#36** `batch_export` binds ONE collection to every target part → N identical full copies stacked in-game. Real mods ship the model in one part + generic 3.5KB stub mesh / 6KB stub mdf2 in the rest (byte-identical across slots, cloneable); drop stub-part chain2 or physics instantiates N×.
- **#35** MHWs tex-pak need is DISPUTED: kevin's post-Aug-4 belief said textures load only from a `.pak`; Dimi says separate tex paks are no longer needed (2026-08-06). Ship BOTH loose tex + `X_tex.pak` until in-game proof; pack/verify via ree-pak-cli. (→detail)
- **#34** `mhws.auto_create_chains` fails headless (`Collection not found:`) — its chainCollection fallback lives in `invoke()`, which scripted `bpy.ops` skips; the toolkit is also double-installed, so patching one class misses. (→detail)
- **#33** DeepSeek locks into refusal after one tool failure plus a phase-slot rejection, and generic "继续" reinforces it. Break it with one action per message naming the exact tool + args and its real slot. (→detail)
- **#32** `vision_available()` caches its resolved bool on first call → mutating `settings.vision_model` in a test is invisible until `refresh_vision_cache()` runs. Reset it in `finally` or the next test is poisoned. (→detail)
- **#31** SUPERSEDED (#20/PR6 deleted compaction): it needed TWO flags because the wrap-up had to land in history before compaction read it. `_phase_just_advanced` survives as the issue #15 pause rail. (→detail)
- **#30** `query_history` needs a server-side `last_n` backstop (default 50, cap 1000) in the tool handler, else the LLM can pull the whole move log back into context. Not in `MoveLog.read()` — hydration needs it uncapped. (→detail)
- **#29** Session recovery is phase-granular: never replay `tool_use`/`tool_result` blocks (the move log stores no `tool_use_id`, and Anthropic 400s on mismatch). Count `phase_advance` entries → `_phase_idx`. (→detail)
- **#28** FE `session.ts` mints a new session_id on every page reload → the whole `moves.jsonl` recovery pipeline is dead code in production. Persist to `localStorage` and validate the format before trusting it. (→detail)
- **#27** Provider/model mismatch is a silent 404 at first chat, not a boot error — `from_settings()` never checks the model exists. Guardrail in `POST /app/config` + `PROVIDER_DEFAULTS` on the UI dropdown. (→detail)
- **#26** Tauri 2 release: always `pnpm tauri build`, never raw `cargo build --release` — cargo sets `--cfg dev`, so the asset handler reads devUrl and the window lands on `chrome-error://`. (→detail)
- **#25** Tauri v2 on Windows spawns its main window offscreen at (-21333,-21333) 158×26 unless you set `"center": true` in `tauri.conf.json`. The `visible:false` + JS `show()` trick is unnecessary.
- **#24** Browser sandboxes strip filesystem paths from drag-drop — the `File` object has `.name`, no `.path`. Real paths need the Tauri shell (or `tauri-plugin-dialog`); PathField degrades to a text input.
- **#23** The issue #15 wrap-up branch must run AFTER the #14 interrupt guard, else an interrupted user pays for an extra `llm.chat`. Tool names ≠ class names (`SetupValidateScene` → `setup_validate_scene`). (→detail)
- **#22** Interrupt bail-out must sit between ReAct rounds or inside the per-tool-call break — never between an assistant `tool_use` append and its `tool_result` (Anthropic 400s). Reset the flag on bail. (→detail)
- **#21** Phase 1 scale-align uses arm-bone average-Z (issue #13), not mesh-bbox-Z — bbox broke on hats/weapons/flying hair. Side-channel Blender queries then break `call_count` assertions in test_phases.py. (→detail)
- **#20** `PresetSupplementWrite` always appends `_extended`, so re-supplementing yields `VRChat_extended_extended.json`. Works, but ugly; polish = mutate in place when the base already ends in `_extended`. (→detail)
- **#19** Don't trust DS's natural-language summary of a tool result: it announced "54/54 (100%)" while the file it wrote was 53/54 — it forgot the unmappable `spine_03`. Re-run the tool or read the returned diff.
- **#18** Unity Humanoid calls the pinky `Little` — grep both when scanning a rig, plus the space-separated spec form `Little Proximal.{L,R}`, which only matches after a preset supplement.
- **#17** DS reasoning-mode (`deepseek-v4-flash`) costs ~3 min/turn with the full workflow + 20 tool schemas, mostly internal CoT. Ollama's `think: False` would short-circuit it, but `OllamaProvider` doesn't expose it.
- **#16** `curl --data` with UTF-8 Chinese on Git Bash mangles the body (cp1252 round-trip) and FastAPI 422s. Use `curl --data-binary @file.json`, or drive the API from Python `httpx`.
- **#15** Phase-tool param names drift from what the loop appears to pass (`MaterialInspect` takes `target_object`, `PhysicsChains` takes `inferred_types`). For direct-call harnesses, mirror `tool_schema`. (→detail)
- **#14** `PhaseError` is a `@dataclass`, not an `Exception` → `raise PhaseError(...)` gives `TypeError: catching classes that do not inherit from BaseException`. Helpers must return `(value, error)` tuples.
- **#13** Modding-Toolkit ships 13 X-presets, not 14: `街霸6.json` sits in `assets/presets/import/` but declares `type="Y_PRESET"`. Filter on `preset_info.type`, not folder location.
- **#12** The standard X-preset slot list is 51 keys, not the 58 quoted in plugin_api.md — that figure is `modder.init_editor`'s editor scaffolding, not what shipped presets actually fill.
- **#11** blender-mcp `get_viewport_screenshot` writes a PNG to a path you supply and reports failure as `status="success"` + `result["error"]`. Don't trust top-level status for this handler. (→detail)
- **#10** Ollama Cloud `/api/chat` is NOT OpenAI-compatible (`body.message.content`); `OpenAIProvider` 200s then dies on parse. Tell: `done`/`eval_count` in the body. Tool-call ids must be synthesized. (→detail)
- **#9** Reasoning Ollama models spend the token budget on CoT before any visible content — `num_predict=32` returned `content=""` + `stop_reason=max_tokens`. The default 4096 is fine.
- **#8** `Path.home()` is a classmethod — patch it with `classmethod(lambda cls: tmp_path)`, not `lambda self:`. The wrong patch leaks to the real `~` and poisons `~/.modpilot/config.json`.
- **#7** Pydantic v2 `extra="allow"` fields land in `model.model_extra`, not `model_dump()` — that's how the widget routes harvest unknown-ahead-of-time keys like `texmap__<slot>__<mat>`.
- **#6** CSS `display:none` on an ancestor beats `display:flex` on a descendant regardless of specificity — the box is never generated. Bit the config-saved badge nested inside the hidden form section.
- **#5** TestClient + `sse-starlette` hang forever on a long-lived stream, even just entering/exiting the `with` block. Verify SSE via `curl -N --max-time N`; in unit tests read the queue directly. (→detail)
- **#4** `call_soon_threadsafe` emits land AFTER a synchronous `put_nowait` even from the loop thread → `done` arrives before earlier messages. Smart sink: push directly when already on the event loop.
- **#3** `LLMClient.from_settings()` runs in the FastAPI lifespan, so a missing `LLM_API_KEY` kills server boot. Smoke tests: `LLM_API_KEY=dummy LLM_BASE_URL=http://127.0.0.1:9999`.
- **#2** `_get_or_create_session` calls `_get_client()`, which 503s when Blender is unreachable, before `loop.step()` — so SSE payloads can't be curl-tested without live Blender. Monkeypatch in unit tests.
- **#1** `cli.py` and the web UI share `app.state.agent_sessions` by session_id, but only web sessions install an event sink — reusing an id across both means the CLI's turns emit no events.
