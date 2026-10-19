"""
Unit tests for physics_bones.py (Phase 3.5, 4A, 4B).

Focus:
  - physics_presets.json loading + get_physics_params / list_inferred_types
  - PhysicsTransplant param validation
  - PhysicsClassification param validation + chain topology parsing
  - PhysicsChains param validation, inferred_type resolution, and
    _apply_params_to_chain_settings ordering logic

Run with: uv run pytest -m unit tests/unit/test_physics_bones.py -v
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.phases.physics_bones import (
    _PRESETS_PATH,
    PhysicsChains,
    PhysicsClassification,
    PhysicsTransplant,
    get_physics_params,
    list_inferred_types,
)

# ── fixtures ──────────────────────────────────────────────────────────────────


def _make_client(output_lines: list[str]) -> MagicMock:
    client = MagicMock()
    client.execute_and_extract.return_value = output_lines
    return client


def _make_cache() -> MagicMock:
    cache = MagicMock()
    cache.refresh.return_value = MagicMock()
    cache.refresh.return_value.diff.return_value = {}
    return cache


# ── physics_presets.json integrity ───────────────────────────────────────────


@pytest.mark.unit
class TestPresetsJson:
    def test_file_exists(self):
        assert _PRESETS_PATH.exists(), f"physics_presets.json not found at {_PRESETS_PATH}"

    def test_file_is_valid_json(self):
        data = json.loads(_PRESETS_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_types_key_present(self):
        data = json.loads(_PRESETS_PATH.read_text(encoding="utf-8"))
        assert "types" in data

    def test_all_types_have_params(self):
        data = json.loads(_PRESETS_PATH.read_text(encoding="utf-8"))
        for type_name, entry in data["types"].items():
            assert "params" in entry, f"type {type_name!r} missing 'params'"

    def test_all_params_have_required_fields(self):
        required = {"gravity", "damping", "springForce", "windEffectCoef"}
        data = json.loads(_PRESETS_PATH.read_text(encoding="utf-8"))
        for type_name, entry in data["types"].items():
            params = entry["params"]
            missing = required - set(params)
            assert not missing, f"type {type_name!r} params missing: {missing}"

    def test_gravity_is_3_element_list(self):
        data = json.loads(_PRESETS_PATH.read_text(encoding="utf-8"))
        for type_name, entry in data["types"].items():
            g = entry["params"].get("gravity")
            if g is not None:
                assert isinstance(g, list) and len(g) == 3, (
                    f"type {type_name!r}: gravity must be [x, y, z], got {g!r}"
                )

    def test_non_reference_types_have_high_or_medium_confidence(self):
        data = json.loads(_PRESETS_PATH.read_text(encoding="utf-8"))
        for type_name, entry in data["types"].items():
            if type_name.startswith("_"):
                continue
            assert entry.get("confidence") in ("high", "medium"), (
                f"type {type_name!r} has unexpected confidence: {entry.get('confidence')}"
            )


# ── get_physics_params / list_inferred_types ─────────────────────────────────


@pytest.mark.unit
class TestHelperFunctions:
    def test_get_physics_params_known_type(self):
        params = get_physics_params("hair_short")
        assert params is not None
        assert "damping" in params
        assert "gravity" in params

    def test_get_physics_params_unknown_type_returns_none(self):
        assert get_physics_params("does_not_exist_xyz") is None

    def test_get_physics_params_returns_copy(self):
        p1 = get_physics_params("hair_short")
        p1["damping"] = 9999.0
        p2 = get_physics_params("hair_short")
        assert p2["damping"] != 9999.0

    def test_list_inferred_types_excludes_reference_types(self):
        types = list_inferred_types()
        assert all(not t.startswith("_") for t in types)

    def test_list_inferred_types_includes_hair_and_cloth(self):
        types = set(list_inferred_types())
        assert "hair_short" in types
        assert "cloth_skirt_waist" in types
        assert "body_jiggle" in types

    def test_list_inferred_types_at_least_15_entries(self):
        assert len(list_inferred_types()) >= 15


# ── PhysicsTransplant ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestPhysicsTransplant:
    tool = PhysicsTransplant()

    def test_name(self):
        assert self.tool.name == "physics_transplant"

    def test_tool_schema_shape(self):
        schema = PhysicsTransplant.tool_schema()
        assert schema["name"] == "physics_transplant"
        assert "description" in schema
        assert "input_schema" in schema

    def test_missing_source_armature_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {"target_armature": "MHWs", "x_preset": "MMD"},
        )
        assert not result.success
        assert result.error.category == "precondition"

    def test_missing_target_armature_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {"source_armature": "Body", "x_preset": "MMD"},
        )
        assert not result.success
        assert result.error.category == "precondition"

    def test_invalid_x_preset_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {
                "source_armature": "Body",
                "target_armature": "MHWs",
                "x_preset": "UnknownPreset",
            },
        )
        assert not result.success
        assert result.error.category == "precondition"

    def test_blender_finished_returns_ok(self):
        client = _make_client(["{'FINISHED'}"])
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "source_armature": "Body",
                "target_armature": "MHWs",
                "x_preset": "MMD",
            },
        )
        assert result.success

    def test_precondition_not_found_fails(self):
        client = _make_client(["PRECONDITION:not_found:MHWs"])
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "source_armature": "Body",
                "target_armature": "MHWs",
                "x_preset": "MMD",
            },
        )
        assert not result.success
        assert result.error.category == "precondition"


# ── PhysicsClassification ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestPhysicsClassification:
    tool = PhysicsClassification()

    def test_name(self):
        assert self.tool.name == "physics_classification"

    def test_missing_armature_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {"x_preset": "MMD"},
        )
        assert not result.success

    def test_invalid_preset_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {"target_armature": "MHWs", "x_preset": "BadPreset"},
        )
        assert not result.success

    def test_valid_chain_data_parsed_into_state_diff(self):
        chain_data = [
            {"name": "hair_001", "role": "head", "depth": 5, "parent": "head"},
        ]
        client = _make_client([f"CHAINS:{json.dumps(chain_data)}"])
        result = self.tool.run(
            client,
            _make_cache(),
            {"target_armature": "MHWs", "x_preset": "MMD"},
        )
        assert result.success
        assert "chain_topology" in result.state_diff
        assert result.state_diff["chain_topology"]["chain_heads"] == chain_data

    def test_precondition_not_found_fails(self):
        client = _make_client(["PRECONDITION:not_found:MHWs"])
        result = self.tool.run(
            client,
            _make_cache(),
            {"target_armature": "MHWs", "x_preset": "MMD"},
        )
        assert not result.success
        assert result.error.category == "precondition"

    def test_empty_output_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {"target_armature": "MHWs", "x_preset": "MMD"},
        )
        assert not result.success


# ── PhysicsChains ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestPhysicsChains:
    tool = PhysicsChains()

    def test_name(self):
        assert self.tool.name == "physics_chains"

    def test_tool_schema_lists_valid_inferred_types(self):
        schema = PhysicsChains.tool_schema()
        desc = schema["input_schema"]["properties"]["inferred_types"]["description"]
        assert "hair_short" in desc

    def test_missing_target_armature_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {
                "chain_collection": "ChainCol",
                "inferred_types": {"hair_001": "hair_short"},
                "x_preset": "MMD",
            },
        )
        assert not result.success

    def test_empty_inferred_types_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {
                "target_armature": "MHWs",
                "chain_collection": "ChainCol",
                "inferred_types": {},
                "x_preset": "MMD",
            },
        )
        assert not result.success

    def test_unknown_inferred_type_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {
                "target_armature": "MHWs",
                "chain_collection": "ChainCol",
                "inferred_types": {"hair_001": "unknown_xyz"},
                "x_preset": "MMD",
            },
        )
        assert not result.success
        assert "unknown_xyz" in result.error.message

    def test_invalid_settings_mode_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {
                "target_armature": "MHWs",
                "chain_collection": "ChainCol",
                "inferred_types": {"hair_001": "hair_short"},
                "x_preset": "MMD",
                "settings_mode": "INVALID",
            },
        )
        assert not result.success

    def test_successful_pipeline_returns_ok(self):
        new_cs = ["RE_CHAIN_CHAINSETTINGS_0"]
        # Responses (SEPARATE mode):
        #   validate, verify_marks, create, apply, angle_ramp
        client = MagicMock()
        client.execute_and_extract.side_effect = [
            ["OK"],
            [f"VERIFY:{json.dumps({'clean': True, 'suspicious': []})}"],
            [f"NEW_CS:{json.dumps({'new_cs': new_cs, 'col': 'MHWilds_Female.chain2'})}"],
            [f"APPLIED:{json.dumps([])}"],
            ["RAMP:{'FINISHED'}"],
        ]
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "chain_collection": "ChainCol",
                "inferred_types": {"hair_001": "hair_short"},
            },
        )
        assert result.success
        assert result.state_diff["chain_settings_created"] == new_cs

    def test_prepare_only_cleanup_succeeds_and_defers_verification(self):
        """prepare_only=True: validate + clear_and_refresh; verification is
        DEFERRED to the chain-creation branch (per the in-code note at
        physics_bones.py:657-668 — verifying here false-positives on bones
        that haven't yet been merged)."""
        client = MagicMock()
        # Responses: validate, clear_and_refresh
        client.execute_and_extract.side_effect = [
            ["OK"],
            ["OK"],
        ]
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "inferred_types": {},
                "prepare_only": True,
            },
        )
        assert result.success
        # No 'marks_clean' key — verification was deferred, not performed.
        assert "marks_clean" not in result.state_diff
        # Message advertises the deferral so the LLM/user knows to expect a
        # later verification pass in the chain-creation step.
        msg = result.state_diff["message"].lower()
        assert "deferred" in msg
        # Only validate + clear — no verify call in prepare_only.
        assert client.execute_and_extract.call_count == 2

    def test_prepare_only_clear_failure_propagates(self):
        """If clear_and_refresh fails (e.g. operator raises), prepare_only
        fails fast and does NOT touch downstream steps."""
        client = MagicMock()
        # validate ok, then clear_and_refresh signals operator failure.
        client.execute_and_extract.side_effect = [
            ["OK"],
            ["CLEAR_ERR:clear_chain_role exploded"],
        ]
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "inferred_types": {},
                "prepare_only": True,
            },
        )
        assert not result.success
        assert result.error.category == "operator_failed"
        assert client.execute_and_extract.call_count == 2

    def test_prepare_only_armature_not_found_fails(self):
        """prepare_only=True propagates precondition error from validate."""
        client = MagicMock()
        client.execute_and_extract.return_value = ["PRECONDITION:armature_not_found:MHWs"]
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "inferred_types": {},
                "prepare_only": True,
            },
        )
        assert not result.success
        assert result.error.category == "precondition"

    def test_bones_to_clear_runs_before_merge_and_creation(self):
        """merge fires first, then clear, then create chains.

        Order is deliberate (physics_bones.py:753-762): merge_into_parent's
        color-refresh would re-mark the just-cleared native bones as physics
        if clear ran first.
        """
        new_cs = ["RE_CHAIN_CHAINSETTINGS_0"]
        client = MagicMock()
        # Responses:
        #   validate, expand_end_children, merge, clear, verify_marks,
        #   create, apply, angle_ramp, header_tune
        client.execute_and_extract.side_effect = [
            ["OK"],
            ["EXTRAS:[]"],          # no _End children to cascade
            ["{'FINISHED'}"],
            ["{'FINISHED'}"],
            [f"VERIFY:{json.dumps({'clean': True, 'suspicious': []})}"],
            [f"NEW_CS:{json.dumps({'new_cs': new_cs, 'col': 'MHWilds_Female.chain2'})}"],
            [f"APPLIED:{json.dumps([])}"],
            ["RAMP:{'FINISHED'}"],
            [f"TUNED:HEADER_0:{json.dumps([])}"],
        ]
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "bones_to_clear": ["Cage", "Cage_L"],
                "bones_to_merge": ["Ribbon_root"],
                "inferred_types": {"hair_001": "hair_short"},
            },
        )
        assert result.success
        assert client.execute_and_extract.call_count == 9
        # merge call is index 2 (after validate + expand_end_children)
        merge_code = client.execute_and_extract.call_args_list[2][0][0]
        assert "Ribbon_root" in merge_code
        # clear call is index 3
        clear_code = client.execute_and_extract.call_args_list[3][0][0]
        assert "Cage" in clear_code
        assert "clear_chain_role" in clear_code

    def test_bones_to_clear_without_merge(self):
        """bones_to_clear works without bones_to_merge."""
        new_cs = ["RE_CHAIN_CHAINSETTINGS_0"]
        client = MagicMock()
        # Responses:
        #   validate, clear, verify_marks, create, apply, angle_ramp, header_tune
        client.execute_and_extract.side_effect = [
            ["OK"],
            ["{'FINISHED'}"],
            [f"VERIFY:{json.dumps({'clean': True, 'suspicious': []})}"],
            [f"NEW_CS:{json.dumps({'new_cs': new_cs, 'col': 'MHWilds_Female.chain2'})}"],
            [f"APPLIED:{json.dumps([])}"],
            ["RAMP:{'FINISHED'}"],
            [f"TUNED:HEADER_0:{json.dumps([])}"],
        ]
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "bones_to_clear": ["Cage"],
                "inferred_types": {"hair_001": "hair_short"},
            },
        )
        assert result.success
        assert client.execute_and_extract.call_count == 7

    def test_bones_to_clear_failure_stops_pipeline(self):
        """If clear_chain_role fails, phase fails without calling _create_chains."""
        client = MagicMock()
        client.execute_and_extract.side_effect = [
            ["OK"],
            ["PRECONDITION:armature_not_found"],
        ]
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "bones_to_clear": ["Cage"],
                "inferred_types": {"hair_001": "hair_short"},
            },
        )
        assert not result.success
        assert client.execute_and_extract.call_count == 2

    def test_bones_to_merge_runs_before_chain_creation(self):
        """bones_to_merge step fires before _create_chains."""
        new_cs = ["RE_CHAIN_CHAINSETTINGS_0"]
        client = MagicMock()
        # Responses (SEPARATE mode):
        #   validate, expand_end_children, merge, verify_marks, create,
        #   apply, angle_ramp, header_tune
        client.execute_and_extract.side_effect = [
            ["OK"],
            ["EXTRAS:[]"],
            ["{'FINISHED'}"],
            [f"VERIFY:{json.dumps({'clean': True, 'suspicious': []})}"],
            [f"NEW_CS:{json.dumps({'new_cs': new_cs, 'col': 'MHWilds_Female.chain2'})}"],
            [f"APPLIED:{json.dumps([])}"],
            ["RAMP:{'FINISHED'}"],
            [f"TUNED:HEADER_0:{json.dumps([])}"],
        ]
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "bones_to_merge": ["Ribbon_root"],
                "inferred_types": {"hair_001": "hair_short"},
            },
        )
        assert result.success
        assert client.execute_and_extract.call_count == 8
        # Merge call is now index 2 (after validate + expand_end_children).
        merge_code = client.execute_and_extract.call_args_list[2][0][0]
        assert "Ribbon_root" in merge_code
        assert "merge_into_parent" in merge_code

    def test_end_child_cascade_into_merge(self):
        """When bones_to_merge contains an auxiliary bone with a `*_End`
        child carrying chain_role (typical Phase-3.5 smart_graft output),
        the cascade helper appends that child so it's also merged — otherwise
        physics_chains would build a degenerate chain on the leftover leaf.
        """
        new_cs = ["RE_CHAIN_CHAINSETTINGS_0"]
        client = MagicMock()
        # validate → expand returns one extra _End child → merge → verify_marks
        # → create → apply → ramp
        client.execute_and_extract.side_effect = [
            ["OK"],
            ['EXTRAS:["Twist wrist_L_End"]'],
            ["{'FINISHED'}"],
            [f"VERIFY:{json.dumps({'clean': True, 'suspicious': []})}"],
            [f"NEW_CS:{json.dumps({'new_cs': new_cs, 'col': 'MHWilds_Female.chain2'})}"],
            [f"APPLIED:{json.dumps([])}"],
            ["RAMP:{'FINISHED'}"],
        ]
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "bones_to_merge": ["Twist wrist_L"],
                "inferred_types": {"hair_001": "hair_short"},
            },
        )
        assert result.success
        # The merge call (index 2) must contain BOTH the user-specified bone
        # AND the cascaded _End leaf.
        merge_code = client.execute_and_extract.call_args_list[2][0][0]
        assert "Twist wrist_L" in merge_code
        assert "Twist wrist_L_End" in merge_code

    def test_end_cascade_failure_is_non_fatal(self):
        """If the expand_end_children scan errors out (Blender-side glitch),
        the pipeline falls back to the original bones_to_merge list and
        continues — non-fatal."""
        from app.blender.client import BlenderError
        new_cs = ["RE_CHAIN_CHAINSETTINGS_0"]
        client = MagicMock()
        # validate → expand (throws) → merge → verify_marks → create →
        # apply → ramp
        client.execute_and_extract.side_effect = [
            ["OK"],
            BlenderError("blender went bonk"),  # expand step throws
            ["{'FINISHED'}"],
            [f"VERIFY:{json.dumps({'clean': True, 'suspicious': []})}"],
            [f"NEW_CS:{json.dumps({'new_cs': new_cs, 'col': 'MHWilds_Female.chain2'})}"],
            [f"APPLIED:{json.dumps([])}"],
            ["RAMP:{'FINISHED'}"],
        ]
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "bones_to_merge": ["Ribbon_root"],
                "inferred_types": {"hair_001": "hair_short"},
            },
        )
        # Merge proceeds with the original (unexpanded) list — pipeline still
        # completes successfully.
        assert result.success
        merge_code = client.execute_and_extract.call_args_list[2][0][0]
        assert "Ribbon_root" in merge_code

    def test_merge_failure_stops_pipeline(self):
        """If merge_into_parent fails, phase fails without calling _create_chains."""
        client = MagicMock()
        # validate, expand_end_children, merge (fails)
        client.execute_and_extract.side_effect = [
            ["OK"],
            ["EXTRAS:[]"],
            ["PRECONDITION:armature_not_found"],
        ]
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "bones_to_merge": ["Ribbon_root"],
                "inferred_types": {"hair_001": "hair_short"},
            },
        )
        assert not result.success
        # validate + expand_end_children + merge (failing) = 3
        assert client.execute_and_extract.call_count == 3

    def test_skipped_params_recorded_in_state_diff(self):
        skipped = ["RE_CHAIN_CHAINSETTINGS_0.motionForce"]
        client = MagicMock()
        # Responses (SEPARATE mode):
        #   validate, verify_marks, create, apply (with skips), angle_ramp
        client.execute_and_extract.side_effect = [
            ["OK"],
            [f"VERIFY:{json.dumps({'clean': True, 'suspicious': []})}"],
            [f"NEW_CS:{json.dumps({'new_cs': ['RE_CHAIN_CHAINSETTINGS_0'], 'col': 'MHWilds_Female.chain2'})}"],
            [f"APPLIED:{json.dumps(skipped)}"],
            ["RAMP:{'FINISHED'}"],
        ]
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "chain_collection": "ChainCol",
                "inferred_types": {"hair_001": "hair_short"},
                "x_preset": "MMD",
            },
        )
        assert result.success
        assert "skipped_params" in result.state_diff
        assert skipped == result.state_diff["skipped_params"]

    def test_scene_validation_fail_returns_precondition(self):
        client = MagicMock()
        client.execute_and_extract.return_value = ["PRECONDITION:collection:ChainCol"]
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "chain_collection": "ChainCol",
                "inferred_types": {"hair_001": "hair_short"},
                "x_preset": "MMD",
            },
        )
        assert not result.success
        assert result.error.category == "precondition"

    def test_cancelled_operator_returns_operator_failed(self):
        client = MagicMock()
        # validate, verify_marks, create (cancelled)
        client.execute_and_extract.side_effect = [
            ["OK"],
            [f"VERIFY:{json.dumps({'clean': True, 'suspicious': []})}"],
            ["CANCELLED:{'CANCELLED'}"],
        ]
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "chain_collection": "ChainCol",
                "inferred_types": {"hair_001": "hair_short"},
                "x_preset": "MMD",
            },
        )
        assert not result.success
        assert result.error.category == "operator_failed"

    def test_consolidation_deduplicates_same_type_chains(self):
        """Single type → Blender creates no extra CS; returns {canonical: type}."""
        tool = PhysicsChains()
        inferred_types = {"aa_bone": "hair_short", "bb_bone": "hair_short"}
        canonical = "CS_0"
        consolidated = {"CS_0": "hair_short"}  # single type, no extra CS created
        client = _make_client([
            f"CONSOLIDATED:{json.dumps({'cs_to_type': consolidated, 'type_to_cs': {'hair_short': 'CS_0'}, 'errors': [], 'unmapped': []})}"
        ])
        _, cs_to_type = tool._consolidate_chain_settings(
            client, canonical, "MHWilds_Female.chain2", inferred_types
        )
        assert cs_to_type == consolidated
        assert len(cs_to_type) == 1

    def test_consolidation_keeps_separate_types(self):
        """Two types → Blender creates one extra CS; both types preserved."""
        tool = PhysicsChains()
        inferred_types = {"aa_bone": "hair_short", "bb_bone": "cloth_skirt_waist"}
        canonical = "CS_0"
        consolidated = {"CS_0": "hair_short", "CS_1": "cloth_skirt_waist"}
        client = _make_client([
            f"CONSOLIDATED:{json.dumps({'cs_to_type': consolidated, 'type_to_cs': {'hair_short': 'CS_0', 'cloth_skirt_waist': 'CS_1'}, 'errors': [], 'unmapped': []})}"
        ])
        _, cs_to_type = tool._consolidate_chain_settings(
            client, canonical, "col", inferred_types
        )
        assert cs_to_type == consolidated
        assert len(cs_to_type) == 2

    def test_consolidation_fallback_on_empty_output(self):
        """No output from Blender → fallback: canonical CS → first unique type."""
        tool = PhysicsChains()
        inferred_types = {"aa_bone": "hair_short", "bb_bone": "cloth_skirt_waist"}
        canonical = "CS_0"
        client = _make_client([])  # empty output
        _, cs_to_type = tool._consolidate_chain_settings(
            client, canonical, "col", inferred_types
        )
        # Fallback: canonical maps to alphabetically first type ("cloth_skirt_waist" < "hair_short")
        assert canonical in cs_to_type
        assert cs_to_type[canonical] in ("hair_short", "cloth_skirt_waist")

    def test_apply_params_by_type_injects_correct_params(self):
        """_apply_params_by_type uses type → params mapping, not bone order."""
        tool = PhysicsChains()
        inferred_types = {"aa_bone": "hair_short", "bb_bone": "hair_short"}
        resolved = {
            "aa_bone": get_physics_params("hair_short"),
            "bb_bone": get_physics_params("hair_short"),
        }
        cs_to_type = {"CS_0": "hair_short"}  # after consolidation, only one CS
        client = _make_client(["APPLIED:[]"])
        skipped = tool._apply_params_by_type(client, cs_to_type, inferred_types, resolved)
        assert skipped == []
        # Verify Blender code was called with hair_short params
        code = client.execute_and_extract.call_args[0][0]
        assert "Character_Chain.cfil" in code  # default collider path

    def test_apply_params_separate_mode_ordering(self):
        """SEPARATE mode (legacy path, SHARED-like) maps cs_names to bone order."""
        tool = PhysicsChains()
        inferred_types = {"zz_bone": "hair_long_straight", "aa_bone": "hair_short"}
        resolved = {
            "aa_bone": get_physics_params("hair_short"),
            "zz_bone": get_physics_params("hair_long_straight"),
        }
        client = _make_client(["APPLIED:[]"])
        tool._apply_params_to_chain_settings(
            client,
            ["cs_0", "cs_1"],
            inferred_types,
            resolved,
            "SEPARATE",
        )
        call_args = client.execute_and_extract.call_args[0][0]
        assert "0.185" in call_args

    def test_collider_path_default_injected(self):
        """Default colliderFilterInfoPath is added to every params dict."""
        tool = PhysicsChains()
        inferred_types = {"hair_001": "hair_short"}
        resolved = {"hair_001": get_physics_params("hair_short")}
        client = _make_client(["APPLIED:[]"])
        tool._apply_params_to_chain_settings(
            client, ["cs_0"], inferred_types, resolved, "SEPARATE"
        )
        call_args = client.execute_and_extract.call_args[0][0]
        assert "Character_Chain.cfil" in call_args

    # ── _tune_chain_header_to_mhwilds (issue #21) ────────────────────────────

    def test_tune_header_emits_all_seven_calibrated_fields(self):
        """Step 6 (issue #21) overrides the 7 RE_CHAIN_HEADER fields MHWs needs."""
        tool = PhysicsChains()
        client = _make_client([f"TUNED:HEADER_0:{json.dumps([])}"])
        tool._tune_chain_header_to_mhwilds(client, "MHWilds_Female.chain2")
        assert client.execute_and_extract.call_count == 1
        code = client.execute_and_extract.call_args[0][0]
        # Header lookup must be dynamic via the chain collection — no hardcoded name.
        assert "RE_CHAIN_HEADER" in code
        assert "MHWilds_Female.chain2" in code
        # All seven MHWs-calibrated overrides (enum identifiers as str).
        assert "('calculateMode', '3')" in code
        assert "('chainAttrFlags', '4')" in code
        assert "('calculateStepTime', 2.0)" in code
        assert "('modelCollisionSearch', 1)" in code
        assert "('highFPSCalculateMode', '2')" in code
        assert "('wilds_unkn1', 1)" in code
        assert "('wilds_unkn2', 1)" in code

    def test_tune_header_skips_when_collection_empty(self):
        """Empty collection name → no Blender round-trip, no error."""
        tool = PhysicsChains()
        client = MagicMock()
        tool._tune_chain_header_to_mhwilds(client, "")
        assert client.execute_and_extract.call_count == 0

    def test_tune_header_swallows_exceptions(self):
        """Helper is non-fatal: a Blender failure does not propagate."""
        tool = PhysicsChains()
        client = MagicMock()
        client.execute_and_extract.side_effect = RuntimeError("socket dropped")
        tool._tune_chain_header_to_mhwilds(client, "ChainCol")
        assert client.execute_and_extract.call_count == 1

    def test_successful_pipeline_calls_header_tune_after_angle_ramp(self):
        """Step 6 runs after Step 5 (angle ramp) in the happy path."""
        new_cs = ["RE_CHAIN_CHAINSETTINGS_0"]
        client = MagicMock()
        # Responses: validate, verify_marks, create, apply, angle_ramp, header_tune
        client.execute_and_extract.side_effect = [
            ["OK"],
            [f"VERIFY:{json.dumps({'clean': True, 'suspicious': []})}"],
            [f"NEW_CS:{json.dumps({'new_cs': new_cs, 'col': 'MHWilds_Female.chain2'})}"],
            [f"APPLIED:{json.dumps([])}"],
            ["RAMP:{'FINISHED'}"],
            [f"TUNED:HEADER_0:{json.dumps([])}"],
        ]
        result = PhysicsChains().run(
            client,
            _make_cache(),
            {
                "target_armature": "MHWs",
                "chain_collection": "ChainCol",
                "inferred_types": {"hair_001": "hair_short"},
            },
        )
        assert result.success
        assert client.execute_and_extract.call_count == 6
        tune_code = client.execute_and_extract.call_args_list[5][0][0]
        assert "RE_CHAIN_HEADER" in tune_code
        assert "calculateMode" in tune_code


