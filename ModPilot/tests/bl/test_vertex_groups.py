"""vertex_groups in real Blender (T1): join the source meshes into one, rename their vertex groups
to the MH Wilds bones (modder.direct_convert), hang the result on the MH Wilds armature, drop the
reference skeleton's own meshes.

The join keeps ONE value per shape key (the active object's) and merges UV / colour layers by NAME,
while the exporter ships each vertex's basis position and writes UV layers by index, so each part's
shape-key mix goes into its basis first, UV layers take the active part's names by position, and
colour layers a part lacks are added white (ModPilot lesson #48, Blender-MHWilds #11 / #42 / #73).
These are the group-A scenarios of tools-5.2 tests/test_l3_fixes.py (join_scene / join_probe).
"""
import math

import bpy
import mathutils
import pytest

import modpilot
from modpilot.core.errors import StepError
from modpilot.testing import scenes

PARAMS = {"x_preset": "VRChat", "y_preset": "mhws", "mesh_objects": ["Body", "Garment", "Hair"]}
UVS = {"Body": [0.0, 0.0, 0.5, 0.0, 0.5, 0.5, 0.0, 0.5] * 2,
       "Garment": [0.25, 0.25, 0.75, 0.25, 0.75, 0.75, 0.25, 0.75],
       "Hair": [0.6, 0.6, 0.9, 0.6, 0.9, 0.9, 0.6, 0.9]}
COLOURS = {"Body": (0.2, 0.4, 0.6, 1.0), "Hair": (0.9, 0.1, 0.1, 1.0)}


def _scene():
    modpilot.call("setup_import_mhwilds", quiet=True)
    src = scenes.make_armature("Armature", [
        ("Hips", None, (0, 0, 0.9), (0, 0, 1.0)), ("Spine", "Hips", (0, 0, 1.0), (0, 0, 1.1)),
        ("Chest", "Spine", (0, 0, 1.1), (0, 0, 1.25)), ("Neck", "Chest", (0, 0, 1.4), (0, 0, 1.5)),
        ("Head", "Neck", (0, 0, 1.5), (0, 0, 1.7))])
    body = scenes.make_quads("Body", [[(-0.1, 0, 0.9), (0.1, 0, 0.9), (0.1, 0, 1.1), (-0.1, 0, 1.1)],
                                      [(-0.1, 0.1, 0.9), (0.1, 0.1, 0.9), (0.1, 0.1, 1.1), (-0.1, 0.1, 1.1)]], "BodyMat")
    garment = scenes.make_quads("Garment", [[(0, 0, 1.15), (0.1, 0, 1.15), (0.1, 0, 1.25), (0, 0, 1.25)]], "GarmentMat")
    hair = scenes.make_quads("Hair", [[(-0.05, 0, 1.6), (0.05, 0, 1.6), (0.05, 0, 1.7), (-0.05, 0, 1.7)]], "HairMat")
    for o, layers in ((body, ["UV 맵", "UVMap"]), (garment, ["UVマップ"]), (hair, ["UV 맵", "UVMap"])):
        for n in layers:
            o.data.uv_layers.new(name=n).data.foreach_set("uv", UVS[o.name])
    for o in (body, hair):
        ca = o.data.color_attributes.new(name="Col", type="BYTE_COLOR", domain="CORNER")
        ca.data.foreach_set("color", list(COLOURS[o.name]) * len(ca.data))
    garment.location = (0.3, 0.0, 0.0)
    garment.rotation_euler = (0.0, 0.0, math.radians(30))
    scenes.skin(body, src, {"Hips": [(i, 1.0) for i in range(8)]})
    scenes.skin(garment, src, {"Chest": [(i, 1.0) for i in range(4)]})
    scenes.skin(hair, src, {"Head": [(i, 1.0) for i in range(4)]})
    bpy.context.view_layer.update()
    scenes.add_key(body, "Big breasts", [(0, 0.01, 0)] * 8, 0.5)
    scenes.add_key(garment, "Big breasts", [(0, 0.02, 0)] * 4, 0.0)
    scenes.add_key(garment, "High heeled", [(0, 0, -0.043)] * 4, 1.0)
    bpy.context.view_layer.update()
    want = {"BodyMat": scenes.world_mix(body), "GarmentMat": scenes.world_mix(garment), "HairMat": scenes.world_mix(hair)}
    deltas = {"BodyMat": {"Big breasts": list(body.matrix_world.to_3x3() @ mathutils.Vector((0, 0.01, 0)))},
              "GarmentMat": {"Big breasts": list(garment.matrix_world.to_3x3() @ mathutils.Vector((0, 0.02, 0))),
                             "High heeled": list(garment.matrix_world.to_3x3() @ mathutils.Vector((0, 0, -0.043)))}}
    return want, deltas


