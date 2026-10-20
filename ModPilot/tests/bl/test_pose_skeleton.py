"""pose_correction and skeleton_align in real Blender (T1), against the real MH Wilds reference
skeleton (setup_import_mhwilds) and a source rig named from the Toolkit's real VRChat preset.

pose_correction: clear the source pose, scale the source so its arm bones' mean height matches the
target's (issue #13), shift it in Y onto the target's arm plane, then the preset's T-pose
conversion (VRChat none, MMD mmd_a_to_tpose, arknights the Endfield record; any other preset only
with an explicit pose_conversion: the legacy tool applied the Endfield pose to all of them)."""
import json
import math

import bpy
import pytest

import modpilot
from modpilot.bl import toolkit
from modpilot.core.errors import StepError
from modpilot.testing import scenes

ARM_SLOTS = ("upperarm_L", "forearm_L", "hand_L", "upperarm_R", "forearm_R", "hand_R")


def _call(step, params=None):
    return modpilot.call(step, params, quiet=True)


def _names(preset_name):
    preset = json.loads((toolkit.preset_dir() / f"{preset_name}.json").read_text(encoding="utf-8"))
    return {slot: preset["mappings"][slot]["main"][0] for slot in ("pelvis", *ARM_SLOTS)}


def _vrchat_names():
    return _names("VRChat")


def _source(arm_z=0.7, y=0.3, names=None):
    """A small rig named from a Toolkit preset (VRChat unless `names`): hips plus both arms at
    height `arm_z`, shifted `y` in Y."""
    n = names or _vrchat_names()
    bones = [(n["pelvis"], None, (0, y, arm_z * 0.6), (0, y, arm_z * 0.7))]
    for side, sx in (("L", 1), ("R", -1)):
        prev = n["pelvis"]
        for i, slot in enumerate((f"upperarm_{side}", f"forearm_{side}", f"hand_{side}")):
            x0, x1 = sx * (0.1 + 0.15 * i), sx * (0.25 + 0.15 * i)
            bones.append((n[slot], prev, (x0, y, arm_z), (x1, y, arm_z)))
            prev = n[slot]
    arm = scenes.make_armature("Armature", bones)
    body = scenes.make_quads("Body", [[(-0.1, y, 0.1), (0.1, y, 0.1), (0.1, y, arm_z), (-0.1, y, arm_z)]], "BodyMat")
    scenes.skin(body, arm, {n["pelvis"]: [(i, 1.0) for i in range(4)]})
    return arm, n


def _mean(arm, names, axis):
    vals = [(arm.matrix_world @ arm.pose.bones[nm].head)[axis] for nm in names if nm in arm.pose.bones]
    return sum(vals) / len(vals)


@pytest.fixture
def target():
    _call("setup_import_mhwilds")
    return bpy.data.objects["MHWilds_Female Armature"]


def test_the_source_is_scaled_and_shifted_onto_the_target_arms(target):
    src, n = _source(arm_z=0.7, y=0.3)
    mh = _names("mhws")                          # the reference skeleton's own bone names
    tgt_names = [mh[s] for s in ARM_SLOTS]
    want_z, want_y = _mean(target, tgt_names, 2), _mean(target, tgt_names, 1)
    r = _call("pose_correction", {"x_preset": "VRChat", "source_armature": "Armature"})["data"]
    bpy.context.view_layer.update()
    names = [n[s] for s in ARM_SLOTS]
    assert r["scale"]["ratio"] == pytest.approx(want_z / 0.7, rel=1e-3)
    assert _mean(src, names, 2) == pytest.approx(want_z, abs=1e-4)
    assert _mean(src, names, 1) == pytest.approx(want_y, abs=1e-4)
    assert tuple(src.scale) == pytest.approx((1, 1, 1)) and tuple(src.location) == pytest.approx((0, 0, 0))
    assert r["pose_conversion"] == "none" and r["y_shift"]["dy"] == pytest.approx(want_y - 0.3 * r["scale"]["ratio"], abs=1e-4)


def test_the_source_pose_is_cleared_first(target):
    src, n = _source()
    pb = src.pose.bones[n["forearm_L"]]
    pb.rotation_mode = "XYZ"
    pb.rotation_euler = (0, 0, math.radians(40))
    _call("pose_correction", {"x_preset": "VRChat", "source_armature": "Armature", "skip_scale_align": True})
    assert tuple(pb.rotation_euler) == pytest.approx((0, 0, 0))


