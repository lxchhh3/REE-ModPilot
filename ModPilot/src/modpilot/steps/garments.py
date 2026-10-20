"""Garment steps the GG and Marette ModPilot runs ran as agent scripts between ModPilot calls
(Known_Good_mod_test/scripts/gg: mute_keys.py, rigid_to_weights.py, restore_ends.py), as library steps.

The other agent scripts of those runs are ModPilot's own now: bake_mix.py and match_layers.py are what
vertex_groups' join does (modpilot.bl.join, group A), mfbase_to_base.py and rigid_to_weights.py's re-hanging
what setup_import_source does (modpilot.bl.source). Marette's prepare_garments.py is that outfit's naming.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from modpilot.core.config import resolve
from modpilot.core.errors import StepError
from modpilot.core.step import step


def _armature(name: str):
    import bpy
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "ARMATURE":
        raise StepError("precondition", f"armature {name!r} not found (or not an ARMATURE)")
    return obj


# ── mute_shape_keys ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class MuteParams:
    objects: list[str] = field(default_factory=list)   # empty: every mesh


@step("mute_shape_keys", MuteParams)
def mute_shape_keys(p: MuteParams, ctx) -> dict:
    """Mute every shape key but the basis (on the named meshes, or all): RE-Mesh-Editor-BlendShape exports
    every unmuted key, and a staging build that ships rest shapes only needs none (tools-5.2's
    scenarios/maya_build.json does the same)."""
    import bpy
    if p.objects:
        missing = [n for n in p.objects if bpy.data.objects.get(n) is None or bpy.data.objects[n].type != "MESH"]
        if missing:
            raise StepError("precondition", f"not meshes in this scene: {missing}")
        objs = [bpy.data.objects[n] for n in p.objects]
    else:
        objs = [o for o in bpy.data.objects if o.type == "MESH"]
    n = 0
    for o in objs:
        keys = o.data.shape_keys
        if keys:
            for kb in keys.key_blocks:
                if kb != keys.reference_key:
                    kb.mute = True
                    n += 1
    return {"muted": n}


# ── rebind_rigid_garments ─────────────────────────────────────────────────


@dataclass(frozen=True)
class RebindParams:
    bones: list[str]                     # candidates, the first the armature has wins
    prefix: str = ""
    armature: str | None = None          # default: the scene config's source armature


@step("rebind_rigid_garments", RebindParams)
def rebind_rigid_garments(p: RebindParams, ctx) -> dict:
    """Move the garments that hang on ONE bone (prefix-named meshes: hung rigidly on a bone, or skinned 1.0
    to one bone, as setup_import_source leaves a rigid one) onto the first of `bones` the armature has,
    world placement kept. kevin 2026-10-16: GG's headset hung rigidly on Maya's Neck; "make the headset parent
    to upper spine (or chest if that doesnt exist)" -- Maya's rig has Chest and no UpperChest."""
    import bpy

    from modpilot.bl import source
    arm = _armature(resolve(p.armature, ctx.config, "source_armature"))
    target = next((b for b in p.bones if b in arm.data.bones), None)
    if target is None:
        raise StepError("precondition", f"{arm.name} has none of the bones {p.bones}", details={"bones": p.bones})
    still_rigid = [o.name for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(p.prefix)
                   and o.parent is arm and o.parent_type == "BONE"]
    hung = source.rigid_to_skinned(arm) if still_rigid else {}
    rebound, skipped = {}, []
    for o in bpy.data.objects:
        if (o.type != "MESH" or not o.name.startswith(p.prefix) or o.parent is not arm or o.parent_type != "OBJECT"
                or not any(m.type == "ARMATURE" and m.object is arm for m in o.modifiers)):
            continue
        if len(o.vertex_groups) != 1:
            skipped.append(o.name)
            continue
        g = o.vertex_groups[0]
        if not all(len(v.groups) == 1 and v.groups[0].group == g.index and v.groups[0].weight == 1.0
                   for v in o.data.vertices):
            skipped.append(o.name)
            continue
        if g.name == target:
            continue
        rebound[o.name] = {"bone": target, "from": g.name, "verts": len(o.data.vertices),
                           "was_rigid": o.name in hung}
        g.name = target
    if skipped:
        ctx.warn(f"left alone (weighted to more than one bone): {', '.join(sorted(skipped))}")
    return {"rebound": rebound, "bone": target}


