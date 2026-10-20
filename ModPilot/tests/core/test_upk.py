"""Pure-python tests for upk.py (reading assets out of a .unitypackage for the GG build, kevin 2026-10-15).
Run with tools-5.2's venv:  .venv/Scripts/python.exe -m pytest scripts/gg/tests -q

A .unitypackage is a gzipped tar of <guid>/{pathname, asset, asset.meta}; prefabs name their materials
and materials their textures by guid. The fixture builds a tiny one with the GG layout.
(Moved with modpilot.formats.upk from Known_Good_mod_test/scripts/gg/tests/test_upk.py.)"""
import hashlib
import io
import json
import tarfile

import pytest

from modpilot.formats import upk

G = {"main3": "a" * 32, "other3": "b" * 32, "main1": "c" * 32, "tex_main3": "d" * 32, "tex_other3": "e" * 32,
     "norm_main": "f" * 32, "mask": "1" * 32, "tex_main1": "2" * 32, "prefab3": "3" * 32, "prefab1": "4" * 32,
     "headset3": "5" * 32, "folder": "6" * 32}

MAT = """%YAML 1.1
--- !u!21 &2100000
Material:
  m_Name: {name}
  m_SavedProperties:
    m_TexEnvs:
    - _BumpMap:
        m_Texture: {{fileID: 2800000, guid: {norm}, type: 3}}
        m_Scale: {{x: 1, y: 1}}
    - _MainTex:
        m_Texture: {{fileID: 2800000, guid: {tex}, type: 3}}
        m_Scale: {{x: 1, y: 1}}
    - _MatCapBlendMask:
        m_Texture: {{fileID: 2800000, guid: {mask}, type: 3}}
    - _EmissionMap:
        m_Texture: {{fileID: 0}}
    m_Colors:
    - _Color: {{r: 1, g: 0.9, b: 0.8, a: 1}}
    - _EmissionColor: {{r: 0, g: 0, b: 0, a: 1}}
"""
PREFAB = """--- !u!137 &1
SkinnedMeshRenderer:
  m_Materials:
  - {{fileID: 2100000, guid: {a}, type: 2}}
  - {{fileID: 2100000, guid: {b}, type: 2}}
  m_Mesh: {{fileID: 4300000, guid: 0123456789abcdef0123456789abcdef, type: 3}}
"""


def _assets():
    return {
        G["main3"]: ("Assets/MeiShop/GG/lilToonMaterial/GG_Main_3.mat",
                     MAT.format(name="GG_Main_3", tex=G["tex_main3"], norm=G["norm_main"], mask="0" * 32).encode()),
        G["other3"]: ("Assets/MeiShop/GG/lilToonMaterial/GG_Other_3.mat",
                      MAT.format(name="GG_Other_3", tex=G["tex_other3"], norm=G["norm_main"], mask=G["mask"]).encode()),
        G["main1"]: ("Assets/MeiShop/GG/lilToonMaterial/GG_Main 1.mat",
                     MAT.format(name="GG_Main 1", tex=G["tex_main1"], norm=G["norm_main"], mask="0" * 32).encode()),
        G["tex_main3"]: ("Assets/MeiShop/GG/TEX/GG_Main_3.png", b"\x89PNG main3"),
        G["tex_other3"]: ("Assets/MeiShop/GG/TEX/GG_Other_3.png", b"\x89PNG other3"),
        G["tex_main1"]: ("Assets/MeiShop/GG/TEX/GG_Main_1.png", b"\x89PNG main1"),
        G["norm_main"]: ("Assets/MeiShop/GG/TEX/NormalMap/GG_Main_NORM.png", b"\x89PNG norm"),
        G["mask"]: ("Assets/MeiShop/GG/TEX/Mask/GG_Other_Mask.png", b"\x89PNG mask"),
        G["prefab3"]: ("Assets/MeiShop/GG/Preafb/GG_Maya_3.prefab", PREFAB.format(a=G["main3"], b=G["other3"]).encode()),
        G["prefab1"]: ("Assets/MeiShop/GG/Preafb/GG_Maya_1.prefab", PREFAB.format(a=G["main1"], b=G["other3"]).encode()),
        G["headset3"]: ("Assets/MeiShop/GG/GG_headset_Maya_3.prefab", PREFAB.format(a=G["other3"], b=G["other3"]).encode()),
        G["folder"]: ("Assets/MeiShop/GG/TEX", None),
    }


def _write_upk(path, assets, extra=()):
    with tarfile.open(path, "w:gz") as t:
        def add(name, data):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
        for guid, (pathname, data) in assets.items():
            add(f"{guid}/pathname", (pathname + "\n00").encode())
            add(f"{guid}/asset.meta", b"fileFormatVersion: 2\n")
            if data is not None:
                add(f"{guid}/asset", data)
        for name, data in extra:
            add(name, data)
    return path


@pytest.fixture()
def pkg(tmp_path):
    return _write_upk(tmp_path / "gg.unitypackage", _assets())


