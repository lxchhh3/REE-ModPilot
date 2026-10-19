"""Calling a Blender operator from a step.

`run("mhws.auto_create_chains", settings_mode="SEPARATE")` requires {'FINISHED'}; anything else,
an operator that is not registered, or an exception from it raises StepError("operator" /
"environment") with what Blender said. Never `getattr(bpy.ops.ns, op, None)`: bpy.ops hands back a
stub for any name and only the call fails (ModPilot lesson #44).
"""
from __future__ import annotations

from contextlib import nullcontext

from modpilot.core.errors import StepError


def registered(op_id: str) -> bool:
    import bpy
    ns, _, name = op_id.partition(".")
    return hasattr(bpy.ops, ns) and name in dir(getattr(bpy.ops, ns))


def run(op_id: str, *, override: dict | None = None, **kwargs) -> set:
    import bpy
    if not registered(op_id):
        raise StepError("environment", f"operator {op_id} is not registered (add-on missing or disabled?)",
                        operator=op_id)
    ns, _, name = op_id.partition(".")
    op = getattr(getattr(bpy.ops, ns), name)
    ctx = bpy.context.temp_override(**override) if override else nullcontext()
    try:
        with ctx:
            ret = op(**kwargs)
    except RuntimeError as exc:
        raise StepError("operator", f"{op_id} failed: {str(exc).strip()}"[:500], operator=op_id,
                        details={"kwargs": {k: repr(v) for k, v in kwargs.items()}}) from exc
    if "FINISHED" not in ret:
        raise StepError("operator", f"{op_id} returned {sorted(ret)}", operator=op_id,
                        details={"returned": sorted(ret), "kwargs": {k: repr(v) for k, v in kwargs.items()}})
    return ret
