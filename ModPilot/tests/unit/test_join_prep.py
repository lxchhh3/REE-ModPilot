"""vertex_groups' join preparation (ModPilot lesson #48; Blender-MHWilds lessons #11 / #42).

Blender's join keeps ONE value per shape key (the active object's) and matches UV / colour layers
by NAME, while the exporter ships each vertex's basis position and writes UV layers by index. So
before the join every part's current shape-key mix becomes its basis (its keys keep their deltas),
its UV layers take the active part's names by position, and colour layers missing on a part are
added white. Behaviour in Blender is pinned by tools-5.2 tests/test_l3_fixes.py; these tests pin
that the prep code runs before the join and that its report reaches the result.
"""

import ast
import json
from unittest.mock import MagicMock

import pytest

from app.blender.state import SceneCache
from app.phases.vertex_groups import JOIN_PREP_SRC, VertexGroups

pytestmark = pytest.mark.unit

PARAMS = {"x_preset": "VRChat", "mesh_objects": ["Body", "Garment"], "target_armature": "MHWilds_Female Armature"}


def _client(prep_lines):
    client = MagicMock()
    client.execute_and_extract.side_effect = [prep_lines, ["{'FINISHED'}"], ["REPARENT_OK"], ["CLEANUP_OK"]]
    client.get_scene_info.return_value = {"name": "Scene", "object_count": 0, "objects": [], "materials_count": 0}
    return client


def test_join_prep_source_is_valid_python():
    ast.parse(JOIN_PREP_SRC)


def test_join_prep_runs_on_every_part_before_the_join():
    client = _client(["PREP_OK:Body"])
    VertexGroups().run(client, SceneCache(client), PARAMS)
    code = client.execute_and_extract.call_args_list[0].args[0]
    assert JOIN_PREP_SRC in code
    call_at = code.index("_prepare_for_join(mesh_objs)")
    assert call_at < code.index("bpy.ops.object.join()")


def test_join_prep_report_reaches_the_result():
    report = {"baked_keys": {"Garment": {"High heeled": 1.0}}, "uv_renamed": {"Garment": {"UVマップ": "UV 맵"}},
              "uv_added": {}, "colour_added": {"Garment": ["Col"]}}
    client = _client(["PREP_OK:Body", "JOIN_PREP:" + json.dumps(report, ensure_ascii=False)])
    result = VertexGroups().run(client, SceneCache(client), PARAMS)
    assert result.success
    assert result.state_diff["join_prep"] == report


def test_a_prep_without_a_report_still_succeeds():
    client = _client(["PREP_OK:Body"])
    result = VertexGroups().run(client, SceneCache(client), PARAMS)
    assert result.success
    assert "join_prep" not in result.state_diff
