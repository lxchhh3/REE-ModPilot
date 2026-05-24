"""Shared agent-loop types + constants.

Lives in its own module to break the circular import between `router.py`,
`phase_loop.py`, and the legacy `loop.py` façade. All three import `LoopState`
and `_PHASE_SEQUENCE` from here; `loop.py` re-exports them for backward
compatibility with tests that do `from app.agent.loop import LoopState`.
"""

from __future__ import annotations

import enum


# ── phase sequence ────────────────────────────────────────────────────────

_PHASE_SEQUENCE: list[str] = [
    "setup_import_source",  # SetupImportSource — FBX import from session.model_path
    "setup_validate",   # SetupValidateScene
    "setup_infer",      # InferModelType (issue #4 — auto-detect source model preset)
    "setup_import",     # SetupImportMHWilds
    "phase_1",
    "phase_2",
    "phase_3",
    "phase_35",
    "phase_4a",
    "phase_4b",
    "phase_4c",          # Body colliders + chain-group collision masks (issue #20)
    "phase_5",
    "phase_6",          # BatchExport runs RE Mesh Tools cleanup internally before export
]

_NEGOTIATING_PHASES: frozenset[str] = frozenset()
# All phases run in RUNNING_PHASE so the LLM always has tool schemas visible.
# NEGOTIATING gives the LLM zero tools, causing it to ask users to operate
# Blender manually instead of calling the registered tools.


# ── per-phase tool subsets (PR2 — setup phases first) ────────────────────
#
# Map from phase slot name → set of phase tool names that the per-phase
# PhaseLoop should expose to the LLM. Query tools and the meta-tools
# (sync_phase_state, query_history) are auto-included by PhaseLoop and do
# NOT need to be listed here. Phases not in this map fall through to the
# legacy "generic" PhaseLoop that sees every registered tool.
#
# PR2 covers setup_*. PR3-5 will add entries for the main phases as each
# migrates onto its own per-phase PhaseLoop.

PHASE_TOOL_SUBSETS: dict[str, frozenset[str]] = {
    # PR2 — setup phases.
    "setup_import_source": frozenset({"setup_import_source"}),
    "setup_validate":      frozenset({"setup_validate_scene"}),
    "setup_infer":         frozenset({
        "setup_infer_model_type",
        "setup_preset_supplement_write",  # issue #5 sub-step
        "setup_preset_custom_write",      # issue #6 sub-step
    }),
    "setup_import":        frozenset({"setup_import_mhwilds"}),
    # PR3 — Phase 1-3 preprocessing block (all three share the
    # "phase_1_3" workflow section, mapped in PHASE_TO_SECTION_KEY).
    "phase_1":             frozenset({"pose_correction"}),
    "phase_2":             frozenset({"skeleton_align"}),
    "phase_3":             frozenset({"vertex_groups"}),
    # PR4 — physics block (3.5 / 4A / 4B / 4C). Each phase gets only
    # its own advancing tool plus any non-advancing sub-step tools.
    # physics_adjust is a phase_4b fine-tuner that doesn't advance.
    # collider_create is a phase_4c sub-step that doesn't advance.
    "phase_35":            frozenset({"physics_transplant"}),
    "phase_4a":            frozenset({"physics_classification"}),
    "phase_4b":            frozenset({"physics_chains", "physics_adjust"}),
    "phase_4c":            frozenset({"collider_create", "collider_apply"}),
    # PR5 — material + export. Phase 5 has the multi-tool inner loop
    # (consolidate → inspect → setup → generate) from issue #16; all four
    # tools must be visible in the same per-phase loop because the LLM
    # picks among them turn-by-turn. Only material_generate advances.
    "phase_5":             frozenset({
        "material_consolidate",
        "material_inspect",
        "material_setup",
        "material_generate",
    }),
    "phase_6":             frozenset({"batch_export"}),
}


# ── meta-tool schema (sync_phase_state) ───────────────────────────────────

_SYNC_PHASE_TOOL_SCHEMA: dict = {
    "name": "sync_phase_state",
    "description": (
        "Sync the frontend phase progress tracker after a session resume or browser reload. "
        "Call this once you have determined the current phase from scene inspection. "
        "It marks all preceding phases as completed and the given phase as active. "
        "Do NOT call this when advancing phases normally — use phase tools for that."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "current_phase": {
                "type": "string",
                "description": (
                    "The phase currently in progress. "
                    f"Valid values: {_PHASE_SEQUENCE}"
                ),
            },
        },
        "required": ["current_phase"],
    },
}


# ── loop bounds ────────────────────────────────────────────────────────────

_MAX_TOOL_ROUNDS = 15
_MAX_ASK_ROUNDS = 6  # raised from 3: user-facing ASK_MODE often needs 4-5 queries
                     # for a thorough diagnosis (list_objects + scene_info +
                     # get_mesh_info + get_material_info + a follow-up call).
_MAX_QUERY_ONLY_ROUNDS = 2  # after this many consecutive query-only rounds, drop query tools


# ── turn-end wrap-up addendum (Issue #15) ─────────────────────────────────

# Appended to the system prompt for the Issue #15 wrap-up llm.chat call only.
# Without this, the model often writes "let me check" / "让我确认一下" at the end
# of a paused turn, which misleads the user into thinking work will continue —
# but the loop has already returned and is awaiting the next user message.
# This instruction makes the model treat the wrap-up as a true turn-end: report
# what just happened, then either ask a concrete question OR state the next
# checkpoint, but never promise further unilateral action.
_WRAP_UP_SYSTEM_ADDENDUM = (
    "\n\n## TURN-END WRAP-UP\n"
    "This is the FINAL message of the current turn. Tools are NOT available "
    "in this response. After you reply, the loop returns control to the user "
    "and waits for their next message.\n\n"
    "Therefore:\n"
    "1. Report what was just accomplished by the tool call(s) you made earlier "
    "   in this turn — concisely.\n"
    "2. Do NOT write anticipatory phrases like '让我检查一下' / '我接下来会...' / "
    "   'let me verify' / 'I will now...'. You will not get to act on them; "
    "   they only mislead the user into thinking the agent is still working.\n"
    "3. End the message with EITHER:\n"
    "   (a) a specific yes/no or multiple-choice question for the user, OR\n"
    "   (b) a clear statement that the phase is complete and what the next "
    "       checkpoint is (e.g. 'Phase 2 done. Say \"继续\" to start Phase 3.').\n"
    "4. If the user must visually inspect the viewport, name exactly what they "
    "   should look at — don't just say '请检查视口'."
)


# ── state enum ─────────────────────────────────────────────────────────────


class LoopState(enum.Enum):
    IDLE = "idle"
    RUNNING_PHASE = "running_phase"
    NEGOTIATING = "negotiating"
    AWAIT_CONFIRM = "await_confirm"
    ERROR_HANDLING = "error_handling"
    ASK_MODE = "ask_mode"
    DONE = "done"
