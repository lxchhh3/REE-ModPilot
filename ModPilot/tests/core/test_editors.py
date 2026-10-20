"""modpilot.formats.editors: RE Chain Editor's and RE Mesh Editor's own bpy-free file modules, from the
enabled add-on inside Blender or tools-5.2's pinned clones outside it, each under its own package name
so the two editors' "modules" packages never collide (Blender-MHWilds lesson #74). The build scripts
had five copies of this loading (collar_lib, mrcheck, gpuc_skirt, meshio, relocate_slot)."""
import sys
import types

import pytest

from modpilot.core.errors import StepError
from modpilot.formats import editors as E

pytestmark = pytest.mark.skipif(not (E.tools52() / "upstream" / "RE-Chain-Editor").is_dir(),
                                reason="tools-5.2's pinned editor clones are not here")


def test_both_editors_load_side_by_side_in_either_order():
    mdf = E.module("mesh", "mdf.file_re_mdf")
    chain2 = E.module("chain", "file_re_chain2")
    clsp = E.module("chain", "file_re_clsp")
    mesh = E.module("mesh", "mesh.file_re_mesh")
    assert hasattr(chain2, "Chain2File") and hasattr(clsp, "readRECLSP")
    assert hasattr(mesh, "readREMesh") and hasattr(mdf, "readMDF")
    assert chain2.__name__.startswith("rechain.") and mesh.__name__.startswith("remesh.")


def test_a_module_is_loaded_once():
    assert E.module("chain", "pymmh3") is E.module("chain", "pymmh3")


def test_inside_blender_the_enabled_add_ons_module_wins(monkeypatch):
    fake = types.ModuleType("RE-Chain-Editor.modules.file_re_chain2")
    monkeypatch.setitem(sys.modules, "RE-Chain-Editor.modules.file_re_chain2", fake)
    monkeypatch.setattr(E, "_LOADED", {})
    assert E.module("chain", "file_re_chain2") is fake


def test_an_unknown_editor_or_module_is_an_error():
    with pytest.raises(StepError) as e:
        E.module("sound", "x")
    assert e.value.category == "params"
    with pytest.raises(ModuleNotFoundError):
        E.module("chain", "no_such_file")


def test_hash_wide_is_the_chain_editors():
    assert E.hash_name("Hip_HJ_00") == E.module("chain", "pymmh3").hash_wide("Hip_HJ_00")
