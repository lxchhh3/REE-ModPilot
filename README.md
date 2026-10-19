# REE-ModPilot

> AI-guided Blender automation for crafting RE Engine character mods.
>
> 面向 RE Engine 游戏（MHWs / MHWI / RE4 / RE9）的 Mod 制作 AI Agent 原型。

---

## Status

**MVP shipped** — Stages 0 / Setup / 1 / 2 / 3 / 4 / 5 / MVP-verification all 🟢, L3 in-game
acceptance against MMD/VRC source models. **672 unit tests**, 70+ Playwright checks.
All design items in [docs/dev/design.md](docs/dev/design.md) (A/B/C/D/E layers) are 🟢 decided.

| Milestone | State |
|-----------|-------|
| Post-MVP polish | ongoing — see [docs/dev/backlog.md](docs/dev/backlog.md) for open P1-P3 items |
| Latest shipped | #19 texture-slot fix, #20 hierarchical loop split + Phase 4C colliders, #21 `RE_CHAIN_HEADER` calibration, #22 VLM-assisted PBR classification — dated detail in [CHANGELOG.md](CHANGELOG.md) |
| First full agent-path export | 🟢 2026-08-06 — Maya Ver1.02.2 → mesh/mdf2/chain2 + 19 tex + fbxskel in `ModPilot/artifacts/e2e_mod_out`. Needed two manual assists (lesson `#34`); textures must be pak'd to load (`#35`). L3 in-game check still outstanding. |

---

## Project Status: Paused (2026-05-25)

The MVP works and was verified at L3 — mods exported through the full pipeline load and run in-game. Development stopped anyway, for an architectural reason worth stating plainly.

**ModPilot is a workflow, not an agent.**

The execution graph is a single line: phases 1→6, fixed order. The LLM's real authority is *classification within a phase* (which bones are physics bones, which texture maps to which slot) — not *deciding what to do next*. Starting mid-pipeline only means picking an insertion point on that same line and continuing downstream. At no point does the system look at the current scene, form its own judgement about what state it is in, and choose an action accordingly.

Turning it into a real agent is not primarily a coding problem. Autonomous evaluation requires knowing **what an observation means** — "the mesh renders black in-game" → a ranked set of causes with the evidence behind each. That is domain knowledge, and for RE Engine model replacement it is largely unwritten: scattered across chat logs, tool source, and the heads of a handful of people.

⇒ Work moved to building that knowledge layer as a separate project. It is not public yet; an open-source knowledge base is planned once the corpus is solid enough to stand on its own. ModPilot resumes when there is something to plug into it.

**What is here is complete and runnable**: 16 phase tools, hand-rolled ReAct loop, provider-agnostic LLM client, React 19 + Tauri frontend, 526 unit tests / 70+ Playwright checks.

---

## Vision

For Blender-literate users who want to make RE Engine character mods but lack RE Engine modding experience: ModPilot is a **step-by-step AI guide + Blender automation layer** that compresses the mod-making pipeline (`docs/user/plan.md` videos 1-7) from hours to ≤ 1 hour.

**MVP scope** (locked in design.md A4):

| Dimension | Decision |
|-----------|----------|
| Target game | **MHWs** (single-game deep integration) |
| Source models | User-provided; **MMD-preferred / VRC-secondary** |
| Pipeline range | plan.md videos 1-7 (full pipeline) |
| Acceptance | **L3** — exported mod actually runs in-game |
| Time target | 30 min marketing anchor / 1 hr engineering target |

The AI's value concentrates in **videos 4-7** (physics bones / materials / batch export / advanced) where experience-class classification decisions matter (e.g. physics-vs-body bone naming, PBR channel mapping, equipment slot routing). Videos 1-3 are mostly mechanical button-pushes.

---

## Architecture

```
Browser (Vite dev server :5173) ────────────╮
   or                                       │ Same React 19 + TS bundle
Tauri desktop shell (modpilot.exe) ─────────┤  (browser-mode falls back to
                                            │   text path inputs; desktop
                                            │   gets native drag-and-drop)
                                            ↓
                          React SPA (motion + structured JSON SSE)
                                            │
                          FastAPI backend (CORS / Vite proxy)
                            ├── Agent loop          (hand-rolled ReAct: RouterLoop + 13 PhaseLoops)
                            ├── Phase tools         (30-tool catalog across 13 phases; each
                            │                        PhaseLoop sees only its own subset)
                            ├── LLM client          (provider-agnostic: Anthropic / OpenAI-compatible / Ollama)
                            └── Blender client      (TCP socket, thread-safe RLock)
                                            ↓
                          blender-mcp addon.py       (port 9876 — `execute_code` channel)
                                            ↓
                          User's Modding-Toolkit     (bpy.ops.modder.* / mhws.* / re4.* / etc.)
```

**Key architectural decisions**:

- **Phase tool middle layer**, not raw operator wrappers. LLM orchestrates *between* phases and makes *classification* decisions inside phases; deterministic Python orchestrates *within* phases. (B6)
- **Hierarchical agent loop** — a dumb `RouterLoop` owns session-wide state (phase index, move log, SSE sink) and delegates each turn to one of 13 per-phase `PhaseLoop` instances, each carrying only its own scoped system prompt + tool subset. Cut the per-request token floor from ~30.6k to ~4-7.5k. (see [docs/dev/refactor_hierarchical_loop.md](docs/dev/refactor_hierarchical_loop.md))
- **Provider-agnostic LLM client** (~150 lines). Default DeepSeek V4 for development; Claude Sonnet 4.6 / Haiku 4.5 as oracle fallback; Ollama Cloud (`deepseek-v4-flash`) as a third option. Runtime-switchable via `/config` UI — no restart needed. (C10)
- **No RAG in MVP** — `docs/agent/agent_workflow.md` (machine-readable execution manual) goes directly into system prompt + prompt cache. `plan.md` is the video script for humans only. Content RAG retained as a future upgrade path. (C11)
- **React 19 + TypeScript + Vite** frontend, with `motion` for transitions; same SSE event surface as the original htmx build. **Tauri v2** ships an optional Rust desktop shell so the path inputs can accept native file/directory drag-and-drop (impossible inside a browser sandbox). (C25 — supersedes C12)
- **Confirmation widgets** — server-rendered Jinja partials pushed over SSE for Phase 4A (physics bone classification) and Phase 5 (material slot → texture mapping). User edits the widget in-browser; confirmed values re-enter the agent loop as prefixed JSON messages.

---

## Tech Stack

| Layer | Choice | Decided in |
|-------|--------|-----------|
| Runtime | Python 3.11+ | — |
| Web framework | FastAPI | C9 |
| Package manager | uv | C13 |
| LLM (dev default) | DeepSeek V4 (OpenAI-compatible API) | C10 |
| LLM (oracle / fallback) | Claude Sonnet 4.6 / Haiku 4.5 (Anthropic SDK) | C10 |
| LLM (third option) | Ollama Cloud (`deepseek-v4-flash` / `deepseek-v4-pro`) | C10 |
| Agent framework | Hand-rolled ReAct (raw SDKs, no LangChain in MVP) | C9 |
| Frontend | React 19 + TypeScript + Vite + motion (SPA) | C25 (supersedes ~~C12~~) |
| Desktop shell (optional) | Tauri v2 (Rust + WebView2) — enables native drag-and-drop file pickers | C25 |
| Blender integration | TCP socket via blender-mcp addon | Stage 0 |
| Tests | pytest (`unit` / `integration` markers) | D14 |
| Lint / format | Ruff | D14 |

---

## Project Structure

```
REE-ModPilot/
├── ModPilot/                     # Backend application
│   ├── pyproject.toml            # uv-managed
│   ├── uv.lock
│   ├── .env.example
│   ├── app/
│   │   ├── main.py               # FastAPI routes (chat, SSE, widgets, config, screenshot)
│   │   ├── config.py             # Settings (LLM / Blender / vision); runtime-mutable
│   │   ├── config_store.py       # ~/.modpilot/config.json persistence
│   │   ├── toolkit_probe.py      # Modding-Toolkit presence / version probe
│   │   ├── agent/                # RouterLoop + 13 PhaseLoops, prompts, MoveLog, DSML parser
│   │   ├── blender/              # BlenderClient (thread-safe), SceneCache, preset_catalog
│   │   ├── llm/                  # LLMClient (Anthropic / OpenAI-compatible / Ollama) + vision
│   │   ├── data/                 # armor_sets, physics_presets, clsp body bits
│   │   └── phases/               # 21 phase tools (30-tool catalog incl. query + meta tools)
│   ├── frontend/                 # React 19 + TS + Vite + motion SPA
│   │   ├── src/                  #   pages, stages (per-phase UI), components, hooks, lib, types
│   │   └── src-tauri/            #   Tauri v2 Rust shell — see docs/dev/desktop_build.md
│   ├── scripts/ eval/            # Playwright walkthrough recorders; context-eval harness
│   ├── artifacts/                # Generated; gitignored. Mod exports + walkthrough webms
│   └── tests/                    # unit (mocked) | integration (real Blender) | e2e (Playwright)
├── docs/
│   ├── agent/                    # agent_workflow.md — injected into the LLM system prompt
│   ├── dev/                      # design, backlog, plugin_api, agent-api, lessons-detail, …
│   └── user/                     # plan.md (7-video script), demo_setup.md
├── verify_blender_mcp.py         # Stage 0 connectivity verification (5 checks)
├── verify_mvp.py                 # Headless E2E script — drives phase tools directly, no agent loop
├── lesson.md                     # Session primer + trimmed lesson log — read this first
├── README.md                     # ← you are here
├── CLAUDE.md                     # Claude-specific working notes
└── AGENTS.md                     # Contributor baseline (commands, conventions)
```

---

## Prerequisites

- Blender 4.3.2 (other 4.x may work, untested)
- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- An LLM API key — DeepSeek V4 recommended for development; Anthropic key as oracle / fallback

### Required Blender addons (install separately — not vendored)

