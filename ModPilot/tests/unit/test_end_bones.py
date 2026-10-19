"""physics_transplant's '_End' bones for weighted leaves (ModPilot lesson #49).

smart_graft only sees weights in meshes still on the SOURCE armature; vertex_groups has moved them
all, so the leaves got no '_End' and physics_chains skipped their chains. The tool adds them after
smart_graft with smart_graft's own rule. Behaviour in Blender: tools-5.2 tests/test_l3_fixes.py.
"""

import ast
from unittest.mock import MagicMock

import pytest

from app.blender.state import SceneCache
from app.phases.physics_bones import END_BONES_SRC, PhysicsTransplant

pytestmark = pytest.mark.unit

PARAMS = {"source_armature": "Armature", "target_armature": "MHWilds_Female Armature", "x_preset": "VRChat"}


def _client(lines):
    client = MagicMock()
    client.execute_and_extract.return_value = lines
    client.get_scene_info.return_value = {"name": "Scene", "object_count": 0, "objects": [], "materials_count": 0}
    return client


def test_end_bones_source_is_valid_python():
    ast.parse(END_BONES_SRC)


def test_end_bones_are_added_after_smart_graft():
    client = _client(["{'FINISHED'}", 'END_BONES:["Ribbon_End"]'])
    PhysicsTransplant().run(client, SceneCache(client), PARAMS)
    code = client.execute_and_extract.call_args_list[0].args[0]
    assert END_BONES_SRC in code
    assert code.index("bpy.ops.modder.smart_graft()") < code.index("ends = _add_missing_end_bones(src, tgt)")


def test_added_end_bones_reach_the_result():
    client = _client(["{'FINISHED'}", 'END_BONES:["Ribbon_End", "Tail.001_End"]'])
    result = PhysicsTransplant().run(client, SceneCache(client), PARAMS)
    assert result.success
    assert result.state_diff["end_bones_added"] == ["Ribbon_End", "Tail.001_End"]


def test_a_cancelled_graft_still_fails():
    client = _client(["{'CANCELLED'}", "END_BONES:[]"])
    result = PhysicsTransplant().run(client, SceneCache(client), PARAMS)
    assert not result.success
    assert result.error.category == "operator_failed"
