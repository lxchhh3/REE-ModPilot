"""The setup steps in real Blender (T1): import the source FBX (fixing what the pipeline can't
carry: bone-hung garments, MochiFitter helper bones), validate the scene, infer the source rig's
X-preset from the Modding-Toolkit's real preset folder, write a supplemented / custom preset,
import the MH Wilds reference skeleton (recording its names in the scene config)."""
import json
import math
import os
from pathlib import Path

import bpy
import mathutils
import pytest

import modpilot
from modpilot.bl import toolkit
from modpilot.core.config import load_config
from modpilot.core.errors import StepError
from modpilot.testing import scenes


def _call(step, params=None):
    return modpilot.call(step, params, quiet=True)


def _error(step, params=None):
    with pytest.raises(StepError) as e:
        _call(step, params)
    return e.value


# ── setup_import_source ───────────────────────────────────────────────────


def _avatar():
    arm = scenes.make_armature("Armature", [
        ("Hips", None, (0, 0, 0.9), (0, 0, 1.0)), ("Spine", "Hips", (0, 0, 1.0), (0, 0, 1.1)),
        ("Chest", "Spine", (0, 0, 1.1), (0, 0, 1.25)), ("Neck", "Chest", (0, 0, 1.4), (0, 0, 1.5)),
        ("Head", "Neck", (0, 0, 1.5), (0, 0, 1.7))])
    body = scenes.make_quads("Body", [[(-0.1, 0, 0.9), (0.1, 0, 0.9), (0.1, 0, 1.1), (-0.1, 0, 1.1)]], "BodyMat")
    scenes.skin(body, arm, {"Hips": [(i, 1.0) for i in range(4)]})
    return arm, body


def test_an_fbx_is_imported_and_its_armature_reported(tmp_path):
    _avatar()
    fbx = tmp_path / "avatar.fbx"
    bpy.ops.export_scene.fbx(filepath=str(fbx), add_leaf_bones=False)
    bpy.ops.wm.read_homefile(use_empty=True)
    r = _call("setup_import_source", {"file_path": str(fbx)})["data"]
    assert r["import_status"] == "imported" and r["source_armature"] == "Armature"
    assert set(r["imported_objects"]) == {"Armature", "Body"}
    assert r["source_fixes"] == {"rigid_to_skinned": {}, "mfbase_folded": {}, "mfbase_skipped": {}}
    assert load_config(bpy.context.scene).source_armature == "Armature"


def test_an_armature_already_in_the_scene_is_used_as_it_is():
    _avatar()
    r = _call("setup_import_source", {"file_path": "C:/no/such.fbx"})["data"]
    assert r == {"import_status": "already_imported", "source_armature": "Armature",
                 "source_fixes": {"rigid_to_skinned": {}, "mfbase_folded": {}, "mfbase_skipped": {}}}


@pytest.mark.parametrize("path,category", [("C:/model.blend", "params"), ("C:/no/such/model.fbx", "precondition"),
                                           ("", "params")])
def test_import_refusals(path, category):
    assert _error("setup_import_source", {"file_path": path}).category == category


def test_a_garment_hung_on_a_bone_becomes_skinned_to_it_in_place():
    arm, _ = _avatar()
    hs = scenes.make_quads("Headset", [[(0, 0, 0), (0.05, 0, 0), (0.05, 0, 0.05), (0, 0, 0.05)]], "HeadsetMat")
    hs.parent, hs.parent_type, hs.parent_bone = arm, "BONE", "Neck"
    hs.location = (0.02, 0.03, -0.01)
    hs.rotation_euler = (math.radians(20), 0, math.radians(15))
    bpy.context.view_layer.update()
    before = scenes.world_mix(hs)
    fixes = _call("setup_import_source", {"file_path": "x.fbx"})["data"]["source_fixes"]
    assert fixes["rigid_to_skinned"] == {"Headset": "Neck"}
    assert (hs.parent_type, hs.parent_bone) == ("OBJECT", "")
    assert [g.name for g in hs.vertex_groups] == ["Neck"]
    assert scenes.nearest_error(before, scenes.world_mix(hs)) < 1e-6
    pb = arm.pose.bones["Neck"]
    pb.rotation_mode = "XYZ"
    pb.rotation_euler = (math.radians(30), 0, 0)
    bpy.context.view_layer.update()
    deform = arm.matrix_world @ pb.matrix @ arm.data.bones["Neck"].matrix_local.inverted() @ arm.matrix_world.inverted()
    assert scenes.nearest_error([list(deform @ mathutils.Vector(p)) for p in before], scenes.world_mix(hs)) < 1e-5


