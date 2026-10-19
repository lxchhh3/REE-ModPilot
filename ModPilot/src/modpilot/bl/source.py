"""Fixes to the source rig right after its import, for what the pipeline cannot carry.

The pipeline carries deformation by vertex groups only, so:
  1. a mesh hung RIGIDLY on a bone (parent_type BONE, as RigForge's "attach to bone" leaves a
     headset on the Neck) becomes a mesh skinned 1.0 to that bone, world placement unchanged.
     Left alone it had no groups: the join put it on Hip and in game it did not follow her neck
     (GG gg5, Blender-MHWilds lesson #44).
  2. MochiFitter's '<bone>_MFBase' helper bones (a copy of <bone> on its head carrying the
     outfit's weights) fold into <bone>: weights added onto it, children re-hung on it, the helper
     and its own '_end' leaf removed. No MH Wilds bone maps to a helper, so the clothes on one did
     not follow her breasts or hips (Marette, mfbase_to_base.py). A helper whose base bone is
     missing, or that is not on the base bone's head (> 0.01 mm), is left alone and reported.
"""
from __future__ import annotations

MFBASE = "_MFBase"


def _deformed_by(obj, arm) -> bool:
    return obj.type == "MESH" and (obj.parent is arm or any(
        m.type == "ARMATURE" and m.object is arm for m in obj.modifiers))


def rigid_to_skinned(arm) -> dict[str, str]:
    import bpy
    import mathutils
    done = {}
    for obj in [o for o in bpy.data.objects if o.type == "MESH" and o.parent is arm and o.parent_type == "BONE"
                and o.parent_bone in arm.data.bones
                # also deformed by an Armature modifier on this rig: deformed twice already, not ours
                and not any(m.type == "ARMATURE" and m.object is arm for m in o.modifiers)]:
        bone = obj.parent_bone
        mw = obj.matrix_world.copy()
        obj.data.transform(mw, shape_keys=True)
        if mw.determinant() < 0:
            obj.data.flip_normals()
        obj.parent_type = "OBJECT"
        obj.parent_bone = ""
        obj.matrix_parent_inverse = arm.matrix_world.inverted()
        obj.matrix_basis = mathutils.Matrix.Identity(4)
        group = obj.vertex_groups.get(bone) or obj.vertex_groups.new(name=bone)
        group.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
        mod = obj.modifiers.new("Armature", "ARMATURE")
        mod.object = arm
        mod.use_vertex_groups = True
        obj.data.update()
        done[obj.name] = bone
    return done


def fold_mfbase(arm) -> tuple[dict[str, str], dict[str, str]]:
    import bpy

    from modpilot.bl import context
    bones = arm.data.bones
    folded, skipped = {}, {}
    for b in bones:
        if not b.name.endswith(MFBASE):
            continue
        base = b.name[:-len(MFBASE)]
        if base not in bones:
            skipped[b.name] = f"no bone {base}"
        elif (off := (b.head_local - bones[base].head_local).length) > 1e-5:
            skipped[b.name] = f"{off * 1000:.3f} mm off {base}"
        else:
            folded[b.name] = base
    if not folded:
        return folded, skipped
    for obj in [o for o in bpy.data.objects if _deformed_by(o, arm)]:
        for helper, base in folded.items():
            src = obj.vertex_groups.get(helper)
            if src is None:
                continue
            dst = obj.vertex_groups.get(base) or obj.vertex_groups.new(name=base)
            for v in obj.data.vertices:
                w = next((e.weight for e in v.groups if e.group == src.index), 0.0)
                if w > 0:
                    have = next((e.weight for e in v.groups if e.group == dst.index), 0.0)
                    dst.add([v.index], have + w, "REPLACE")
            obj.vertex_groups.remove(src)
    with context.edit_mode(arm):
        eb = arm.data.edit_bones
        for helper, base in folded.items():
            doomed = [eb[helper]]
            for child in list(eb[helper].children):
                if child.name.startswith(helper) and not child.children:
                    doomed.append(child)        # the helper's own '_end' leaf
                else:
                    child.use_connect = False
                    child.parent = eb[base]
            for e in doomed:
                eb.remove(e)
    return folded, skipped


def fix_source_rig(arm) -> dict:
    from modpilot.bl import context
    context.object_mode()
    rigid = rigid_to_skinned(arm)
    folded, skipped = fold_mfbase(arm)
    return {"rigid_to_skinned": rigid, "mfbase_folded": folded, "mfbase_skipped": skipped}