# ── _verify_chain_marks ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestVerifyChainMarks:
    tool = PhysicsChains()

    def test_clean_returns_true(self):
        """All chain heads have _End descendants → clean=True."""
        payload = json.dumps({"clean": True, "suspicious": []})
        client = _make_client([f"VERIFY:{payload}"])
        err, clean = self.tool._verify_chain_marks(client, "ArmObj")
        assert err is None
        assert clean is True

    def test_suspicious_bones_returns_false(self):
        """Chain head without _End descendant → clean=False."""
        payload = json.dumps({"clean": False, "suspicious": ["Spine", "Hips"]})
        client = _make_client([f"VERIFY:{payload}"])
        err, clean = self.tool._verify_chain_marks(client, "ArmObj")
        assert err is None
        assert clean is False

    def test_no_output_returns_error_and_false(self):
        """Empty output from Blender → error returned."""
        client = _make_client([])
        err, clean = self.tool._verify_chain_marks(client, "ArmObj")
        assert err is not None
        assert err.category == "operator_failed"
        assert clean is False

    def test_precondition_not_found_returns_error(self):
        """Armature not found in Blender → precondition error."""
        client = _make_client(["PRECONDITION:not_found"])
        err, clean = self.tool._verify_chain_marks(client, "MissingArm")
        assert err is not None
        assert err.category == "precondition"
        assert clean is False

    def test_unexpected_output_returns_error(self):
        """Unrecognised output format → unexpected error."""
        client = _make_client(["GARBAGE:data"])
        err, clean = self.tool._verify_chain_marks(client, "ArmObj")
        assert err is not None
        assert err.category == "unexpected"
        assert clean is False

    def test_verify_code_uses_end_bone_detection(self):
        """Generated Blender code must reference '_End' suffix and iterative BFS."""
        client = _make_client([f"VERIFY:{json.dumps({'clean': True, 'suspicious': []})}"])
        self.tool._verify_chain_marks(client, "ArmObj")
        code = client.execute_and_extract.call_args[0][0]
        assert "_End" in code
        assert "stack" in code  # iterative BFS, not recursion