def test_index_maps_every_pathname_to_its_guid(pkg):
    idx = upk.read_index(pkg)
    assert idx.path_of[G["main3"]] == "Assets/MeiShop/GG/lilToonMaterial/GG_Main_3.mat"
    assert idx.guid_of["Assets/MeiShop/GG/TEX/GG_Other_3.png"] == G["tex_other3"]
    assert G["folder"] in idx.path_of and G["folder"] not in idx.has_asset   # a folder entry has no asset
    assert len(idx.path_of) == len(_assets())


def test_pathname_keeps_only_its_first_line(pkg):
    # Unity appends a second line ("00") to some pathname files
    assert all("\n" not in p for p in upk.read_index(pkg).path_of.values())


def test_prefab_materials_in_slot_order(pkg):
    idx = upk.read_index(pkg)
    text = upk.read_text(pkg, idx.guid_of["Assets/MeiShop/GG/Preafb/GG_Maya_3.prefab"])
    assert upk.prefab_materials(text, idx) == ["Assets/MeiShop/GG/lilToonMaterial/GG_Main_3.mat",
                                               "Assets/MeiShop/GG/lilToonMaterial/GG_Other_3.mat"]


def test_material_textures_by_slot_skip_empty_and_foreign(pkg):
    idx = upk.read_index(pkg)
    m = upk.material_textures(upk.read_text(pkg, G["main3"]), idx)
    # _EmissionMap is fileID 0; the _MatCapBlendMask guid 000.. is not in the package
    assert m == {"_BumpMap": "Assets/MeiShop/GG/TEX/NormalMap/GG_Main_NORM.png",
                 "_MainTex": "Assets/MeiShop/GG/TEX/GG_Main_3.png"}


def test_material_colors(pkg):
    c = upk.material_colors(upk.read_text(pkg, G["main3"]))
    assert c["_Color"] == (1.0, 0.9, 0.8, 1.0)
    assert c["_EmissionColor"] == (0.0, 0.0, 0.0, 1.0)


def test_colourway_closure_from_prefabs(pkg):
    want = upk.prefab_closure(pkg, ["Assets/MeiShop/GG/Preafb/GG_Maya_3.prefab",
                                    "Assets/MeiShop/GG/GG_headset_Maya_3.prefab"])
    assert want == {
        "Assets/MeiShop/GG/Preafb/GG_Maya_3.prefab", "Assets/MeiShop/GG/GG_headset_Maya_3.prefab",
        "Assets/MeiShop/GG/lilToonMaterial/GG_Main_3.mat", "Assets/MeiShop/GG/lilToonMaterial/GG_Other_3.mat",
        "Assets/MeiShop/GG/TEX/GG_Main_3.png", "Assets/MeiShop/GG/TEX/GG_Other_3.png",
        "Assets/MeiShop/GG/TEX/NormalMap/GG_Main_NORM.png", "Assets/MeiShop/GG/TEX/Mask/GG_Other_Mask.png"}
    assert "Assets/MeiShop/GG/TEX/GG_Main_1.png" not in want   # another colourway stays in the package


def test_unknown_prefab_is_an_error(pkg):
    with pytest.raises(KeyError):
        upk.prefab_closure(pkg, ["Assets/MeiShop/GG/Preafb/GG_Maya_9.prefab"])


def test_extract_writes_bytes_and_manifest(pkg, tmp_path):
    out = tmp_path / "out"
    want = ["Assets/MeiShop/GG/TEX/GG_Main_3.png", "Assets/MeiShop/GG/lilToonMaterial/GG_Main_3.mat"]
    man = upk.extract(pkg, want, out)
    for p in want:
        data = (out / p).read_bytes()
        assert data == dict(_assets().values())[p]
        assert man[p]["sha256"] == hashlib.sha256(data).hexdigest()
        assert man[p]["bytes"] == len(data) and man[p]["guid"] == upk.read_index(pkg).guid_of[p]
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == sorted(want)


def test_extract_refuses_paths_outside_the_output(tmp_path):
    evil = _write_upk(tmp_path / "evil.unitypackage", {"9" * 32: ("Assets/../../escape.png", b"x")})
    with pytest.raises(ValueError):
        upk.extract(evil, ["Assets/../../escape.png"], tmp_path / "out")
    assert not (tmp_path / "escape.png").exists()


def test_extract_refuses_a_missing_or_assetless_path(pkg, tmp_path):
    with pytest.raises(KeyError):
        upk.extract(pkg, ["Assets/MeiShop/GG/TEX/GG_Main_7.png"], tmp_path / "o1")
    with pytest.raises(KeyError):
        upk.extract(pkg, ["Assets/MeiShop/GG/TEX"], tmp_path / "o2")   # a folder entry


def test_manifest_is_json_serialisable(pkg, tmp_path):
    man = upk.extract(pkg, ["Assets/MeiShop/GG/TEX/GG_Main_3.png"], tmp_path / "out")
    json.dumps(man)
