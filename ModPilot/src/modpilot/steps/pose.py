"""Phase 1 and 2: pose correction and skeleton alignment (plan.md videos 1-2). Ported from the
legacy app/phases/pose_correction.py and skeleton_align.py, operator for operator.

Changes from the legacy tools: an X-preset other than VRChat / MMD / arknights no longer gets the
Endfield A-to-T pose applied by default (the legacy tool applied it to every other preset), it
needs an explicit `pose_conversion`; an unknown preset fails instead of falling back to bare slot
names; the skipped Y alignment and the armatures skeleton_align unhid are reported as warnings
(the legacy tools dropped both).
"""
from __future__ import annotations

from dataclasses import dataclass

from modpilot import presets
from modpilot.core.config import resolve
from modpilot.core.errors import StepError
from modpilot.core.step import step

ARM_SLOTS = ("upperarm_L", "forearm_L", "hand_L", "upperarm_R", "forearm_R", "hand_R")
# pose_conversion: what the preset's source rig needs to stand in the target's T-pose
CONVERSIONS = {"VRChat": "none", "MMD": "mmd_a_to_tpose", "arknights": "endfield"}
ENDFIELD_RECORD = "终末地 A转Tpose"          # Toolkit assets/presets/pose/<record>.json


def _armature(name: str, role: str):
    import bpy
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "ARMATURE":
        raise StepError("precondition", f"{role} armature {name!r} not found (or not an ARMATURE)",
                        details={role: name})
    return obj


def _catalog():
    from modpilot.bl import toolkit
    catalog, _ = presets.enumerate_x_presets(toolkit.preset_dir())
    return catalog


def _check_preset(name: str, catalog: dict, role: str) -> None:
    if name not in catalog:
        raise StepError("params", f"{role} preset {name!r} is not a Toolkit preset", details={"known": sorted(catalog)})


def _arm_candidates(meta) -> dict[str, list[str]]:
    return {slot: list((meta.mappings.get(slot) or {}).get("main") or []) or [slot] for slot in ARM_SLOTS}


def _sample(arm, candidates, axis: int) -> tuple[list[float], list[str]]:
    values, matched = [], []
    for slot in ARM_SLOTS:
        for name in candidates.get(slot, [slot]):
            pb = arm.pose.bones.get(name)
            if pb is not None:
                values.append((arm.matrix_world @ pb.head)[axis])
                matched.append(slot)
                break
    return values, matched


# ── pose_correction ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class PoseParams:
    x_preset: str | None = None
    source_armature: str | None = None
    target_armature: str | None = None
    y_preset: str | None = None
    skip_scale_align: bool = False
    pose_conversion: str = "auto"          # auto | none | mmd_a_to_tpose | endfield