# ── bone selection works on Blender 4 and Blender 5 ──────────────────────────
#
# Blender 5 moved pose-mode selection from Bone.select to PoseBone.select (Bone has no
# `select` any more), found by tools-5.2 L3: `'Bone' object has no attribute 'select'`.
# These run the generated code against a fake bpy shaped like each version.


class _Bone4:
    def __init__(self):
        self.select = False


class _PoseBone4:  # Blender 4: no PoseBone.select; selection is on the Bone
    __slots__ = ("name", "bone")

    def __init__(self, name):
        self.name, self.bone = name, _Bone4()


class _Bone5:  # Blender 5: Bone.select is gone
    __slots__ = ()


class _PoseBone5:
    def __init__(self, name):
        self.name, self.bone, self.select = name, _Bone5(), False


class _AnyOp:
    """bpy.ops / bpy.context stand-in: any attribute, any call -> {'FINISHED'}."""

    def __getattr__(self, name):
        return _AnyOp()

    def __call__(self, *args, **kwargs):
        return {"FINISHED"}


def _run_with_fake_bpy(code, pose_bones, monkeypatch):
    import sys
    from types import SimpleNamespace

    arm = SimpleNamespace(pose=SimpleNamespace(bones={b.name: b for b in pose_bones}),
                          select_set=lambda v: None)
    fake = SimpleNamespace(data=SimpleNamespace(objects={"MHWs": arm}), context=_AnyOp(), ops=_AnyOp())
    monkeypatch.setitem(sys.modules, "bpy", fake)
    exec(code, {})