# ── restore_leaf_bones ────────────────────────────────────────────────────


@dataclass(frozen=True)
class RestoreLeavesParams:
    orig_fbx: str
    prefix: str = ""
    armature: str | None = None          # default: the scene config's source armature
    max_head_gap: float = 1e-4           # metres: the shared bones of both rigs must sit this close


@step("restore_leaf_bones", RestoreLeavesParams)
def restore_leaf_bones(p: RestoreLeavesParams, ctx) -> dict:
    """Put back chain leaf bones a composed FBX lost (RigForge's zero-weight sweep dropped each GG skirt
    strand's end and the ribbon tails' .002): from the original FBX, every unweighted prefix-named leaf the
    armature lacks comes back as '<its parent>_End' (ModPilot's naming: physics_chains closes a chain only at
    an _End), same world head, tail and roll. The original is imported beside the scene and removed again;
    its shared bones must sit within max_head_gap of the scene's. A rerun adds nothing."""
    import bpy

    from modpilot.bl import context
    arm = _armature(resolve(p.armature, ctx.config, "source_armature"))
    if not Path(p.orig_fbx).is_file():
        raise StepError("precondition", f"orig_fbx {p.orig_fbx!r} is not a file")
    kinds = ("objects", "meshes", "materials", "armatures", "images", "actions", "collections")
    before = {k: set(getattr(bpy.data, k)) for k in kinds}
    context.object_mode()
    from modpilot.core import ops
    ops.run("import_scene.fbx", filepath=p.orig_fbx)
    new = {k: set(getattr(bpy.data, k)) - before[k] for k in kinds}
    try:
        orig = next((o for o in new["objects"] if o.type == "ARMATURE"), None)
        if orig is None:
            raise StepError("precondition", f"{p.orig_fbx} has no armature")
        cw, ow = arm.matrix_world, orig.matrix_world
        shared = [b.name for b in orig.data.bones if b.name.startswith(p.prefix) and b.name in arm.data.bones]
        gap = max((((cw @ arm.data.bones[n].head_local) - (ow @ orig.data.bones[n].head_local)).length
                   for n in shared), default=float("inf"))
        if not shared or gap > p.max_head_gap:
            raise StepError("precondition", f"the original's and the scene's {p.prefix}* bones disagree: "
                            f"{len(shared)} shared, max head gap {gap * 1000:.3f} mm",
                            details={"shared": len(shared), "max_head_mm": gap * 1000})
        leaves = [b for b in orig.data.bones if b.name.startswith(p.prefix) and b.name not in arm.data.bones
                  and not b.children and b.parent is not None and b.parent.name in arm.data.bones]
        present = {b.parent.name + "_End": b.name for b in leaves if b.parent.name + "_End" in arm.data.bones}
        leaves = [b for b in leaves if b.parent.name + "_End" not in arm.data.bones]
        spec = {b.name: (b.parent.name, ow @ b.head_local, ow @ b.tail_local, ow @ b.matrix_local) for b in leaves}
    finally:
        for o in new["objects"]:
            bpy.data.objects.remove(o, do_unlink=True)
        for k in ("meshes", "materials", "armatures", "images", "actions", "collections"):
            coll = getattr(bpy.data, k)
            for block in new[k]:
                if block.name in coll and block.users == 0:
                    coll.remove(block)
    added = {}
    if spec:
        inv = cw.inverted()
        with context.edit_mode(arm) as eb:
            for name, (parent, head, tail, mat) in spec.items():
                e = eb.new(parent + "_End")
                e.matrix = inv @ mat
                e.head = inv @ head
                e.tail = inv @ tail
                e.parent = eb[parent]
                e.use_connect = False
                added[e.name] = name
    return {"added": added, "already_present": present, "shared": len(shared), "max_head_mm": round(gap * 1000, 4)}