@step("pose_correction", PoseParams, needs=("modder",))
def pose_correction(p: PoseParams, ctx) -> dict:
    """Clear the source pose; scale the source so its arm bones' mean height equals the target's
    (issue #13) and shift it in Y onto the target's arm plane; then the preset's T-pose conversion."""
    import bpy

    from modpilot.bl import context
    from modpilot.core import ops
    x = resolve(p.x_preset, ctx.config, "x_preset")
    y = resolve(p.y_preset, ctx.config, "y_preset")
    catalog = _catalog()
    _check_preset(x, catalog, "x")
    _check_preset(y, catalog, "y")
    conversion = CONVERSIONS.get(x) if p.pose_conversion == "auto" else p.pose_conversion
    if conversion not in ("none", "mmd_a_to_tpose", "endfield"):
        raise StepError("params", f"no T-pose conversion is known for x_preset {x!r}: pass pose_conversion "
                                  "none | mmd_a_to_tpose | endfield" if p.pose_conversion == "auto" else
                        f"unknown pose_conversion {p.pose_conversion!r}",
                        details={"x_preset": x, "known": sorted(CONVERSIONS)})
    src = _armature(resolve(p.source_armature, ctx.config, "source_armature"), "source")
    tgt = _armature(resolve(p.target_armature, ctx.config, "target_armature"), "target")

    # 1. pose reset
    context.object_mode()
    bpy.context.view_layer.objects.active = src
    ops.run("object.mode_set", mode="POSE")
    ops.run("pose.select_all", action="SELECT")
    ops.run("pose.transforms_clear")
    ops.run("object.mode_set", mode="OBJECT")

    # 2. arm-height scale + Y alignment
    scale = y_shift = None
    if not p.skip_scale_align:
        meshes = [c for c in src.children if c.type == "MESH"]
        context.select_only([src, *meshes], active=src)
        ops.run("object.transform_apply", location=False, rotation=False, scale=True)
        bpy.context.view_layer.update()
        src_c, tgt_c = _arm_candidates(catalog[x]), _arm_candidates(catalog[y])
        src_z, src_m = _sample(src, src_c, 2)
        tgt_z, tgt_m = _sample(tgt, tgt_c, 2)
        if len(src_z) < 2:
            raise StepError("precondition", f"source arm bones unresolved (matched {src_m}): at least 2 of "
                                            f"{', '.join(ARM_SLOTS)} must exist; or pass skip_scale_align",
                            details={"matched": src_m})
        if len(tgt_z) < 2:
            raise StepError("precondition", f"target arm bones unresolved (matched {tgt_m})", details={"matched": tgt_m})
        src_h, tgt_h = sum(src_z) / len(src_z), sum(tgt_z) / len(tgt_z)
        if src_h <= 0 or tgt_h <= 0:
            raise StepError("precondition", f"arm height not above zero (source {src_h:.3f}, target {tgt_h:.3f})")
        ratio = tgt_h / src_h
        src.scale = (ratio, ratio, ratio)
        context.select_only([src], active=src)
        ops.run("object.transform_apply", location=False, rotation=False, scale=True)
        scale = {"ratio": round(ratio, 6), "src_mean_z": round(src_h, 6), "tgt_mean_z": round(tgt_h, 6),
                 "src_matched": src_m, "tgt_matched": tgt_m}
        bpy.context.view_layer.update()
        src_y, _ = _sample(src, src_c, 1)
        tgt_y, _ = _sample(tgt, tgt_c, 1)
        if len(src_y) < 2 or len(tgt_y) < 2:
            ctx.warn("Y alignment skipped: fewer than 2 arm bones sampled on a side")
        else:
            src_my, tgt_my = sum(src_y) / len(src_y), sum(tgt_y) / len(tgt_y)
            dy = tgt_my - src_my
            src.location.y += dy
            context.select_only([src, *meshes], active=src)
            ops.run("object.transform_apply", location=True, rotation=False, scale=False)
            y_shift = {"dy": round(dy, 6), "src_mean_y": round(src_my, 6), "tgt_mean_y": round(tgt_my, 6)}

    # 3. T-pose conversion
    if conversion != "none":
        settings = bpy.context.scene.mhw_suite_settings
        settings.pose_import_preset_enum = f"{x}.json"
        if conversion == "endfield":
            settings.pose_preset_enum = f"{ENDFIELD_RECORD}.json"
        context.object_mode()
        bpy.context.view_layer.objects.active = src
        ops.run("modder.mmd_a_to_tpose" if conversion == "mmd_a_to_tpose" else "modder.apply_transform_forward")
    return {"scale": scale, "y_shift": y_shift, "pose_conversion": conversion}


# ── skeleton_align ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AlignParams:
    x_preset: str | None = None
    source_armature: str | None = None
    target_armature: str | None = None
    y_preset: str | None = None


@step("skeleton_align", AlignParams, needs=("modder",))
def skeleton_align(p: AlignParams, ctx) -> dict:
    """modder.universal_snap: the source skeleton snapped onto the target's (X/Y presets set, source
    selected first, target active). Hidden armatures are unhidden first, and reported."""
    import bpy

    from modpilot.bl import context, toolkit
    from modpilot.core import ops
    x = resolve(p.x_preset, ctx.config, "x_preset")
    y = resolve(p.y_preset, ctx.config, "y_preset")
    catalog = _catalog()
    _check_preset(x, catalog, "x")
    _check_preset(y, catalog, "y")
    src = _armature(resolve(p.source_armature, ctx.config, "source_armature"), "source")
    tgt = _armature(resolve(p.target_armature, ctx.config, "target_armature"), "target")
    toolkit.set_presets(x, y)
    unhidden = []
    for o in (src, tgt):
        if o.hide_viewport:
            o.hide_viewport = False
            unhidden.append(f"{o.name}:hide_viewport")
        if o.hide_get():
            o.hide_set(False)
            unhidden.append(f"{o.name}:hide_get")
    context.object_mode()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    src.select_set(True)
    tgt.select_set(True)
    bpy.context.view_layer.objects.active = tgt
    not_selected = [o.name for o in (src, tgt) if not o.select_get()]
    if not_selected:
        raise StepError("precondition", f"armature(s) not selectable even after unhiding: {not_selected} "
                                        "(in an excluded collection, or hide_select set?)",
                        details={"not_selectable": not_selected})
    ops.run("modder.universal_snap")
    if unhidden:
        ctx.warn(f"unhid {', '.join(unhidden)} so universal_snap could select them")
    return {"unhidden": unhidden}
