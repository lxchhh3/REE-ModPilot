"""The report a step call returns: one plain-JSON envelope.

`data` is the step's own result; it keeps the legacy tools' `state_diff` keys (join_prep,
end_bones_added, source_fixes, collider_info, clsp_collection, ...) so call logs and tools-5.2
checks read the same names. `scene_diff` is what changed in the scene (objects added/removed,
object and material counts), as the legacy SceneState.diff reported it.
"""
from __future__ import annotations

import json

from modpilot.core.errors import StepError

PREFIX = "MODPILOT_REPORT="


def make_report(*, step, params, data, warnings, skipped, scene_diff, popups, seconds, code, blender) -> dict:
    return {"ok": True, "step": step, "params": params, "data": data, "warnings": list(warnings),
            "skipped": list(skipped), "scene_diff": scene_diff, "popups": list(popups),
            "seconds": round(float(seconds), 3), "code": code, "blender": blender}


def dumps_report(report: dict) -> str:
    """The report as JSON. A step that returns something JSON cannot carry (a set, a bpy struct,
    NaN) is a bug in the step, reported as such instead of being stringified."""
    try:
        return json.dumps(report, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise StepError("internal", f"step {report.get('step')!r} returned data that is not plain JSON: {exc}",
                        step=report.get("step", "")) from exc
