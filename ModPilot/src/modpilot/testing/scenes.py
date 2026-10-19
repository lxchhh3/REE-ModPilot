"""Synthetic scenes for the tests that run inside Blender: tiny avatars (an armature, a few quads,
weights, shape keys) so one step can be run against a scene whose answer is known.

Ported from tools-5.2 harness/fixes/scene_lib.py (the group-A fix scenarios, 2026-10-19); that
file stays the source of tools-5.2's own scenarios until M5 repoints them here."""
import json

import bpy


def clear_scene():
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.armatures, bpy.data.materials):
        for d in list(coll):
            coll.remove(d)


def make_armature(name, bones, location=(0.0, 0.0, 0.0)):
    """bones: [(name, parent or None, head, tail)] in armature space."""
    arm = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, arm)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for n, parent, head, tail in bones:
        eb = arm.edit_bones.new(n)
        eb.head, eb.tail = head, tail
        if parent:
            eb.parent = arm.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


def make_quads(name, corners, material):
    """One quad per entry of `corners` (4 points each), all on one material."""
    me = bpy.data.meshes.new(name)
    verts, faces = [], []
    for quad in corners:
        faces.append(tuple(range(len(verts), len(verts) + 4)))
        verts.extend(quad)
    me.from_pydata(verts, [], faces)
    me.materials.append(bpy.data.materials.get(material) or bpy.data.materials.new(material))
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def skin(obj, arm, weights):
    """Parent `obj` to `arm` as an ordinary skinned mesh. weights: {group: [(vertex, weight)]}."""
    obj.parent = arm
    obj.matrix_parent_inverse = arm.matrix_world.inverted()
    for g, entries in weights.items():
        vg = obj.vertex_groups.get(g) or obj.vertex_groups.new(name=g)
        for vi, w in entries:
            vg.add([vi], w, "REPLACE")
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm


def add_key(obj, name, offsets, value):
    """A relative shape key moving vertex i by offsets[i] (object space), set to `value`."""
    if obj.data.shape_keys is None:
        obj.shape_key_add(name="Basis", from_mix=False)
    kb = obj.shape_key_add(name=name, from_mix=False)
    for i, d in enumerate(offsets):
        kb.data[i].co = kb.data[i].co + type(kb.data[i].co)(d)
    kb.value = value
    return kb


def world_mix(obj):
    """World positions of `obj` as it looks now (shape-key mix and modifiers evaluated)."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    mw = ev.matrix_world
    return [list(mw @ v.co) for v in ev.data.vertices]


def remember(key, value):
    bpy.context.scene[key] = json.dumps(value)


def recall(key):
    return json.loads(bpy.context.scene[key])


def material_vertices(obj, material):
    """Vertex indices of the faces on `material` (name, '.NNN' suffix ignored)."""
    names = [(m.name.rsplit(".", 1)[0] if m and m.name[-4:-3] == "." else (m.name if m else "")) for m in obj.data.materials]
    idx = {i for i, n in enumerate(names) if n == material}
    out = []
    for p in obj.data.polygons:
        if p.material_index in idx:
            out.extend(p.vertices)
    return sorted(set(out))


def nearest_error(expected, got):
    """Max over `expected` of the distance to the nearest point in `got` (both lists of xyz)."""
    worst = 0.0
    for e in expected:
        best = min(sum((a - b) ** 2 for a, b in zip(e, g, strict=True)) ** 0.5 for g in got)
        worst = max(worst, best)
    return worst