def _selected(pose_bones):
    return sorted(b.name for b in pose_bones
                  if (b.select if hasattr(b, "select") else b.bone.select))


class TestBoneSelectionAcrossBlenderVersions:
    tool = PhysicsChains()

    @pytest.mark.parametrize("pose_bone", [_PoseBone4, _PoseBone5], ids=["blender4", "blender5"])
    def test_merge_selects_the_named_bones(self, pose_bone, monkeypatch):
        client = _make_client(["{'FINISHED'}"])
        assert self.tool._merge_into_parents(client, "MHWs", ["Ribbon_root"]) is None
        bones = [pose_bone("Ribbon_root"), pose_bone("Head")]
        _run_with_fake_bpy(client.execute_and_extract.call_args[0][0], bones, monkeypatch)
        assert _selected(bones) == ["Ribbon_root"]

    @pytest.mark.parametrize("pose_bone", [_PoseBone4, _PoseBone5], ids=["blender4", "blender5"])
    def test_clear_selects_the_named_bones(self, pose_bone, monkeypatch):
        client = _make_client(["{'FINISHED'}"])
        assert self.tool._clear_specific_bone_roles(client, "MHWs", ["Cage", "Cage_L"]) is None
        bones = [pose_bone("Cage"), pose_bone("Cage_L"), pose_bone("Head")]
        _run_with_fake_bpy(client.execute_and_extract.call_args[0][0], bones, monkeypatch)
        assert _selected(bones) == ["Cage", "Cage_L"]