def _run(params=PARAMS):
    return modpilot.call("vertex_groups", params, quiet=True)


def test_every_part_ships_as_it_looked_and_keeps_its_keys():
    want, deltas = _scene()
    r = _run()
    m = bpy.data.objects[r["data"]["merged"]]
    keys = m.data.shape_keys
    basis, mw = keys.reference_key.data, m.matrix_world
    assert all(k.value == 0 for k in keys.key_blocks[1:])
    for mat, expected in want.items():
        vs = scenes.material_vertices(m, mat)
        assert scenes.nearest_error(expected, [list(mw @ basis[i].co) for i in vs]) < 1e-5, mat
        for key, d in deltas.get(mat, {}).items():
            kb = keys.key_blocks[key]
            assert max(((mw.to_3x3() @ (kb.data[i].co - basis[i].co)) - mathutils.Vector(d)).length for i in vs) < 1e-5
    assert r["data"]["join_prep"]["baked_keys"]["Garment"] == {"High heeled": 1.0}


def test_uv_layers_match_by_position_and_colourless_parts_are_white():
    _scene()
    m = bpy.data.objects[_run()["data"]["merged"]]
    assert [u.name for u in m.data.uv_layers] == ["UV 맵", "UVMap"]
    uv0, ca = m.data.uv_layers[0].data, m.data.color_attributes[0]
    for mat, src in (("BodyMat", "Body"), ("GarmentMat", "Garment"), ("HairMat", "Hair")):
        vs = set(scenes.material_vertices(m, mat))
        loops = [li for p in m.data.polygons if p.vertices[0] in vs for li in p.loop_indices]
        got = sorted((round(uv0[li].uv[0], 4), round(uv0[li].uv[1], 4)) for li in loops)
        want = sorted((round(UVS[src][2 * i], 4), round(UVS[src][2 * i + 1], 4)) for i in range(len(UVS[src]) // 2))
        assert got == want, mat
        colour = COLOURS.get(src, (1.0, 1.0, 1.0, 1.0))
        assert all(max(abs(a - b) for a, b in zip(ca.data[li].color, colour, strict=True)) < 0.01 for li in loops), mat


def test_the_merged_mesh_hangs_on_the_mh_wilds_armature_in_place():
    want, _ = _scene()
    r = _run()
    m = bpy.data.objects[r["data"]["merged"]]
    tgt = bpy.data.objects["MHWilds_Female Armature"]
    assert m.parent is tgt and m.parent_type == "OBJECT"
    mods = [(md.type, md.object.name) for md in m.modifiers if md.type == "ARMATURE"]
    assert mods == [("ARMATURE", tgt.name)] and m.modifiers["Armature"].use_bone_envelopes is False
    assert m.name in bpy.data.collections["MHWilds_Female.mesh"].objects
    pts = [list(m.matrix_world @ v.co) for v in m.data.vertices]
    assert scenes.nearest_error([p for ps in want.values() for p in ps], pts) < 1e-5


def test_vertex_groups_get_the_mh_wilds_bone_names():
    _scene()
    m = bpy.data.objects[_run()["data"]["merged"]]
    names = {g.name for g in m.vertex_groups}
    assert "Hip" in names and "Hips" not in names


def test_the_reference_skeletons_own_meshes_are_deleted():
    _scene()
    col = bpy.data.collections["MHWilds_Female.mesh"]
    ref_meshes = {o.name for o in col.all_objects if o.type == "MESH"}
    assert ref_meshes
    r = _run()
    assert sorted(r["data"]["deleted_reference_meshes"]) == sorted(ref_meshes)
    assert {o.name for o in col.all_objects if o.type == "MESH"} == {r["data"]["merged"]}


def test_a_mesh_without_material_gets_a_placeholder_and_mmd_helper_groups_go():
    _scene()
    bpy.data.objects["Hair"].data.materials.clear()
    bpy.data.objects["Body"].vertex_groups.new(name="mmd_edge_scale")
    m = bpy.data.objects[_run({**PARAMS, "x_preset": "MMD"})["data"]["merged"]]
    assert "Hair_mat" in [s.material.name for s in m.material_slots]
    assert "mmd_edge_scale" not in m.vertex_groups


def test_missing_or_non_mesh_objects_are_a_precondition():
    _scene()
    with pytest.raises(StepError) as e:
        _run({**PARAMS, "mesh_objects": ["Body", "Nope", "Armature"]})
    assert e.value.category == "precondition"
    assert e.value.details == {"not_found": ["Nope"], "not_mesh": ["Armature"]}