def test_skip_scale_align_leaves_the_size_alone(target):
    src, n = _source(arm_z=0.7)
    r = _call("pose_correction", {"x_preset": "VRChat", "source_armature": "Armature", "skip_scale_align": True})
    assert r["data"]["scale"] is None
    assert _mean(src, [n[s] for s in ARM_SLOTS], 2) == pytest.approx(0.7, abs=1e-6)


def test_names_come_from_the_scene_config(target):
    _source()
    modpilot.call("setup_import_source", {"file_path": "x.fbx"}, quiet=True)
    modpilot.call("setup_infer_model_type", {"forced_preset": "VRChat"}, quiet=True)
    assert _call("pose_correction")["data"]["pose_conversion"] == "none"


def test_a_preset_with_no_known_conversion_needs_one_named(target):
    _source()
    with pytest.raises(StepError) as e:
        _call("pose_correction", {"x_preset": "vrm", "source_armature": "Armature", "skip_scale_align": True})
    assert e.value.category == "params" and "pose_conversion" in e.value.message
    r = _call("pose_correction", {"x_preset": "vrm", "source_armature": "Armature", "skip_scale_align": True,
                                  "pose_conversion": "none"})
    assert r["data"]["pose_conversion"] == "none"


def test_too_few_arm_bones_is_a_precondition(target):
    scenes.make_armature("Armature", [("Root", None, (0, 0, 0), (0, 0, 1))])
    with pytest.raises(StepError) as e:
        _call("pose_correction", {"x_preset": "VRChat", "source_armature": "Armature"})
    assert e.value.category == "precondition" and "source" in e.value.message


def test_an_unknown_preset_is_a_params_error(target):
    _source()
    with pytest.raises(StepError) as e:
        _call("pose_correction", {"x_preset": "NoSuch", "source_armature": "Armature"})
    assert e.value.category == "params"


# ── skeleton_align ────────────────────────────────────────────────────────


def test_skeleton_align_snaps_and_reports_what_it_unhid(target):
    src, n = _source()
    src.hide_set(True)
    r = _call("skeleton_align", {"x_preset": "VRChat", "source_armature": "Armature"})
    assert r["ok"] and "Armature:hide_get" in r["data"]["unhidden"]
    assert any("unhid" in w for w in r["warnings"])


def test_skeleton_align_needs_both_armatures(target):
    with pytest.raises(StepError) as e:
        _call("skeleton_align", {"x_preset": "VRChat", "source_armature": "Nope"})
    assert e.value.category == "precondition"


# Found 2026-10-20 (M6 test mapping): both Toolkit conversions end in core/pose_ops._apply_and_rebind,
# whose bpy.ops.object.select_grouped poll fails in headless Blender 5.2, even with the Layout 3D View
# lent through temp_override. No landed build was MMD or Endfield (all VRChat); the legacy unit tests
# only checked the generated code named the operator. Strict: passes once the conversion runs.
CONVERSION_BROKEN = pytest.mark.xfail(strict=True, reason="Toolkit pose conversion: select_grouped poll fails headless")


@pytest.mark.parametrize("preset, conversion, enums", [
    pytest.param("MMD", "mmd_a_to_tpose", {"pose_import_preset_enum": "MMD.json"}, marks=CONVERSION_BROKEN),
    pytest.param("arknights", "endfield", {"pose_import_preset_enum": "arknights.json",
                                           "pose_preset_enum": "终末地 A转Tpose.json"}, marks=CONVERSION_BROKEN),
])
def test_mmd_and_endfield_rigs_get_their_t_pose_conversion(target, preset, conversion, enums):
    # the Toolkit's own operator runs (modder.mmd_a_to_tpose / apply_transform_forward) on a rig named
    # from that preset, with the pose presets the Toolkit's panel would set
    _source(names=_names(preset))
    r = _call("pose_correction", {"x_preset": preset, "source_armature": "Armature", "skip_scale_align": True})
    assert r["data"]["pose_conversion"] == conversion
    settings = bpy.context.scene.mhw_suite_settings
    assert {k: getattr(settings, k) for k in enums} == enums
