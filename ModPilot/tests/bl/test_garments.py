"""The garment steps in real Blender (T1), from the agent scripts the GG and Marette ModPilot runs used between
ModPilot calls (Known_Good_mod_test/scripts/gg: mute_keys.py, rigid_to_weights.py, restore_ends.py):
mute_shape_keys, rebind_rigid_garments (kevin 2026-10-16: the headset onto her upper spine, or Chest when the rig
has no UpperChest) and restore_leaf_bones (the chain leaves RigForge's zero-weight sweep dropped)."""
import bpy
import pytest
from mathutils import Matrix, Vector

import modpilot
from modpilot.core.errors import StepError
from modpilot.testing import scenes


def _call(step, params=None):
    return modpilot.call(step, params, quiet=True)


def _rig(upper_chest=False, rigid=True):
    """Armature Hips > Spine > Chest [> UpperChest] > Neck, a skinned Body and a GG_headset on Neck."""
    bones = [("Hips", None, (0, 0, 0.80), (0, 0, 0.83)), ("Spine", "Hips", (0, 0, 0.83), (0, 0, 0.90)),
             ("Chest", "Spine", (0, 0, 0.90), (0, 0, 0.98))]
    top = "Chest"
    if upper_chest:
        bones.append(("UpperChest", "Chest", (0, 0, 0.98), (0, 0, 1.06)))
        top = "UpperChest"
    bones.append(("Neck", top, (0, 0, 1.06), (0, 0, 1.12)))
    arm = scenes.make_armature("Armature", bones)
    arm.matrix_world = Matrix.Rotation(0.3, 4, "Z") @ Matrix.Translation((0.1, -0.2, 0.0))
    body = scenes.make_quads("Body", [[(-0.1, 0, 0.8), (0.1, 0, 0.8), (0.1, 0, 1.0), (-0.1, 0, 1.0)]], "BodyMat")
    scenes.skin(body, arm, {"Hips": [(i, 1.0) for i in range(4)]})
    hs = scenes.make_quads("GG_headset", [[(-0.05, 0.02, 1.08), (0.05, 0.02, 1.08), (0.05, 0.02, 1.12),
                                           (-0.05, 0.02, 1.12)]], "HeadsetMat")
    bpy.context.view_layer.update()
    world = [hs.matrix_world @ v.co for v in hs.data.vertices]
    hs.parent, hs.parent_type, hs.parent_bone = arm, "BONE", "Neck"
    hs.matrix_world = Matrix.Identity(4)
    bpy.context.view_layer.update()
    inv = hs.matrix_world.inverted()
    for v, w in zip(hs.data.vertices, world, strict=True):
        v.co = inv @ w
    bpy.context.view_layer.update()
    if not rigid:
        from modpilot.bl import source
        source.rigid_to_skinned(arm)
    return arm, hs


def _world(obj):
    bpy.context.view_layer.update()
    return [obj.matrix_world @ v.co for v in obj.data.vertices]


def _groups(obj):
    names = {g.index: g.name for g in obj.vertex_groups}
    out = {}
    for v in obj.data.vertices:
        for g in v.groups:
            out.setdefault(names[g.group], []).append(round(g.weight, 6))
    return out


# ── mute_shape_keys ───────────────────────────────────────────────────────


def test_every_key_but_the_basis_is_muted():
    _, hs = _rig()
    body = bpy.data.objects["Body"]
    for o in (hs, body):
        scenes.add_key(o, "A", [(0, 0, 0.01)] * 4, 0.5)
        scenes.add_key(o, "B", [(0, 0.01, 0)] * 4, 1.0)
    assert _call("mute_shape_keys")["data"] == {"muted": 4}
    for o in (hs, body):
        kb = o.data.shape_keys.key_blocks
        assert not kb[0].mute and all(k.mute for k in kb[1:])


def test_mute_can_be_limited_to_named_objects():
    _, hs = _rig()
    body = bpy.data.objects["Body"]
    for o in (hs, body):
        scenes.add_key(o, "A", [(0, 0, 0.01)] * 4, 0.5)
    assert _call("mute_shape_keys", {"objects": ["GG_headset"]})["data"] == {"muted": 1}
    assert not body.data.shape_keys.key_blocks["A"].mute
    with pytest.raises(StepError) as e:
        _call("mute_shape_keys", {"objects": ["Nope"]})
    assert e.value.category == "precondition"


# ── rebind_rigid_garments ─────────────────────────────────────────────────


@pytest.mark.parametrize("upper_chest, rigid, want", [(False, True, "Chest"), (True, True, "UpperChest"),
                                                      (False, False, "Chest"), (True, False, "UpperChest")])
