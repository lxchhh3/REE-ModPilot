"""Setup steps: bring the source model in, check it, find its X-preset, bring the MH Wilds
reference skeleton in. Ported from the legacy app/phases/setup.py, infer_model_type.py and
preset_write.py; the names each step finds go into the scene config for the steps after it.

Changes from the legacy tools (no silent paths): an FBX that brings no armature fails instead of
reporting source_armature None; an unknown `forced_preset` fails instead of falling back to
inference; an unreadable preset file becomes a warning; rig_bone_count is the rig's real count on
the forced-preset path too (the legacy tool reported 0 there).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from modpilot import presets
from modpilot.core.config import resolve
from modpilot.core.errors import StepError
from modpilot.core.step import step


def _mhwilds_objects(ctx) -> set[str]:
    import bpy
    col = bpy.data.collections.get(ctx.config.mesh_collection or "")
    return {o.name for o in col.all_objects} if col else set()


# ── setup_import_source ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ImportSourceParams:
    file_path: str


@step("setup_import_source", ImportSourceParams, needs=("import_scene",))
def setup_import_source(p: ImportSourceParams, ctx) -> dict:
    """Import the source FBX, unless a source armature is already in the scene (outside the MH
    Wilds collection); then fix what the pipeline can't carry (modpilot.bl.source)."""
    import bpy

    from modpilot.bl import context, source
    from modpilot.core import ops
    path = p.file_path.strip()
    if not path:
        raise StepError("params", "file_path is empty: pass the source model's .fbx")
    if not path.lower().endswith(".fbx"):
        raise StepError("params", f"file_path must be an .fbx file, got {path!r}", details={"file_path": path})
    excluded = _mhwilds_objects(ctx)
    present = [o for o in bpy.context.scene.objects if o.type == "ARMATURE" and o.name not in excluded]
    if present:
        arm = present[0]
        fixes = source.fix_source_rig(arm)
        ctx.set_config(source_armature=arm.name)
        return {"import_status": "already_imported", "source_armature": arm.name, "source_fixes": fixes}
    if not os.path.isfile(path):
        raise StepError("precondition", f"source FBX not found at {path!r}", details={"file_path": path})
    before = {o.name for o in bpy.data.objects}
    context.object_mode()
    ops.run("import_scene.fbx", filepath=path)
    added = sorted({o.name for o in bpy.data.objects} - before)
    arms = [bpy.data.objects[n] for n in added if bpy.data.objects[n].type == "ARMATURE"]
    if not arms:
        raise StepError("postcondition", f"{os.path.basename(path)} brought no armature",
                        details={"imported_objects": added}, partial={"imported_objects": added})
    fixes = source.fix_source_rig(arms[0])
    ctx.set_config(source_armature=arms[0].name)
    return {"import_status": "imported", "source_armature": arms[0].name, "imported_objects": added,
            "source_fixes": fixes}


# ── setup_validate_scene ──────────────────────────────────────────────────


@dataclass(frozen=True)
class NoParams:
    pass


@step("setup_validate_scene", NoParams, mutates=False)
def setup_validate_scene(p: NoParams, ctx) -> dict:
    """Exactly one source armature with only MESH children, nothing else outside the MH Wilds
    collection."""
    import bpy
    excluded = _mhwilds_objects(ctx)
    remaining = [o for o in bpy.context.scene.objects if o.name not in excluded]
    arms = [o for o in remaining if o.type == "ARMATURE"]
    meshes = [o for o in remaining if o.type == "MESH"]
    others = [o for o in remaining if o.type not in ("ARMATURE", "MESH")]
    errors, src, kids = [], None, []
    if not arms:
        errors.append("No armature found (excluding MHWilds collection).")
    elif len(arms) > 1:
        errors.append(f"Expected 1 armature, found {len(arms)}: {[a.name for a in arms]}")
    else:
        src = arms[0].name
        kids = [m.name for m in meshes if m.parent == arms[0]]
        loose = [m.name for m in meshes if m.parent != arms[0]]
        if loose:
            errors.append(f"Meshes not parented to armature: {loose}")
        if others:
            errors.append(f"Stray non-mesh/armature objects: {[o.name for o in others]}")
    result = {"valid": not errors, "errors": errors, "source_armature": src, "child_meshes": kids,
              "mhwilds_imported": bool(excluded) or bpy.data.collections.get(ctx.config.mesh_collection or "") is not None}
    if errors:
        raise StepError("precondition", "Scene validation failed: " + "; ".join(errors), details=result)
    return result


# ── setup_infer_model_type ────────────────────────────────────────────────


@dataclass(frozen=True)
class InferParams:
    source_armature: str | None = None
    force_custom: bool = False
    forced_preset: str = ""


