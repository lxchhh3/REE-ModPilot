"""The material steps in real Blender (T1): material_setup wires textures into each material's
Principled BSDF (VRChat normals through a 1-Y chain, Endfield's directly; emission into 'Emission
Color' with its strength turned on), checking the whole mapping before it changes anything;
material_generate runs the Toolkit's MDF2 generator with the agreed presets and fails on any
material the generator could not make (the generator itself only prints them); material_inspect
reads what is wired where; material_consolidate groups materials by the textures they use and merges
the groups it is given."""
import json
import os
import sys
from pathlib import Path

import bpy
import pytest

import modpilot
from modpilot.core.errors import StepError
from modpilot.testing.materials import node_material, textured_avatar


def _call(step, params):
    return modpilot.call(step, params, quiet=True)


def _bsdf(mat):
    return next(n for n in bpy.data.materials[mat].node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def _source(sock):
    assert sock.is_linked, sock.name
    return sock.links[0].from_node


def _setup(tmp_path, preset="VRChat", mapping=None):
    tex = textured_avatar(tmp_path / "tex")
    return tex, _call("material_setup", {"target_object": "Body", "x_preset": preset,
                                         "texture_mapping": mapping or tex})


# ── material_setup ────────────────────────────────────────────────────────


def test_base_colour_and_emission_are_wired_and_reported(tmp_path):
    tex, r = _setup(tmp_path)
    assert r["data"]["materials_wired"] == ["MatA.Base Color", "MatA.Normal", "MatA.Emission", "MatB.Base Color"]
    a = _bsdf("MatA")
    node = _source(a.inputs["Base Color"])
    assert node.type == "TEX_IMAGE" and Path(node.image.filepath).name == "MatA_BC.png"
    assert _source(a.inputs["Emission Color"]).image.filepath.endswith("MatA_E.png")
    assert a.inputs["Emission Strength"].default_value == 1.0
    assert _source(_bsdf("MatB").inputs["Base Color"]).image.filepath.endswith("MatB_BC.png")


def test_vrchat_normals_flip_green(tmp_path):
    _setup(tmp_path)
    nm = _source(_bsdf("MatA").inputs["Normal"])
    assert nm.type == "NORMAL_MAP"
    cmb = _source(nm.inputs["Color"])
    assert cmb.type == "COMBXYZ"
    sub = _source(cmb.inputs["Y"])
    assert (sub.type, sub.operation, sub.inputs[0].default_value) == ("MATH", "SUBTRACT", 1.0)


def test_endfield_normals_go_straight_in(tmp_path):
    _setup(tmp_path, preset="終末地")
    nm = _source(_bsdf("MatA").inputs["Normal"])
    assert _source(nm.inputs["Color"]).type == "TEX_IMAGE"


def test_a_null_slot_is_left_alone(tmp_path):
    tex = textured_avatar(tmp_path / "tex")
    r = _call("material_setup", {"target_object": "Body", "x_preset": "VRChat",
                                 "texture_mapping": {"MatB": {"Base Color": tex["MatB"]["Base Color"], "Roughness": None}}})
    assert r["data"]["materials_wired"] == ["MatB.Base Color"]
    assert not _bsdf("MatB").inputs["Roughness"].is_linked


def test_a_material_not_on_the_target_is_wired_with_a_warning(tmp_path):
    tex = textured_avatar(tmp_path / "tex")
    node_material("Elsewhere")
    r = _call("material_setup", {"target_object": "Body", "x_preset": "VRChat",
                                 "texture_mapping": {"Elsewhere": {"Base Color": tex["MatB"]["Base Color"]}}})
    assert r["data"]["materials_wired"] == ["Elsewhere.Base Color"]
    assert any("Elsewhere" in w and "Body" in w for w in r["warnings"])


@pytest.mark.parametrize("change, category", [
    ({"x_preset": "MMD"}, "params"),
    ({"target_object": "Nope"}, "precondition"),
    ({"mapping": {"MatA": {"Specular": "<tex>"}}}, "params"),
    ({"mapping": {"NoSuchMat": {"Base Color": "<tex>"}}}, "precondition"),
    ({"mapping": {"MatA": {"Base Color": "<missing>"}}}, "precondition"),
    ({"mapping": {}}, "params"),
])
def test_a_bad_mapping_changes_nothing(tmp_path, change, category):
    tex = textured_avatar(tmp_path / "tex")
    good = tex["MatB"]["Base Color"]
    mapping = change.get("mapping", tex)
    mapping = {m: {s: (good if f == "<tex>" else str(tmp_path / "gone.png") if f == "<missing>" else f)
                   for s, f in slots.items()} for m, slots in mapping.items()}
    # the good entry goes first: nothing of it may be wired either
    mapping = {"MatB": {"Base Color": good}, **mapping} if change.get("mapping") else mapping
    params = {"target_object": "Body", "x_preset": "VRChat", "texture_mapping": mapping}
    params.update({k: v for k, v in change.items() if k != "mapping"})
    links = {m.name: len(m.node_tree.links) for m in bpy.data.materials if m.node_tree}
    with pytest.raises(StepError) as e:
        _call("material_setup", params)
    assert e.value.category == category
    assert {m.name: len(m.node_tree.links) for m in bpy.data.materials if m.node_tree} == links


# ── material_generate ─────────────────────────────────────────────────────


def _generate(tmp_path, mapping=None, **over):
    tex = textured_avatar(tmp_path / "tex")
    _call("material_setup", {"target_object": "Body", "x_preset": "VRChat",
                             "texture_mapping": {m: {"Base Color": s["Base Color"]} for m, s in tex.items()}})
    root = tmp_path / "mod"
    root.mkdir()
    params = {"mesh_collection": "MHWilds_Female.mesh", "natives_root": str(root),
              "texture_base_path": "test/Avatar/", "preset_mapping": mapping or {"MatA": "Character", "MatB": "Skin"}}
    params.update(over)
    return root, params


def _generator_module():
    return next(m for n, m in sys.modules.items() if n.endswith("core.mdf_generator_base"))


def test_generate_makes_the_mdf_collection_and_the_textures(tmp_path):
    root, params = _generate(tmp_path)
    r = _call("material_generate", params)["data"]
    assert r["mdf_collection"] == "MHWilds_Female.mdf2"
    assert bpy.data.collections.get("MHWilds_Female.mdf2") is not None
    assert sorted(r["materials_processed"]) == ["MatA", "MatB"] and r["presets_auto_guessed"] == []
    assert json.loads(bpy.context.scene["modpilot_config"])["mdf2_collection"] == "MHWilds_Female.mdf2"
    assert list(root.rglob("*.tex.*")), "no textures written"
    col = bpy.data.collections["MHWilds_Female.mesh"]
    # one mesh per material, named Group_0_Sub_N__<material> (N is the generator's order)
    meshes = [o for o in col.all_objects if o.type == "MESH"]
    assert sorted(o.name.split("__", 1)[1] for o in meshes) == ["MatA", "MatB"]
    assert all(o.name.startswith("Group_0_Sub_") and len(o.material_slots) == 1 for o in meshes)


def test_materials_left_out_of_the_mapping_are_reported_as_auto_guessed(tmp_path):
    _, params = _generate(tmp_path, mapping={"MatA": "Character"})
    assert _call("material_generate", params)["data"]["presets_auto_guessed"] == ["MatB"]


@pytest.mark.parametrize("over, category", [
    ({"preset_mapping": {"MatA": "NoSuchPreset"}}, "params"),
    ({"preset_mapping": {"NotInTheCollection": "Character"}}, "precondition"),
    ({"natives_root": "<missing>"}, "precondition"),
    ({"mesh_collection": "NoSuch.mesh"}, "precondition"),
])
def test_bad_generate_params_fail_before_generating(tmp_path, over, category):
    root, params = _generate(tmp_path)
    if over.get("natives_root") == "<missing>":
        over = {"natives_root": str(tmp_path / "nowhere")}
    params.update(over)
    with pytest.raises(StepError) as e:
        _call("material_generate", params)
    assert e.value.category == category
    assert bpy.data.collections.get("MHWilds_Female.mdf2") is None
    assert not list(root.rglob("*.tex.*"))


def test_a_material_the_generator_fails_on_fails_the_step_by_name(tmp_path, monkeypatch):
    _, params = _generate(tmp_path)
    base = _generator_module().MdfGenProcessBase
    original = base._process_one_material

    def broken(runner, context, entry, *a, **k):
        if entry.blender_material == "MatB":
            raise ValueError("synthetic failure")
        return original(runner, context, entry, *a, **k)
    monkeypatch.setattr(base, "_process_one_material", staticmethod(broken))
    with pytest.raises(StepError) as e:
        _call("material_generate", params)
    assert e.value.category == "postcondition"
    assert e.value.details["failed"] == {"MatB": "synthetic failure"}
    assert e.value.partial["materials_processed"] == ["MatA"]


# ── material_inspect ──────────────────────────────────────────────────────


def _inspect(tmp_path, **over):
    return _call("material_inspect", {"target_object": "Body", "texture_dir": str(tmp_path / "tex"), **over})


def test_inspect_traces_each_wired_slot_back_to_its_image(tmp_path):
    tex, _ = _setup(tmp_path)
    (tmp_path / "tex" / "notes.txt").write_text("not an image")
    r = _inspect(tmp_path)["data"]
    assert r["materials"] == ["MatA", "MatB"]
    assert r["texture_files"] == sorted(str(p) for p in (tmp_path / "tex").glob("*.png"))
    none = dict.fromkeys(("Base Color", "Alpha", "Roughness", "Metallic", "Emission", "Normal"))
    # the VRChat normal goes through the 1-Y chain and a Normal Map node, and is still traced
    assert r["existing_connections"] == {"MatA": {**none, **tex["MatA"]}, "MatB": {**none, **tex["MatB"]}}


def test_inspect_before_wiring_finds_nothing_connected(tmp_path):
    textured_avatar(tmp_path / "tex")
    r = _inspect(tmp_path, purpose="verify")["data"]
    assert all(v is None for slots in r["existing_connections"].values() for v in slots.values())


@pytest.mark.parametrize("over, category", [
    ({"target_object": "Nope"}, "precondition"),
    ({"texture_dir": "<missing>"}, "precondition"),
    ({"purpose": "guess"}, "params"),
])
def test_inspect_refuses_a_bad_target_folder_or_purpose(tmp_path, over, category):
    textured_avatar(tmp_path / "tex")
    if over.get("texture_dir") == "<missing>":
        over = {"texture_dir": str(tmp_path / "nowhere")}
    with pytest.raises(StepError) as e:
        _inspect(tmp_path, **over)
    assert e.value.category == category


# ── material_consolidate ──────────────────────────────────────────────────


def _shared(tmp_path):
    """MatA and MatB on the same base colour texture, plus 'Plain' (no textures) in a third slot."""
    tex = textured_avatar(tmp_path / "tex")
    bc = tex["MatA"]["Base Color"]
    _call("material_setup", {"target_object": "Body", "x_preset": "VRChat",
                             "texture_mapping": {"MatA": {"Base Color": bc}, "MatB": {"Base Color": bc}}})
    bpy.data.objects["Body"].data.materials.append(node_material("Plain"))
    return bc


def _slots():
    body = bpy.data.objects["Body"].data
    return [m.name for m in body.materials], [p.material_index for p in body.polygons]


def test_a_dry_run_groups_materials_by_their_textures_and_changes_nothing(tmp_path):
    _shared(tmp_path)
    r = _call("material_consolidate", {"target_object": "Body"})["data"]
    assert r["material_count_before"] == 3
    assert r["consolidation_groups"] == [
        {"texture_set": [os.path.normcase("MatA_BC.png")], "materials": ["MatA", "MatB"], "keeper": "MatA", "to_remove": ["MatB"],
         "is_singleton": False},
        {"texture_set": [], "materials": ["Plain"], "keeper": "Plain", "to_remove": [], "is_singleton": True}]
    assert _slots() == (["MatA", "MatB", "Plain"], [0, 1])


@pytest.mark.parametrize("keeper, removed, slots", [
    ("MatA", "MatB", (["MatA", "Plain"], [0, 0])),
    ("MatB", "MatA", (["MatB", "Plain"], [0, 0])),     # the keeper's slot moves down
])
def test_merging_moves_the_faces_to_the_keeper_and_drops_the_slot(tmp_path, keeper, removed, slots):
    _shared(tmp_path)
    r = _call("material_consolidate", {"target_object": "Body", "dry_run": False,
                                       "groups": [{"keeper": keeper, "to_remove": [removed]}]})["data"]
    assert r["merged_groups"] == [{"keeper": keeper, "removed": [removed]}]
    assert (r["material_count_before"], r["material_count_after"], r["skipped"]) == (3, 2, [])
    assert _slots() == slots


@pytest.mark.parametrize("params, category", [
    ({"dry_run": False}, "params"),
    ({"dry_run": False, "groups": [{"keeper": "MatA", "to_remove": ["Nope"]}]}, "precondition"),
    ({"dry_run": False, "groups": [{"keeper": "Nope", "to_remove": ["MatB"]}]}, "precondition"),
    ({"dry_run": False, "groups": [{"keeper": "MatA", "to_remove": ["MatA"]}]}, "params"),
    ({"dry_run": False, "groups": [{"keeper": "MatA"}]}, "params"),
    ({"target_object": "Nope"}, "precondition"),
])
def test_consolidate_checks_every_group_before_merging_any(tmp_path, params, category):
    _shared(tmp_path)
    with pytest.raises(StepError) as e:
        _call("material_consolidate", {"target_object": "Body", **params})
    assert e.value.category == category
    assert _slots() == (["MatA", "MatB", "Plain"], [0, 1])