# ── SEPARATE mode: each chain settings object gets ITS OWN chain head's params ──
#
# Bug (GG outfit run, 2026-10-15): SEPARATE mode gave cs_names[i] the params of
# sorted(inferred_types)[i], purely by list position. inferred_types holds every
# classified head (hair, breasts, Hips, ribbons, skirt strands...), the chains built
# are a subset in another order, so 7 of the 10 GG skirt strands (all typed
# cloth_skirt_waist) shipped with body_jiggle or accessory_ribbon params.
#
# These run the generated code against a fake bpy shaped like RE Chain Editor's
# scene: a CHAINGROUP is parented to its CHAINSETTINGS object, its first child
# RE_CHAIN_NODE is the chain head, bound to the bone by the "BoneName" constraint.

# The inferred_types the GG run passed (Known_Good_mod_test/scripts/gg/physics_chains.json).
_GG_INFERRED_TYPES = {
    "Ahoge.001": "hair_short", "Ear_L.001": "hair_short", "Ear_R.001": "hair_short",
    "F_Hair": "hair_front_bangs", "F_Hair_L.001": "hair_front_bangs",
    "F_Hair_R.001": "hair_front_bangs",
    "GG_Ribbon_L.001": "accessory_ribbon", "GG_Ribbon_R.001": "accessory_ribbon",
    "GG_Skirt.Root_B.001": "cloth_skirt_waist", "GG_Skirt.Root_B_L.001": "cloth_skirt_waist",
    "GG_Skirt.Root_B_R.001": "cloth_skirt_waist", "GG_Skirt.Root_F_L.001": "cloth_skirt_waist",
    "GG_Skirt.Root_F_R.001": "cloth_skirt_waist", "GG_Skirt.Root_L.001": "cloth_skirt_waist",
    "GG_Skirt.Root_L.006": "cloth_skirt_waist", "GG_Skirt.Root_M.001": "cloth_skirt_waist",
    "GG_Skirt.Root_R.001": "cloth_skirt_waist", "GG_Skirt.Root_R.006": "cloth_skirt_waist",
    "Hips_L": "body_jiggle", "Hips_R": "body_jiggle",
    "Ribbon_Head_L_L": "accessory_ribbon", "Ribbon_Head_L_L.001": "accessory_ribbon",
    "Ribbon_Head_L_R": "accessory_ribbon", "Ribbon_Head_L_R.001": "accessory_ribbon",
    "Ribbon_Head_R_L": "accessory_ribbon", "Ribbon_Head_R_L.001": "accessory_ribbon",
    "Ribbon_Head_R_R": "accessory_ribbon", "Ribbon_Head_R_R.001": "accessory_ribbon",
    "S2_Hair_L.001": "hair_short", "S2_Hair_R.001": "hair_short",
    "S_Hair_L.001": "hair_medium", "S_Hair_R.001": "hair_medium",
    "Tail": "fur_tail", "Twin tail_L.001": "hair_twintail", "Twin tail_R.001": "hair_twintail",
    "breast_L": "body_jiggle", "breast_R": "body_jiggle",
}

