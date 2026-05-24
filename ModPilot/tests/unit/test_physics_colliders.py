"""Unit tests for physics_colliders.py (Phase 4C).

Focus:
  - clsp_body_bits.json catalog integrity (20 bits, monotonic, sum == 0xFFFFF)
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

    def test_has_exactly_20_bits(self):
        data = json.loads(_BITS_PATH.read_text(encoding="utf-8"))
        assert len(data["bits"]) == 20

    def test_each_entry_has_bit_and_label(self):
        data = json.loads(_BITS_PATH.read_text(encoding="utf-8"))
        for key, entry in data["bits"].items():
            assert "bit" in entry, f"key {key!r} missing 'bit'"
            assert "label" in entry, f"key {key!r} missing 'label'"
            assert isinstance(entry["bit"], int), f"key {key!r} bit must be int"

    def test_bits_are_distinct_powers_of_two(self):
        data = json.loads(_BITS_PATH.read_text(encoding="utf-8"))
        bits = [e["bit"] for e in data["bits"].values()]
        assert len(set(bits)) == 20, "bit values must be distinct"
        for b in bits:
            assert b > 0 and (b & (b - 1)) == 0, f"bit {b:#x} is not a power of two"

    def test_full_mask_is_20_low_bits(self):
        data = json.loads(_BITS_PATH.read_text(encoding="utf-8"))
        full = 0
        for entry in data["bits"].values():
            full |= entry["bit"]
        assert full == 0xFFFFF, f"OR of all bits should be 0xFFFFF, got {full:#x}"

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
    def test_list_body_bit_keys_returns_20(self):
        keys = list_body_bit_keys()
        assert len(keys) == 20

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
        assert sorted(keys_for_mask(0xFFFFF)) == sorted(list_body_bit_keys())


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
        """If create_full_body_clsp op missing, return precondition error pointing
        at the WildsChain plugin install."""
        client = _client(["MISSING_OP:re_chain.create_full_body_clsp"])
        result = self.tool.run(client, _cache(), {})
        assert not result.success
        assert result.error.category == "precondition"
        assert "create_full_body_clsp" in result.error.message
        assert "Wilds Chain Editor" in result.error.suggestion or "chain editor" in result.error.suggestion.lower()

    def test_operator_cancelled_fails(self):
        client = _client(["CANCELLED:{'CANCELLED'}"])
        result = self.tool.run(client, _cache(), {})
        assert not result.success
        assert result.error.category == "operator_failed"


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
