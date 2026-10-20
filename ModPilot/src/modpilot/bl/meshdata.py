"""Blender mesh data the build recipes read and write: per-vertex weights, a shape-key state's world
positions and normals, a separated sub-mesh's material, the bones a chain group hangs on, an MDF2
imported as a collection. Moved from the helpers Known_Good_mod_test/scripts/gg/build_gg.py and
marette/rebuild/build_marette.py both carried byte for byte (their globals became arguments)."""
from __future__ import annotations

import numpy as np


def weights_of(obj):
    """Per vertex, {group name: weight} of its non-zero weights."""
    names = {g.index: g.name for g in obj.vertex_groups}
    return [{names[g.group]: g.weight for g in v.groups if g.weight > 0} for v in obj.data.vertices]


def set_weights(obj, i, old, new):
    """Vertex i's weights from `old` to `new` ({group: weight}): groups not in new lose it, the rest
    are set (groups created as needed)."""
    for n in old:
        if n not in new:
            obj.vertex_groups[n].remove([i])
    for n, x in new.items():
        (obj.vertex_groups.get(n) or obj.vertex_groups.new(name=n)).add([i], x, "REPLACE")


def material_of(obj):
    """The material a separated sub-mesh is named after: 'Group_0_Sub_3__Body all.001' -> 'Body all'."""
    return obj.name.split("__", 1)[-1].split(".")[0]


def key_state(obj, values):
    """World positions and vertex normals (unit, loop normals summed) of `obj` with only these shape
    keys on ({key name: value}; every other key 0)."""
    import bpy
    for k in obj.data.shape_keys.key_blocks[1:]:
        k.value = values.get(k.name, 0.0)
    bpy.context.view_layer.update()
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    mw = obj.matrix_world
    pos = np.array([tuple(mw @ v.co) for v in me.vertices])
    nrm = np.zeros((len(me.vertices), 3))
    for lp, cn in zip(me.loops, me.corner_normals, strict=True):
        nrm[lp.vertex_index] += np.array(tuple(mw.to_3x3() @ cn.vector))
    ev.to_mesh_clear()
    return pos, nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)


def chain_bones(group, arm, bone_of_hash):
    """The bones a chain2 group hangs on, terminal first, walking up from its terminal bone (by name
    hash: bone_of_hash) as many as it has nodes; [] when the terminal is not on `arm`."""
    t = bone_of_hash.get(group.terminateNodeNameHash)
    if t is None or t not in arm.data.bones:
        return []
    out, b = [t], arm.data.bones[t]
    while b.parent is not None and len(out) < len(group.nodeList):
        b = b.parent
        out.append(b.name)
    return out


def import_mdf(path):
    """RE Mesh Editor's MDF2 import: (the new .mdf2 collection, its RE_MDF_MATERIAL objects)."""
    import bpy
    before = {c.name for c in bpy.data.collections}
    bpy.ops.re_mdf.importfile(files=[{"name": path.name}], directory=str(path.parent))
    coll = next(c for c in bpy.data.collections if c.name not in before and ".mdf2" in c.name)
    return coll, [o for o in coll.all_objects if o.get("~TYPE") == "RE_MDF_MATERIAL"]