@step("setup_infer_model_type", InferParams, mutates=False)
def setup_infer_model_type(p: InferParams, ctx) -> dict:
    """Pick the Toolkit X-preset that maps the most of the source rig's bones: exact (100%),
    supplement (80-99%), custom (1-79%); no match at all fails."""
    import bpy

    from modpilot.bl import toolkit
    name = resolve(p.source_armature, ctx.config, "source_armature")
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "ARMATURE":
        raise StepError("precondition", f"object {name!r} does not exist or is not an ARMATURE")
    folder = toolkit.preset_dir()
    catalog, unreadable = presets.enumerate_x_presets(folder)
    for u in unreadable:
        ctx.warn(f"preset file not read: {u['path']} ({u['why']})")
    if not catalog:
        raise StepError("environment", f"no X-presets under {folder}; is the Toolkit install complete?")
    bones = [b.name for b in obj.data.bones]
    forced = p.forced_preset.strip()
    if forced and forced != "Auto-detect" and not p.force_custom:
        if forced not in catalog:
            raise StepError("params", f"forced_preset {forced!r} is not a Toolkit X-preset",
                            details={"known": sorted(catalog)})
        ctx.set_config(x_preset=forced)
        return {"inferred_preset": forced, "coverage": 1.0, "decision": "user_specified", "covered_slots": [],
                "uncovered_slots": [], "optional_skipped_slots": [], "total_slots": 0,
                "candidates": [{"preset": forced, "coverage": 1.0}], "preset_path": str(catalog[forced].path),
                "rig_bone_count": len(bones)}
    winner, reports = presets.pick_best_preset(catalog.values(), set(bones))
    decision = "custom" if p.force_custom else presets.decide(winner.coverage)
    result = {"inferred_preset": winner.preset_name, "coverage": round(winner.coverage, 4), "decision": decision,
              "covered_slots": winner.covered_slots, "uncovered_slots": winner.uncovered_slots,
              "optional_skipped_slots": winner.optional_skipped, "total_slots": winner.total_slots,
              "candidates": [{"preset": r.preset_name, "coverage": round(r.coverage, 4)} for r in reports[:3]],
              "preset_path": str(catalog[winner.preset_name].path), "rig_bone_count": len(bones)}
    if decision == "unsupported":
        raise StepError("precondition", f"No X-preset matched any bone in {name!r}. The source rig may use an "
                                        "unsupported naming convention.",
                        details={"legacy_category": "unsupported_rig", "result": result})
    if decision == "exact":
        ctx.set_config(x_preset=winner.preset_name)
    return result


# ── preset writers ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SupplementParams:
    base_preset_name: str
    mappings: dict[str, str]


@step("setup_preset_supplement_write", SupplementParams)
def setup_preset_supplement_write(p: SupplementParams, ctx) -> dict:
    """<base>_extended.json in the Toolkit's preset folder: the base preset plus the confirmed
    source-rig bone names for its uncovered slots."""
    from modpilot.bl import toolkit
    out = presets.write_supplement(toolkit.preset_dir(), p.base_preset_name, p.mappings)
    ctx.set_config(x_preset=out["new_preset_name"])
    return out


@dataclass(frozen=True)
class CustomParams:
    character_name: str
    mappings: dict[str, str]
    description: str = ""


@step("setup_preset_custom_write", CustomParams)
def setup_preset_custom_write(p: CustomParams, ctx) -> dict:
    """<character>_custom.json in the Toolkit's preset folder, one slot per confirmed bone."""
    from modpilot.bl import toolkit
    out = presets.write_custom(toolkit.preset_dir(), p.character_name.strip(), p.mappings, p.description.strip())
    ctx.set_config(x_preset=out["new_preset_name"])
    return out


# ── setup_import_mhwilds ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ImportMHWildsParams:
    convert_to_tpose: bool = True
    merge_facial_bones: bool = True


@step("setup_import_mhwilds", ImportMHWildsParams, needs=("mbt",))
def setup_import_mhwilds(p: ImportMHWildsParams, ctx) -> dict:
    """The MH Wilds female reference skeleton (Modder-Batch-Tool), unless the configured one is
    already in the scene; records the armature and collection it created in the scene config."""
    import bpy

    from modpilot.bl import context
    from modpilot.core import ops
    cfg = ctx.config
    if bpy.data.collections.get(cfg.mesh_collection or "") is not None and cfg.target_armature in bpy.data.objects:
        return {"mhwilds_collection": cfg.mesh_collection, "mhwilds_armature": cfg.target_armature,
                "import_status": "already_imported"}
    context.object_mode()
    cols, objs = {c.name for c in bpy.data.collections}, {o.name for o in bpy.data.objects}
    panel = bpy.context.scene.mbt_toolpanel
    panel.mhwilds_convert_to_tpose = p.convert_to_tpose
    panel.mhwilds_merge_facial_bones = p.merge_facial_bones
    ops.run("mbt.import_mhwilds_fmesh")
    arms = [o for o in bpy.data.objects if o.name not in objs and o.type == "ARMATURE"]
    if len(arms) != 1:
        raise StepError("postcondition", f"expected the import to add one armature, it added {len(arms)}",
                        details={"armatures": [a.name for a in arms]})
    arm = arms[0]
    homes = [c for c in bpy.data.collections if c.name not in cols and arm.name in c.all_objects]
    if not homes:
        raise StepError("postcondition", f"the reference armature {arm.name!r} is in no new collection")
    col = next((c for c in homes if c.name.endswith(".mesh")), homes[0])
    ctx.set_config(target_armature=arm.name, mesh_collection=col.name)
    return {"mhwilds_collection": col.name, "mhwilds_armature": arm.name, "import_status": "imported"}
