"""Phase 6 (plan.md video 6): the mod files. Ported from the legacy app/phases/batch_export.py.

The Toolkit's mhws.batch_export exports every part the armor scheme has: the bound collections of
the target parts (mesh, mdf2, chain2, clsp), blank files for the rest, then the BoneSystem (fbxskel +
json) for the MH Wilds armature. Bindings are scene properties
`mhws_<armor_id>_<part>_<filetype>`; part ids: 1 Arms, 2 Body, 3 Helmet, 4 Legs, 5 Waist; variant =
hunter + armor gender (ff, fm, mf, mm).

Changes from the legacy tool (no silent paths): the pre-export mesh cleanup's operator failures were
collected as mesh_cleanup_warnings (the whole cleanup's failure dropped) and now fail the step; the
exporter prints a failed file or BoneSystem export and still returns FINISHED, and its per-file
helpers ignore a CANCELLED operator, so the step records both for the call and fails on them and on
any bound file that did not appear (files_written lists what was). Collection names default to the
scene config; natives_root must be a folder.

"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass

from modpilot.core.config import resolve
from modpilot.core.errors import StepError
from modpilot.core.step import step

PART_NAMES = {"1": "Arms", "2": "Body", "3": "Helmet", "4": "Legs", "5": "Waist"}
VARIANTS = ("ff", "fm", "mf", "mm")
FILETYPES = ("mesh", "mdf2", "chain2")
CLSP_COLLECTION_TAG = "RE_CLSP_COLLECTION"
DEFAULT_ARMOR_SCHEME = "mhws_armor_sets.json"
EXPORTER_MODULE_SUFFIX = "games.mhws.batch_export"
CLEANUP_OPS = (("re_mesh.delete_loose", {}), ("re_mesh.solve_repeated_uvs", {}),
               ("re_mesh.remove_zero_weight_vertex_groups", {}), ("re_mesh.limit_total_normalize", {"maxWeights": "12"}))


@dataclass(frozen=True)
class ExportParams:
    armor_id: str
    armor_variant: str
    target_parts: list[str]
    fbxskel_name: str
    natives_root: str
    mesh_collection: str | None = None
    mdf2_collection: str | None = None
    chain2_collection: str | None = None
    target_armature: str | None = None
    armor_scheme: str = DEFAULT_ARMOR_SCHEME
    # None: the collection collider_create imported (RE Chain Editor tags it); "": a blank clsp
    clsp_collection: str | None = None


def _exporter():
    for name, mod in list(sys.modules.items()):
        if name.endswith(EXPORTER_MODULE_SUFFIX) and hasattr(mod, "_EXPORT_FUNCS"):
            return mod
    raise StepError("environment", "the Modding Toolkit's MH Wilds batch exporter is not loaded")


@contextmanager
def _recording(exp):
    """Record every bound file the exporter writes or fails on, and the BoneSystem outcome."""
    funcs = exp._EXPORT_FUNCS
    originals = dict(funcs)
    bonesystem = exp._do_bonesystem_export
    rec = {"written": [], "failed": {}, "bonesystem": None}

    def wrap(filetype, fn):
        def recorded(filepath, collection_name):
            try:
                fn(filepath, collection_name)
            except Exception as exc:
                rec["failed"][f"{filetype}:{collection_name}"] = str(exc)
                raise
            rec["written"].append({"filetype": filetype, "collection": collection_name, "path": filepath})
        return recorded

    def bonesystem_recorded(*args, **kwargs):
        rec["bonesystem"] = bonesystem(*args, **kwargs)
        return rec["bonesystem"]
    for ft, fn in originals.items():
        funcs[ft] = wrap(ft, fn)
    exp._do_bonesystem_export = bonesystem_recorded
    try:
        yield rec
    finally:
        funcs.update(originals)
        exp._do_bonesystem_export = bonesystem


def _clsp(p: ExportParams) -> str | None:
    import bpy
    if p.clsp_collection is None:
        tagged = sorted(c.name for c in bpy.data.collections if c.get("~TYPE") == CLSP_COLLECTION_TAG)
        if len(tagged) > 1:
            raise StepError("precondition", f"several collider collections {tagged}: pass clsp_collection "
                            "(or \"\" for a blank clsp)", details={"candidates": tagged})
        return tagged[0] if tagged else None
    if p.clsp_collection and bpy.data.collections.get(p.clsp_collection) is None:
        raise StepError("precondition", f"clsp_collection {p.clsp_collection!r} not found")
    return p.clsp_collection or None


def _cleanup(col) -> list[str]:
    """RE Mesh Editor's pre-export cleanup on each mesh of the collection."""
    import bpy

    from modpilot.bl import context
    from modpilot.core import ops
    meshes = [o for o in col.objects if o.type == "MESH"]
    for obj in meshes:
        context.select_only([obj], active=obj)
        for op_id, kw in CLEANUP_OPS:
            ops.run(op_id, **kw)
    bpy.ops.object.select_all(action="DESELECT")
    return [o.name for o in meshes]


