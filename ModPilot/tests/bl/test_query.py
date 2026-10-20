"""The read-only query steps in real Blender (T1): the legacy query tools' answers as data, failing
on a name that isn't there instead of answering {"error": ...} (the bridged legacy tool still
answers that way), and never changing the scene."""
import bpy
import pytest

import modpilot
from modpilot.core.errors import StepError
from modpilot.testing import scenes
from modpilot.testing.materials import node_material, png
from modpilot.testing.rigs import TYPES, chains, grafted, groups, transplant


def _q(step, params=None):
    r = modpilot.call(step, params, quiet=True)
    assert r["scene_diff"] == {}, step
    return r["data"]


def _scene():
    arm = scenes.make_armature("Rig", [("Hips", None, (0, 0, 0.9), (0, 0, 1.0)), ("Tail", "Hips", (0, 0.1, 0.9), (0, 0.2, 0.8))])
    arm.pose.bones["Tail"]["chain_role"] = "head"
    body = scenes.make_quads("Body", [[(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]], "BodyMat")
    scenes.skin(body, arm, {"Hips": [(0, 1.0)], "Tail": [(1, 1.0)]})
    body.data.uv_layers.new(name="UVMap")
    body["note"] = "hello"
    col = bpy.data.collections.new("Thing.chain2")
    col["~TYPE"] = "RE_CHAIN_COLLECTION"
    bpy.context.scene.collection.children.link(col)
    return arm, body


def test_scene_info_lists_every_object_not_the_first_ten():
    for i in range(12):
        scenes.make_quads(f"Q{i:02d}", [[(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]], "M")
    d = _q("scene_info")
    assert d["object_count"] == 12 and len(d["objects"]) == 12
    assert d["name"] == bpy.context.scene.name and d["materials_count"] == len(bpy.data.materials)
    assert set(d["objects"][0]) == {"name", "type", "location"}


def test_get_bone_info_with_and_without_a_filter():
    _scene()
    d = _q("get_bone_info", {"armature_name": "Rig"})
    assert (d["total_bones"], d["returned_bones"]) == (2, 2)
    assert {b["name"]: b["parent"] for b in d["bones"]} == {"Hips": None, "Tail": "Hips"}
    d = _q("get_bone_info", {"armature_name": "Rig", "filter_custom_prop": "chain_role"})
    assert d["bones"] == [{"name": "Tail", "parent": "Hips", "custom_props": {"chain_role": "head"}}]


def test_list_collections_and_the_chain_filter():
    _scene()
    all_ = {c["name"]: c for c in _q("list_collections")["collections"]}
    assert all_["Thing.chain2"]["custom_props"] == {"~TYPE": "RE_CHAIN_COLLECTION"}
    assert [c["name"] for c in _q("list_collections", {"chain_only": True})["collections"]] == ["Thing.chain2"]


def test_get_mesh_info():
    _scene()
    d = _q("get_mesh_info", {"mesh_name": "Body", "max_vgroups": 1})
    assert d == {"mesh": "Body", "parent_armature": "Rig", "vertex_count": 4, "vertex_group_count": 2,
                 "vertex_groups": ["Hips"], "material_slots": ["BodyMat"], "uv_layers": ["UVMap"]}


def test_get_material_info_reports_the_output_shader_and_textures(tmp_path):
    _scene()
    mat = node_material("BodyMat")
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(png(tmp_path / "t.png", (1, 0, 0, 1)))
    slot = _q("get_material_info", {"mesh_name": "Body"})["material_slots"][0]
    assert (slot["material_name"], slot["use_nodes"], slot["shader_type"]) == ("BodyMat", True, "Principled BSDF")
    assert slot["textures"][0]["image"] == "t.png" and slot["textures"][0]["has_data"] in (True, False)


def test_get_object_props():
    _scene()[1]["_internal"] = 1          # "_" keys are left out, as the legacy query did
    assert _q("get_object_props", {"object_name": "Body"}) == {"object": "Body", "type": "MESH",
                                                                "custom_props": {"note": "hello"}}


def test_inspect_material_nodes(tmp_path):
    mat = node_material("Shader")
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(png(tmp_path / "t.png", (1, 0, 0, 1)))
    d = _q("inspect_material_nodes", {"material_name": "Shader"})
    assert d["output_shader"]["type"] == "BSDF_PRINCIPLED"
    orphan = [n for n in d["orphan_nodes"] if n["type"] == "TEX_IMAGE"]
    assert orphan and orphan[0]["image"] == {"path": str(tmp_path / "t.png"), "exists": True}
    assert d["node_count"] == len(d["nodes"]) and d["links"]


def test_physics_read_all_and_selected():
    grafted()
    transplant()
    chains({"inferred_types": TYPES})
    cs = groups()["Tail"].parent.name
    every = _q("physics_read")["chain_settings"]
    assert cs in {e["name"] for e in every}
    one = _q("physics_read", {"targets": [cs], "properties": ["damping", "gravity"]})["chain_settings"]
    assert one[0]["name"] == cs and set(one[0]["values"]) == {"damping", "gravity"}
    assert len(one[0]["values"]["gravity"]) == 3


def test_list_mdf_presets():
    presets = _q("list_mdf_presets")["presets"]
    assert {"Character", "Skin", "Hair"} <= set(presets)


@pytest.mark.parametrize("step, params, category", [
    ("get_bone_info", {"armature_name": "Nope"}, "precondition"),
    ("get_mesh_info", {"mesh_name": "Rig"}, "precondition"),
    ("get_material_info", {"mesh_name": "Nope"}, "precondition"),
    ("get_object_props", {"object_name": "Nope"}, "precondition"),
    ("inspect_material_nodes", {"material_name": "Nope"}, "precondition"),
    ("physics_read", {"targets": ["Body"]}, "precondition"),
    ("physics_read", {"properties": ["dampnig"]}, "params"),
])
def test_a_name_that_is_not_there_fails(step, params, category):
    _scene()
    with pytest.raises(StepError) as e:
        modpilot.call(step, params, quiet=True)
    assert e.value.category == category