_GG_SKIRT_HEADS = sorted(b for b, t in _GG_INFERRED_TYPES.items() if t == "cloth_skirt_waist")


class _ChainObj:
    """bpy Object stand-in: custom props via get(), children, constraints, chain settings PG."""

    def __init__(self, name, obj_type, children=(), bone=None):
        self.name = name
        self._props = {"TYPE": obj_type}
        self.children = list(children)
        self.constraints = {} if bone is None else {"BoneName": SimpleNamespace(subtarget=bone)}
        self.re_chain_chainsettings = SimpleNamespace()  # records every setattr
        self.parent = None
        for child in self.children:
            child.parent = self

    def get(self, key, default=None):
        return self._props.get(key, default)


def _chain_scene(cs_chains):
    """{cs_name: [[head_bone, next_bone, ...] per chain group]} -> bpy.data.objects dict."""
    objects = {}
    for cs_name, chains in cs_chains.items():
        groups = []
        for gi, bones in enumerate(chains):
            node = None
            for bone in reversed(bones):
                node = _ChainObj(bone, "RE_CHAIN_NODE", [node] if node else [], bone=bone)
            groups.append(_ChainObj(f"CHAIN_GROUP_{cs_name}_{gi}", "RE_CHAIN_CHAINGROUP", [node]))
        objects[cs_name] = _ChainObj(cs_name, "RE_CHAIN_CHAINSETTINGS", groups)
        objects.update({g.name: g for g in groups})
    return objects


