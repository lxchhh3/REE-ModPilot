"""modpilot.mods.colour_fix on the verified builds (moved with Known_Good_mod_test/scripts/bhs_shader/tests/
test_colour_fix.py's single-file tests; its gg22 checks stay there): it finds exactly the doubled materials, and on
og_collar1B it gives bhs_colour2 (kept in game, kevin 2026-10-18) byte for byte."""
import shutil

import pytest

from modpilot.formats import editors
from modpilot.formats import mdf as materials
from modpilot.mods import colour_fix

KG = editors.tools52().parent / "Known_Good_mod_test"
BASE = KG / "Output/og_collar1B/mod"
MDF = "natives/STM/Art/Model/Character/ch03/024/001/2/ch03_024_0012.mdf2.45"
GG21 = KG / "Output/gg21/mod"
GG_MDF = "natives/STM/Art/Model/Character/ch03/039/001/2/ch03_039_0012.mdf2.45"
MARETTE = KG / "Output/marette2/mod/natives/STM/Art/Model/Character/ch03/030/601/2/ch03_030_6012.mdf2.45"

pytestmark = pytest.mark.skipif(not (BASE / MDF).is_file(), reason="the verified builds are not here")


@pytest.mark.parametrize("path, expected", [
    (BASE / MDF, {"BHS_A", "BHS_B", "BHS_F", "Cloth", "Shoes", "Eye", "Effect"}),
    (GG21 / GG_MDF, {"GG_Main", "GG_Other", "Cloth", "Eye", "Effect"}),
    (MARETTE, {"MR_Metal", "MR_Stocking", "Eye", "Effect"}),
])
def test_finds_exactly_the_doubled_materials(path, expected):
    f = materials.read(path)
    assert {m.materialName for m in f.materialList if colour_fix.doubled(m)} == expected


def test_skin_and_fixed_materials_are_not_doubled():
    f = materials.read(KG / "Output/bhs_colour2/mod" / MDF)
    assert not [m.materialName for m in f.materialList if colour_fix.doubled(m)]


def test_on_og_collar1b_it_gives_bhs_colour2_byte_for_byte(tmp_path):
    out = tmp_path / "fixed.mdf2.45"
    names = colour_fix.fix_mdf(BASE / MDF, out)
    assert sorted(names) == sorted(["BHS_A", "BHS_B", "BHS_F", "Cloth", "Shoes", "Eye", "Effect"])
    assert out.read_bytes() == (KG / "Output/bhs_colour2/mod" / MDF).read_bytes()


def test_a_fixed_file_is_left_alone(tmp_path):
    src = KG / "Output/bhs_colour2/mod" / MDF
    out = tmp_path / "again.mdf2.45"
    assert colour_fix.fix_mdf(src, out) == []
    assert not out.exists()


def test_fix_tree_fixes_every_mdf2_of_a_mod_in_place(tmp_path):
    shutil.copytree(BASE, tmp_path / "mod")
    assert colour_fix.fix_tree(tmp_path / "mod") == {MDF: ["BHS_A", "BHS_B", "BHS_F", "Cloth", "Shoes", "Eye", "Effect"]}
    assert (tmp_path / "mod" / MDF).read_bytes() == (KG / "Output/bhs_colour2/mod" / MDF).read_bytes()
