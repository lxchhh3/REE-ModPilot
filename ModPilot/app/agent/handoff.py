"""Typed phase-boundary handoffs (PR1 shells).

In the hierarchical agent loop refactor, each PhaseLoop returns a `PhaseHandoff`
at phase exit. The Router uses it for: (a) the wrap-up summary surfaced to the
user, (b) seeding the next PhaseLoop's prompt with structured upstream state.

PR1 ships the base shell only — `state_diff: dict` carries everything untyped,
matching today's `PhaseResult.state_diff` shape. PRs 2-5 will add per-boundary
subclasses with named fields (`Phase4AHandoff.inferred_types`, etc.) as each
phase migrates onto its own isolated PhaseLoop instance.

The base + per-boundary subclasses are co-located here on purpose: the schemas
ARE the contract between phases, and seeing them together makes it easy to spot
when an upstream phase changes what a downstream phase will see.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PhaseHandoff:
    """What every PhaseLoop returns at phase exit.

    The Router consumes `summary` for chat display (and for the future
    phase-summary log that replaces in-place compaction in PR6), and
    `state_diff` as the structured payload for the next PhaseLoop.
    """

    completed_phase: str
    summary: str
    next_phase: str | None
    state_diff: dict = field(default_factory=dict)


# Per-boundary subclasses — shells in PR1, fields added per-phase in PRs 2-5.
# Subclasses kept thin on purpose so PR1 can swap any existing `state_diff`
# producer in without touching call sites.


@dataclass
class SetupImportSourceHandoff(PhaseHandoff):
    pass


@dataclass
class SetupValidateHandoff(PhaseHandoff):
    pass


@dataclass
class SetupInferHandoff(PhaseHandoff):
    pass


@dataclass
class SetupImportMHWildsHandoff(PhaseHandoff):
    pass


@dataclass
class Phase1Handoff(PhaseHandoff):
    pass


@dataclass
class Phase2Handoff(PhaseHandoff):
    pass


@dataclass
class Phase3Handoff(PhaseHandoff):
    pass


@dataclass
class Phase35Handoff(PhaseHandoff):
    pass


@dataclass
class Phase4AHandoff(PhaseHandoff):
    # PR4 will add: inferred_types, bones_to_merge, bones_to_clear, target_armature
    pass


@dataclass
class Phase4BHandoff(PhaseHandoff):
    # PR4 will add: chain_collection, chain_groups
    pass


@dataclass
class Phase4CHandoff(PhaseHandoff):
    # PR4 will add: clsp_collection, applied_flags
    pass


@dataclass
class Phase5Handoff(PhaseHandoff):
    # PR5 will add: material_mapping, mdf2_collection
    pass


@dataclass
class Phase6Handoff(PhaseHandoff):
    pass
