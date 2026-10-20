"""The collider steps in real Blender (T1): collider_create imports full_body.clsp.3 onto the MH Wilds
armature (never the avatar's, which is in the scene too) and lists the chain groups to classify;
collider_apply writes the agreed clspFlags0/1, checking every entry before it writes any."""
import json

import bpy
import pytest

from modpilot.core.errors import StepError
from modpilot.testing.rigs import TYPES, call, chains, grafted, groups, transplant

TARGET = "MHWilds_Female Armature"


def _chained():
    grafted()
    transplant()
    return chains({"inferred_types": TYPES})["data"]


def test_create_binds_every_collider_to_a_bone_of_the_target_armature():
    _chained()
    r = call("collider_create")
    info = r["data"]["collider_info"]
    tgt = bpy.data.objects[TARGET]
    # a capsule is a root (no bone) holding a start and an end sphere, each CHILD_OF its bone
    roots = [c for c in info["colliders"] if c["type"].endswith("_ROOT")]
    assert len(roots) == 21
    for c in info["colliders"]:
        assert bpy.data.objects[c["name"]].get("TYPE", "").startswith("RE_CHAIN_COLLISION")
        if c not in roots:
            assert c["bone"] in tgt.data.bones, c
    assert not r["warnings"]
    col = bpy.data.collections[info["clsp_collection"]]
    assert {c["name"] for c in info["colliders"]} <= {o.name for o in col.all_objects}
    assert json.loads(bpy.context.scene["modpilot_config"])["clsp_collection"] == col.name


def test_create_lists_each_chain_group_with_its_head_bone_and_flags():
    _chained()
    info = call("collider_create")["data"]["collider_info"]
    heads = {g["parent_bone"]: g for g in info["chain_groups"]}
    assert {"Ribbon", "Tail", "Ear"} <= set(heads)
    assert heads["Tail"]["name"] == groups()["Tail"].name
    assert isinstance(heads["Tail"]["clspFlags0"], int) and isinstance(heads["Tail"]["clspFlags1"], int)


def test_a_chain_collection_hint_must_be_a_collection():
    r = _chained()
    info = call("collider_create", {"chain_collection": r["chain_collection"]})["data"]["collider_info"]
    assert len(info["chain_groups"]) == len(groups())
    with pytest.raises(StepError) as e:
        call("collider_create", {"chain_collection": "NoSuch.chain2"})
    assert e.value.category == "params"


def test_create_needs_an_armature():
    _chained()
    with pytest.raises(StepError) as e:
        call("collider_create", {"target_armature": "Nope"})
    assert e.value.category == "precondition"


def test_apply_writes_both_flag_forms():
    _chained()
    call("collider_create")
    g = groups()
    r = call("collider_apply", {"target_armature": TARGET, "chain_flags": {
        g["Tail"].name: 0x800001, g["Ribbon"].name: {"clspFlags0": 2, "clspFlags1": 4}}})["data"]
    assert sorted(a["name"] for a in r["applied"]) == sorted([g["Tail"].name, g["Ribbon"].name])
    assert (g["Tail"].re_chain_chaingroup.clspFlags0, g["Tail"].re_chain_chaingroup.clspFlags1) == (0x800001, 0)
    assert (g["Ribbon"].re_chain_chaingroup.clspFlags0, g["Ribbon"].re_chain_chaingroup.clspFlags1) == (2, 4)


@pytest.mark.parametrize("bad, category", [
    ({"NoSuchGroup": 0}, "precondition"),
    ({"<tail>": 0x100000}, "params"),
    ({"<tail>": "1"}, "params"),
    ({}, "params"),
])
def test_apply_checks_every_entry_before_writing_any(bad, category):
    _chained()
    call("collider_create")
    g = groups()
    before = g["Ribbon"].re_chain_chaingroup.clspFlags0
    flags = {g["Ribbon"].name: 2, **{k.replace("<tail>", g["Tail"].name): v for k, v in bad.items()}}
    if not bad:
        flags = {}
    with pytest.raises(StepError) as e:
        call("collider_apply", {"chain_flags": flags})
    assert e.value.category == category
    assert g["Ribbon"].re_chain_chaingroup.clspFlags0 == before
