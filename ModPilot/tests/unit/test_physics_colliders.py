"""Unit tests for physics_colliders.py (Phase 4C).

Focus:
  - clsp_body_bits.json catalog integrity (21 bits: the 20 body regions + hip_wide 0x800000)
  - bit helpers (mask_for_keys / keys_for_mask round-trip)
  - ColliderCreate: tool metadata, scan-only success path, missing-op fallback
  - ColliderApply: tool metadata, param validation, flag assignment, dict shape

Run: uv run pytest -m unit tests/unit/test_physics_colliders.py -v
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.phases.physics_colliders import (
    _BITS_PATH,
    ColliderApply,
    ColliderCreate,
    keys_for_mask,
    list_body_bit_keys,
    mask_for_keys,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


def _client(*outputs: list[str]) -> MagicMock:
    """Mock BlenderClient with a side-effect list of execute_and_extract outputs."""
    client = MagicMock()
    client.execute_and_extract.side_effect = list(outputs)
    return client


def _cache() -> MagicMock:
    cache = MagicMock()
    cache.refresh.return_value = MagicMock()
    cache.refresh.return_value.diff.return_value = {}
    return cache


# ── clsp_body_bits.json integrity ────────────────────────────────────────────


@pytest.mark.unit
class TestClspBodyBitsJson:
    def test_file_exists(self):
        assert _BITS_PATH.exists(), f"clsp_body_bits.json not found at {_BITS_PATH}"

    def test_file_is_valid_json(self):
        data = json.loads(_BITS_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_has_exactly_21_bits(self):
        # one per collider of full_body.clsp.3 (20 body regions + the wide hip sphere)
        data = json.loads(_BITS_PATH.read_text(encoding="utf-8"))
        assert len(data["bits"]) == 21

    def test_each_entry_has_bit_and_label(self):
        data = json.loads(_BITS_PATH.read_text(encoding="utf-8"))
        for key, entry in data["bits"].items():
            assert "bit" in entry, f"key {key!r} missing 'bit'"
            assert "label" in entry, f"key {key!r} missing 'label'"
            assert isinstance(entry["bit"], int), f"key {key!r} bit must be int"

    def test_bits_are_distinct_powers_of_two(self):
        data = json.loads(_BITS_PATH.read_text(encoding="utf-8"))
        bits = [e["bit"] for e in data["bits"].values()]
        assert len(set(bits)) == 21, "bit values must be distinct"
        for b in bits:
            assert b > 0 and (b & (b - 1)) == 0, f"bit {b:#x} is not a power of two"

    def test_full_mask_is_20_low_bits_plus_the_wide_hip(self):
        data = json.loads(_BITS_PATH.read_text(encoding="utf-8"))
        full = 0
        for entry in data["bits"].values():
            full |= entry["bit"]
        assert full == 0xFFFFF | 0x800000, f"OR of all bits should be 0x8FFFFF, got {full:#x}"

    def test_known_bit_positions(self):
        """Spot-check the canonical bit values from the issue spec."""
        data = json.loads(_BITS_PATH.read_text(encoding="utf-8"))
        bits = data["bits"]
        assert bits["hip"]["bit"] == 0x00001
        assert bits["spine_0"]["bit"] == 0x00002
        assert bits["head"]["bit"] == 0x02000
        assert bits["l_thigh"]["bit"] == 0x04000
        assert bits["r_foot"]["bit"] == 0x80000


# ── bit helpers ──────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestBitHelpers:
    def test_list_body_bit_keys_returns_21(self):
        keys = list_body_bit_keys()
        assert len(keys) == 21

    def test_mask_for_keys_single(self):
        assert mask_for_keys(["spine_0"]) == 0x00002

    def test_mask_for_keys_multiple(self):
        # spine_0 | spine_1 | spine_2 == 0x2 | 0x4 | 0x8 == 0xE
        assert mask_for_keys(["spine_0", "spine_1", "spine_2"]) == 0x0000E

    def test_mask_for_keys_unknown_key_raises(self):
        with pytest.raises(KeyError):
            mask_for_keys(["not_a_real_part"])

    def test_keys_for_mask_round_trip(self):
        original = ["head", "spine_1", "l_thigh"]
        mask = mask_for_keys(original)
        assert sorted(keys_for_mask(mask)) == sorted(original)

    def test_keys_for_mask_empty(self):
        assert keys_for_mask(0) == []

    def test_keys_for_mask_full(self):
        assert sorted(keys_for_mask(0xFFFFF | 0x800000)) == sorted(list_body_bit_keys())


# ── ColliderCreate ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestColliderCreate:
    tool = ColliderCreate()

    def test_name(self):
        assert self.tool.name == "collider_create"

    def test_does_not_advance_phase(self):
        # Sub-step tool — Step 3 (collider_apply) is what advances.
        assert self.tool.advances_phase is False

    def test_phase_slot_is_4c(self):
        # advances_phase=False so slot is not strictly enforced, but declaring
        # it documents intent and keeps parity with PhysicsChains prepare_only.
        assert self.tool.phase_slot == "phase_4c"

    def test_tool_schema_shape(self):
        schema = ColliderCreate.tool_schema()
        assert schema["name"] == "collider_create"
        assert "description" in schema
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"

    def test_success_returns_collider_info(self):
        """Happy path: operator FINISHED + scan returns collider list and groups."""
        scan_payload = {
            "colliders": [
                {"name": "Collider_Spine_0", "bone": "Spine_0", "type": "CAPSULE"},
                {"name": "Collider_Head", "bone": "Head", "type": "SPHERE"},
            ],
            "chain_groups": [
                {
                    "name": "CHAIN_GROUP_0",
                    "parent_bone": "Hair_Front_001",
                    "clspFlags0": -1,
                    "clspFlags1": 0,
                },
            ],
            "clsp_collection": "Chain Clsps - MHWilds_Female.clsp",
        }
        client = _client(["FULL_BODY:" + json.dumps(scan_payload)])
        result = self.tool.run(client, _cache(), {})
        assert result.success, result.error.message if result.error else "no error"
        info = result.state_diff["collider_info"]
        assert len(info["colliders"]) == 2
        assert len(info["chain_groups"]) == 1
        assert info["chain_groups"][0]["parent_bone"] == "Hair_Front_001"
        assert info["clsp_collection"] == "Chain Clsps - MHWilds_Female.clsp"

    def test_missing_operator_fails_with_precondition(self):
        """If RE Chain Editor's re_clsp.importfile is missing, return a precondition
        error pointing at the RE Chain Editor install."""
        client = _client(["MISSING_OP:re_clsp.importfile"])
        result = self.tool.run(client, _cache(), {})
        assert not result.success
        assert result.error.category == "precondition"
        assert "re_clsp.importfile" in result.error.message
        assert "RE Chain Editor" in result.error.suggestion

    def test_operator_cancelled_fails(self):
        client = _client(["CANCELLED:{'CANCELLED'}"])
        result = self.tool.run(client, _cache(), {})
        assert not result.success
        assert result.error.category == "operator_failed"

    # Which armature the colliders bind to. Found by the tools-5.2 L3 coverage replay
    # (2026-10-12): after Phase 4B the scene holds the avatar's armature AND the MH Wilds one,
    # with no armature active, so re_clsp.importfile (bound to the active object) cancelled
    # with "More than one armature was found in the scene", in Blender 4.3 and 5.2 alike.

    def test_schema_takes_an_optional_target_armature(self):
        schema = ColliderCreate.tool_schema()["input_schema"]
        assert "target_armature" in schema["properties"]
        assert "target_armature" not in schema.get("required", [])

    def test_binds_to_the_mhwilds_armature_not_the_active_object(self, monkeypatch):
        imports, out = _run_create_with_fake_bpy(self.tool, {}, monkeypatch)
        assert [kw["targetArmature"] for kw in imports] == ["MHWilds_Female Armature.data"]

    def test_an_explicit_target_armature_wins(self, monkeypatch):
        imports, out = _run_create_with_fake_bpy(self.tool, {"target_armature": "Armature"}, monkeypatch)
        assert [kw["targetArmature"] for kw in imports] == ["Armature.data"]

    def test_a_missing_target_armature_is_not_imported_onto_something_else(self, monkeypatch):
        imports, out = _run_create_with_fake_bpy(self.tool, {"target_armature": "Nope"}, monkeypatch)
        assert imports == []
        assert "NO_ARMATURE:Nope" in out

    def test_a_missing_target_armature_fails_with_precondition(self):
        client = _client(["NO_ARMATURE:MHWilds_Female Armature"])
        result = self.tool.run(client, _cache(), {})
        assert not result.success
        assert result.error.category == "precondition"
        assert "MHWilds_Female Armature" in result.error.message


class _FakeObj:
    def __init__(self, name, type_):
        self.name, self.type, self.constraints = name, type_, []
        self.data = type("Data", (), {"name": f"{name}.data"})() if type_ == "ARMATURE" else None

    def get(self, key, default=None):
        return default


class _FakeObjects(dict):
    """bpy.data.objects: .get(name) by name, iteration over the objects."""

    def __iter__(self):
        return iter(list(self.values()))


def _run_create_with_fake_bpy(tool, params, monkeypatch):
    """Run ColliderCreate's Blender-side code against a scene like a real one after Phase 4B
    (the avatar's armature, the MH Wilds armature, a mesh active); return (importfile kwargs, stdout)."""
    import contextlib
    import io
    import sys
    from types import SimpleNamespace

    client = _client(["CANCELLED:{'CANCELLED'}"])
    tool.run(client, _cache(), params)
    code = client.execute_and_extract.call_args[0][0]

    imports = []

    def importfile(**kwargs):
        imports.append(kwargs)
        return {"CANCELLED"}

    re_clsp = SimpleNamespace(importfile=importfile)
    objs = [_FakeObj("Armature", "ARMATURE"), _FakeObj("MHWilds_Female Armature", "ARMATURE"),
            _FakeObj("Body", "MESH")]
    fake = SimpleNamespace(
        data=SimpleNamespace(objects=_FakeObjects({o.name: o for o in objs})),
        context=SimpleNamespace(active_object=objs[2]),
        ops=SimpleNamespace(re_clsp=re_clsp),
    )
    monkeypatch.setitem(sys.modules, "bpy", fake)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(code, {})
    return imports, out.getvalue()


# ── ColliderApply ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestColliderApply:
    tool = ColliderApply()

    def test_name(self):
        assert self.tool.name == "collider_apply"

    def test_advances_phase(self):
        assert self.tool.advances_phase is True

    def test_phase_slot_is_4c(self):
        assert self.tool.phase_slot == "phase_4c"

    def test_requires_user_pause(self):
        # Collider masks land mid-pipeline — checkpoint before Phase 5 material work.
        assert self.tool.requires_user_pause is True

    def test_tool_schema_shape(self):
        schema = ColliderApply.tool_schema()
        assert schema["name"] == "collider_apply"
        props = schema["input_schema"]["properties"]
        assert "chain_flags" in props
        assert "chain_flags" in schema["input_schema"]["required"]

    def test_empty_chain_flags_fails(self):
        result = self.tool.run(_client(), _cache(), {"chain_flags": {}})
        assert not result.success
        assert result.error.category == "precondition"

    def test_missing_chain_flags_fails(self):
        result = self.tool.run(_client(), _cache(), {})
        assert not result.success

    def test_int_flag_shorthand_writes_flags0(self):
        """A bare int value sets clspFlags0 and leaves clspFlags1 untouched (0)."""
        payload = {
            "applied": [
                {"name": "CHAIN_GROUP_0", "clspFlags0": 0x41000, "clspFlags1": 0, "status": "ok"},
            ],
            "not_found": [],
            "errors": [],
        }
        client = _client(["APPLIED:" + json.dumps(payload)])
        result = self.tool.run(
            client,
            _cache(),
            {"chain_flags": {"CHAIN_GROUP_0": 0x41000}},
        )
        assert result.success
        assert result.state_diff["applied"][0]["clspFlags0"] == 0x41000

    def test_dict_flag_writes_both_words(self):
        """Dict form {clspFlags0, clspFlags1} sets both."""
        payload = {
            "applied": [
                {"name": "CHAIN_GROUP_0", "clspFlags0": 0x41000, "clspFlags1": 0x1, "status": "ok"},
            ],
            "not_found": [],
            "errors": [],
        }
        client = _client(["APPLIED:" + json.dumps(payload)])
        result = self.tool.run(
            client,
            _cache(),
            {
                "chain_flags": {
                    "CHAIN_GROUP_0": {"clspFlags0": 0x41000, "clspFlags1": 0x1}
                }
            },
        )
        assert result.success
        diff = result.state_diff["applied"][0]
        assert diff["clspFlags0"] == 0x41000
        assert diff["clspFlags1"] == 0x1

    def test_not_found_group_surfaced_as_warning(self):
        """A name in chain_flags that doesn't exist in the scene reports as not_found
        but the phase still advances — partial application is informative."""
        payload = {
            "applied": [
                {"name": "CHAIN_GROUP_0", "clspFlags0": 0, "clspFlags1": 0, "status": "ok"},
            ],
            "not_found": ["GHOST_GROUP"],
            "errors": [],
        }
        client = _client(["APPLIED:" + json.dumps(payload)])
        result = self.tool.run(
            client,
            _cache(),
            {"chain_flags": {"CHAIN_GROUP_0": 0, "GHOST_GROUP": 0}},
        )
        assert result.success
        assert "GHOST_GROUP" in result.state_diff["not_found"]

    def test_invalid_flag_value_type_fails(self):
        result = self.tool.run(
            _client(),
            _cache(),
            {"chain_flags": {"CHAIN_GROUP_0": "not an int"}},
        )
        assert not result.success
        assert result.error.category == "precondition"

    def test_flag_value_out_of_range_fails(self):
        # 0xFFFFF is the max valid 20-bit mask; anything above is bogus.
        result = self.tool.run(
            _client(),
            _cache(),
            {"chain_flags": {"CHAIN_GROUP_0": 0x100000000}},
        )
        assert not result.success
