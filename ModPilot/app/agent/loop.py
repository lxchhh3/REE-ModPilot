"""`AgentLoop` is now an alias for `RouterLoop`.

Historical note: this module used to host the entire 1500+ line ReAct loop
as a single `AgentLoop` class. The hierarchical refactor (PRs 1-6) split it
into `RouterLoop` (session orchestrator + per-phase loop dispatch) and one
`PhaseLoop` per phase (scoped tools + isolated `_phase_history`). The
`AgentLoop` name is preserved as an alias so that:

  - existing imports (`from app.agent.loop import AgentLoop`) keep working,
  - existing tests that patch attributes on a loop instance keep working
    (the proxy properties for `_phase_history`, `_annotate_chains`, etc.
    now live directly on `RouterLoop`),
  - the FastAPI route layer (`app/main.py`) does not need to change shape.

New code should prefer `from app.agent.router import RouterLoop` directly.

`LoopState`, `_PHASE_SEQUENCE`, and friends are re-exported here for tests
that do `from app.agent.loop import LoopState, _PHASE_SEQUENCE`.
"""

from __future__ import annotations

from app.agent.router import RouterLoop
from app.agent.state import (  # re-exports for backward compatibility
    LoopState,
    _MAX_ASK_ROUNDS,
    _MAX_QUERY_ONLY_ROUNDS,
    _MAX_TOOL_ROUNDS,
    _NEGOTIATING_PHASES,
    _PHASE_SEQUENCE,
    _SYNC_PHASE_TOOL_SCHEMA,
    _WRAP_UP_SYSTEM_ADDENDUM,
)

AgentLoop = RouterLoop

__all__ = [
    "AgentLoop",
    "LoopState",
    "_PHASE_SEQUENCE",
    "_NEGOTIATING_PHASES",
    "_SYNC_PHASE_TOOL_SCHEMA",
    "_MAX_TOOL_ROUNDS",
    "_MAX_ASK_ROUNDS",
    "_MAX_QUERY_ONLY_ROUNDS",
    "_WRAP_UP_SYSTEM_ADDENDUM",
]
