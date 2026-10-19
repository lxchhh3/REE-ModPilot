"""physics_chains SHARED mode: one chain settings object per inferred type (board e20281fe).

_consolidate_chain_settings looked for 'RE_CHAIN_CHAINNODE' children with a 'parent_bone'
property and reassigned groups through a 'chainSetting' property; none of the three exists in RE
Chain Editor, so it mapped 0 groups and every chain got the alphabetically-first type. A group's
head is its first RE_CHAIN_NODE child's BoneName bone, and a group belongs to the settings object
it is PARENTED to. Behaviour in Blender: tools-5.2 tests/test_l3_fixes.py (SHARED scenario).
"""

import json
from unittest.mock import MagicMock

import pytest

from app.phases.physics_bones import PhysicsChains

pytestmark = pytest.mark.unit


def _client(lines):
    client = MagicMock()
    client.execute_and_extract.return_value = lines
    return client


def _consolidation_code(inferred):
    client = _client([])
    PhysicsChains()._consolidate_chain_settings(client, "CS_0", "col", inferred)
    return client.execute_and_extract.call_args[0][0]


def test_consolidation_reads_heads_the_way_re_chain_editor_does():
    code = _consolidation_code({"Ribbon": "accessory_ribbon", "Tail": "fur_tail"})
    assert "'RE_CHAIN_NODE'" in code
    assert "constraints.get('BoneName')" in code
    assert "RE_CHAIN_CHAINNODE" not in code
    assert "parent_bone" not in code


def test_consolidation_moves_groups_by_parent():
    code = _consolidation_code({"Ribbon": "accessory_ribbon", "Tail": "fur_tail"})
    assert "cg.parent = target" in code
    assert "chainSetting" not in code


def test_an_untouched_settings_object_reaches_apply_as_the_empty_type():
    payload = {"cs_to_type": {"CS_0": "", "CS_1": "accessory_ribbon", "CS_2": "fur_tail"},
               "type_to_cs": {"accessory_ribbon": "CS_1", "fur_tail": "CS_2"}, "errors": [],
               "unmapped": ["CHAIN_GROUP_02_Ear:Ear"]}
    client = _client(["CONSOLIDATED:" + json.dumps(payload)])
    _, cs_to_type = PhysicsChains()._consolidate_chain_settings(
        client, "CS_0", "col", {"Ribbon": "accessory_ribbon", "Tail": "fur_tail"})
    assert cs_to_type == payload["cs_to_type"]


def test_apply_by_type_sets_nothing_on_the_empty_type_and_reports_it():
    client = _client(["APPLIED:[]"])
    PhysicsChains()._apply_params_by_type(client, {"CS_0": "", "CS_1": "hair_short"},
                                          {"aa": "hair_short"}, {"aa": {"damping": 0.1}})
    code = client.execute_and_extract.call_args[0][0]
    params_list = json.loads(code.split("params_list = json.loads(", 1)[1].split(")\n", 1)[0].strip("'"))
    assert params_list[0] == {}
    assert "untouched: no inferred_type for chain head" in code
