"""Phase 3 (plan.md video 3): one mesh, MH Wilds vertex groups, on the MH Wilds armature. Ported from
the legacy app/phases/vertex_groups.py, operator for operator:

  1. every part gets a material slot (a placeholder '<name>_mat' if it had none), the parts are
     made join-safe (modpilot.bl.join) and joined (the first named part is the one kept); MMD's
     functional groups (mmd_edge_scale / mmd_vertex_order) are dropped; zero weights are cleaned
     and the weights normalised
  2. the vertex groups are renamed from the source preset's bone names to the MH Wilds ones
     (modder.direct_convert, X/Y presets set)
  3. the result is hung on the MH Wilds armature without moving (parent cleared keeping the
     transform, one fresh Armature modifier) and moved into the MH Wilds mesh collection
  4. the reference skeleton's own meshes are deleted

Changes from the legacy tool: the deleted reference meshes are reported (the legacy deletion ran
outside its error handling and reported nothing).
"""
from __future__ import annotations

from dataclasses import dataclass

from modpilot.core.config import resolve
from modpilot.core.errors import StepError
from modpilot.core.step import step

MMD_FUNCTIONAL_GROUPS = ("mmd_edge_scale", "mmd_vertex_order")


@dataclass(frozen=True)
class VertexGroupsParams:
    mesh_objects: list[str]
    x_preset: str | None = None
    y_preset: str | None = None
    target_armature: str | None = None


@step("vertex_groups", VertexGroupsParams, needs=("modder",))
def vertex_groups(p: VertexGroupsParams, ctx) -> dict:
    """Join the source meshes, convert their vertex groups to MH Wilds bones, hang the result on the
    MH Wilds armature; the reference skeleton's own meshes go."""
    import bpy

    from modpilot.bl import context, join, toolkit
    from modpilot.core import ops
    if not p.mesh_objects:
        raise StepError("params", "mesh_objects is empty: name the source meshes to join")
    x = resolve(p.x_preset, ctx.config, "x_preset")
    y = resolve(p.y_preset, ctx.config, "y_preset")
    tgt_name = resolve(p.target_armature, ctx.config, "target_armature")
    tgt = bpy.data.objects.get(tgt_name)
    if tgt is None or tgt.type != "ARMATURE":
        raise StepError("precondition", f"target armature {tgt_name!r} not found (or not an ARMATURE)")
    missing = [n for n in p.mesh_objects if n not in bpy.data.objects]
    not_mesh = [n for n in p.mesh_objects if n in bpy.data.objects and bpy.data.objects[n].type != "MESH"]
    if missing or not_mesh:
        raise StepError("precondition", f"mesh_objects: not found {missing}, not a mesh {not_mesh}",
                        details={"not_found": missing, "not_mesh": not_mesh})
    objs = [bpy.data.objects[n] for n in p.mesh_objects]

    # 1. prepare and join
    for obj in objs:
        if len(obj.material_slots) == 0:
            obj.data.materials.append(bpy.data.materials.new(name=obj.name + "_mat"))
    context.object_mode()
    join_prep = join.prepare_for_join(objs)
    context.select_only(objs, active=objs[0])
    if len(objs) > 1:          # with one mesh object.join has nothing to do and returns CANCELLED
        ops.run("object.join")
    merged = bpy.context.view_layer.objects.active
    if x == "MMD":
        for name in MMD_FUNCTIONAL_GROUPS:
            group = merged.vertex_groups.get(name)
            if group:
                merged.vertex_groups.remove(group)
    context.select_only([merged], active=merged)
    ops.run("object.vertex_group_clean", group_select_mode="ALL", limit=0.0)
    ops.run("object.vertex_group_normalize_all", lock_active=False)

    # 2. vertex groups to MH Wilds bone names
    toolkit.set_presets(x, y)
    context.select_only([merged], active=merged)
    ops.run("modder.direct_convert")

    # 3. onto the MH Wilds armature, in place
    context.select_only([merged], active=merged)
    ops.run("object.parent_clear", type="CLEAR_KEEP_TRANSFORM")
    for mod in [m for m in merged.modifiers if m.type == "ARMATURE"]:
        merged.modifiers.remove(mod)
    merged.parent = tgt
    merged.matrix_parent_inverse = tgt.matrix_world.inverted()
    mod = merged.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = tgt
    mod.use_vertex_groups = True
    mod.use_bone_envelopes = False
    col = bpy.data.collections.get(ctx.config.mesh_collection or "")
    if col is not None:
        for c in list(merged.users_collection):
            c.objects.unlink(merged)
        col.objects.link(merged)
    else:
        ctx.warn(f"no MH Wilds mesh collection {ctx.config.mesh_collection!r}: the merged mesh stays where it was")

    # 4. the reference skeleton's own meshes
    deleted = []
    if col is not None:
        for obj in [o for o in col.objects if o.type == "MESH" and o.parent == tgt and o.name != merged.name]:
            deleted.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    return {"merged": merged.name, "join_prep": join_prep, "deleted_reference_meshes": deleted}
