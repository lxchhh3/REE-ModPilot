# Lesson Detail — REE-ModPilot

Depth for the lessons marked `(→detail)` in [../../lesson.md](../../lesson.md).
**Open BY ID only** — never read this file wholesale; that defeats the point of the trimmed primer.

IDs are stable and match `lesson.md` exactly. This file runs the project's own `#NN` sequence,
independent of the global `~/.claude/lesson.md` sequence — resolve a bare `#NN` within its own domain.

Entries here are the verbatim pre-trim text, kept for the commands, exact symbols and diagnostic
orders that don't survive a 300-char summary.

---

## #5 — TestClient + sse-starlette don't compose

TestClient + `sse-starlette` long-lived stream don't compose: `client.stream(...).iter_text()` and even just entering/exiting `with client.stream(...)` block can hang forever waiting for body drain → Verify SSE wire format via manual `curl -N --max-time N` against a running uvicorn, not via TestClient. In unit tests, inspect `app.state.agent_streams[sid]` queue contents directly.

---

## #10 — Ollama Cloud is not OpenAI-compatible

Ollama Cloud's `POST /api/chat` is NOT OpenAI-compatible (response is `body.message.content`, not `choices[0].message.content`) so `OpenAIProvider` 200s the request then explodes on parse. Wire format check: if a provider returns `done` / `done_reason` / `eval_count` you're talking Ollama, write a dedicated `OllamaProvider` against `httpx`. Tool-call ids are NOT returned — synthesize client-side uuids so the agent loop can pair `tool_use ↔ tool_result` across turns.

---

## #11 — `get_viewport_screenshot` reports failure in-band

blender-mcp `get_viewport_screenshot` writes the PNG to a filepath we supply on disk (NOT a base64 blob in the response) and reports failures as `status="success"` + `result["error"]` rather than top-level `status="error"` (the addon catches its own exceptions before returning) → Wrapper picks a `tempfile.NamedTemporaryFile(delete=False)` path, sends it as `filepath`, reads bytes back, deletes the temp, and inspects `result.get("error")` itself to raise `BlenderError`. Don't trust top-level status alone for this handler.

---

## #15 — Phase-tool param-name drift

Phase-tool param-name drift between schema and runtime is invisible from outside the agent loop: e.g. `MaterialInspect`/`MaterialSetup` take `target_object` (not `mesh_object`), `MaterialGenerate` takes `mesh_collection` + `preset_mapping` (not `mesh_object` + `material_presets`), `PhysicsChains` takes `inferred_types` (not `chain_classifications`). The LLM-driven path normally hides this because the prompt+schema flow ensures names match. When writing direct-call harnesses like `verify_mvp.py`, grep `tool_schema` for each phase you call and use the exact key names — don't mirror what the agent loop appears to do, mirror what the JSON schema declares.

---

## #20 — `PresetSupplementWrite` suffix chaining

`PresetSupplementWrite` always writes `<base>_extended.json` — if the user (or LLM) passes `base_preset_name="VRChat_extended"`, the result is `VRChat_extended_extended.json`. Functionally correct (merges fine, registers via `add_x_preset`) but the chain of `_extended` suffixes is ugly when the LLM re-supplements a preset it just wrote. Verified on the Eku VRChat avatar run: turn 1 produced `VRChat_extended` @ 83.33%, turn 2 then produced `VRChat_extended_extended` @ 98.15%. Polish path (post-MVP): when the base already ends with `_extended`, mutate it in place instead of generating a deeper suffix.

---

## #21 — Phase 1 scale-align switched to arm bones (issue #13)

Phase 1 scale-align method changed in issue #13: was mesh-bbox-Z-max ratio, is now arm-bone average-Z ratio (upperarm/forearm/hand × L/R). The bbox method silently failed on rigs with anything sticking above the head (hats, weapons, hair flying up). Note that this also means the existing test_phases.py PoseCorrection class needs an autouse fixture to stub `_resolve_arm_candidates` — otherwise `discover_preset_dir` triggers an extra `execute_and_extract` call on the mock client and inflates `call_count` past existing assertions (3 → 4 for MMD/Endfield paths). Pattern: when a phase tool starts doing a side-channel Blender query, audit `call_count`-based assertions in its test file. The check itself isn't broken, but it becomes a coupling that propagates.

---

