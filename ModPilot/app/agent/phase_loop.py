"""PhaseLoop — hosts the per-turn reasoning loop for one phase.

Each phase listed in `PHASE_TOOL_SUBSETS` gets its own PhaseLoop instance,
lazily built and cached on RouterLoop. PhaseLoop owns:
  - `_phase_history` — isolated per-phase conversation history
  - `_phase_tools` — the phase's scoped tool subset (filtered from the full
    catalog by `_tool_names_filter` at construction)
  - `_pending_error` — set when a phase tool fails
  - `_phase_just_advanced` + `_last_tool_requires_pause` — Issue #15 pause rail

Hosts:
  - `_run_react_turn` — the main tool-call loop (DSML fallback + throttle + rails)
  - `_run_negotiating_turn` — legacy, unused (`_NEGOTIATING_PHASES` is empty)
  - `_handle_*` — AWAIT_CONFIRM / ERROR_HANDLING / ASK_MODE
  - `_execute_tool_call` — phase-slot gate + tool dispatch + state_diff handling
  - `_emit_widget_if_inspector` — Issue #3 widget timing (stashes on Router)
  - Tool-list builders + assistant-msg builders

Module-level `build_full_tool_catalog()` returns the complete
`{tool_name: tool_instance}` registry — single source of truth for both
PhaseLoop's `_register_available_phases` and the AgentLoop façade's
full-tool-view proxies.

Cross-loop access: PhaseLoop holds a `_router: RouterLoop` reference and
forwards everything session-wide (event sink, MoveLog, _phase_idx, state,
`_pending_widget`) through it. Properties below proxy the most-accessed
Router attributes so extracted method bodies read identically to the
originals.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from app.agent.dsml import (
    parse_dsml_tool_calls,
    strip_dsml_block,
)
from app.agent.history import (
    QUERY_HISTORY_DEFAULT_LAST_N,
    QUERY_HISTORY_MAX_LAST_N,
    QUERY_HISTORY_TOOL_NAME,
    QUERY_HISTORY_TOOL_SCHEMA,
)
from app.agent.history_heal import heal_history
from app.agent.prompts import build_phase_prompt
from app.agent.state import (
    LoopState,
    PHASE_TOOL_SUBSETS,
    _MAX_ASK_ROUNDS,
    _MAX_QUERY_ONLY_ROUNDS,
    _MAX_TOOL_ROUNDS,
    _PHASE_SEQUENCE,
    _SYNC_PHASE_TOOL_SCHEMA,
    _WRAP_UP_SYSTEM_ADDENDUM,
)
from app.llm.client import LLMResponse, Message
from app.phases.base import PhaseError, PhaseResult, PhaseTool
from app.phases.material import (
    infer_textures_by_reverse_uv_layout,
    suggest_texture_mapping,
)
from app.phases.physics_annotate import annotate_chains
from app.phases.query_tools import QueryTool

if TYPE_CHECKING:
    from app.agent.router import RouterLoop

logger = logging.getLogger(__name__)


_TOOL_CATALOG_CACHE: dict[str, PhaseTool] | None = None


def build_full_tool_catalog() -> dict[str, PhaseTool]:
    """Return the complete `{tool_name: tool_instance}` registry.

    Single source of truth — both `PhaseLoop._register_available_phases` and
    the AgentLoop façade's full-tool-view proxies build their dicts from
    this. Imports are local so module import order can't introduce cycles
    (every phase package transitively pulls a chunk of the stack).

    Cached after first call: tool instances are stateless under our
    contract (the Blender / cache / params come in via `run(...)`), so
    handing back the same instances across calls is safe and lets tests
    do identity comparisons (`loop._phase_tools["x"] is other._phase_tools["x"]`).
    """
    global _TOOL_CATALOG_CACHE
    if _TOOL_CATALOG_CACHE is not None:
        return _TOOL_CATALOG_CACHE
    from app.phases.batch_export import BatchExport
    from app.phases.infer_model_type import InferModelType
    from app.phases.material import (
        MaterialConsolidate,
        MaterialGenerate,
        MaterialInspect,
        MaterialSetup,
    )
    from app.phases.physics_bones import (
        PhysicsAdjust,
        PhysicsChains,
        PhysicsClassification,
        PhysicsTransplant,
    )
    from app.phases.physics_colliders import ColliderApply, ColliderCreate
    from app.phases.pose_correction import PoseCorrection
    from app.phases.preset_write import PresetCustomWrite, PresetSupplementWrite
    from app.phases.query_tools import (
        GetBoneInfo,
        GetMaterialInfo,
        GetMeshInfo,
        GetObjectProps,
        InspectMaterialNodes,
        ListCollections,
        ListMdfPresets,
        ListObjects,
        PhysicsRead,
        SceneInfo,
    )
    from app.phases.setup import (
        SetupImportMHWilds,
        SetupImportSource,
        SetupValidateScene,
    )
    from app.phases.skeleton_align import SkeletonAlign
    from app.phases.vertex_groups import VertexGroups

    tools: list[PhaseTool] = [
        # Phase tools (advance _phase_idx on success unless overridden)
        SetupImportSource(),
        SetupValidateScene(),
        InferModelType(),
        PresetSupplementWrite(),  # issue #5 — write _extended.json after user confirm
        PresetCustomWrite(),      # issue #6 — write _custom.json after user confirm
        SetupImportMHWilds(),
        PoseCorrection(),
        SkeletonAlign(),
        VertexGroups(),
        PhysicsTransplant(),
        PhysicsClassification(),
        PhysicsChains(),
        PhysicsAdjust(),
        ColliderCreate(),        # Phase 4C Step 1 — sub-step
        ColliderApply(),         # Phase 4C Step 3 — advances to phase_5
        MaterialConsolidate(),
        MaterialInspect(),
        MaterialSetup(),
        MaterialGenerate(),
        BatchExport(),
        # Query tools (read-only, always available regardless of subset)
        SceneInfo(),
        ListObjects(),
        GetBoneInfo(),
        ListCollections(),
        GetMeshInfo(),
        GetMaterialInfo(),
        GetObjectProps(),
        InspectMaterialNodes(),
        ListMdfPresets(),
        PhysicsRead(),
    ]
    _TOOL_CATALOG_CACHE = {tool.name: tool for tool in tools}
    return _TOOL_CATALOG_CACHE


class PhaseLoop:
    """Hosts the per-turn reasoning loop. See module docstring."""

    def __init__(
        self,
        router: "RouterLoop",
        *,
        phase_name: str | None = None,
        system_prompt: str | None = None,
        tool_names: set[str] | frozenset[str] | None = None,
    ) -> None:
        """Construct a PhaseLoop.

        Production usage (built lazily by `RouterLoop._build_per_phase_loop`):
          - `phase_name` — the slot name this PhaseLoop is dedicated to.
            Drives `build_phase_prompt` seeding into `_phase_history` and
            identifies the loop in diagnostics.
          - `system_prompt` — a per-phase system prompt (built via the
            phase-scoped `build_system_prompt(include_section_keys=...)`
            overload). Required for the scoped prompt to take effect; falls
            back to Router's session-wide prompt when None (test fixtures
            that construct a no-kwarg PhaseLoop rely on this).
          - `tool_names` — restrict the visible phase tools to this subset
            (query tools are always included). When None, every registered
            tool is exposed.

        `_phase_history` is always isolated — every PhaseLoop owns its own.
        """
        self._router = router
        self._phase_name = phase_name
        self._own_system_prompt = system_prompt
        self._tool_names_filter = (
            frozenset(tool_names) if tool_names is not None else None
        )

        # PhaseLoop-owned state
        self._phase_tools: dict[str, PhaseTool] = {}
        self._register_available_phases()
        if self._tool_names_filter is not None:
            # Keep query tools (always available) + listed phase tools.
            self._phase_tools = {
                name: tool
                for name, tool in self._phase_tools.items()
                if isinstance(tool, QueryTool) or name in self._tool_names_filter
            }

        self._pending_error: PhaseError | None = None
        # Issue #3 deferred widget emit moved to Router (PR4) — see
        # `RouterLoop._pending_widget`. PhaseLoop accesses it via the
        # @property below so call sites read like `self._pending_widget`
        # without the indirection showing.

        # Issue #15 — inter-phase pause flags. See _execute_tool_call (producer)
        # and _run_react_turn (consumer).
        self._phase_just_advanced: bool = False
        self._last_tool_requires_pause: bool = True

        # phase_history: isolated per PhaseLoop. Pre-seeded with the phase
        # brief on first entry (see _maybe_seed_phase_history).
        self._phase_history: list[Message] = []
        self._phase_history_seeded: bool = False

    # ── Router proxies (minimize diff between AgentLoop body & extracted body) ──

    @property
    def state(self) -> LoopState:
        return self._router.state

    @state.setter
    def state(self, v: LoopState) -> None:
        self._router.state = v

    @property
    def current_phase(self) -> str | None:
        return self._router.current_phase

    @property
    def _phase_idx(self) -> int:
        return self._router._phase_idx

    @_phase_idx.setter
    def _phase_idx(self, v: int) -> None:
        self._router._phase_idx = v

    @property
    def _llm(self):
        return self._router._llm

    @property
    def _blender(self):
        return self._router._blender

    @property
    def _cache(self):
        return self._router._cache

    @property
    def _system_prompt(self) -> str:
        # Per-phase scoped prompt wins; falls back to Router's session-wide
        # prompt only when no scoped prompt was passed at construction
        # (no-kwarg test fixtures rely on this fallback).
        if self._own_system_prompt is not None:
            return self._own_system_prompt
        return self._router._system_prompt

    # ── active-history selection ─────────────────────────────────────────

    def _active_history(self) -> list[Message]:
        """The history list that this turn's LLM calls read/write against.

        Always `_phase_history` post-PR6 (every per-phase loop is isolated).
        Seeded on first entry with the phase brief — user "Phase instructions"
        + assistant "Understood" — so the Anthropic API sees a valid
        alternating sequence even before the user's first real message lands.
        """
        self._maybe_seed_phase_history()
        return self._phase_history

    def _maybe_seed_phase_history(self) -> None:
        """Seed `_phase_history` with this phase's brief on first entry.

        Only runs once per PhaseLoop lifetime. Skipped when no `phase_name`
        was supplied at construction (defensive; per-phase loops always get
        one in practice).
        """
        if self._phase_history_seeded or not self._phase_name:
            return
        brief = build_phase_prompt(self._phase_name)
        if brief:
            self._phase_history.append({
                "role": "user",
                "content": f"[Phase instructions]\n{brief}",
            })
            self._phase_history.append({
                "role": "assistant",
                "content": "Understood. I will follow these phase instructions.",
            })
        self._phase_history_seeded = True

    @property
    def _error_handler(self):
        return self._router._error_handler

    @property
    def _move_log(self):
        return self._router._move_log

    @property
    def _interrupted(self) -> bool:
        return self._router._interrupted

    @_interrupted.setter
    def _interrupted(self, v: bool) -> None:
        self._router._interrupted = v

    @property
    def _skipped_phases(self) -> set[str]:
        return self._router._skipped_phases

    # Convenience: forward emit + log to router so extracted code reads identically
    def _emit(self, event_type: str, **payload: Any) -> None:
        self._router._emit(event_type, **payload)

    def _log_move(self, move: dict[str, Any]) -> None:
        self._router._log_move(move)

    def _on_phase_advance(self, completed_phase: str | None = None) -> str | None:
        """Forward to Router. Kept on PhaseLoop so error-choice / wrap-up sites
        read like the original AgentLoop body."""
        return self._router._on_phase_advance(completed_phase=completed_phase)

    # ── dispatch ──────────────────────────────────────────────────────────

    async def dispatch(self, user_message: str) -> str:
        """Route one turn based on current state. DONE branch lives in Router.

        Under isolation, the LLM call inside this loop reads `_phase_history`,
        so the user message has to be mirrored in here for the LLM to see it.
        We only mirror when the user_message is conversational content the LLM
        should read (RUNNING_PHASE / AWAIT_CONFIRM widget-confirm payload).
        ERROR_HANDLING / ASK_MODE receive protocol-level strings ("[Retry]",
        "[Skip]", "[Ask]") that are parsed by `_handle_*` handlers — landing
        them in `_phase_history` would waste tokens and confuse the LLM into
        echoing the choice back.
        """
        # Mirror only conversational turns. ERROR_HANDLING / ASK_MODE receive
        # protocol-level strings ("[Retry]", "[Skip]", parsed-out free text)
        # that `_handle_*` consumes directly; landing them in `_phase_history`
        # wastes tokens and risks the LLM echoing the choice back.
        # NEGOTIATING runs its own append inside `_run_negotiating_turn`.
        mirror = self.state in (
            LoopState.RUNNING_PHASE,
            LoopState.AWAIT_CONFIRM,
            LoopState.IDLE,
        )
        if mirror:
            self._maybe_seed_phase_history()
            self._phase_history.append({"role": "user", "content": user_message})

        match self.state:
            case LoopState.RUNNING_PHASE:
                reply = await self._run_react_turn()
            case LoopState.NEGOTIATING:
                reply = await self._run_negotiating_turn(user_message)
            case LoopState.AWAIT_CONFIRM:
                reply = await self._handle_await_confirm(user_message)
            case LoopState.ERROR_HANDLING:
                reply = await self._handle_error_choice(user_message)
            case LoopState.ASK_MODE:
                reply = await self._handle_ask_mode(user_message)
            case LoopState.IDLE:
                # Router transitioned IDLE → RUNNING_PHASE before delegating.
                # Reach here only if state was reset mid-step; treat as RUNNING.
                reply = await self._run_react_turn()
            case _:
                # DONE shouldn't reach here (Router short-circuits) but guard.
                reply = "All phases are complete. The mod export is finished."

        if mirror:
            self._phase_history.append({"role": "assistant", "content": reply})

        return reply

    # ── ReAct turn (phases 1-3) ───────────────────────────────────────────

    async def _run_react_turn(self) -> str:
        """
        Drive the LLM in a tool-call loop until it produces a text-only response.
        Uses global_history as the active conversation context.
        Returns the final text reply.

        Query-tool throttle: after _MAX_QUERY_ONLY_ROUNDS consecutive rounds where
        every call was a query tool (scene_info, list_objects, etc.), the tool list
        is restricted to phase tools only. This forces the LLM to commit to a phase
        tool call instead of indefinitely querying scene state.
        """
        history = self._active_history()
        query_tool_names = {
            name for name, t in self._phase_tools.items() if isinstance(t, QueryTool)
        }
        query_only_rounds = 0  # consecutive rounds with only query tool calls

        # Issue #14 — short-circuit if interrupt() was called before step entry.
        if self._interrupted:
            return self._handle_interrupt_bailout()

        for _ in range(_MAX_TOOL_ROUNDS):
            # Issue #14 — between-round interrupt check. Tool_use/tool_result
            # pairs from any previous round are already balanced in history at
            # this point, so bailing out here cannot leave orphan blocks.
            if self._interrupted:
                return self._handle_interrupt_bailout()

            # Restrict to phase tools after too many query-only rounds
            if query_only_rounds >= _MAX_QUERY_ONLY_ROUNDS:
                tools = self._build_phase_only_tool_list()
            else:
                tools = self._build_tool_list()

            # Defensive: backstop any unmatched assistant tool_use blocks
            # before sending to the LLM API (Anthropic 400 on mismatched ids).
            heal_history(history)

            response = await asyncio.to_thread(
                self._llm.chat,
                history,
                system=self._system_prompt,
                tools=tools if tools else None,
            )

            if not response.has_tool_calls:
                content = response.content
                # DeepSeek fallback: DSML markup in text instead of API tool_calls.
                # Parse the markup directly and execute — retrying doesn't help
                # because DeepSeek repeatedly outputs markup when in thinking mode.
                dsml_calls = parse_dsml_tool_calls(content)
                if dsml_calls:
                    clean = strip_dsml_block(content)
                    history.append({
                        "role": "assistant",
                        "content": clean or "[tool call via inline markup]",
                    })
                    all_query = all(c["name"] in query_tool_names for c in dsml_calls)
                    query_only_rounds = query_only_rounds + 1 if all_query else 0
                    tool_results_text: list[str] = []
                    error_reply: str | None = None
                    for tc in dsml_calls:
                        result_text, error_reply = await self._execute_tool_call(tc)
                        tool_results_text.append(result_text)
                        if error_reply or self.state != LoopState.RUNNING_PHASE:
                            break
                    history.append({"role": "user", "content": "\n".join(tool_results_text)})
                    if error_reply:
                        return error_reply
                    # Issue #15 — same pause rule applies to the DSML branch.
                    # Honor per-tool `requires_user_pause`: mechanical setup
                    # tools chain straight into the next tool without a wrap-up.
                    if self.state != LoopState.RUNNING_PHASE or (
                        self._phase_just_advanced and self._last_tool_requires_pause
                    ):
                        self._phase_just_advanced = False
                        self._last_tool_requires_pause = True
                        final = await asyncio.to_thread(
                            self._llm.chat,
                            history,
                            system=self._system_prompt + _WRAP_UP_SYSTEM_ADDENDUM,
                        )
                        return final.content
                    # No-pause path: keep _phase_just_advanced=True false-ified
                    # so we don't re-enter wrap-up next iteration on this same
                    # advance, but reset the per-tool flag for the next call.
                    self._phase_just_advanced = False
                    self._last_tool_requires_pause = True
                    continue
                # Detect propose-and-confirm proposal (may occur in RUNNING_PHASE
                # when LLM classifies chains before calling a tool).
                if (
                    '"requires_user_review": true' in content
                    or '"requires_user_review":true' in content
                ):
                    self.state = LoopState.AWAIT_CONFIRM
                    self._emit("state", state=self.state.value)
                return content

            # Append assistant message with tool_use blocks
            history.append(self._build_assistant_tool_msg(response))

            # Track whether this round was query-tools-only
            all_query = all(tc["name"] in query_tool_names for tc in response.tool_calls)
            query_only_rounds = query_only_rounds + 1 if all_query else 0

            # Execute each tool call; collect results.
            # try/finally guarantees tool_results are ALWAYS appended to history,
            # even if _execute_tool_call raises (e.g. error_handler LLM call fails).
            # An unmatched tool_use in history causes a 400 on the next API call.
            tool_results: list[dict[str, Any]] = []
            error_reply: str | None = None

            try:
                for tc in response.tool_calls:
                    try:
                        result_text, error_reply = await self._execute_tool_call(tc)
                    except Exception as exc:
                        result_text = f"Tool execution raised unexpectedly: {exc}"
                        error_reply = f"Unexpected error during {tc.get('name', '?')}: {exc}"
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tc["id"],
                            "content": result_text,
                        }
                    )
                    if (
                        error_reply
                        or self.state != LoopState.RUNNING_PHASE
                        or self._interrupted  # issue #14 — bail mid-round
                    ):
                        break
            finally:
                # Fill placeholder tool_results for any tool_use IDs not yet executed.
                # The Anthropic API requires every tool_use block in an assistant message
                # to have a matching tool_result in the immediately following user message.
                # When a tool failure triggers `break`, remaining IDs would be left unmatched.
                executed_ids = {tr["tool_use_id"] for tr in tool_results}
                for tc in response.tool_calls:
                    if tc["id"] not in executed_ids:
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tc["id"],
                                "content": "Skipped — a preceding tool call in this round failed.",
                            }
                        )
                history.append({"role": "user", "content": tool_results})

            if error_reply:
                return error_reply

            # Issue #14 takes priority over the issue #15 phase-advance pause —
            # an interrupted user does not want to wait through a wrap-up LLM
            # call. Drain happened above so history is balanced.
            if self._interrupted:
                return self._handle_interrupt_bailout()

            if self.state != LoopState.RUNNING_PHASE or (
                self._phase_just_advanced and self._last_tool_requires_pause
            ):
                # Three cases that all funnel into the same wrap-up:
                #   1. State changed (DONE / NEGOTIATING / ERROR_HANDLING / AWAIT_CONFIRM)
                #   2. Issue #15 — phase-advancing tool succeeded AND the tool
                #      opted in to a user pause; tools that opt out (mechanical
                #      setup steps) chain straight into the next tool below.
                # In both cases ask the LLM for a text-only completion report
                # (tools=None), return it as the assistant reply, and let the
                # next user message re-enter the loop.
                self._phase_just_advanced = False
                self._last_tool_requires_pause = True
                heal_history(history)
                final = await asyncio.to_thread(
                    self._llm.chat,
                    history,
                    system=self._system_prompt + _WRAP_UP_SYSTEM_ADDENDUM,
                )
                return final.content
            # No-pause path: an opted-out phase tool just advanced. Clear the
            # flags so the next iteration's tool_use call is unrestricted.
            self._phase_just_advanced = False
            self._last_tool_requires_pause = True

        return "Reached the maximum number of tool-call rounds. Please try again."

    def _handle_interrupt_bailout(self) -> str:
        """Clean-shutdown path for an interrupt observed in `_run_react_turn`.

        Resets the flag (so the next user turn proceeds normally), transitions
        to IDLE, emits a state event for the SSE clients, and returns the
        reply string that the agent message bubble will render. Callers must
        only invoke this once history is balanced (no orphan tool_use blocks).
        """
        self._interrupted = False
        self.state = LoopState.IDLE
        self._emit("state", state=self.state.value)
        return "Interrupted by user."

    async def _execute_tool_call(self, tc: dict) -> tuple[str, str | None]:
        """
        Execute one LLM tool call.

        Returns (tool_result_text, error_reply).
        error_reply is non-None when the phase fails; it is the formatted
        user-facing error message and should be returned from step() directly.

        Query tools (isinstance(tool, QueryTool)) return their result directly
        without advancing phase state or triggering error handling.
        """
        tool_name = tc["name"]
        params = tc.get("input", {})

        self._emit("tool_call", id=tc.get("id"), name=tool_name, input=params)

        # Meta-tool: sync phase bubbles to the given phase without touching Blender.
        if tool_name == "sync_phase_state":
            phase_name = params.get("current_phase", "")
            self._router._sync_to_phase(phase_name)
            self._emit(
                "tool_result",
                id=tc.get("id"),
                name=tool_name,
                success=True,
                summary=f"Phase synced to: {phase_name}",
            )
            self._log_move({
                "kind": "tool",
                "phase": self.current_phase,
                "name": tool_name,
                "args": params,
                "result_summary": f"synced to {phase_name}",
                "success": True,
            })
            return f"Frontend phase state synced to '{phase_name}'.", None

        # Meta-tool: read from the off-prompt MoveLog. Re-injects detail the
        # LLM compacted away — never advances phase state, never touches
        # Blender. Schema lives in app.agent.history.
        if tool_name == QUERY_HISTORY_TOOL_NAME:
            if self._move_log is None:
                result_str = json.dumps({
                    "error": "Move log is not enabled for this session.",
                    "moves": [],
                })
            else:
                # Backstop the LLM-controlled `last_n` so a no-args call (or
                # one with an absurd value) cannot yank the entire move log
                # back into the prompt. The system prompt asks the LLM to
                # keep last_n small; this enforces it.
                raw_last_n = params.get("last_n")
                if not isinstance(raw_last_n, int) or raw_last_n <= 0:
                    capped_last_n = QUERY_HISTORY_DEFAULT_LAST_N
                else:
                    capped_last_n = min(raw_last_n, QUERY_HISTORY_MAX_LAST_N)
                moves = self._move_log.read(
                    phase=params.get("phase"),
                    kind=params.get("kind"),
                    name=params.get("name"),
                    last_n=capped_last_n,
                )
                result_str = json.dumps(moves, ensure_ascii=False)
            self._emit(
                "tool_result",
                id=tc.get("id"),
                name=tool_name,
                success=True,
                summary=f"{result_str[:200]}",
            )
            self._log_move({
                "kind": "tool",
                "phase": self.current_phase,
                "name": tool_name,
                "args": params,
                "result_summary": f"{len(result_str)} bytes",
                "success": True,
            })
            return result_str, None

        tool = self._phase_tools.get(tool_name)
        if tool is None:
            # Naming the current phase in the message lets the LLM self-correct
            # when it hallucinates a cross-phase tool name (e.g. calling
            # setup_import_source while in phase_6) and makes debug logs
            # carry the same context the old phase_slot guard surfaced.
            current = self.current_phase or "<unknown phase>"
            msg = (
                f"Tool '{tool_name}' is not available in {current}. "
                f"Only this phase's own tools and query tools can be called here."
            )
            self._emit(
                "tool_result",
                id=tc.get("id"),
                name=tool_name,
                success=False,
                summary=msg,
            )
            return msg, None

        # Query tools: read-only, no phase advancement
        if isinstance(tool, QueryTool):
            result_str = await asyncio.to_thread(tool.run, self._blender, params)
            self._emit(
                "tool_result",
                id=tc.get("id"),
                name=tool_name,
                success=True,
                summary=result_str[:500],
            )
            self._log_move({
                "kind": "tool",
                "phase": self.current_phase,
                "name": tool_name,
                "args": params,
                "result_summary": result_str[:500],
                "success": True,
            })
            return result_str, None

        # Phase-slot gate: refuse to execute a phase-advancing tool whose
        # declared slot does not match the current _phase_idx slot. Without
        # this gate, the loop blindly advances `_PHASE_SEQUENCE[_phase_idx]`
        # whenever any advances_phase=True tool succeeds — so a stray
        # post-phase_5 call to `setup_import_source` (Phase 0) would mark
        # `phase_6` completed and flip the pipeline to done without
        # batch_export ever running.
        #
        # Skip-this-check conditions:
        # - tool.phase_slot is None (legacy opt-in default; sub-step / query
        #   tools never set this).
        # - tool.advances_phase is False at declaration time (sub-step path —
        #   no risk of bumping _phase_idx). PhysicsChains is the one tool
        #   whose advances_phase is dynamic on prepare_only, but its
        #   phase_slot ("phase_4b") is correct for both branches.
        slot = tool.phase_slot
        if slot is not None:
            if self._phase_idx >= len(_PHASE_SEQUENCE):
                msg = (
                    f"Tool '{tool_name}' rejected: pipeline is already complete "
                    f"(all phases done). Use a query tool (e.g. list_collections, "
                    f"scene_info) or sync_phase_state to revisit a prior phase."
                )
                self._emit(
                    "tool_result",
                    id=tc.get("id"),
                    name=tool_name,
                    success=False,
                    summary=msg,
                )
                self._log_move({
                    "kind": "tool",
                    "phase": self.current_phase,
                    "name": tool_name,
                    "args": params,
                    "result_summary": msg,
                    "success": False,
                })
                return msg, None
            expected = _PHASE_SEQUENCE[self._phase_idx]
            if slot != expected:
                msg = (
                    f"Tool '{tool_name}' rejected: it advances slot '{slot}', "
                    f"but the loop is currently at slot '{expected}'. "
                    f"Pick a tool whose phase_slot matches '{expected}', or call "
                    f"a query tool to inspect scene state. Blender was NOT touched."
                )
                self._emit(
                    "tool_result",
                    id=tc.get("id"),
                    name=tool_name,
                    success=False,
                    summary=msg,
                )
                self._log_move({
                    "kind": "tool",
                    "phase": self.current_phase,
                    "name": tool_name,
                    "args": params,
                    "result_summary": msg,
                    "success": False,
                })
                return msg, None

        # Phase tools: execute, advance state on success.
        # Wrap in try/except so unexpected runtime errors (e.g. Blender
        # disconnecting mid-tool) are converted to PhaseResult.fail instead
        # of propagating as unhandled exceptions. An unhandled exception here
        # would leave the assistant's tool_use blocks in history without a
        # matching tool_result, causing a 400 on the next API call.
        try:
            result = await asyncio.to_thread(
                tool.run, self._blender, self._cache, params
            )
        except Exception as exc:
            result = PhaseResult.fail(
                PhaseError(
                    category="unexpected",
                    operator=tool_name,
                    message=f"Unexpected error in {tool_name}: {exc}",
                    raw=type(exc).__name__,
                )
            )

        if result.success:
            diff = (
                json.dumps(result.state_diff, ensure_ascii=False)
                if result.state_diff
                else "no scene changes"
            )
            if tool.advances_phase:
                # Defensive: should be unreachable if state == DONE bounces
                # in Router for fully-complete sessions, but guard the
                # IndexError so a future state-machine regression cannot brick
                # the session the same way the unrestored-DONE bug did.
                if self._phase_idx >= len(_PHASE_SEQUENCE):
                    self.state = LoopState.DONE
                    self._emit("state", state=self.state.value)
                    return (
                        f"Tool {tool_name} succeeded, but the workflow is "
                        "already past the final phase. All phases are complete."
                    ), None
                completed = _PHASE_SEQUENCE[self._phase_idx]
                self._phase_idx += 1
                # Issue #15 — signal the inter-phase pause rail. The flag is
                # consumed by `_run_react_turn` AFTER the tool_result lands in
                # history (so the wrap-up llm.chat sees a balanced trace) and
                # is reset by the wrap-up branch itself.
                self._phase_just_advanced = True
                # Per-tool override of the Issue #15 pause rail. Mechanical
                # setup tools opt out so the loop can chain into the next
                # tool in the same turn.
                self._last_tool_requires_pause = tool.requires_user_pause
                next_phase = (
                    _PHASE_SEQUENCE[self._phase_idx]
                    if self._phase_idx < len(_PHASE_SEQUENCE)
                    else None
                )
                self._emit(
                    "tool_result",
                    id=tc.get("id"),
                    name=tool_name,
                    success=True,
                    summary=f"Phase {completed} completed. {diff}",
                )
                self._log_move({
                    "kind": "tool",
                    "phase": completed,
                    "name": tool_name,
                    "args": params,
                    "result_summary": diff,
                    "success": True,
                })
                self._log_move({
                    "kind": "phase_advance",
                    "phase": completed,
                    "to_phase": next_phase,
                })
                await self._emit_widget_if_inspector(tool_name, result.state_diff, params)
                self._on_phase_advance(completed_phase=completed)
                return f"Phase {completed} completed. Scene diff: {diff}", None
            else:
                self._emit(
                    "tool_result",
                    id=tc.get("id"),
                    name=tool_name,
                    success=True,
                    summary=f"sub-step ok: {diff}",
                )
                self._log_move({
                    "kind": "tool",
                    "phase": self.current_phase,
                    "name": tool_name,
                    "args": params,
                    "result_summary": diff,
                    "success": True,
                })
                await self._emit_widget_if_inspector(tool_name, result.state_diff, params)
                return f"Tool {tool_name} succeeded (sub-step, phase not advanced). Result: {diff}", None
        else:
            self._pending_error = result.error
            self.state = LoopState.ERROR_HANDLING
            self._emit("state", state=self.state.value)
            self._emit(
                "tool_result",
                id=tc.get("id"),
                name=tool_name,
                success=False,
                summary=result.error.message,
            )
            self._log_move({
                "kind": "tool",
                "phase": self.current_phase,
                "name": tool_name,
                "args": params,
                "result_summary": result.error.message,
                "success": False,
            })
            self._emit(
                "error_choice",
                operator=result.error.operator,
                category=result.error.category,
                message=result.error.message,
                summary=result.error.message[:120],
            )
            try:
                error_reply = await asyncio.to_thread(
                    self._error_handler.format, result.error, self._llm
                )
            except Exception as exc:
                error_reply = (
                    f"[FAIL] {tool_name}: {result.error.message}\n"
                    f"（错误格式化失败: {exc}）\n"
                    "[Retry] — 重新执行  |  [Skip] — 跳过继续  |  [Ask] — 查看详情"
                )
            return f"Phase failed: {result.error.message}", error_reply

    # ── NEGOTIATING turn (legacy, unused since _NEGOTIATING_PHASES is empty) ──

    async def _run_negotiating_turn(self, user_message: str) -> str:
        """
        One NEGOTIATING turn: inject phase prompt on first entry, add user message,
        call LLM with phase_history, detect proposal → transition to AWAIT_CONFIRM.
        """
        # First turn: seed phase_history with phase instructions
        if not self._phase_history:
            phase_prompt = build_phase_prompt(self.current_phase or "")
            if phase_prompt:
                self._phase_history.append(
                    {
                        "role": "user",
                        "content": f"[Phase instructions]\n{phase_prompt}",
                    }
                )
                self._phase_history.append(
                    {
                        "role": "assistant",
                        "content": "Understood. I will follow these phase instructions.",
                    }
                )

        self._phase_history.append({"role": "user", "content": user_message})

        heal_history(self._phase_history)
        response = await asyncio.to_thread(
            self._llm.chat,
            self._phase_history,
            system=self._system_prompt,
        )

        reply = strip_dsml_block(response.content)
        self._phase_history.append({"role": "assistant", "content": reply})

        # Detect structured proposal from LLM (propose_and_confirm protocol)
        if '"requires_user_review": true' in reply or '"requires_user_review":true' in reply:
            self.state = LoopState.AWAIT_CONFIRM
            self._emit("state", state=self.state.value)

        return reply

    async def _handle_await_confirm(self, user_message: str) -> str:
        """
        User replied to a proposal (confirm or correction).

        Transitions back to RUNNING_PHASE so the LLM can call the phase tool
        with the confirmed parameters. The full conversation history provides
        the classification context needed to build the correct tool call.
        If the user made a correction the LLM will re-propose; the proposal
        detection in _run_react_turn will set AWAIT_CONFIRM again.
        """
        self.state = LoopState.RUNNING_PHASE
        return await self._run_react_turn()

    # ── error handling ────────────────────────────────────────────────────

    async def _handle_error_choice(self, user_message: str) -> str:
        """Route user's [Retry] / [Skip] / [Ask] choice after a phase failure."""
        choice = await asyncio.to_thread(
            self._error_handler.parse_user_choice, user_message, self._llm
        )

        match choice:
            case "retry":
                self.state = LoopState.RUNNING_PHASE
                self._pending_error = None
                return await self._run_react_turn()

            case "skip":
                skipped = self.current_phase or "unknown"
                self._skipped_phases.add(skipped)
                self._phase_idx += 1
                next_phase = (
                    _PHASE_SEQUENCE[self._phase_idx]
                    if self._phase_idx < len(_PHASE_SEQUENCE)
                    else None
                )
                # Mirror the bookkeeping a successful phase tool would have
                # done: record the advance on disk so session recovery counts
                # this phase.
                self._log_move({
                    "kind": "phase_advance",
                    "phase": skipped,
                    "to_phase": next_phase,
                    "skipped": True,
                })
                # The success path returns to RUNNING_PHASE via the wrap-up
                # branch; the skip path has no LLM call to ride on, so set
                # the state explicitly. _on_phase_advance can still override
                # to DONE / NEGOTIATING when warranted.
                self.state = LoopState.RUNNING_PHASE
                self._on_phase_advance(completed_phase=skipped)
                self._pending_error = None
                warning = (
                    f"Skipping {skipped}. "
                    "Warning: downstream phases may fail if they depend on this step."
                )
                if self.state == LoopState.DONE:
                    return warning + " All other phases are complete."
                return warning + f" Continuing to {self.current_phase}."

            case "ask":
                self.state = LoopState.ASK_MODE
                return await self._handle_ask_mode(user_message)

            case _:
                return (
                    "Please choose one of the options: "
                    "[Retry] to try again, [Skip] to skip this phase, "
                    "[Ask] for more information about the error."
                )

    async def _handle_ask_mode(self, user_message: str) -> str:
        """
        Explanation + scene-query mode (A2).

        The LLM may call read-only query tools (scene_info, list_objects,
        get_bone_info, list_collections) to fetch live data for its answer.
        Phase-advancing tools are NOT available — the loop rejects them.
        Exits back to ERROR_HANDLING when user mentions retry/skip/continue.

        Error details from _pending_error are injected into the system prompt
        so the LLM can explain the actual failure rather than guessing.
        """
        system = self._system_prompt + (
            "\n\n[ASK MODE] You are in explanation-and-query mode. "
            "You may call ANY of the read-only query tools in your tool list "
            "(scene_info, list_objects, get_bone_info, list_collections, "
            "get_mesh_info, get_material_info, get_object_props, inspect_material_nodes, "
            "list_mdf_presets, physics_read) "
            "to fetch live Blender data for diagnosis. "
            "You CANNOT call phase-advancing tools (pose_correction, skeleton_align, "
            "vertex_groups, physics_chains, physics_transplant, physics_classification, "
            "physics_adjust, material_setup, material_generate, batch_export, etc.) "
            "in this mode. "
            "Do NOT output DSML tool-call markup."
        )
        if self._pending_error:
            err = self._pending_error
            detail_lines = [
                "\n\n[PENDING ERROR — use this to answer the user's question]",
                f"operator: {err.operator}",
                f"message: {err.message}",
            ]
            if err.suggestion:
                detail_lines.append(f"suggestion: {err.suggestion}")
            if err.raw:
                detail_lines.append(f"raw_output: {err.raw}")
            system += "\n".join(detail_lines)

        query_tools = self._build_query_tool_list()
        history = self._active_history()

        for _ in range(_MAX_ASK_ROUNDS):
            heal_history(history)
            response = await asyncio.to_thread(
                self._llm.chat,
                history,
                system=system,
                tools=query_tools if query_tools else None,
            )

            if not response.has_tool_calls:
                # Check for DSML markup even in ASK_MODE (DeepSeek fallback)
                dsml_calls = parse_dsml_tool_calls(response.content)
                if dsml_calls:
                    # Filter to query tools only; reject phase tools silently
                    query_names = {t["name"] for t in query_tools}
                    dsml_calls = [c for c in dsml_calls if c["name"] in query_names]
                if dsml_calls:
                    clean = strip_dsml_block(response.content)
                    history.append({
                        "role": "assistant",
                        "content": clean or "[querying scene]",
                    })
                    results = []
                    for tc in dsml_calls:
                        res, _ = await self._execute_tool_call(tc)
                        results.append(res)
                    history.append({"role": "user", "content": "\n".join(results)})
                    continue
                # Plain text answer — done
                reply = strip_dsml_block(response.content)
                break

            # Structured tool calls
            history.append(self._build_assistant_tool_msg(response))
            results: list[dict] = []
            query_names = {t["name"] for t in query_tools}
            for tc in response.tool_calls:
                if tc["name"] not in query_names:
                    res_text = (
                        f"Tool '{tc['name']}' is not available in ASK MODE. "
                        "Only scene inspection tools may be called here."
                    )
                else:
                    res_text, _ = await self._execute_tool_call(tc)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": res_text,
                })
            history.append({"role": "user", "content": results})
        else:
            reply = "已达到查询轮数上限。请根据以上信息告诉我您想 [重试] 还是 [跳过]。"

        exit_keywords = ("continue", "retry", "skip", "back", "exit",
                         "继续", "重试", "跳过", "返回", "退出", "开始", "执行")
        if any(kw in user_message.lower() for kw in exit_keywords):
            self.state = LoopState.ERROR_HANDLING
        return reply

    # ── widget timing (Issue #3 deferred emit) ───────────────────────────

    async def _annotate_chains(self, chains: list[dict]) -> list[dict]:
        """Thin wrapper around `physics_annotate.annotate_chains` so tests can
        still `patch.object(loop, "_annotate_chains", ...)` and so the call
        site reads naturally. All prompt-engineering and JSON-recovery lives
        in `app.phases.physics_annotate`.
        """
        return await annotate_chains(self._llm, chains, emit=self._emit)

    async def _suggest_texture_mapping(
        self,
        materials: list[str],
        texture_files: list[str],
        existing_connections: dict[str, dict[str, str]],
        *,
        vision_marks: dict[str, list[str]] | None = None,
    ) -> dict[str, dict[str, str]]:
        """Thin wrapper around `material.suggest_texture_mapping` so tests can
        still `patch.object(AgentLoop, "_suggest_texture_mapping", ...)` and
        the call site reads naturally. Prompt + filtering live in
        `app.phases.material`.

        Pass `vision_marks={}` to receive the parallel provenance map listing
        which slots came from Layer 3 (vision) classification.
        """
        return await suggest_texture_mapping(
            self._llm, materials, texture_files, existing_connections,
            vision_marks=vision_marks,
        )

    async def _emit_widget_if_inspector(
        self,
        tool_name: str,
        state_diff: dict | None,
        params: dict | None = None,
    ) -> None:
        """Stage a widget event for tools whose result needs user confirmation.

        Issue #7: physics_classification's chain_topology and material_inspect's
        materials+texture_files+existing_connections feed structured editable
        UI widgets instead of free-text Q&A. The next user message arrives
        prefixed `[CONFIRMED_CLASSIFICATIONS]` / `[CONFIRMED_MATERIAL_MAPPING]`
        carrying the user's selections as JSON.

        Deferred emit (Issue 3): for physics_classification and material_inspect
        we DO NOT emit the widget event here. Emitting at tool-return time
        surfaces an empty-looking table to the user BEFORE the LLM has a chance
        to comment on the result in chat — confusing UX. Instead we stash the
        payload in `self._pending_widget` and Router emits it after the LLM's
        next text-only response (so chat commentary lands first).

        Issue #11: for material_inspect, run the LLM pre-fill (suggest texture
        mapping) inline NOW so the deferred-emit payload already carries
        `suggestions` — the suggest call piggybacks on the same dead time as
        `_annotate_chains` (while the agent commentary renders).

        Other widget-like emits (model_type_inferred) remain immediate because
        they don't pair with an LLM commentary in the same way.
        """
        if not state_diff:
            return
        if tool_name == "physics_classification":
            chain_topology = state_diff.get("chain_topology") or {}
            chains = chain_topology.get("chain_heads") or []
            if chains:
                # Run the annotation LLM call now (slow) so the widget is
                # ready to emit immediately when the deferred-emit point hits.
                chains = await self._annotate_chains(chains)
                from app.phases.physics_bones import list_inferred_types
                self._pending_widget = (
                    "widget_classification",
                    {"chains": chains, "inferred_types": list_inferred_types()},
                )
        elif tool_name == "material_inspect":
            # Suppress the editing widget when the LLM marks this call as a
            # post-wire verification (Phase 5A Step 6). Otherwise the verify
            # inspect re-emits the widget, the user has no other reply channel,
            # and material_setup gets re-run in a self-feeding loop. See
            # docs/agent/agent_workflow.md Phase 5A Steps 3 and 6.
            purpose = (params or {}).get("purpose", "classify")
            if purpose == "verify":
                return
            materials = state_diff.get("materials") or []
            if materials:
                existing = state_diff.get("existing_connections") or {}
                texture_files = state_diff.get("texture_files") or []
                # Issue #11: run the suggest LLM call NOW so the deferred
                # widget arrives with `suggestions` populated. Issue #22 S1:
                # collect vision provenance so the widget can badge the rows
                # the user should review more carefully.
                vision_marks: dict[str, list[str]] = {}
                suggestions = await self._suggest_texture_mapping(
                    materials, texture_files, existing,
                    vision_marks=vision_marks,
                )
                # Issue #22 Stage 3 (experimental, flag-gated): reverse
                # texture inference. Returns {} unless
                # settings.vision_reverse_inference is True AND a vision
                # model is configured. Suggestions surface separately —
                # never merged into `suggestions` — so the widget can
                # render them as EXPERIMENTAL with explicit confirmation.
                experimental_suggestions = await infer_textures_by_reverse_uv_layout(
                    self._blender, params.get("target_object") if params else "",
                    materials, texture_files,
                )
                self._pending_widget = (
                    "widget_material",
                    {
                        "materials": materials,
                        "existing_connections": existing,
                        "texture_files": texture_files,
                        "suggestions": suggestions,
                        "vision_suggested_slots": vision_marks,
                        "experimental_suggestions": experimental_suggestions,
                    },
                )
        elif tool_name == "setup_infer_model_type":
            # Issue #4: surface the inference outcome to the form's
            # `model_type` dropdown via SSE so the user can either accept the
            # auto-pick or override before the pipeline continues.
            preset = state_diff.get("inferred_preset")
            decision = state_diff.get("decision")
            if preset and decision:
                self._emit(
                    "model_type_inferred",
                    preset=preset,
                    coverage=state_diff.get("coverage", 0.0),
                    decision=decision,
                    candidates=state_diff.get("candidates") or [],
                    uncovered_slots=state_diff.get("uncovered_slots") or [],
                )

    @property
    def _pending_widget(self) -> tuple[str, dict] | None:
        return self._router._pending_widget

    @_pending_widget.setter
    def _pending_widget(self, v: tuple[str, dict] | None) -> None:
        self._router._pending_widget = v

    def _flush_pending_widget(self) -> None:
        """Forward to Router (PR4 — Router owns the deferred widget slot).

        Retained as a thin shim so call sites (`patch.object(loop,
        "_flush_pending_widget", ...)`) and the AgentLoop façade keep working
        without rewrite.
        """
        self._router.flush_pending_widget()

    # ── tool registration + tool list builders ───────────────────────────

    def _register_available_phases(self) -> None:
        """Populate `self._phase_tools` with the full tool catalog.

        The actual import list lives in module-level `build_full_tool_catalog`
        so the AgentLoop façade can expose the full registry (`_phase_tools`,
        `_build_tool_list`) without owning a per-loop instance just to read
        from. The PhaseLoop constructor then filters by `_tool_names_filter`.
        """
        self._phase_tools.update(build_full_tool_catalog())

    def _build_tool_list(self) -> list[dict]:
        return (
            [t.tool_schema() for t in self._phase_tools.values()]
            + [_SYNC_PHASE_TOOL_SCHEMA, QUERY_HISTORY_TOOL_SCHEMA]
        )

    def _build_phase_only_tool_list(self) -> list[dict]:
        """Phase tools only — excludes query tools. Used when the LLM has spent
        too many rounds on scene inspection and must commit to a phase tool call."""
        return [
            t.tool_schema()
            for t in self._phase_tools.values()
            if not isinstance(t, QueryTool)
        ]

    def _build_query_tool_list(self) -> list[dict]:
        return [
            t.tool_schema()
            for t in self._phase_tools.values()
            if isinstance(t, QueryTool)
        ]

    @staticmethod
    def _build_assistant_tool_msg(response: LLMResponse) -> Message:
        """Build an Anthropic-format assistant message containing tool_use blocks.

        Uses response.content_blocks when available so that opaque blocks
        (e.g. thinking) are round-tripped verbatim and not stripped out.
        """
        if response.content_blocks:
            return {"role": "assistant", "content": response.content_blocks}
        # Fallback for providers that do not populate content_blocks (OpenAI).
        content: list[dict[str, Any]] = []
        if response.content:
            content.append({"type": "text", "text": response.content})
        for tc in response.tool_calls:
            content.append(
                {
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                }
            )
        return {"role": "assistant", "content": content}
