"""batch_export in real Blender (T1): the graft avatar carried through chains, colliders and
materials, exported as armor pl024 (ff: ch03_024_0012) part 2 (Body). The Toolkit's exporter prints
a failed file or BoneSystem export and still returns FINISHED, and its per-file helpers ignore a
CANCELLED operator: the step fails on both, and on a file that did not appear."""
import re
import sys

import bpy
import pytest

from modpilot.core.errors import StepError
from modpilot.testing.rigs import call, exportable

BODY = "ch03_024_0012"
EXPECTED = {
    "mesh": rf"{BODY}\.mesh\.241111606$",
    "mdf2": rf"{BODY}\.mdf2\.45$",
    "chain2": rf"{BODY}\.chain2\.14$",
    "clsp": rf"{BODY}\.clsp\.\d+$",
    "skeleton": r"/test_Avatar\.fbxskel\.7$",
    "bone system json": rf"reframework/data/BoneSystem/{BODY}\.json$",
}


def _exportable(tmp_path):
    return exportable(tmp_path)


def _files(root):
    return [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]


def test_the_body_part_exports_with_its_colliders_and_bone_system(tmp_path):
    root, params = _exportable(tmp_path)
    r = call("batch_export", params)["data"]
    # the pre-export cleanup's re_mesh.solve_repeated_uvs smooths every face (normals kept), as in
    # the in-game-verified builds (kevin 2026-10-20: keep it)
    col = bpy.data.collections["MHWilds_Female.mesh"]
    assert all(p.use_smooth for o in col.objects if o.type == "MESH" for p in o.data.polygons)
    assert r["meshes_cleaned"] == [o.name for o in col.objects if o.type == "MESH"]
    files = _files(root)
    for what, pattern in EXPECTED.items():
        assert any(re.search(pattern, f) for f in files), (what, files)
    assert r["exported_parts"] == {"2": "Body"}
    assert (r["armor_id"], r["armor_variant"], r["fbxskel_name"]) == ("pl024", "ff", "test_Avatar")
    assert r["clsp_collection"] == "full_body.clsp"
    assert {e["filetype"] for e in r["files_written"]} == {"mesh", "mdf2", "chain2", "clsp"}


def test_collections_come_from_the_scene_config_when_not_given(tmp_path):
    root, params = _exportable(tmp_path)
    r = call("batch_export", params)
    assert r["params"].get("mesh_collection") is None
    assert any(re.search(EXPECTED["mesh"], f) for f in _files(root))


def test_an_empty_clsp_collection_exports_a_blank_clsp(tmp_path):
    _, params = _exportable(tmp_path)
    r = call("batch_export", {**params, "clsp_collection": ""})["data"]
    assert r["clsp_collection"] is None
    assert "clsp" not in {e["filetype"] for e in r["files_written"]}


@pytest.mark.parametrize("over, category", [
    ({"armor_variant": "xx"}, "params"),
    ({"target_parts": ["6"]}, "params"),
    ({"target_parts": []}, "params"),
    ({"mdf2_collection": "NoSuch.mdf2"}, "precondition"),
    ({"target_armature": "Nope"}, "precondition"),
    ({"clsp_collection": "NoSuch.clsp"}, "precondition"),
    ({"natives_root": "<missing>"}, "precondition"),
    ({"<no uv map>": True}, "precondition"),
])
def test_bad_export_params_fail_before_exporting(tmp_path, over, category):
    root, params = _exportable(tmp_path)
    if over.get("natives_root") == "<missing>":
        over = {"natives_root": str(tmp_path / "nowhere")}
    if over.pop("<no uv map>", False):      # RE Mesh can't export it; its UV cleanup can't run on it
        mesh = next(o for o in bpy.data.collections["MHWilds_Female.mesh"].objects if o.type == "MESH")
        while mesh.data.uv_layers:
            mesh.data.uv_layers.remove(mesh.data.uv_layers[0])
    before = _files(root)
    with pytest.raises(StepError) as e:
        call("batch_export", {**params, **over})
    assert e.value.category == category
    assert _files(root) == before


def _exporter():
    return next(m for n, m in sys.modules.items() if n.endswith("games.mhws.batch_export"))


def test_a_file_the_exporter_fails_on_fails_the_step(tmp_path, monkeypatch):
    _, params = _exportable(tmp_path)

    def broken(filepath, collection_name):
        raise RuntimeError("synthetic mdf2 failure")
    monkeypatch.setitem(_exporter()._EXPORT_FUNCS, "mdf2", broken)
    with pytest.raises(StepError) as e:
        call("batch_export", params)
    assert e.value.category == "postcondition"
    assert "synthetic mdf2 failure" in str(e.value.details["failed"])


def test_an_export_that_writes_nothing_fails_the_step(tmp_path, monkeypatch):
    _, params = _exportable(tmp_path)
    monkeypatch.setitem(_exporter()._EXPORT_FUNCS, "chain2", lambda filepath, collection_name: None)
    with pytest.raises(StepError) as e:
        call("batch_export", params)
    assert e.value.category == "postcondition"
    assert any("chain2" in m for m in e.value.details["missing_files"])


def test_a_failed_bone_system_export_fails_the_step(tmp_path, monkeypatch):
    _, params = _exportable(tmp_path)
    monkeypatch.setattr(_exporter(), "_do_bonesystem_export", lambda *a: (False, "synthetic bonesystem failure"))
    with pytest.raises(StepError) as e:
        call("batch_export", params)
    assert e.value.category == "postcondition"
    assert "synthetic bonesystem failure" in str(e.value.details)


def test_bindings_of_parts_not_exported_are_cleared(tmp_path):
    root, params = _exportable(tmp_path)
    scene, aid = bpy.context.scene, params["armor_id"]
    scene[f"mhws_{aid}_3_mesh"] = "Stale.mesh"         # an earlier export of part 3
    scene[f"mhws_{aid}_3_clsp"] = "Stale.clsp"
    call("batch_export", params)
    assert f"mhws_{aid}_3_mesh" not in scene and f"mhws_{aid}_3_clsp" not in scene
    assert scene[f"mhws_{aid}_2_mesh"] == "MHWilds_Female.mesh"