## #22 — Interrupt bail-point placement (issue #14)

Issue #14 interrupt mechanism: bail point MUST be at the top of the `_run_react_turn` for-loop (i.e. *between* rounds) and inside the per-tool-call inner break — NEVER between `history.append(assistant tool_use msg)` and the matching `history.append(user tool_result msg)`. The Anthropic API rejects unmatched `tool_use` blocks with HTTP 400. The existing try/finally placeholder injector (the "Skipped — preceding tool call failed" branch) covers the inner-loop break path so partial drains stay balanced. Reset the flag on bail-out — a sticky flag silently swallows the user's NEXT message. Also: on the JS side, ignore Escape when the focus is inside an `INPUT`/`TEXTAREA`/`SELECT` (otherwise Esc-to-blur kills the agent) and skip the POST when status isn't `thinking` (no in-flight phase to interrupt).

---

## #23 — Phase-transition pause ordering + tool-name ≠ class-name (issue #15)

Issue #15 phase-transition pause: when adding a NEW wrap-up branch to `_run_react_turn`, the issue #14 interrupt check MUST run first — otherwise the interrupted user pays for an extra wrap-up `llm.chat` round-trip before the bail-out fires. Order: drain → error_reply guard → `_interrupted` guard → `state != RUNNING_PHASE or _phase_just_advanced` wrap-up.

Also: tool *names* differ from class names — `SetupValidateScene` registers as `"setup_validate_scene"` (not `"setup_validate"`), `InferModelType` as `"setup_infer_model_type"` (not `"setup_infer"`). When mocking tool_calls in tests, grep `def name(self)` on the phase module — guessing from the `_PHASE_SEQUENCE` slot name (which IS truncated, e.g. `setup_validate`) makes the test silently hit the "Tool not available" path and the phase never advances.

---

## #26 — Tauri 2 release builds must go through `pnpm tauri build`

For Tauri 2 release builds, always use `pnpm tauri build` (or `--no-bundle` variant for just the exe), NEVER raw `cargo build --release` → cargo alone compiles with `--cfg dev` set (visible in `cargo build --release -v` rustc invocation line), which makes Tauri's asset handler read from `devUrl` (Vite at :5173) instead of using the embedded bundle. modpilot.exe then spawns, opens its window with default title "ModPilot", and the WebView2 webview navigates to `http://tauri.localhost/index.html`, gets a 404 from an empty asset handler, falls back to `chrome-error://chromewebdata` (DevTools console shows `Not allowed to load local resource: chrome-error://chromewebdata/#buttons`). Backend sidecar starts fine, Rust shell logs all green, the only thing missing is the JS bundle itself.

Diagnostic: grep the built exe for the current JS bundle filename (e.g. `Select-String index-XXXXXXXX` in PowerShell); zero matches = bundle not embedded; ~8.5 MB exe size also indicates dev mode (production with bundle is ~9.2+ MB). Today we lost ~2 hours chasing port conflicts, system proxy interference, WebView2 user-data corruption, and Tauri 2 capability/CSP theories before noticing `--cfg dev` in the verbose build output.

Build invariant for ModPilot: never run `cargo build` against `src-tauri/` directly except for syntax checks; always go through `pnpm tauri build`.

---

## #27 — LLM provider/model mismatch is a silent 404

LLM provider/model mismatch is a silent 404, not a startup error: `~/.modpilot/config.json` is allowed to persist any combination of `llm_provider` + `llm_model`, the `LLMClient.from_settings()` factory constructs the provider object successfully (no model-existence check), and the failure only surfaces when an actual chat round-trip hits the provider's `/api/chat` endpoint with an unknown model id.

Symptom: `POST /agent/messages → 500` with `httpx.HTTPStatusError: 404 Not Found for 'https://ollama.com/api/chat'` because the persisted config carried `provider=ollama` + `model=deepseek-chat` (the `deepseek-chat` model lives on api.deepseek.com via OpenAI-compatible, NOT on Ollama Cloud). Root cause was the `/config` UI dropdown: when the user switched Provider from openai_compatible to ollama, the Model field stayed at `deepseek-chat` — nothing reset it.

Fix shipped in commit `481cd9d` covers both sides:

- (a) server guardrail `_validate_provider_model_combo()` in `POST /app/config` returns 422 + `field_errors.llm_model` for obvious mismatches (ollama + `deepseek-chat`/`claude-*`/`gpt-*`; anthropic + non-claude); openai_compatible stays open-universe since you can't enumerate every Qwen/GLM/Mistral variant.
- (b) UI `PROVIDER_DEFAULTS` map in `ConfigPage.tsx` — switching the Provider dropdown swaps Model + Base URL to the new provider's known-good defaults, but ONLY if the current values match a recognized default (so a manually-typed `qwen-max` isn't clobbered when switching openai_compatible → openai_compatible). ConfigPage also unwraps `ApiError.body.detail.field_errors[0]` for the user-facing message instead of "POST failed: 422".

Diagnostic order when you see `/agent/messages` 500 in the future: (1) `GET /app/config` to inspect persisted `(provider, model, base_url)`; (2) `Get-Content $env:LOCALAPPDATA\com.modpilot.app\logs\backend.log -Tail 30` for the httpx URL + status — provider mismatch shows up as a 404 against the wrong host before any LLM-internal error.

---

## #28 — FE session_id must persist or recovery is dead code

Frontend `session.ts` mints a fresh 12-char hex on every page reload by default — backend session recovery is useless without persistence. Flip to `localStorage` (key `modpilot.session_id.v1`), validate the stored value against `/^[a-f0-9]{12}$/i` before trusting it (defends against manual tampering / future format migrations), and fall back to module-scope cache when `localStorage.getItem`/`setItem` throws (Safari private mode, locked-down WebViews).

Without the localStorage flip, the entire `moves.jsonl` recovery pipeline is dead code in production: same browser, same backend, fresh session_id every reload → backend always creates a new AgentLoop → prior session orphaned on disk.

---

## #29 — Session-recovery hydration is phase-granular

Session-recovery hydration must be phase-granular, not turn-granular. Faithfully replaying `tool_use` / `tool_result` blocks into `_global_history` requires preserving the exact `tool_use_id` strings the LLM generated — Anthropic API 400s on any mismatch, and the move log doesn't store ids. The robust path: count `phase_advance` entries → `_phase_idx`, inject one `[compacted] <wrap-up>` summary per completed phase, NEVER replay mid-phase tool detail.

Mid-phase work is recovered via (a) scene-is-memory (the agent re-queries Blender on next turn) and (b) `query_history` (past decisions stay on disk). The cost is that a mid-phase crash loses the partial work's chat context — but ModPilot's design already treats Blender's saved state as the source of truth, so this is in-policy.

> **Partly superseded by issue #20 (PR6):** hydration was simplified to restoring `_phase_idx` only —
> the synthetic `[compacted]` history rebuild is gone. The phase-granular *principle* still holds.
> See [refactor_hierarchical_loop.md](refactor_hierarchical_loop.md).

---

## #30 — `query_history` needs a server-side `last_n` backstop

`query_history` meta-tool cannot rely on system-prompt advice alone for `last_n` bounds. The prompt asks the LLM to keep it small, but a misbehaving (or just curious) LLM can call `query_history()` with no args and force the entire move log back into context — defeating the whole point of compaction.

Server-side backstop in `_execute_tool_call`'s handler: default to `QUERY_HISTORY_DEFAULT_LAST_N=50` when omitted/invalid (non-int, ≤ 0), clamp to `QUERY_HISTORY_MAX_LAST_N=1000` otherwise. Keep the cap in the handler, NOT in `MoveLog.read()`, so internal callers like `_hydrate_from_move_log()` stay uncapped (hydration legitimately needs every `phase_advance` to count the phase index correctly).

---

## #31 — Compaction needed two flags, not one (SUPERSEDED)