@step("batch_export", ExportParams, needs=("mhws", "re_mesh", "re_mdf", "re_chain", "re_clsp"))
def batch_export(p: ExportParams, ctx) -> dict:
    """Bind the mesh / mdf2 / chain2 / clsp collections to the target parts of armor `armor_id`
    (all other parts get blank files), set the BoneSystem (fbxskel `fbxskel_name` from the target
    armature) and run mhws.batch_export into natives_root."""
    import bpy

    from modpilot.core import ops
    if not p.armor_id:
        raise StepError("params", "armor_id is required (e.g. 'pl024')")
    if p.armor_variant not in VARIANTS:
        raise StepError("params", f"armor_variant must be one of {list(VARIANTS)}, got {p.armor_variant!r}")
    bad = [x for x in p.target_parts if x not in PART_NAMES]
    if not p.target_parts or bad:
        raise StepError("params", f"target_parts must be a non-empty list of {sorted(PART_NAMES)}, got {p.target_parts}")
    if not p.fbxskel_name:
        raise StepError("params", "fbxskel_name is required")
    names = {"mesh": resolve(p.mesh_collection, ctx.config, "mesh_collection"),
             "mdf2": resolve(p.mdf2_collection, ctx.config, "mdf2_collection"),
             "chain2": resolve(p.chain2_collection, ctx.config, "chain2_collection")}
    missing = {f"{ft}_collection": n for ft, n in names.items() if not n or bpy.data.collections.get(n) is None}
    arm_name = resolve(p.target_armature, ctx.config, "target_armature")
    arm = bpy.data.objects.get(arm_name or "")
    if arm is None or arm.type != "ARMATURE":
        missing["target_armature"] = arm_name
    if missing:
        raise StepError("precondition", f"not in the scene: {missing}", details={"missing": missing})
    if not os.path.isdir(p.natives_root):
        raise StepError("precondition", f"natives_root {p.natives_root!r} is not a folder")
    clsp = _clsp(p)
    no_uv = [o.name for o in bpy.data.collections[names["mesh"]].objects if o.type == "MESH" and not o.data.uv_layers]
    if no_uv:
        raise StepError("precondition", f"meshes without a UV map (RE Mesh exports none): {no_uv}",
                        details={"no_uv_map": no_uv})
    exp = _exporter()

    cleaned = _cleanup(bpy.data.collections[names["mesh"]])
    scene = bpy.context.scene
    for part in PART_NAMES:
        for ft in (*FILETYPES, "clsp"):
            scene.pop(f"mhws_{p.armor_id}_{part}_{ft}", None)
    for part in p.target_parts:
        for ft in FILETYPES:
            scene[f"mhws_{p.armor_id}_{part}_{ft}"] = names[ft]
        if clsp:
            scene[f"mhws_{p.armor_id}_{part}_clsp"] = clsp
    s = scene.mhw_suite_settings
    scene["mhws_natives_root"] = p.natives_root
    s.mhws_armor_scheme = p.armor_scheme
    s.mhws_selected_armor = p.armor_id
    s.mhws_armor_variant = p.armor_variant
    s.mhws_use_blank_export = True
    s.mhws_fbxskel_name = p.fbxskel_name
    s.mhws_bs_armature = arm
    s.mhws_use_bonesystem = True

    with _recording(exp) as rec:
        ops.run("mhws.batch_export")
    data = {"exported_parts": {x: PART_NAMES[x] for x in p.target_parts}, "armor_id": p.armor_id,
            "armor_variant": p.armor_variant, "fbxskel_name": p.fbxskel_name, "clsp_collection": clsp,
            "files_written": rec["written"], "meshes_cleaned": cleaned}
    absent = [f"{w['filetype']}:{w['path']}" for w in rec["written"] if not os.path.isfile(w["path"])]
    bs_ok, bs_msg = rec["bonesystem"] if rec["bonesystem"] is not None else (False, "BoneSystem export did not run")
    if rec["failed"] or absent or not bs_ok:
        raise StepError("postcondition", "the exporter did not write every file: "
                        f"failed {rec['failed']}, missing {absent}, BoneSystem {'ok' if bs_ok else bs_msg!r}",
                        details={"failed": rec["failed"], "missing_files": absent,
                                 "bonesystem": None if bs_ok else bs_msg}, partial=data)
    expected = {(x, ft) for x in p.target_parts for ft in (*FILETYPES, *(("clsp",) if clsp else ()))}
    if len(rec["written"]) < len(expected):
        raise StepError("postcondition", f"the exporter wrote {len(rec['written'])} bound file(s), expected "
                        f"{len(expected)}: the armor scheme may not include part(s) {p.target_parts}",
                        details={"written": rec["written"]}, partial=data)
    return data
