"""The restructure's strangler adapter (M1, kevin's plan 2026-10-19).

A tool named in PORTED runs as the new in-Blender step, `modpilot.call(name, params)`, sent over
the same BlenderClient, while keeping the legacy tool's name, schema, phase slot and result shape.
So the agent loop and tools-5.2's L3 replays run the new code unchanged, one tool at a time, and
each port is proven by a differential test (legacy tool vs new step on the same checkpoint) before
its name joins PORTED. Deleted with the rest of app/ in M6.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:      # the uvicorn app and tools-5.2's replay run from ModPilot/, not src/
    sys.path.insert(0, str(_SRC))

from app.blender.client import BlenderClient, BlenderError  # noqa: E402
from app.blender.state import SceneCache  # noqa: E402
from app.phases.base import PhaseError, PhaseResult, PhaseTool  # noqa: E402
from app.phases.query_tools import QueryTool  # noqa: E402
from modpilot.core.errors import StepError  # noqa: E402
from modpilot_host.transport import BridgeError as _HostBridgeError  # noqa: E402
from modpilot_host.transport import call_code, report_from_stdout, unwrap_bridge_error  # noqa: E402

#: Tools whose new step passed its differential test against the legacy tool.
PORTED: frozenset[str] = frozenset({
    "list_objects",      # M1: T2 tests/diff/test_list_objects.py, 13 checkpoints x 2 versions
    # M2.1: T2 tests/diff/test_setup_diff.py (claude_run1 calls 0-3 + both preset writers, 2 versions)
    "setup_import_source", "setup_validate_scene", "setup_infer_model_type",
    "setup_preset_supplement_write", "setup_preset_custom_write", "setup_import_mhwilds",
    # M2.2: T2 tests/diff/test_run1_diff.py (claude_run1 calls 4-5, 2 versions)
    "pose_correction", "skeleton_align",
    # M2.3: T2 tests/diff/test_run1_diff.py (claude_run1 call 6, 2 versions)
    "vertex_groups",
    # M2.4: T2 claude_run1 calls 7-10, 2 versions. physics_adjust waits: no golden call to diff
    "physics_transplant", "physics_classification", "physics_chains",
    # M2.5: T2 claude_run1 calls 14-15, 2 versions
    "collider_create", "collider_apply",
    # M2.6: T2 tests/diff/test_materials_diff.py (synthetic avatar, 2 versions, identical files)
    "material_setup", "material_generate",
})

#: How a ported query tool's report data becomes the legacy JSON it returned.
QUERY_SHAPES = {
    "list_objects": lambda data: data["objects"],
}

_CATEGORY = {"params": "precondition", "precondition": "precondition", "environment": "precondition",
             "operator": "operator_failed", "postcondition": "operator_failed", "internal": "unexpected"}


# Per call, as the legacy tools set theirs (up to 1200 s): material_generate bakes and physics_chains
# builds for minutes, past the client's 30 s default. modpilot_host.BridgeTransport uses the same.
STEP_TIMEOUT = 1800.0


def _run(client: BlenderClient, name: str, params: dict) -> dict:
    """The step's report; raises StepError, or BlenderError when the bridge failed otherwise."""
    try:
        stdout = client.execute(call_code(name, params), timeout=STEP_TIMEOUT)
    except BlenderError as exc:
        err, inner = unwrap_bridge_error(str(exc))
        if err is not None:
            raise err from None
        raise BlenderError(inner) from None
    try:
        return report_from_stdout(name, stdout)
    except _HostBridgeError as exc:
        raise BlenderError(str(exc)) from None


class BridgedQueryTool(QueryTool):
    def __init__(self, legacy: QueryTool) -> None:
        self._legacy = legacy

    @property
    def name(self) -> str:
        return self._legacy.name

    def tool_schema(self) -> dict[str, Any]:  # instance call works like the legacy classmethod
        return type(self._legacy).tool_schema()

    def run(self, client: BlenderClient, params: dict) -> str:
        try:
            report = _run(client, self.name, params)
        except StepError as err:
            return json.dumps({"error": err.message, "step_error": err.to_dict()}, ensure_ascii=False)
        except BlenderError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        return json.dumps(QUERY_SHAPES[self.name](report["data"]), ensure_ascii=False)


class BridgedPhaseTool(PhaseTool):
    def __init__(self, legacy: PhaseTool) -> None:
        self._legacy = legacy

    @property
    def name(self) -> str:
        return self._legacy.name

    @property
    def advances_phase(self) -> bool:
        return self._legacy.advances_phase

    @property
    def phase_slot(self) -> str | None:
        return self._legacy.phase_slot

    @property
    def requires_user_pause(self) -> bool:
        return self._legacy.requires_user_pause

    def tool_schema(self) -> dict[str, Any]:
        return type(self._legacy).tool_schema()

    def run(self, client: BlenderClient, cache: SceneCache, params: dict) -> PhaseResult:
        try:
            report = _run(client, self.name, params)
        except StepError as err:
            category = err.details.get("legacy_category") or _CATEGORY[err.category]
            return PhaseResult.fail(PhaseError(category=category, operator=err.operator,
                                               message=err.message, raw=json.dumps(err.to_dict(), ensure_ascii=False)))
        except BlenderError as exc:
            return PhaseResult.fail(PhaseError(category="unexpected", operator=self.name, message=str(exc)[:2000]))
        return PhaseResult.ok({**report["data"], **report["scene_diff"]})


def wrap(catalog: dict, ported=PORTED) -> dict:
    """`catalog` with every ported tool replaced by its bridged twin."""
    out = dict(catalog)
    for name in ported:
        tool = catalog[name]
        out[name] = BridgedQueryTool(tool) if isinstance(tool, QueryTool) else BridgedPhaseTool(tool)
    return out
