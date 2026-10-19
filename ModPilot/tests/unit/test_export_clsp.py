"""batch_export binds the colliders Phase 4C built (ModPilot lesson #47).

batch_export bound mesh / mdf2 / chain2 only, so the clsp collection collider_create imported was
never exported: every chain's collision mask pointed at a blank clsp in game (claude_run1 bound it
by hand). The clsp RE Chain Editor imports is the collection tagged ~TYPE = RE_CLSP_COLLECTION;
with exactly one in the scene it is bound for the target parts, an explicit `clsp_collection`
overrides that ("" binds none), and several without an explicit choice fail instead of guessing.
"""

from unittest.mock import MagicMock

import pytest

from app.blender.state import SceneCache
from app.phases.batch_export import BatchExport

pytestmark = pytest.mark.unit

PARAMS = {"armor_id": "pl024", "armor_variant": "ff", "target_parts": ["2"],
          "mesh_collection": "M.mesh", "mdf2_collection": "M.mdf2", "chain2_collection": "M.chain2",
          "target_armature": "MHWilds_Female Armature", "fbxskel_name": "Maya", "natives_root": "C:/out"}


def _client(configure_lines):
    client = MagicMock()
    client.execute_and_extract.side_effect = [["OK"], ['{"warnings": {}}'], configure_lines, ["{'FINISHED'}"]]
    client.get_scene_info.return_value = {"name": "Scene", "object_count": 0, "objects": [], "materials_count": 0}
    return client


def _configure_code(client):
    return client.execute_and_extract.call_args_list[2].args[0]


def test_the_clsp_binding_is_cleared_with_the_others():
    client = _client(["CONFIGURED", "CLSP:full_body.clsp"])
    BatchExport().run(client, SceneCache(client), PARAMS)
    code = _configure_code(client)
    for part in "12345":
        assert f"scene.pop('mhws_pl024_{part}_clsp', None)" in code


def test_the_imported_clsp_is_found_by_its_collection_tag_and_bound_to_the_target_parts():
    client = _client(["CONFIGURED", "CLSP:full_body.clsp"])
    result = BatchExport().run(client, SceneCache(client), {**PARAMS, "target_parts": ["2", "4"]})
    code = _configure_code(client)
    assert "RE_CLSP_COLLECTION" in code
    assert "for _part in ['2', '4']:" in code
    assert "scene['mhws_pl024_' + _part + '_clsp'] = _clsp" in code
    assert result.success
    assert result.state_diff["clsp_collection"] == "full_body.clsp"


def test_an_explicit_clsp_collection_is_used_as_given():
    client = _client(["CONFIGURED", "CLSP:My.clsp"])
    BatchExport().run(client, SceneCache(client), {**PARAMS, "clsp_collection": "My.clsp"})
    assert "_clsp = 'My.clsp'" in _configure_code(client)


def test_no_clsp_leaves_it_blank():
    client = _client(["CONFIGURED", "CLSP:"])
    result = BatchExport().run(client, SceneCache(client), PARAMS)
    assert result.success
    assert result.state_diff["clsp_collection"] is None


def test_several_clsp_collections_without_a_choice_fail():
    client = _client(["PRECONDITION:clsp_ambiguous:A.clsp,B.clsp"])
    result = BatchExport().run(client, SceneCache(client), PARAMS)
    assert not result.success
    assert result.error.category == "precondition"
    assert "clsp_collection" in result.error.suggestion


def test_the_armor_id_example_is_not_pl001():
    """pl001 hosts none of kevin's verified BoneSystem mods, and ModPilot's August pl001 build lost
    its custom bones in game (board cf4863aa); the example the LLM copies must not point there."""
    desc = BatchExport.tool_schema()["input_schema"]["properties"]["armor_id"]["description"]
    assert "e.g. 'pl001'" not in desc
    assert "pl001" in desc  # named as the slot to avoid
    client = MagicMock()
    result = BatchExport().run(client, SceneCache(client), {**PARAMS, "armor_id": ""})
    assert "pl001" not in result.error.message