def _apply_separate_on_fake_scene(objects, cs_names, inferred_types, monkeypatch, capsys):
    """Run SEPARATE-mode _apply_params_to_chain_settings' generated code on a fake scene.

    Returns the skipped list the generated code printed after APPLIED:.
    """
    import sys

    resolved = {bone: get_physics_params(itype) for bone, itype in inferred_types.items()}
    client = _make_client(["APPLIED:[]"])
    PhysicsChains()._apply_params_to_chain_settings(
        client, cs_names, inferred_types, resolved, "SEPARATE"
    )
    code = client.execute_and_extract.call_args[0][0]
    monkeypatch.setitem(sys.modules, "bpy", SimpleNamespace(data=SimpleNamespace(objects=objects)))
    capsys.readouterr()
    exec(code, {})
    applied = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("APPLIED:")]
    assert len(applied) == 1
    return json.loads(applied[0][len("APPLIED:"):])


@pytest.mark.unit
class TestSeparateModeParamsByChainHead:
    def test_gg_skirt_strands_all_get_cloth_skirt_waist(self, monkeypatch, capsys):
        """The GG case: chains are a subset of inferred_types, in pose-bone order."""
        heads = (
            ["Twin tail_L.001", "Twin tail_R.001", "GG_Ribbon_L.001", "GG_Ribbon_R.001"]
            + ["GG_Skirt.Root_M.001", "GG_Skirt.Root_F_L.001", "GG_Skirt.Root_F_R.001",
               "GG_Skirt.Root_L.001", "GG_Skirt.Root_R.001", "GG_Skirt.Root_B_L.001",
               "GG_Skirt.Root_B.001", "GG_Skirt.Root_B_R.001", "GG_Skirt.Root_L.006",
               "GG_Skirt.Root_R.006"]
            + ["Tail", "breast_L", "breast_R"]
        )
        cs_names = [f"CHAIN_SETTINGS_{i:02d}" for i in range(len(heads))]
        objects = _chain_scene(
            {cs: [[h, h + "_next"]] for cs, h in zip(cs_names, heads, strict=True)}
        )

        skipped = _apply_separate_on_fake_scene(
            objects, cs_names, _GG_INFERRED_TYPES, monkeypatch, capsys
        )

        assert skipped == []
        for cs, head in zip(cs_names, heads, strict=True):
            want = get_physics_params(_GG_INFERRED_TYPES[head])
            pg = objects[cs].re_chain_chainsettings
            assert (pg.damping, pg.springForce) == (want["damping"], want["springForce"]), (
                f"{cs} (head {head}) got the wrong preset"
            )
        skirt_cs = [cs for cs, h in zip(cs_names, heads, strict=True) if h in _GG_SKIRT_HEADS]
        assert len(skirt_cs) == 10
        assert {objects[cs].re_chain_chainsettings.damping for cs in skirt_cs} == {0.12}
        assert {objects[cs].re_chain_chainsettings.springForce for cs in skirt_cs} == {0.002}

    def test_cs_whose_chain_head_has_no_inferred_type_is_untouched_and_reported(
        self, monkeypatch, capsys
    ):
        """No positional fallback: an untyped chain head leaves its CS alone, named in skipped."""
        inferred = {"Tail": "fur_tail"}
        objects = _chain_scene({
            "CHAIN_SETTINGS_00": [["Tail", "Tail.001"]],
            "CHAIN_SETTINGS_01": [["Mystery_Strand", "Mystery_Strand.001"]],
        })

        skipped = _apply_separate_on_fake_scene(
            objects, ["CHAIN_SETTINGS_00", "CHAIN_SETTINGS_01"], inferred, monkeypatch, capsys
        )

        assert objects["CHAIN_SETTINGS_00"].re_chain_chainsettings.damping == (
            get_physics_params("fur_tail")["damping"]
        )
        assert vars(objects["CHAIN_SETTINGS_01"].re_chain_chainsettings) == {}
        assert len(skipped) == 1
        assert skipped[0].startswith("CHAIN_SETTINGS_01.")
        assert "Mystery_Strand" in skipped[0]
        assert "untouched" in skipped[0]

    def test_cs_whose_chain_heads_disagree_on_type_is_untouched_and_reported(
        self, monkeypatch, capsys
    ):
        """One CS used by chains of two different types: no single right preset, so none."""
        inferred = {"breast_L": "body_jiggle", "Tail": "fur_tail"}
        objects = _chain_scene({
            "CHAIN_SETTINGS_00": [["breast_L", "breast_L_End"], ["Tail", "Tail.001"]],
        })

        skipped = _apply_separate_on_fake_scene(
            objects, ["CHAIN_SETTINGS_00"], inferred, monkeypatch, capsys
        )

        assert vars(objects["CHAIN_SETTINGS_00"].re_chain_chainsettings) == {}
        assert len(skipped) == 1
        assert skipped[0].startswith("CHAIN_SETTINGS_00.")
        assert "body_jiggle" in skipped[0] and "fur_tail" in skipped[0]

    def test_cs_shared_by_chains_of_one_type_gets_that_type(self, monkeypatch, capsys):
        """A CS reused by several chains (re-run / recovery over an existing collection)
        still gets its chains' type when they all agree — not the alphabetically first head's."""
        inferred = {
            "Ahoge.001": "hair_short",
            "GG_Skirt.Root_B.001": "cloth_skirt_waist",
            "GG_Skirt.Root_M.001": "cloth_skirt_waist",
        }
        objects = _chain_scene({
            "CHAIN_SETTINGS_00": [
                ["GG_Skirt.Root_M.001", "GG_Skirt.Root_M.002"],
                ["GG_Skirt.Root_B.001", "GG_Skirt.Root_B.002"],
            ],
        })

        skipped = _apply_separate_on_fake_scene(
            objects, ["CHAIN_SETTINGS_00"], inferred, monkeypatch, capsys
        )

        assert skipped == []
        pg = objects["CHAIN_SETTINGS_00"].re_chain_chainsettings
        assert (pg.damping, pg.springForce) == (0.12, 0.002)