def test_mochifitter_helper_bones_fold_into_the_bones_they_copy():
    arm, _ = _avatar()
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    for name, parent, head, tail in [("breast_L", "Chest", (0.05, -0.05, 1.2), (0.05, -0.12, 1.2)),
                                     ("breast_L_MFBase", "Chest", (0.05, -0.05, 1.2), (0.05, -0.1, 1.21)),
                                     ("breast_L_MFBase_end", "breast_L_MFBase", (0.05, -0.1, 1.21), (0.05, -0.12, 1.21)),
                                     ("Ribbon_L", "breast_L_MFBase", (0.05, -0.1, 1.15), (0.05, -0.1, 1.05)),
                                     ("Far_MFBase", "Chest", (0.3, 0, 1.2), (0.3, 0, 1.3))]:
        b = eb.new(name)
        b.head, b.tail, b.parent = head, tail, eb[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    top = scenes.make_quads("Top", [[(0, -0.06, 1.15), (0.1, -0.06, 1.15), (0.1, -0.06, 1.25), (0, -0.06, 1.25)]], "TopMat")
    scenes.skin(top, arm, {"breast_L_MFBase": [(0, 0.6), (1, 0.6)], "Chest": [(0, 0.3), (1, 0.4), (2, 1.0), (3, 1.0)],
                           "breast_L": [(0, 0.1)]})
    fixes = _call("setup_import_source", {"file_path": "x.fbx"})["data"]["source_fixes"]
    assert fixes["mfbase_folded"] == {"breast_L_MFBase": "breast_L"}
    assert fixes["mfbase_skipped"] == {"Far_MFBase": "no bone Far"}
    bones = arm.data.bones
    assert "breast_L_MFBase" not in bones and "breast_L_MFBase_end" not in bones
    assert bones["Ribbon_L"].parent.name == "breast_L"
    w = {v.index: g.weight for v in top.data.vertices for g in v.groups if top.vertex_groups[g.group].name == "breast_L"}
    assert {k: round(x, 5) for k, x in w.items()} == {0: 0.7, 1: 0.6}


# ── setup_validate_scene ──────────────────────────────────────────────────


def test_one_armature_with_its_meshes_is_valid():
    _avatar()
    r = _call("setup_validate_scene")["data"]
    assert r == {"valid": True, "errors": [], "source_armature": "Armature", "child_meshes": ["Body"],
                 "mhwilds_imported": False}


@pytest.mark.parametrize("problem", ["stray_empty", "unparented_mesh", "two_armatures", "no_armature"])
def test_an_invalid_layout_fails_with_every_problem_named(problem):
    if problem != "no_armature":
        _avatar()
    if problem == "stray_empty":
        bpy.context.scene.collection.objects.link(bpy.data.objects.new("Stray", None))
    elif problem == "unparented_mesh":
        scenes.make_quads("Loose", [[(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]], "LooseMat")
    elif problem == "two_armatures":
        scenes.make_armature("Other", [("Root", None, (0, 0, 0), (0, 0, 1))])
    e = _error("setup_validate_scene")
    assert e.category == "precondition" and e.details["errors"]
    assert e.message.startswith("Scene validation failed: ")


# ── setup_infer_model_type ────────────────────────────────────────────────


def _vrchat_rig():
    preset = json.loads((toolkit.preset_dir() / "VRChat.json").read_text(encoding="utf-8"))
    names = []
    for slot in preset["mappings"].values():
        main = [c for c in slot.get("main") or [] if isinstance(c, str)]
        if main and main[0] not in names:
            names.append(main[0])
    return scenes.make_armature("Armature", [(n, None, (i * 0.01, 0, 0), (i * 0.01, 0, 0.1)) for i, n in enumerate(names)])


def test_a_vrchat_rig_is_inferred_as_vrchat():
    _vrchat_rig()
    r = _call("setup_infer_model_type", {"source_armature": "Armature"})["data"]
    assert (r["inferred_preset"], r["decision"]) == ("VRChat", "exact") and r["coverage"] == 1.0
    assert r["candidates"][0] == {"preset": "VRChat", "coverage": 1.0}
    assert Path(r["preset_path"]).name == "VRChat.json"


def test_the_source_armature_comes_from_the_config_when_not_given():
    _vrchat_rig()
    modpilot.call("setup_import_source", {"file_path": "x.fbx"}, quiet=True)
    assert _call("setup_infer_model_type")["data"]["inferred_preset"] == "VRChat"


def test_a_forced_preset_skips_inference_and_force_custom_wins_over_it():
    _vrchat_rig()
    r = _call("setup_infer_model_type", {"source_armature": "Armature", "forced_preset": "MMD"})["data"]
    assert (r["inferred_preset"], r["decision"]) == ("MMD", "user_specified")
    r = _call("setup_infer_model_type", {"source_armature": "Armature", "forced_preset": "MMD",
                                         "force_custom": True})["data"]
    assert r["decision"] == "custom"


def test_an_unknown_forced_preset_fails_instead_of_inferring():
    _vrchat_rig()
    e = _error("setup_infer_model_type", {"source_armature": "Armature", "forced_preset": "NoSuchPreset"})
    assert e.category == "params" and "VRChat" in e.details["known"]


def test_a_rig_no_preset_matches_is_unsupported():
    scenes.make_armature("Armature", [("zzq_1", None, (0, 0, 0), (0, 0, 1))])
    e = _error("setup_infer_model_type", {"source_armature": "Armature"})
    assert e.category == "precondition" and e.details["legacy_category"] == "unsupported_rig"
    assert e.details["result"]["decision"] == "unsupported"


def test_a_missing_armature_is_a_precondition():
    assert _error("setup_infer_model_type", {"source_armature": "Nope"}).category == "precondition"


# ── preset writers (into this session's copy of the Toolkit) ───────────────


def test_a_supplemented_preset_lands_in_the_toolkit_and_is_inferred_next():
    out = _call("setup_preset_supplement_write", {"base_preset_name": "VRChat",
                                                  "mappings": {"head": "Kopf"}})["data"]
    path = Path(out["new_preset_path"])
    try:
        assert path.parent == toolkit.preset_dir() and out["new_preset_name"] == "VRChat_extended"
        scenes.make_armature("Armature", [("Kopf", None, (0, 0, 0), (0, 0, 1))])
        names = [c["preset"] for c in _call("setup_infer_model_type", {"source_armature": "Armature"})["data"]["candidates"]]
        assert "VRChat_extended" in names
    finally:
        os.remove(path)


def test_a_custom_preset_lands_in_the_toolkit():
    out = _call("setup_preset_custom_write", {"character_name": "Probe", "mappings": {"pelvis": "Root"}})["data"]
    path = Path(out["new_preset_path"])
    try:
        assert path.parent == toolkit.preset_dir() and out["slot_count"] == 1
        assert json.loads(path.read_text(encoding="utf-8"))["mappings"] == {"pelvis": {"main": ["Root"], "aux": []}}
    finally:
        os.remove(path)


# ── setup_import_mhwilds ──────────────────────────────────────────────────


def test_the_reference_skeleton_is_imported_and_its_names_recorded():
    r = _call("setup_import_mhwilds", {"convert_to_tpose": True, "merge_facial_bones": True})
    d = r["data"]
    assert d["import_status"] == "imported"
    arm = bpy.data.objects[d["mhwilds_armature"]]
    assert arm.type == "ARMATURE" and arm.name in bpy.data.collections[d["mhwilds_collection"]].all_objects
    cfg = load_config(bpy.context.scene)
    assert (cfg.target_armature, cfg.mesh_collection) == (d["mhwilds_armature"], d["mhwilds_collection"])
    assert d["mhwilds_armature"] in r["scene_diff"]["objects_added"]
    again = _call("setup_import_mhwilds")["data"]
    assert again["import_status"] == "already_imported" and again["mhwilds_armature"] == d["mhwilds_armature"]
