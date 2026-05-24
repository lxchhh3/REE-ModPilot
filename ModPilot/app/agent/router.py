"""RouterLoop — top-level session orchestrator for the hierarchical agent loop.

RouterLoop owns:
  - The mechanical phase advance (`_phase_idx`, phase events)
  - The session-wide event sink (single `_emit` chokepoint with DSML sanitization)
  - The persistent move log (`MoveLog`) + cold-start hydration (restores
    `_phase_idx` only; per-phase loops own their isolated histories)
  - `_pending_widget` — Issue #3 deferred widget emit slot, held here so a
    phase-advancing inspector tool that swaps `_phase_loop` mid-step does
    not lose the slot before the in-finally flush
  - Session-global flags (interrupt, skipped phases)
  - Shared infrastructure passed to PhaseLoop: `LLMClient`, `BlenderClient`,
    `SceneCache`, `ErrorHandler`, session config

Per-turn work delegates to a per-phase PhaseLoop instance, looked up via
`_select_active_phase_loop` from `_per_phase_loops` (lazily built and
cached per phase from `PHASE_TOOL_SUBSETS`). Each PhaseLoop maintains its
own `_phase_history`; Router itself holds no in-prompt conversation state.
Persistent state survives via `MoveLog` on disk and is recallable by the
LLM through the `query_history` meta-tool.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.agent.dsml import looks_like_dsml, sanitize_outbound
from app.agent.error_handler import ErrorHandler
from app.agent.history import MoveLog
from app.agent.prompts import PHASE_TO_SECTION_KEY, build_system_prompt
from app.agent.state import (
    LoopState,
    PHASE_TOOL_SUBSETS,
    _NEGOTIATING_PHASES,
    _PHASE_SEQUENCE,
    _SYNC_PHASE_TOOL_SCHEMA,
)
from app.blender.client import BlenderClient
from app.blender.state import SceneCache
from app.llm.client import LLMClient

if TYPE_CHECKING:
    from app.agent.phase_loop import PhaseLoop

logger = logging.getLogger(__name__)


class RouterLoop:
    """Top-level session orchestrator. See module docstring."""

    def __init__(
        self,
        llm: LLMClient,
        blender: BlenderClient,
        physics_presets: dict | None = None,
        event_sink: Callable[[dict], None] | None = None,
        session_config: dict | None = None,
        session_id: str | None = None,
    ) -> None:
        self._llm = llm
        self._blender = blender
        self._cache = SceneCache(blender)
        self._error_handler = ErrorHandler()
        self._event_sink = event_sink
        self._session_config = session_config or {}
        # Held so `_build_per_phase_loop` can pass physics presets into each
        # per-phase scoped system prompt at construction time.
        self._physics_presets = physics_presets

        # Off-prompt move log — sole source of truth for cross-session state.
        # session_id is optional: existing tests that don't care about
        # persistence pass nothing and disable the whole subsystem.
        self._move_log: MoveLog | None = MoveLog(session_id) if session_id else None

        # Session-wide state
        self.state = LoopState.IDLE
        self._phase_idx: int = 0
        self._skipped_phases: set[str] = set()

        # Issue #14 — user-interrupt flag. Set by AgentLoop.interrupt() from
        # the FastAPI route layer (Escape key in FE → POST /agent/interrupt).
        # PhaseLoop polls this through `router._interrupted` between rounds
        # and between tool calls within a round.
        self._interrupted: bool = False

        # Issue #3 deferred widget emit. Lives on Router (one slot per
        # session-step) because a phase-advancing inspector tool
        # (physics_classification) stashes a widget on the OUTGOING PhaseLoop,
        # but `_on_phase_advance` swaps `_phase_loop` to the next phase's
        # loop before this step ends — a per-loop slot would be stranded by
        # the time `Router.step`'s finally tries to flush.
        self._pending_widget: tuple[str, dict] | None = None

        # Session-wide system prompt is no longer used by any PhaseLoop call
        # site — every phase has its own scoped prompt built via
        # `build_system_prompt(include_section_keys={...})`. Kept around so
        # the AgentLoop façade's `_system_prompt` proxy can still report a
        # representative session prompt for tests.
        self._system_prompt = build_system_prompt(physics_presets, session_config)

        # PhaseLoop wiring must happen AFTER all of Router's own state is in
        # place — per-phase PhaseLoops reach into Router via
        # `self._router._cache`, etc. Lazy import keeps phase_loop.py free
        # to type-hint RouterLoop without a runtime cycle.
        from app.agent.phase_loop import PhaseLoop as _PhaseLoop
        self._PhaseLoop_cls = _PhaseLoop
        # Per-phase PhaseLoops, lazily built on first activation. Cached so
        # phase_history persists across the in-phase tool-call rounds (a
        # phase can take many user turns).
        self._per_phase_loops: dict[str, PhaseLoop] = {}
        # `_phase_loop` is the currently-active per-phase loop. Tests and
        # the façade read this; never reassign it manually — go through
        # `_select_active_phase_loop()`.
        self._phase_loop: PhaseLoop | None = None

        # Session recovery: if a move log already exists on disk for this
        # session_id, restore `_phase_idx` from its `phase_advance` count.
        # No in-prompt history is replayed — per-phase loops start fresh
        # from their phase brief; the LLM uses `query_history` to recall
        # older decisions.
        self._hydrate_from_move_log()
        # Activate the right PhaseLoop for whatever phase we ended up on
        # (cold-start: phase_idx=0 = setup_import_source; resumed: whatever
        # phase_advance count says). Idempotent and no-op when the choice
        # doesn't change.
        self._select_active_phase_loop()

    # ── public API ────────────────────────────────────────────────────────

    @property
    def current_phase(self) -> str | None:
        if self._phase_idx >= len(_PHASE_SEQUENCE):
            return None
        return _PHASE_SEQUENCE[self._phase_idx]

    async def step(self, user_message: str) -> str:
        """Process one user turn. Returns the agent reply string.

        Router wrapping: classify + log the user move, append to history,
        emit user-message SSE event. Delegate the actual reasoning to
        PhaseLoop. After delegation, append assistant reply, emit, log,
        and flush any deferred widget (Issue #3).
        """
        # Refresh the active PhaseLoop at the top of every turn. Two reasons:
        #   (1) tests sometimes mutate `_phase_idx` directly between steps
        #       without going through advance_phase, leaving `_phase_loop`
        #       stale.
        #   (2) keeps the choice idempotent — no harm if already correct.
        self._select_active_phase_loop()

        # Issue #15 defensive reset — see PhaseLoop._run_react_turn for the
        # producer side. Reset here so a leaked True from a prior turn can't
        # short-circuit the new one. Skipped in DONE state where no
        # PhaseLoop is active (`_dispatch` short-circuits before reaching
        # one). `_phase_loop` is None there per `_on_phase_advance`.
        if self._phase_loop is not None:
            self._phase_loop._phase_just_advanced = False
            self._phase_loop._last_tool_requires_pause = True

        # Classify BEFORE dispatch — _classify_user_move_kind reads state,
        # and _dispatch may transition state before the assistant reply lands.
        user_kind = self._classify_user_move_kind(user_message)
        self._emit("message", role="user", content=user_message)
        self._log_move({
            "kind": user_kind,
            "phase": self.current_phase,
            "content": user_message,
        })
        try:
            reply = await self._dispatch(user_message)
            self._emit("message", role="assistant", content=reply)
            self._log_move({
                "kind": "assistant",
                "phase": self.current_phase,
                "content": reply,
            })
            return reply
        finally:
            # Issue #3 deferred widget emit — see PhaseLoop._emit_widget_if_inspector.
            # Flushed on Router (not the active loop) because a phase-advancing
            # inspector tool may have already swapped `_phase_loop` to the next
            # phase by the time this finally runs.
            self.flush_pending_widget()

    def interrupt(self) -> None:
        """Request graceful bail-out of an in-flight phase (issue #14).

        Safe to call from a concurrent FastAPI route handler — flipping a bool
        is atomic under the GIL. PhaseLoop polls `router._interrupted` between
        rounds and between tool calls within a round, then transitions to
        IDLE. Idempotent: a second call while the flag is still set is a no-op.
        """
        if self._interrupted:
            return
        self._interrupted = True
        self._emit("interrupted")
        self._log_move({"kind": "interrupt", "phase": self.current_phase})

    def emit_phase_sync(self) -> None:
        """Re-emit phase progress events so a reconnecting FE can sync its bubbles."""
        self._sync_to_phase(
            _PHASE_SEQUENCE[self._phase_idx]
            if self._phase_idx < len(_PHASE_SEQUENCE)
            else None
        )

    # ── dispatch ──────────────────────────────────────────────────────────

    async def _dispatch(self, user_message: str) -> str:
        """Route one user turn based on current state.

        DONE is owned by Router (pipeline complete). Every other state
        (IDLE / RUNNING_PHASE / NEGOTIATING / AWAIT_CONFIRM / ERROR_HANDLING /
        ASK_MODE) is delegated to PhaseLoop. The IDLE→RUNNING_PHASE transition
        + initial `phase_started` emit are Router concerns even though the
        actual reasoning then runs in PhaseLoop.
        """
        if self.state == LoopState.DONE:
            return "All phases are complete. The mod export is finished."

        if self.state == LoopState.IDLE:
            self.state = LoopState.RUNNING_PHASE
            self._emit("state", state=self.state.value)
            if self.current_phase is not None:
                self._emit(
                    "phase_started",
                    phase=self.current_phase,
                    index=self._phase_idx,
                    total=len(_PHASE_SEQUENCE),
                )

        return await self._phase_loop.dispatch(user_message)

    # ── phase advancement ────────────────────────────────────────────────

    def _on_phase_advance(self, completed_phase: str | None = None) -> str | None:
        """Emit phase_completed + phase_started; update Router state.

        Mirrors the body of the original AgentLoop._on_phase_advance.
        Returns the next phase name (or None if done) for callers that need
        to surface it in user-facing strings.
        """
        if completed_phase is not None:
            self._emit(
                "phase_completed",
                phase=completed_phase,
                index=self._phase_idx - 1,
                total=len(_PHASE_SEQUENCE),
            )
        if self._phase_idx >= len(_PHASE_SEQUENCE):
            self.state = LoopState.DONE
            self._emit("state", state=self.state.value)
            # Explicit: no active PhaseLoop in DONE state. Every code path
            # that touches `_phase_loop` must already short-circuit on
            # `state == DONE`; setting None here turns silent stale-reads
            # into loud `AttributeError`s.
            self._phase_loop = None
            return None
        next_phase = _PHASE_SEQUENCE[self._phase_idx]
        self._emit(
            "phase_started",
            phase=next_phase,
            index=self._phase_idx,
            total=len(_PHASE_SEQUENCE),
        )
        if next_phase in _NEGOTIATING_PHASES:
            self.state = LoopState.NEGOTIATING
            self._emit("state", state=self.state.value)
            self._phase_loop._phase_history = []
        # Phase advanced — swap to whichever PhaseLoop owns the new phase.
        # Per-phase loops are cached, so re-entry into a previously-active
        # phase keeps its `_phase_history`. (Pipeline only advances forward
        # in practice, but cheap to support.)
        self._select_active_phase_loop()
        return next_phase

    def _sync_to_phase(self, phase_name: str | None) -> None:
        """Update _phase_idx to phase_name and emit phase_completed/started events."""
        if phase_name is None or phase_name not in _PHASE_SEQUENCE:
            return
        target_idx = _PHASE_SEQUENCE.index(phase_name)
        self._phase_idx = target_idx
        for i in range(target_idx):
            self._emit(
                "phase_completed",
                phase=_PHASE_SEQUENCE[i],
                index=i,
                total=len(_PHASE_SEQUENCE),
            )
        self._emit(
            "phase_started",
            phase=phase_name,
            index=target_idx,
            total=len(_PHASE_SEQUENCE),
        )
        # Resume / FE-sync paths land here; align the active PhaseLoop to
        # the synced phase so the next step() runs on the right loop.
        self._select_active_phase_loop()

    # ── per-phase PhaseLoop orchestration ────────────────────────────────

    def _select_active_phase_loop(self) -> None:
        """Make `self._phase_loop` point at the right per-phase PhaseLoop.
        Idempotent.

        Every phase in `_PHASE_SEQUENCE` has a corresponding entry in
        `PHASE_TOOL_SUBSETS` (PR6 — no more fallback to a generic loop). If
        called when the pipeline is DONE (`current_phase is None`), the
        existing `_phase_loop` reference is preserved so Router.step's
        finally clause can still flush a pending widget that was stashed by
        the last phase.

        Called from: __init__ (after hydration), step (top of every turn),
        _on_phase_advance (after a successful advance/skip), _sync_to_phase
        (FE-driven resume).
        """
        cp = self.current_phase
        if cp is None:
            return
        self._phase_loop = self._get_or_build_phase_loop(cp)

    def _get_or_build_phase_loop(self, phase_name: str):
        """Return the cached per-phase PhaseLoop for `phase_name`, building
        it on first access. Caller is responsible for ensuring `phase_name`
        is in PHASE_TOOL_SUBSETS; otherwise this builds an isolated loop
        that nothing else points at.

        Lets the AgentLoop façade reach a specific per-phase loop's instance
        dict for `patch.object(loop, "_annotate_chains", ...)` style tests
        that target a phase the active loop hasn't reached yet.
        """
        loop = self._per_phase_loops.get(phase_name)
        if loop is None:
            loop = self._build_per_phase_loop(phase_name)
            self._per_phase_loops[phase_name] = loop
        return loop

    def _build_per_phase_loop(self, phase_name: str):
        """Construct a per-phase PhaseLoop with a scoped system prompt and
        a scoped tool subset. Called once per phase the first time it
        activates; result is cached in `_per_phase_loops`.
        """
        section_key = PHASE_TO_SECTION_KEY.get(phase_name)
        include = {section_key} if section_key else set()
        scoped_prompt = build_system_prompt(
            self._physics_presets,
            self._session_config,
            include_section_keys=include,
        )
        tool_names = PHASE_TOOL_SUBSETS.get(phase_name)
        return self._PhaseLoop_cls(
            router=self,
            phase_name=phase_name,
            system_prompt=scoped_prompt,
            tool_names=tool_names,
        )

    # ── event emission + move logging ────────────────────────────────────

    def _emit(self, event_type: str, **payload: Any) -> None:
        """Publish one structured event to the sink, if any.

        The sink must be thread-safe — emits may originate from threadpool
        workers when tools run via asyncio.to_thread. Sink installers in the
        route layer wrap a queue.put with loop.call_soon_threadsafe.
        """
        if self._event_sink is None:
            return
        # Single-chokepoint defense against DSML markup leaking to the UI.
        # Per-branch strippers may miss new variants; this one scrubs any
        # DSML-ish residue on every outbound message event.
        if event_type == "message":
            raw = payload.get("content")
            if isinstance(raw, str) and looks_like_dsml(raw):
                cleaned = sanitize_outbound(raw)
                if cleaned != raw:
                    logger.warning(
                        "DSML markup leaked to outbound message — sanitized at emit. "
                        "role=%s len_before=%d len_after=%d",
                        payload.get("role"),
                        len(raw),
                        len(cleaned),
                    )
                payload = {**payload, "content": cleaned}
        evt: dict[str, Any] = {
            "type": event_type,
            "ts": time.time(),
            "phase": self.current_phase,
            "state": self.state.value,
            **payload,
        }
        self._event_sink(evt)

    def _log_move(self, move: dict[str, Any]) -> None:
        """Append a move to the persistent log if one is configured.

        No-op when session_id was not supplied at construction. All log
        writes go through this helper so the None-check lives in one place.
        """
        if self._move_log is not None:
            self._move_log.append(move)

    def _classify_user_move_kind(self, user_message: str) -> str:
        """Map an incoming user message to the right `kind` field for the log.

        Widget-confirm and error-choice prefixes are protocol-level, not
        free-form chat. Surfacing them as distinct kinds lets the LLM
        (via query_history) page through past widget submissions and
        retry/skip decisions without first parsing every user message.
        """
        if self.state == LoopState.ERROR_HANDLING:
            return "error_choice"
        if user_message.startswith("[CONFIRMED_CLASSIFICATIONS]") or user_message.startswith(
            "[CONFIRMED_MATERIAL_MAPPING]"
        ):
            return "widget"
        return "user"

    # ── deferred widget emit (Issue #3) ──────────────────────────────────

    def flush_pending_widget(self) -> None:
        """Emit any stashed widget event after the LLM's text reply has landed.

        Public (no underscore) — PhaseLoop and the façade call across the
        module boundary. Idempotent: clears the slot after emitting so
        re-calls are no-ops.
        """
        if self._pending_widget is None:
            return
        event_type, payload = self._pending_widget
        self._pending_widget = None
        self._emit(event_type, **payload)

    # ── session recovery ────────────────────────────────────────────────

    def _hydrate_from_move_log(self) -> None:
        """Rebuild session state from the on-disk move log.

        Called once at the end of __init__. Idempotent and no-op when no log
        exists (cold-start new session).

        Restores `_phase_idx` only. Per-phase loops operate on isolated
        histories built from their phase brief; they do not need a
        session-level replay. `query_history` reads the move log directly
        when the LLM needs to recall past phase work.

        Completed-session overshoot guard: a log with every phase advanced
        would push `_phase_idx` past `_PHASE_SEQUENCE` and crash later
        lookups, so we treat that as "start fresh" and write a
        `session_completed` marker.
        """
        if self._move_log is None:
            return
        moves = self._move_log.read()
        if not moves:
            return

        self._phase_idx = sum(1 for m in moves if m.get("kind") == "phase_advance")

        if self._phase_idx >= len(_PHASE_SEQUENCE):
            self._move_log.append({"kind": "session_completed"})
            self._phase_idx = 0
            logger.info(
                "Session %s was already complete on hydrate; reset to phase 0.",
                self._move_log.path,
            )

    # ── test-compat proxies (forward to active PhaseLoop) ────────────────
    #
    # The AgentLoop façade used to host these properties/methods. PR6
    # collapsed `AgentLoop = RouterLoop`, so the proxies live here. They
    # forward to whichever per-phase PhaseLoop is currently active, except
    # `_annotate_chains` / `_suggest_texture_mapping`, which target a
    # specific phase loop so that `patch.object(loop, "_annotate_chains")`
    # called before `step` lands on the same instance step() later activates.

    @property
    def _phase_history(self):
        return self._phase_loop._phase_history

    @_phase_history.setter
    def _phase_history(self, v) -> None:
        self._phase_loop._phase_history = v

    @property
    def _pending_error(self):
        return self._phase_loop._pending_error

    @_pending_error.setter
    def _pending_error(self, v) -> None:
        self._phase_loop._pending_error = v

    @property
    def _phase_just_advanced(self) -> bool:
        return self._phase_loop._phase_just_advanced

    @_phase_just_advanced.setter
    def _phase_just_advanced(self, v: bool) -> None:
        self._phase_loop._phase_just_advanced = v

    @property
    def _last_tool_requires_pause(self) -> bool:
        return self._phase_loop._last_tool_requires_pause

    @_last_tool_requires_pause.setter
    def _last_tool_requires_pause(self, v: bool) -> None:
        self._phase_loop._last_tool_requires_pause = v

    # Full tool catalog — global view for tests / route inspection.
    # Internal call sites use the per-phase loop's scoped `_phase_tools`
    # directly, bypassing this.
    @property
    def _phase_tools(self):
        from app.agent.phase_loop import build_full_tool_catalog
        return build_full_tool_catalog()

    def _build_tool_list(self) -> list[dict]:
        from app.agent.history import QUERY_HISTORY_TOOL_SCHEMA
        from app.agent.phase_loop import build_full_tool_catalog
        return (
            [t.tool_schema() for t in build_full_tool_catalog().values()]
            + [_SYNC_PHASE_TOOL_SCHEMA, QUERY_HISTORY_TOOL_SCHEMA]
        )

    def _build_phase_only_tool_list(self) -> list[dict]:
        from app.agent.phase_loop import build_full_tool_catalog
        from app.phases.query_tools import QueryTool
        return [
            t.tool_schema()
            for t in build_full_tool_catalog().values()
            if not isinstance(t, QueryTool)
        ]

    def _build_query_tool_list(self) -> list[dict]:
        from app.agent.phase_loop import build_full_tool_catalog
        from app.phases.query_tools import QueryTool
        return [
            t.tool_schema()
            for t in build_full_tool_catalog().values()
            if isinstance(t, QueryTool)
        ]

    def _build_assistant_tool_msg(self, response):
        return self._phase_loop._build_assistant_tool_msg(response)

    def _register_available_phases(self) -> None:
        self._phase_loop._register_available_phases()

    def _handle_interrupt_bailout(self) -> str:
        return self._phase_loop._handle_interrupt_bailout()

    async def _run_react_turn(self) -> str:
        return await self._phase_loop._run_react_turn()

    async def _run_negotiating_turn(self, user_message: str) -> str:
        return await self._phase_loop._run_negotiating_turn(user_message)

    async def _handle_await_confirm(self, user_message: str) -> str:
        return await self._phase_loop._handle_await_confirm(user_message)

    async def _handle_error_choice(self, user_message: str) -> str:
        return await self._phase_loop._handle_error_choice(user_message)

    async def _handle_ask_mode(self, user_message: str) -> str:
        return await self._phase_loop._handle_ask_mode(user_message)

    async def _execute_tool_call(self, tc: dict):
        return await self._phase_loop._execute_tool_call(tc)

    async def _emit_widget_if_inspector(
        self,
        tool_name: str,
        state_diff: dict | None,
        params: dict | None = None,
    ) -> None:
        await self._phase_loop._emit_widget_if_inspector(tool_name, state_diff, params)

    def _flush_pending_widget(self) -> None:
        self.flush_pending_widget()

    # `_annotate_chains` / `_suggest_texture_mapping` target the per-phase
    # loop that actually consumes them, NOT the currently-active loop:
    # tests `patch.object(loop, "_annotate_chains", ...)` BEFORE calling
    # `step`, so the active loop at patch time is whatever
    # `_select_active_phase_loop` picked at __init__ end (usually the setup
    # loop). Routing through `_get_or_build_phase_loop` gives a stable
    # cached instance — the patch lands on the same loop step() later
    # activates.

    @property
    def _annotate_chains(self):
        return self._get_or_build_phase_loop("phase_4a")._annotate_chains

    @_annotate_chains.setter
    def _annotate_chains(self, v) -> None:
        self._get_or_build_phase_loop("phase_4a")._annotate_chains = v

    @_annotate_chains.deleter
    def _annotate_chains(self) -> None:
        loop = self._per_phase_loops.get("phase_4a")
        if loop is None:
            return
        try:
            del loop.__dict__["_annotate_chains"]
        except KeyError:
            pass

    @property
    def _suggest_texture_mapping(self):
        return self._get_or_build_phase_loop("phase_5")._suggest_texture_mapping

    @_suggest_texture_mapping.setter
    def _suggest_texture_mapping(self, v) -> None:
        self._get_or_build_phase_loop("phase_5")._suggest_texture_mapping = v

    @_suggest_texture_mapping.deleter
    def _suggest_texture_mapping(self) -> None:
        loop = self._per_phase_loops.get("phase_5")
        if loop is None:
            return
        try:
            del loop.__dict__["_suggest_texture_mapping"]
        except KeyError:
            pass
