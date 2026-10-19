"""M1's three steps, in real headless Blender (T1).

doctor            what this Blender has: version, add-ons, operator namespaces, modpilot code
list_objects      the legacy query tool's output, as data
scene_fingerprint a stable digest of the scene, the yardstick of M2's differential tests
                  (legacy tool vs new step on the same checkpoint)
"""
import bpy
import pytest

import modpilot
from modpilot.core.errors import StepError
from modpilot.testing import scenes


def test_doctor_lists_the_pinned_add_ons_operator_namespaces():
    d = modpilot.call("doctor", quiet=True)["data"]
    assert d["blender"] == bpy.app.version_string and d["background"] is True
    for ns in ("modder", "mhws", "mbt", "re_mesh", "re_chain", "re_clsp"):
        assert d["namespaces"][ns] > 0, (ns, d["namespaces"])
    assert "doctor" in d["steps"] and d["modpilot"]["sha"]


def test_doctor_fails_when_a_required_namespace_is_missing():
    with pytest.raises(StepError) as e:
        modpilot.call("doctor", {"require": ["re_chain", "no_such_ns"]}, quiet=True)
    assert e.value.category == "environment" and e.value.details["missing"] == ["no_such_ns"]


def test_list_objects_reports_what_the_legacy_query_reported():
    arm = scenes.make_armature("Armature", [("Hips", None, (0, 0, 0.9), (0, 0, 1.0))])
    body = scenes.make_quads("Body", [[(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]], "BodyMat")
    body.hide_set(True)
    objs = modpilot.call("list_objects", quiet=True)["data"]["objects"]
    assert {o["name"]: o for o in objs} == {
        "Armature": {"name": "Armature", "type": "ARMATURE", "visible": True, "hide_viewport": False, "hide_get": False},
        "Body": {"name": "Body", "type": "MESH", "visible": False, "hide_viewport": False, "hide_get": True},
    }
    only = modpilot.call("list_objects", {"type_filter": "armature"}, quiet=True)["data"]["objects"]
    assert [o["name"] for o in only] == ["Armature"]
    assert arm.name == "Armature"


def _two_part_scene():
    arm = scenes.make_armature("Armature", [("Hips", None, (0, 0, 0.9), (0, 0, 1.0)),
                                            ("Spine", "Hips", (0, 0, 1.0), (0, 0, 1.1))])
    body = scenes.make_quads("Body", [[(-0.1, 0, 0.9), (0.1, 0, 0.9), (0.1, 0, 1.1), (-0.1, 0, 1.1)]], "BodyMat")
    scenes.skin(body, arm, {"Hips": [(0, 1.0), (1, 1.0)], "Spine": [(2, 1.0), (3, 0.5)]})
    scenes.add_key(body, "Big", [(0, 0.01, 0)] * 4, 0.5)
    return arm, body


def test_the_same_scene_gives_the_same_fingerprint():
    _two_part_scene()
    a = modpilot.call("scene_fingerprint", quiet=True)["data"]
    bpy.ops.wm.read_homefile(use_empty=True)
    _two_part_scene()
    b = modpilot.call("scene_fingerprint", quiet=True)["data"]
    assert a["digest"] == b["digest"] and a["sections"] == b["sections"]


@pytest.mark.parametrize("change", ["bone", "weight", "key", "uv_name", "material"])
def test_a_change_the_pipeline_cares_about_changes_the_fingerprint(change):
    arm, body = _two_part_scene()
    before = modpilot.call("scene_fingerprint", quiet=True)["data"]
    if change == "bone":
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode="EDIT")
        arm.data.edit_bones["Spine"].tail.z += 0.01
        bpy.ops.object.mode_set(mode="OBJECT")
    elif change == "weight":
        body.vertex_groups["Spine"].add([3], 0.75, "REPLACE")
    elif change == "key":
        body.data.shape_keys.key_blocks["Big"].data[0].co.y += 0.001
    elif change == "uv_name":
        body.data.uv_layers.new(name="UVMap2")
    elif change == "material":
        body.data.materials.append(bpy.data.materials.new("Other"))
    after = modpilot.call("scene_fingerprint", quiet=True)["data"]
    assert after["digest"] != before["digest"]
    changed = [k for k in before["sections"] if before["sections"][k] != after["sections"][k]]
    assert changed, change


def test_the_fingerprint_does_not_change_the_scene():
    _two_part_scene()
    r = modpilot.call("scene_fingerprint", quiet=True)
    assert r["scene_diff"] == {}
