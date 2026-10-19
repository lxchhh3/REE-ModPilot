"""doctor: what this Blender offers a build: its version, the enabled add-ons, how many operators
each MH Wilds namespace registers, the modpilot code and the scene's config. With `require`, a
missing namespace fails the call (the legacy app's toolkit probe only reported)."""
from __future__ import annotations

import dataclasses
import sys
from dataclasses import dataclass, field

from modpilot.core import version
from modpilot.core.errors import StepError
from modpilot.core.step import REGISTRY, step

NAMESPACES = ("modder", "mhws", "mbt", "re_mesh", "re_mdf", "re_chain", "re_clsp")


@dataclass(frozen=True)
class DoctorParams:
    require: list[str] = field(default_factory=list)


@step("doctor", DoctorParams, mutates=False)
def doctor(p: DoctorParams, ctx) -> dict:
    """Blender version, add-ons, operator namespaces, modpilot code and scene config."""
    import bpy
    namespaces = {}
    for ns in sorted(set(NAMESPACES) | set(p.require)):
        namespaces[ns] = len(dir(getattr(bpy.ops, ns))) if hasattr(bpy.ops, ns) else 0
    missing = [ns for ns in p.require if namespaces.get(ns, 0) == 0]
    if missing:
        raise StepError("environment", f"no operators registered under {', '.join(missing)}",
                        details={"missing": missing, "namespaces": namespaces})
    return {
        "blender": bpy.app.version_string,
        "python": sys.version.split()[0],
        "background": bool(bpy.app.background),
        "addons": sorted(a.module for a in bpy.context.preferences.addons),
        "namespaces": namespaces,
        "modpilot": version.code(),
        "config": dataclasses.asdict(ctx.config),
        "steps": REGISTRY.names(),
    }
