"""The physics steps in real Blender (T1): physics_transplant (smart_graft + the `_End` bones it
can't see after the join, ModPilot lesson #49), physics_classification (chain heads),
physics_chains (prepare / SEPARATE / SHARED settings, MH Wilds header calibration, angle ramp,
merges with their `_End` leaves), physics_adjust. Includes tools-5.2's group-A graft and shared
scenarios (tests/test_l3_fixes.py)."""
import json

import bpy
import pytest

from modpilot import physics
from modpilot.core.errors import StepError
from modpilot.testing.rigs import TYPES
from modpilot.testing.rigs import call as _call
from modpilot.testing.rigs import chains as _chains
from modpilot.testing.rigs import grafted as _grafted
from modpilot.testing.rigs import groups as _groups
from modpilot.testing.rigs import transplant as _transplant

# ── physics_transplant ────────────────────────────────────────────────────


def test_every_weighted_leaf_gets_its_end_bone_after_the_join():
    src = _grafted(ear=False)
    r = _transplant()["data"]
    tgt = bpy.data.objects["MHWilds_Female Armature"]
    assert sorted(r["end_bones_added"]) == ["Ribbon_End", "Tail.001_End"]
    for leaf in ("Ribbon", "Tail.001"):
        end = tgt.data.bones[leaf + "_End"]
        assert end.parent.name == leaf
        assert ((tgt.matrix_world @ end.head_local) - (src.matrix_world @ src.pose.bones[leaf].tail)).length < 1e-4
    assert "Helper_End" not in tgt.data.bones and "Tail_End" not in tgt.data.bones
    assert src.hide_viewport is True
    assert bpy.context.scene.mhw_suite_settings.import_preset_enum == "mhws.json"


# ── physics_classification ────────────────────────────────────────────────


def test_classification_lists_the_chain_heads():
    _grafted()
    _transplant()
    heads = {h["name"]: h for h in _call("physics_classification")["data"]["chain_topology"]["chain_heads"]}
    assert {"Ribbon", "Tail", "Ear"} <= set(heads)
    assert heads["Tail"]["role"] == "head" and heads["Tail"]["depth"] >= 2 and heads["Tail"]["parent"]
    assert bpy.context.mode == "OBJECT"


# ── physics_chains ────────────────────────────────────────────────────────


def _matches(cs, itype):
    want = physics.params_for(itype)
    pg = cs.re_chain_chainsettings
    return all(abs(getattr(pg, k) - v) < 1e-4 for k, v in want.items()
               if isinstance(v, float | int) and not isinstance(v, bool) and hasattr(pg, k)
               and not isinstance(getattr(pg, k), str))


def test_prepare_only_refreshes_the_marks_and_says_so():
    _grafted()
    _transplant()
    r = _call("physics_chains", {"prepare_only": True})["data"]
    assert "Chain role marks refreshed" in r["message"]
    tgt = bpy.data.objects["MHWilds_Female Armature"]
    assert tgt.pose.bones["Ribbon"].get("chain_role") == "head"


def test_separate_settings_take_each_heads_type_and_leave_untyped_ones_alone():
    _grafted()
    _transplant()
    r = _chains({"inferred_types": TYPES})["data"]
    g = _groups()
    assert {"Ribbon", "Tail", "Ear"} <= set(g)
    assert len({g[h].parent.name for h in ("Ribbon", "Tail", "Ear")}) == 3
    assert _matches(g["Ribbon"].parent, "accessory_ribbon") and _matches(g["Tail"].parent, "fur_tail")
    assert any("untouched" in s and "Ear" in s for s in r["skipped_params"])
    assert set(r["chain_settings_created"]) >= {g[h].parent.name for h in ("Ribbon", "Tail")}


def test_shared_settings_give_each_type_its_own_object():
    _grafted()
    _transplant()
    r = _chains({"inferred_types": TYPES, "settings_mode": "SHARED"})["data"]
    g = _groups()
    assert len({g[h].parent.name for h in ("Ribbon", "Tail", "Ear")}) == 3
    assert _matches(g["Ribbon"].parent, "accessory_ribbon") and _matches(g["Tail"].parent, "fur_tail")
    assert any("untouched" in s and "Ear" in s for s in r["skipped_params"])


