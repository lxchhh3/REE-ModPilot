"""modpilot.bl.meshdata in real Blender (T1): the helpers the GG and Marette build drivers shared."""
from pathlib import Path
from types import SimpleNamespace as NS

import bpy
import numpy as np
import pytest

from modpilot.bl import meshdata as D
from modpilot.formats import editors
from modpilot.testing import scenes

MDF = (editors.tools52().parent / "Known_Good_mod_test/Output/og_collar1B/mod/natives/STM/Art/Model/Character/ch03/024/001/2/"
       "ch03_024_0012.mdf2.45")


def _quad():
    arm = scenes.make_armature("Rig", [("Hips", None, (0, 0, 0), (0, 0, 1)), ("Tail", "Hips", (0, 0, 1), (0, 0, 2)),
                                       ("Tail.001", "Tail", (0, 0, 2), (0, 0, 3))])
    q = scenes.make_quads("Group_0_Sub_2__Body all.001", [[(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]], "M")
    scenes.skin(q, arm, {"Hips": [(0, 1.0), (1, 0.5)], "Tail": [(1, 0.5)]})
    return arm, q


def test_weights_read_and_write():
    _, q = _quad()
    w = D.weights_of(q)
    assert w[0] == {"Hips": 1.0} and w[1] == pytest.approx({"Hips": 0.5, "Tail": 0.5}) and w[2] == {}
    D.set_weights(q, 1, w[1], {"Tail": 0.25, "New": 0.75})
    assert D.weights_of(q)[1] == pytest.approx({"Tail": 0.25, "New": 0.75})


def test_material_of_a_separated_sub_mesh():
    _, q = _quad()
    assert D.material_of(q) == "Body all"


def test_key_state_sets_only_the_given_keys():
    _, q = _quad()
    q.location = (0, 0, 1)
    scenes.add_key(q, "Up", [(0, 0, 0.1)] * 4, 0.0)
    scenes.add_key(q, "Side", [(0.2, 0, 0)] * 4, 1.0)
    pos, nrm = D.key_state(q, {"Up": 1.0})
    assert np.allclose(pos[0], [0, 0, 1.1]) and q.data.shape_keys.key_blocks["Side"].value == 0.0
    assert np.allclose(np.linalg.norm(nrm, axis=1), 1.0)


def test_chain_bones_walk_up_from_the_terminal():
    arm, _ = _quad()
    hashes = {1: "Tail.001", 2: "Gone"}
    assert D.chain_bones(NS(terminateNodeNameHash=1, nodeList=[0, 0]), arm, hashes) == ["Tail.001", "Tail"]
    assert D.chain_bones(NS(terminateNodeNameHash=1, nodeList=[0] * 9), arm, hashes) == ["Tail.001", "Tail", "Hips"]
    assert D.chain_bones(NS(terminateNodeNameHash=2, nodeList=[0]), arm, hashes) == []


@pytest.mark.skipif(not MDF.is_file(), reason="the og_collar1B build is not here")
def test_import_mdf_gives_its_collection_and_materials():
    coll, mats = D.import_mdf(Path(MDF))
    assert ".mdf2" in coll.name and mats and all(m.get("~TYPE") == "RE_MDF_MATERIAL" for m in mats)
    assert bpy.data.collections.get(coll.name) is coll