> **Superseded by issue #20 (PR6):** compaction was deleted outright — `compact_phase_range`,
> `COMPACT_MARKER` and `_just_completed_phase` no longer exist. Per-phase history isolation
> replaced it. `_phase_just_advanced` (the issue #15 wrap-up rail) IS still live on each `PhaseLoop`.
> Kept because the two-flag reasoning explains why the wrap-up rail sits where it does.

Context-management compaction needs TWO flags on AgentLoop, not one. `_phase_just_advanced` (Issue #15) drives the IN-TURN wrap-up llm.chat — set when `_phase_idx += 1`, consumed at the end of `_run_react_turn`, reset same turn. `_just_completed_phase` (this work) drives the NEXT-TURN compaction — set in the same place, consumed at the TOP of the next `_run_react_turn`, reset there. Don't collapse them into one flag: the wrap-up message has to land in history BEFORE compaction reads it as the summary text, so the two events fire on opposite sides of an `await asyncio.to_thread(self._llm.chat, ...)` boundary that spans two user turns.

Also: the wrap-up `assistant` move logged in `step()` carries the NEW phase in its `phase` field (because `_phase_idx` already incremented before `step()` appended), so when hydrating from `moves.jsonl` you cannot filter by phase to find the wrap-up — use append order + look for the first `assistant` move AFTER the `phase_advance` entry.

---

## #32 — `vision_available()` cache + refresh discipline

`vision_available()` snapshots `settings.vision_model` on first call (issue #22 spec §配置探测规则 demands the cache) → tests that mutate `settings.vision_model` directly observe a stale value until `refresh_vision_cache()` runs. POST `/app/config` invalidates on every save so the FE sees fresh state on the next GET; tests must do it manually.

Even `patch("app.llm.vision_client.settings") as mock_settings` doesn't bypass it — the cache stores the resolved bool, not a settings reference, so swapping the module's settings object alone doesn't help.

Pattern: `refresh_vision_cache(); settings.vision_model = "X"; assert vision_available() is True` and a `finally` that resets `vision_model = ""` + `refresh_vision_cache()` so the next test isn't poisoned.

Diagnostic when a vision test flakes by ordering: grep the failing file for `refresh_vision_cache` — if it's missing on the mutation path, the prior test's cached value is leaking through. Cache exists for spec compliance, not perf (`bool(str)` is free); the symptom you'll actually hit is test-isolation drift, not slow calls.

---

## #33 — DeepSeek learned-helplessness loop

DeepSeek agent learned-helplessness pattern: after `physics_chains` failed once AND the phase-slot gate rejected it post-sync-to-phase_5, DS locked into "我无法从我这端执行" — repeating scene checks, telling the user to click Blender UI buttons, and never trying `sync_phase_state` backward on its own. Generic "继续" nudges make it worse (each refusal in history reinforces the next).

What worked: one action per message, stating its ACTUAL current slot, naming the exact meta-tool + arguments, and correcting it with its own evidence ("你的工具列表里有 X").

Kin of #19 (the DS-summary lesson): its "导出完成" report listed invented file paths — always verify `batch_export` from `moves.jsonl` `result_summary` + `Get-ChildItem` of natives_root, never from the chat reply.

---

## #34 — `mhws.auto_create_chains` is headless-broken in the installed toolkit

`mhws.auto_create_chains` fails headless with `RuntimeError: Collection not found:` (empty name): the chainCollection-PointerProperty fallback that `PhysicsChains` documents as the "post-toolkit patch" lives in the operator's `invoke()` only, and scripted `bpy.ops` calls go straight to `execute()` — so `self.chain_collection` (a dynamic enum whose items list is also populated only by `invoke()`) is always empty.

Compounding it, the toolkit is DOUBLE-INSTALLED in `%APPDATA%\Blender Foundation\Blender\4.3\scripts\addons\` (`Modding-Toolkit` AND `Modding-Toolkit-main`, both from 2026-05-12); both register the same `bl_idname`, so monkeypatching the first class returned by `Operator.__subclasses__()` fixes nothing when the other copy's registration won the idname.

2026-08-06 workaround: in-memory patch of EVERY class carrying the idname (wrap `execute` to repopulate `_chain_col_items` + default `chain_collection` from `re_chain_toolpanel.chainCollection`) — reverts on Blender restart.

Durable fix (kevin to decide): move the fallback into `execute()` in the addon source, and/or delete the duplicate install.

---

## #35 — MHWs tex-pak requirement (disputed)

Original claim (kevin, 2026-08-06, from fixing mods after the Aug 4 game update): MHWs loads mod TEXTURES only from a `.pak`, never loose — every shipped mod carries a tex pak; mesh/mdf2/chain2/fbxskel run fine loose alongside it.
Disputed same day: Dimi says a separate tex pak is no longer needed. Until an in-game test settles it, ship BOTH loose tex and the tex pak — `e2e_mod_out` does, so it is covered either way. Update this entry with the verdict once L3 runs.

Pack with `ree-pak-cli pack -i <staging-root-containing-natives/> -o <mod>/X_tex.pak` (tool at `disable hunter glow\Tools_unpacked\ree-pak-cli\`; older copy in `mhws_Proj...教学\工具\解包跟封包工具`).

Verify by round-trip: `unpack --project <name>` resolves names via `assets/filelist/<name>.list` relative to CWD — write the expected paths there, then hash-compare. Done for `e2e_mod_out/Maya_tex.pak` (19 entries, byte-identical).

Candidate backlog item: make Phase 6 emit the tex pak itself.

## #38 — VRChat-avatar MDF pitfalls (alpha semantics + hair master)

Round 3-4 of the Maya E2E port (2026-08-06) surfaced three reusable facts for the MDF generator:

1. **Cloth ALBD alpha is not transparency.** VRChat avatars encode outfit TOGGLES in the albedo alpha channel. With the donor block's `BaseAlphaTestEnable` on, the skirt's faces alpha-discarded and the skirt "disappeared". Cloth/body materials need alpha test OFF (round-2 flags value `134217880`).
2. **Hair needs the opposite.** Hair strand cutout is real alpha — the donor's hair block runs alpha-test ON (`134217883`).
3. **Deprecated hair master darkens white hair.** Our generator put Hair on `Base_ATOS_VFX_Hair_NoPDO.mmtr` with default props (`DeepShadowColor`/`Basecolor_Fade` defaults) — white-silver hair rendered dark red-brown. The working maya2 mod (same avatar) puts hair on `Base_Equip.mmtr` with a color+alpha ALBD (their hair.tex is NEUTRAL gray, sat 0.014 — no baked tint) and it renders faithfully. Fix applied: clone the donor hair block, point ALBD at `Hair_BaseAlpha`, keep our `Hair_NRRO`.

Tooling notes: RE-Mesh-Editor's `modules/mdf/file_re_mdf.py` is bpy-free and round-trips mdf2.45 byte-losslessly (verified md5) — ideal for surgery. Pak-entry hashes are `(mmh3_utf16(path.upper()) << 32) | mmh3_utf16(path.lower())` over the full `natives/stm/...` path — usable to label `_Unknown` unpack outputs. `texconv` PNG output needs WIC (fails headless with 80004002); TGA output works.

## #39 — MHWs armor physics-file kit (chain2/clsp coverage + post-update versioning)

Round-4 "skirt/butt/tail-tip vanish in-game" root-caused by A/B against TWO working mods
(Dimi's BHS `ch03_024` and the maya2 donor `ch03_062`):

1. **Coverage.** Both working mods override the physics layer on *all 5* armor part slots, not just
   the slot carrying the model. Kill-files: 16 B empty CLSP (`43 4C 53 50 00 00 00 00 10 00 00 00 00 00 00 00`)
   on every part; 128 B empty chain2 v14 header (0 groups/settings/collisions/links) on parts whose
   vanilla chains must die. Our e2e artifact shipped only part-2 chain2 → all vanilla pl001 `clsp.3`
   files stayed live.
2. **clspFlags semantics.** `Chain2GroupData.clspFlags0/1` are bitmasks into the collision groups of
   the clsp loaded *for that part*. ModPilot's Phase-4C flags-only fallback (lesson #37) wrote fat
   masks (245763 skirt/Hips, 49155 Tail, 12351 twin tails) intended for a generated full-body clsp
   that never existed (`create_full_body_clsp` absent in Chain Editor v11) — so the masks indexed the
   *vanilla* part-2 clsp. The in-game vanish pattern (skirt, butt=Hips jiggle, tail tip) maps exactly
   to the groups with the largest orphaned masks. BHS ships masks (8634368) only on skirt strands and
   only alongside his own 800 B clsp; everything else is 0.
3. **Versioning.** The Aug-4-2026 update bumped chain2 to v14: the engine now requests `.chain2.14`;
   `.chain2.13` files (vanilla filelist, donor's stale stub parts) are dead paths. clsp stayed `.clsp.3`.
   Vanilla pl001 has NO jcns (donor's jcns overrides are specific to ch03_062).

Fix applied to `artifacts/e2e_mod_out` (v6): zeroed clspFlags on 34/38 groups in our part-2 chain2
(RE-Chain-Editor `file_re_chain2.py` is bpy-free and round-trips v14 byte-losslessly — verified before
surgery; backup `.pre_clsp_bak`), wrote clsp kill-stubs on parts 1-5 and chain2 kill-stubs on 1/3/4/5.
Proper fix later: generate a real body clsp + matching masks. Cosmetic gaps left: no chain links
(BHS has 6 inter-strand skirt links), 38 unique settings vs BHS's 11 shared, `_end_End` doubled
terminal names (self-consistent, harmless). fbxskel exonerated: every fbxskel in every working mod is
22,136 B = vanilla bone set with re-proportioned transforms (BoneSystem grafts no custom bones from it).

**Update 2026-08-07 (post-v6 corrections).** The v6 in-game test came back identical to v5, which
falsifies "orphaned clspFlags → vanish" as the root cause (the coverage convention above still
matches every working mod and stays). Corrections from extracting current game paks
(ree-pak-cli + an augmented filelist with `.chain2.13→.14` variant paths, game at
`D:\SteamLibrary\steamapps\common\MonsterHunterWilds`):

1. **Version behavior**: the Aug-4 TU did NOT deprecate `.chain2.13`. Patches 012-015 contain only
   8 `.chain2.14` files (TU-touched assets, incl. `ch03_024_0015`); every other armor still loads
   its base-pak `.13`. Engine reads both; a `.14` override shadows the vanilla `.13`.
2. **Attr exoneration**: vanilla `ch03_001_0012.chain2.13` (14,248 B, 27 groups) uses
   `groupDefaultAttr=0x100A0` on most chains and `settingsAttrFlags=1` on several — the exact combo
   our vanished chains carry. It is Capcom-standard, not poison. Vanilla also sets `clspFlags1=2272`
   everywhere (pairs with its shipped 1,024 B clsp).
3. **Install-staleness theory retracted**: the empty ch03\001 tree in the game dir was just kevin
   uninstalling between tests — v6 WAS tested fresh, so its null result genuinely falsifies the
   clsp/mask hypothesis. Fluffy-ready package built anyway for one-click installs:
   `ModPilot/artifacts/Maya_pl001_v7.zip` (modinfo.ini added; backups + Maya_tex.pak excluded).
   Extracted vanilla pl001 chain2/clsp live in the session scratchpad `vanilla_extract/base_pl001/`
   as the authoritative attr donor if the v7 bisect implicates chain2 content after all.

**Update 2026-08-07 #2 — v7 bisect verdict.** With part-2 chain2 replaced by an EMPTY stub (zero
chains loaded, clsp killed on all parts), skirt/butt/tail-tip STILL vanish. The chain2 file is
therefore fully exonerated — the custom bones' verts collapse with no chain sim in play at all,
meaning those bones never receive valid runtime matrices. Combined with HideFace no-oping, the
failure lives in the runtime skeleton / part-instantiation layer (pfb per Dimi's C5), not in any
file our exporter writes. Note ch03_001_0012.pfb is 4.9 KB vs ch03_024_0012.pfb 2.6 KB — armor
hosts differ structurally; armor 001 may simply be a hostile host for custom-bone meshes.
Unverified assumption exposed: nobody has confirmed the reference mods' PHYSICS still work
post-Aug-4 (ModFixer fixed materials only) — verify on armors 062/024 in-game before further work.

## #40 — Exported fbxskel carried hunter proportions (root cause of round-5 "bone is broken")

kevin's in-game read after the first successful BoneSystem engagement on armor 001: "the mod used a
hunter bone instead of the right bone for maya". Verified offline in one script
(mhwilds-fbxskel-tools `FbxskelParser`, per-bone `loc` deltas over the 224 common bones):

| pair | total pos delta | bones moved >1mm |
|---|---|---|
| ours vs vanilla example | **1.84** | 67 |
| ours vs donor (same avatar) | 5.85 | 115 |
| ours vs BHS | 6.07 | 110 |
| donor vs BHS (avatar family) | 4.03 | 130 |
| donor vs vanilla | 6.67 | 126 |

Our `Maya.fbxskel.7` clusters with the VANILLA hunter skeleton, not with the two proven
Maya-family skeletons. Spot check: `L_Shin` local Y = +0.056 in ours where vanilla/donor/BHS are
all negative — out-of-family garbage. Conclusion: ModPilot generated the fbxskel from the wrong
armature state (template `MHWilds_Female Armature` proportions, pre-avatar-merge), not the final
merged Maya rig. Pipeline fix pending (Plan-then-Code with kevin): fbxskel export must run on the
aligned/merged rig; also confirm the uint32 at file offset 0x40 (differs per mod, 0 in vanilla —
likely a name hash the writer must set).

Interim fix shipped in `Maya_pl001_v9.zip`: quarantined our fbxskel
(`Maya.fbxskel.7.hunter_bak`), shipped the donor's proven `ch03_062_0002.fbxskel.7` byte-identical
under its own name, json `FbxPath` → `ch03_062_0002`.

**Verification-loop takeaway**: this bug class is now checkable OFFLINE in seconds — compare
per-bone positions of a generated fbxskel against a known-good same-avatar reference (family
clustering). First brick of a static L3 pre-flight harness; candidate for a `ModPilot verify`
subcommand alongside the mdf/mesh/chain parsers already proven bpy-free this week.

**Correction 2026-08-07 (same day).** kevin corrected the in-game read: the skeleton is overall
FINE — only minor issues on the legs (consistent with the L_Shin sign-flip; small, real, not
fatal). The original conclusion above ("hunter proportions = wrong armature") was flawed:
ModPilot's Phase-1 strategy FITS THE AVATAR TO THE TEMPLATE RIG, so a near-vanilla fbxskel is the
expected, correct output for our pipeline. RigForge-based mods (donor, BHS) use the opposite
strategy — keep avatar shape, re-proportion the skeleton toward it — which is why their fbxskels
deviate heavily from vanilla. Family-clustering against RigForge outputs therefore CANNOT judge a
ModPilot fbxskel; a strategy-aware baseline is needed (e.g. compare against the aligned template
rig, or bound the per-bone deltas). v9 (donor fbxskel + FbxPath repoint) is SHELVED — applying the
donor's avatar-proportioned skeleton to our template-fitted mesh risks distorting it; stay on v8
(our fbxskel restored). The L_Shin flip stays as a minor polish item for the exporter.

## #41 — Single-sided VRChat cloth + the adjacent-bit trap (round-5 root cause candidate)

**The trap.** `MDFFlags` bit0 = `BaseTwoSideEnable`, bit1 = `BaseAlphaTestEnable` — adjacent. In round 4
the skirt-vanish was blamed on alpha-test (lesson #38), and the "fix" ASSIGNED `134217880` to the four
cloth/body materials. `134217883 - 134217880 = 3` = **both** bits: that assignment silently cleared
two-sided rendering as well. Rule: read-modify-write single bits via the ctypes bitfield
(`mat.flags.BaseTwoSideEnable = 1`), never assign a whole flag int copied from another material.

**Why it hides geometry.** VRChat avatar cloth is modelled as single-sided sheets. Measured on our
export (faces whose verts are all dominant-weighted to a region; a directed edge with no reverse twin
is a boundary):

| region | material | faces | boundary edges | in-game |
|---|---|---|---|---|
| skirt | Cloth (two-side **OFF**) | 1102 | 476 (43%) | **invisible** |
| twin tails | Hair (two-side **ON**) | 1466 | 1350 (92%) | renders |
| tail tip | Hair (two-side ON) | 1124 | 196 | invisible — separate cause, likely Hair's `BaseAlphaTestEnable` + transparent UV region |

Equally single-sided geometry renders or not exactly according to the flag. Both working references
agree: donor maya2 `cloth/skir/pantu/acc/kutu` and BHS `Cloth/BHS_A/B/F/Shoes` are all `134217883`
(two-side + alpha-test ON); only their *body/face* materials differ (donor OFF, BHS ON).

**Fix shipped (v10)**: `BaseTwoSideEnable=1` on Body/Body_all/Cloth/Effect → `134217881`. Deliberately
ONE bit — alpha-test stays off so the VRChat outfit-toggle alpha (lesson #38) can't confound the test.
Exactly 4 bytes changed in the 82,618 B mdf2; `Maya_pl001_v10.zip`, backup `.pre_twoside_bak`.
If the skirt returns but stray geometry appears, `134217883` (matching both references) is next.

**Elimination context (everything ruled out first, all offline):** runtime probe proved the armor part
loads with all 373 joints at correct world positions and `enabled=true` with 5 materials; bone tree
links 100% reachable; per-submesh distinct-bone counts (72 max) below donor's 79 so no palette limit;
zero verts use the extended 8-weight slots; palette index is not a cutoff (BHS works with skirt at
171-191). The decisive reframe: the skirt was VISIBLE in v2 and vanished in v3, and the only file that
changed was the mdf2 — the mesh was never guilty.

**Correction 2026-08-07 — #41 fix did NOT work.** v10 (`BaseTwoSideEnable=1` → 134217881 on
Body/Body_all/Cloth/Effect) left the skirt/butt/tail-tip exactly as before in-game. The adjacent-bit
trap and the two-side divergence from both working references are real and the fix is KEPT (it matches
donor + BHS), but two-sided rendering is NOT the mechanism hiding the geometry. The single-sided-sheet
correlation table above is therefore suggestive, not causal — Hair (two-side ON) also loses its tail
tip, which should have warned me before shipping the claim.

**Honest state at end of round 5.** Everything measurable has been exonerated by direct test:
mesh bytes (bone tree, skinning, palette, weight slots, faces), runtime instantiation (probe: part
object present, 373 joints, correct world positions, `enabled=true`, 5 materials), chain2 and clsp
(empty-stub bisect), fbxskel (strategy-aware — near-vanilla is correct for ModPilot's avatar→rig fit),
BoneSystem (engaged via REF UI, no change), REF autorun scripts (all disabled, no change), MDF flags.
`HideFace` provably never applies (`Player_Face`, 393 joints, still instantiated).

**Strongest untested lead**: the mdf2 property VALUES. kevin reported the skirt VISIBLE in v2 and gone
in v3, and the only file that changed between them was the mdf2 (old 187-prop layout → donor's
post-update 191-prop blocks). `Maya_pl001_v11_mdfbisect.zip` is prepared for that test: v10 files with
the pre-donor mdf2 restored. It will render with the old black-material bug, but it answers one
question — does the skirt come back? Yes → the mdf2 is the file, bisect its 31 differing property
values. No → the v2-visible premise is wrong and the search restarts from the pfb layer.

**Process lesson (for me, not the code)**: three "root cause found" claims this round, all wrong. Each
was a strong correlation shipped before an in-game test could refute it. Correlations over a single
sample are hypotheses; only kevin's 5-minute in-game loop converts them to facts, so they must be
labelled as candidates until then.

## #43 — Blender 5.x breaks two scripted add-on paths ModPilot depends on (2026-10-11)

Found by running ModPilot's real Phase 4C code headless in Blender 5.2.2 with the pinned add-on set
from `Blender-MHWilds/tools-5.2` (it passed in 4.3.0: 63 collider objects, 42 bound to existing
bones). Registration-level checks (L0) and file-format round trips (L1) were all green on 5.2.2;
only executing the operators shows these.

1. **`object.select_grouped` needs a 3D View in 5.x.** `bpy.ops.object.select_grouped.poll()` is
   False in background mode whether or not the active object is selected; 4.3.0 polls True.
   blender-mcp runs code from a `bpy.app.timers` callback with `context.area = None`, so the agent
   path is expected to hit it too (clicking the button in the viewport works). Victim:
   Modder_Batch_Tool `games/MHWilds/ToPose.py:180` inside `mbt.mhwilds_tpose`, which
   `mbt.import_mhwilds_fmesh` calls when `mbt_toolpanel.mhwilds_convert_to_tpose` is on.
   Version-proof replacement: `for c in arm.children_recursive: c.select_set(True)`.
2. **Geometry Nodes modifier inputs lost dict access in 5.x.** `mod["Socket_1"] = obj` raises
   `TypeError: ... id properties not supported for this type` (reads: `no __getitem__ support`).
   The 5.x surface is `mod.properties.inputs.Socket_1.value = obj` (attribute per input
   identifier; `inputs.Socket_1` itself is read-only). Victim: RE Chain Editor, 28 sites across
   `blender_re_chain.py`, `blender_re_clsp.py`, `re_chain_operators.py`, `re_chain_propertyGroups.py`;
   first hit is `blender_re_clsp.py:510` during `re_clsp.importfile`. RE Mesh Editor, Modding-Toolkit
   and Modder_Batch_Tool have no such sites. NSACloud ended support 2026-04-01, so a fix means a fork.