Install these into your Blender add-on directory before using ModPilot:

| Addon | Source | Role |
|-------|--------|------|
| **Modding-Toolkit** | [Dimcirui/Modding-Toolkit](https://github.com/Dimcirui/Modding-Toolkit) | Provides the `bpy.ops.modder.* / mhws.* / re4.* / re9.* / mhwi.*` operators ModPilot orchestrates |
| **Modder_Batch_Tool** | [Dimcirui/Modder_Batch_Tool](https://github.com/Dimcirui/Modder_Batch_Tool) | Provides the `modder.* / mbt.*` operators ModPilot orchestrates |
| **blender-mcp** | [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp) | TCP socket bridge on `localhost:9876` (we only use its `addon.py`, not the FastMCP server) |
| **RE-Mesh-Editor** | [NSACloud/RE-Mesh-Editor](https://github.com/NSACloud/RE-Mesh-Editor) | Provide editing dependencies for .mesh model files and .mdf2 material files |
| **RE-Chain-Editor** | [NSACloud/RE-Chain-Editor](https://github.com/NSACloud/RE-Chain-Editor) | Provide editing dependencies for .chain2 physics files and .clsp collision files |

After enabling both in Blender → Edit → Preferences → Add-ons, open the BlenderMCP side panel (N-key in 3D viewport) and click **Connect to Claude** — the socket server starts on port 9876.

---

## Quick Start

**1. Verify Blender connectivity (Stage 0)**

```bash
# In Blender: enable both addons, open the BlenderMCP side panel,
# click "Connect to Claude" so port 9876 starts listening.
python verify_blender_mcp.py
```

Expected output ends with `=== Stage 0 PASSED. Pipeline is alive. ===`.

**2. Run the backend**

```bash
cd ModPilot
uv run uvicorn app.main:app --reload   # binds 127.0.0.1:8000
```

**3. Run the frontend (pick one)**

```bash
# (a) Browser mode — fastest dev loop, text-only path inputs
cd ModPilot/frontend
pnpm install                 # one-time
pnpm dev                     # http://localhost:5173, proxies /agent /app /viewport_screenshot /health → :8000

# (b) Tauri desktop mode — native drag-and-drop file/dir paths via PathField
cd ModPilot/frontend
pnpm tauri:dev               # boots Vite, then spawns the Rust shell pointing at it
```

LLM config: first launch (no API key) redirects to `/config`. Enter provider / key / model, or seed via `ModPilot/.env` (see `.env.example` — `LLM_PROVIDER=ollama`, `LLM_API_KEY=…`, `LLM_MODEL=deepseek-v4-flash` for Ollama Cloud). Settings layer in `~/.modpilot/config.json`; `.env` is git-ignored.

**4. Start a mod session**

Fill in the session-config form (source file path, mod root, character name, body part radio, hunter type, armor set, etc.) and click **Start**. The agent walks through Phases 1-6 automatically, pausing at classification checkpoints (physics bone table, material texture mapping) for user confirmation via in-browser widgets.

**5. Run unit tests**

```bash
uv run pytest -m unit -v   # 672 tests, no Blender required
```

**6. (Optional) Headless MVP verification**

```bash
# Copy and fill in the config template, then:
python verify_mvp.py --config verify_mvp_config.json [--phases setup phase_1_2_3 ...] [--report out.json]
```

See `docs/user/demo_setup.md` for prerequisite addon install order, MMD model recommendations, mod folder layout, and the full config field reference.

---

## References

| Doc | Purpose |
|-----|---------|
| [lesson.md](lesson.md) | Session primer + trimmed lesson log (`#NN`; depth in `docs/dev/lessons-detail.md`) |
| [CLAUDE.md](CLAUDE.md) | Claude-specific working notes (footguns, blender-mcp wire protocol, memory map) |
| [AGENTS.md](AGENTS.md) | Agent / contributor baseline (commands, hard rules, conventions) |
| [CHANGELOG.md](CHANGELOG.md) | Dated release history; [docs/dev/backlog.md](docs/dev/backlog.md) for open P1-P3 work |
| [docs/dev/design.md](docs/dev/design.md) | A/B/C/D/E-layer design decisions (rationale, alternatives, escape hatches) |
| [docs/agent/agent_workflow.md](docs/agent/agent_workflow.md) | Machine-readable execution manual (phases 1-6, protocols, operator index) |
| [docs/dev/plugin_api.md](docs/dev/plugin_api.md) | Modding-Toolkit operator API reference |
| [docs/dev/agent-api.md](docs/dev/agent-api.md) | Agent-callable tool catalog |
| [docs/dev/refactor_hierarchical_loop.md](docs/dev/refactor_hierarchical_loop.md) | RouterLoop + PhaseLoop architecture |
| [docs/dev/desktop_build.md](docs/dev/desktop_build.md) | Tauri installer build + code signing |
| [docs/user/plan.md](docs/user/plan.md) | 7-video mod-making workflow script (human reference) |
| [docs/user/demo_setup.md](docs/user/demo_setup.md) | Addon install order, model setup, L3 acceptance procedure |