def test_a_rigid_headset_ends_on_the_upper_spine_where_it_hung(upper_chest, rigid, want):
    arm, hs = _rig(upper_chest, rigid)
    before = _world(hs)
    r = _call("rebind_rigid_garments", {"prefix": "GG_", "armature": "Armature", "bones": ["UpperChest", "Chest"]})
    assert r["data"]["rebound"]["GG_headset"]["bone"] == want
    assert r["data"]["rebound"]["GG_headset"]["from"] == "Neck"
    assert _groups(hs) == {want: [1.0] * 4}
    assert hs.parent is arm and hs.parent_type == "OBJECT"
    assert [m.object for m in hs.modifiers if m.type == "ARMATURE"] == [arm]
    assert max((a - b).length for a, b in zip(before, _world(hs), strict=True)) < 1e-6


def test_a_garment_on_several_bones_is_left_alone_and_reported():
    arm, _ = _rig(rigid=False)
    other = scenes.make_quads("GG_skirt", [[(0, 0, 0.7), (0.1, 0, 0.7), (0.1, 0, 0.8), (0, 0, 0.8)]], "SkirtMat")
    scenes.skin(other, arm, {"Hips": [(0, 1.0), (1, 1.0)], "Spine": [(2, 1.0), (3, 1.0)]})
    r = _call("rebind_rigid_garments", {"prefix": "GG_", "armature": "Armature", "bones": ["Chest"]})
    assert "GG_skirt" not in r["data"]["rebound"] and _groups(other) == {"Hips": [1.0, 1.0], "Spine": [1.0, 1.0]}


def test_no_candidate_bone_changes_nothing():
    _, hs = _rig()
    with pytest.raises(StepError) as e:
        _call("rebind_rigid_garments", {"prefix": "GG_", "armature": "Armature", "bones": ["UpperChest"]})
    assert e.value.category == "precondition" and "UpperChest" in str(e.value)
    assert hs.parent_type == "BONE" and not hs.vertex_groups


# ── restore_leaf_bones ────────────────────────────────────────────────────


def _original_fbx(tmp_path):
    """The rig with GG chain leaves, exported as the original FBX; the scene's copy then loses the leaves the
    way RigForge's zero-weight sweep dropped them."""
    arm, _ = _rig(rigid=False)
    with scenes_edit(arm) as eb:
        for name, parent, head, tail in (("GG_Ribbon_L", "Neck", (0.05, 0.05, 1.10), (0.05, 0.10, 1.05)),
                                         ("GG_Ribbon_L.001", "GG_Ribbon_L", (0.05, 0.10, 1.05), (0.05, 0.14, 1.00)),
                                         ("GG_Ribbon_L.002", "GG_Ribbon_L.001", (0.05, 0.14, 1.00), (0.05, 0.17, 0.96))):
            b = eb.new(name)
            b.head, b.tail, b.parent = Vector(head), Vector(tail), eb[parent]
    path = tmp_path / "orig.fbx"
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, add_leaf_bones=False)
    with scenes_edit(arm) as eb:
        eb.remove(eb["GG_Ribbon_L.002"])
    return arm, path


class scenes_edit:
    def __init__(self, arm):
        self.arm = arm

    def __enter__(self):
        from modpilot.bl import context
        context.select_only([self.arm], active=self.arm)
        bpy.ops.object.mode_set(mode="EDIT")
        return self.arm.data.edit_bones

    def __exit__(self, *exc):
        bpy.ops.object.mode_set(mode="OBJECT")


def test_a_dropped_leaf_comes_back_as_its_parents_end_bone(tmp_path):
    arm, fbx = _original_fbx(tmp_path)
    objects = {o.name for o in bpy.data.objects}
    r = _call("restore_leaf_bones", {"orig_fbx": str(fbx), "armature": "Armature", "prefix": "GG_"})["data"]
    assert r["added"] == {"GG_Ribbon_L.001_End": "GG_Ribbon_L.002"}
    end = arm.data.bones["GG_Ribbon_L.001_End"]
    assert end.parent.name == "GG_Ribbon_L.001"
    want = arm.matrix_world @ Vector((0.05, 0.14, 1.00))
    assert ((arm.matrix_world @ end.head_local) - want).length < 1e-4
    assert {o.name for o in bpy.data.objects} == objects            # the extra import is gone
    again = _call("restore_leaf_bones", {"orig_fbx": str(fbx), "armature": "Armature", "prefix": "GG_"})["data"]
    assert again["added"] == {} and again["already_present"] == {"GG_Ribbon_L.001_End": "GG_Ribbon_L.002"}


def test_an_original_that_does_not_line_up_is_refused(tmp_path):
    arm, fbx = _original_fbx(tmp_path)
    arm.location.x += 0.01
    objects = {o.name for o in bpy.data.objects}
    with pytest.raises(StepError) as e:
        _call("restore_leaf_bones", {"orig_fbx": str(fbx), "armature": "Armature", "prefix": "GG_"})
    assert e.value.category == "precondition"
    assert "GG_Ribbon_L.001_End" not in arm.data.bones and {o.name for o in bpy.data.objects} == objects


def test_a_missing_fbx_is_a_precondition(tmp_path):
    _rig()
    with pytest.raises(StepError) as e:
        _call("restore_leaf_bones", {"orig_fbx": str(tmp_path / "nope.fbx"), "armature": "Armature", "prefix": "GG_"})
    assert e.value.category == "precondition"
