"""modpilot.mods.relocate's path rules (moved with Known_Good_mod_test/scripts/gg/tests/test_relocate_slot.py's unit
tests; its checks on the built gg21 stay there)."""
import pytest

from modpilot.mods import relocate as RS

CHAR = RS.CHAR
SRC, DST = ("ch03", "024", "001"), ("ch03", "039", "001")      # GG: pl024 (BHS) -> pl039 Lagiacrus


def test_slot_path_moves_folder_and_file_name():
    src = f"{CHAR}ch03/024/001/2/ch03_024_0012.mesh.241111606"
    assert RS.slot_path(src, SRC, DST) == f"{CHAR}ch03/039/001/2/ch03_039_0012.mesh.241111606"
    assert (RS.slot_path(f"{CHAR}ch03/024/001/5/ch03_024_0015.chain2.14", SRC, DST)
            == f"{CHAR}ch03/039/001/5/ch03_039_0015.chain2.14")


def test_slot_path_refuses_a_file_named_for_another_slot():
    with pytest.raises(ValueError):
        RS.slot_path(f"{CHAR}ch03/024/001/2/ch03_025_0012.mesh.241111606", SRC, DST)


def test_slot_path_refuses_a_path_outside_the_slot():
    with pytest.raises(ValueError):
        RS.slot_path(f"{CHAR}ch03/025/001/2/ch03_025_0012.mesh.241111606", SRC, DST)


def test_texture_map_moves_mod_textures_and_keeps_engine_ones():
    m = RS.texture_map(["Art/Dimcirui/MayaBHS/Body_ALBD.tex", "Art/kevin/MayaGG/GG_Main_ALBD.tex",
                        "MasterMaterial/Textures/bluenoise_msk1.tex", "systems/rendering/NullWhite.tex"],
                       "Art/kevin/MayaGG")
    assert m == {"Art/Dimcirui/MayaBHS/Body_ALBD.tex": "Art/kevin/MayaGG/Body_ALBD.tex"}


def test_texture_map_keeps_the_engine_library():
    """Base_Equip_NoMultiBlend binds the game's wind field from RE_ENGINE_LIBRARY (Marette cloth, kevin 2026-10-18)."""
    lib = "RE_ENGINE_LIBRARY/VFX_Library/Texture/TEX_Vectorfield/tex_capcom_vectorfield_0003_MSK4.tex"
    assert RS.texture_map([lib], "Art/kevin/MayaMarette") == {}
    assert lib.startswith(RS.ENGINE)


def test_texture_map_refuses_two_textures_landing_on_one_name():
    with pytest.raises(ValueError):
        RS.texture_map(["Art/Dimcirui/MayaBHS/Body_ALBD.tex", "Art/Other/Body_ALBD.tex"], "Art/kevin/MayaGG")


def test_set_fbx_path_changes_only_that_value_and_keeps_crlf():
    src = b'{\r\n    "BindFace": true,\r\n    "FbxPath": "MayaBHS",\r\n    "HideHair": true\r\n}'
    assert RS.set_fbx_path(src, "MayaGG") == src.replace(b'"MayaBHS"', b'"MayaGG"')


# ------------------------------------------------------------------ the relocated GG mod