def test_the_chain_header_gets_the_mh_wilds_calibration_and_the_collection_is_recorded():
    _grafted()
    _transplant()
    r = _chains({"inferred_types": TYPES})
    col = bpy.data.collections[r["data"]["chain_collection"]]
    header = next(o for o in col.all_objects if o.get("TYPE") == "RE_CHAIN_HEADER").re_chain_header
    assert (header.calculateMode, header.chainAttrFlags, header.highFPSCalculateMode) == ("3", "4", "2")
    assert header.calculateStepTime == pytest.approx(2.0)
    assert json.loads(bpy.context.scene["modpilot_config"])["chain2_collection"] == col.name


def test_the_angle_limits_ramp_down_each_chain():
    _grafted()
    _transplant()
    _chains({"inferred_types": TYPES})
    nodes = [c for c in _groups()["Tail"].children_recursive if c.get("TYPE") == "RE_CHAIN_NODE"]
    limits = [n.re_chain_chainnode.angleLimitRad for n in nodes]
    # RE Chain Editor's ramp: node i gets max * (i + 1) / maxIteration, from node maxIteration-1 on max
    assert limits and min(limits) == pytest.approx(1.047198 / 4, abs=1e-5)
    assert max(limits) <= 1.047198 + 1e-5


def test_merged_bones_take_their_end_leaves_with_them():
    _grafted()
    _transplant()
    r = _chains({"inferred_types": {"Tail": "fur_tail"}, "bones_to_merge": ["Ribbon"],
                 "bones_to_clear": ["NoSuchBone"]})
    tgt = bpy.data.objects["MHWilds_Female Armature"]
    assert "Ribbon" not in tgt.data.bones and "Ribbon_End" not in tgt.data.bones
    assert r["data"]["end_cascade_added"] == ["Ribbon_End"]
    assert any("NoSuchBone" in w for w in r["warnings"])


@pytest.mark.parametrize("params", [{"inferred_types": {}}, {"inferred_types": {"Tail": "no_such_type"}},
                                    {"inferred_types": TYPES, "settings_mode": "BOTH"}])
def test_bad_chain_params_fail_before_touching_the_scene(params):
    _grafted()
    _transplant()
    with pytest.raises(StepError) as e:
        _call("physics_chains", params)
    assert e.value.category == "params"
    assert not [o for o in bpy.data.objects if o.get("TYPE") == "RE_CHAIN_CHAINGROUP"]


# ── physics_adjust ────────────────────────────────────────────────────────


def test_adjust_sets_scalars_and_vectors():
    _grafted()
    _transplant()
    _chains({"inferred_types": TYPES})
    cs = _groups()["Tail"].parent
    r = _call("physics_adjust", {"targets": [cs.name], "properties": {"damping": 0.3, "gravity": [0, -2.0, 0]}})
    assert r["data"] == {"adjusted_targets": [cs.name]}   # the legacy tool's result
    assert cs.re_chain_chainsettings.damping == pytest.approx(0.3)
    assert tuple(cs.re_chain_chainsettings.gravity) == pytest.approx((0, -2.0, 0))


def test_adjust_refuses_unknown_targets_and_properties_before_changing_anything():
    _grafted()
    _transplant()
    _chains({"inferred_types": TYPES})
    cs = _groups()["Tail"].parent
    before = cs.re_chain_chainsettings.damping
    for params, category in (({"targets": ["Nope"], "properties": {"damping": 0.3}}, "precondition"),
                             ({"targets": [cs.name], "properties": {"damping": 0.3, "dampnig": 1}}, "params")):
        with pytest.raises(StepError) as e:
            _call("physics_adjust", params)
        assert e.value.category == category
    assert cs.re_chain_chainsettings.damping == before
