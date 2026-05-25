"""
Unit tests for material.py (Phase 5A, 5B, 5C).

Focus:
  - MaterialInspect: param validation, texture_dir scan, Blender PRECONDITION/INSPECT parsing
  - MaterialSetup: param validation, x_preset routing, Normal chain code correctness,
    null-slot skip, WIRED result parsing
  - MaterialGenerate: param validation, collection not found, preset matching,
    auto_guessed tracking, RESULT/CANCELLED/EXCEPTION handling

Run with: uv run pytest -m unit tests/unit/test_material.py -v
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.phases.material import (
    IMAGE_EXTENSIONS,
    PRINCIPLED_SLOTS,
    VALID_SETUP_PRESETS,
    MaterialGenerate,
    MaterialInspect,
    MaterialSetup,
)
from app.phases.base import PhaseResult


# ── fixtures ──────────────────────────────────────────────────────────────────


def _make_client(output_lines: list[str]) -> MagicMock:
    client = MagicMock()
    client.execute_and_extract.return_value = output_lines
    return client


def _make_cache() -> MagicMock:
    cache = MagicMock()
    state = MagicMock()
    state.diff.return_value = {}
    cache.refresh.return_value = state
    return cache


def _inspect_response(materials: list[str], connections: dict) -> str:
    return "INSPECT:" + json.dumps({"materials": materials, "connections": connections})


def _wired_response(wired: list[str], skipped: list[str] | None = None) -> str:
    return "WIRED:" + json.dumps({"wired": wired, "skipped": skipped or []})


def _result_response(mdf_collection: str, processed: list[str], auto_guessed: list[str]) -> str:
    return "RESULT:" + json.dumps({
        "mdf_collection": mdf_collection,
        "materials_processed": processed,
        "presets_auto_guessed": auto_guessed,
    })


# ── MaterialInspect — constants ───────────────────────────────────────────────


@pytest.mark.unit
class TestMaterialConstants:
    def test_valid_setup_presets(self):
        assert "VRChat" in VALID_SETUP_PRESETS
        assert "終末地" in VALID_SETUP_PRESETS
        assert "MMD" not in VALID_SETUP_PRESETS

    def test_principled_slots_has_normal(self):
        assert "Normal" in PRINCIPLED_SLOTS

    def test_principled_slots_count(self):
        assert len(PRINCIPLED_SLOTS) == 6

    def test_image_extensions_coverage(self):
        for ext in (".png", ".tga", ".dds", ".jpg"):
            assert ext in IMAGE_EXTENSIONS


# ── MaterialInspect ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestMaterialInspect:
    tool = MaterialInspect()

    def test_name(self):
        assert self.tool.name == "material_inspect"

    def test_tool_schema_shape(self):
        schema = MaterialInspect.tool_schema()
        assert schema["name"] == "material_inspect"
        assert "target_object" in schema["input_schema"]["required"]
        assert "texture_dir" in schema["input_schema"]["required"]

    def test_missing_target_object_fails(self):
        result = self.tool.run(_make_client([]), _make_cache(), {"texture_dir": "C:/tex"})
        assert not result.success
        assert result.error.category == "precondition"

    def test_missing_texture_dir_fails(self):
        result = self.tool.run(_make_client([]), _make_cache(), {"target_object": "Body"})
        assert not result.success
        assert result.error.category == "precondition"

    def test_nonexistent_texture_dir_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {"target_object": "Body", "texture_dir": "Z:/no_such_dir_xyz123"},
        )
        assert not result.success
        assert result.error.category == "precondition"
        assert "texture_dir" in result.error.message.lower() or "not found" in result.error.message.lower()

    def test_object_not_found_precondition(self):
        client = _make_client(["PRECONDITION:object_not_found:Body"])
        with patch.object(MaterialInspect, "_scan_texture_dir", return_value=[]):
            result = self.tool.run(
                client, _make_cache(), {"target_object": "Body", "texture_dir": "C:/tex"}
            )
        assert not result.success
        assert result.error.category == "precondition"

    def test_empty_blender_output_fails(self):
        client = _make_client([])
        with patch.object(MaterialInspect, "_scan_texture_dir", return_value=[]):
            result = self.tool.run(
                client, _make_cache(), {"target_object": "Body", "texture_dir": "C:/tex"}
            )
        assert not result.success
        assert result.error.category == "operator_failed"

    def test_successful_inspect_populates_state_diff(self):
        materials = ["Body", "Hair"]
        connections = {
            "Body": {"Base Color": "C:/tex/body_d.png", "Normal": None},
            "Hair": {"Base Color": None, "Normal": None},
        }
        client = _make_client([_inspect_response(materials, connections)])
        with patch.object(MaterialInspect, "_scan_texture_dir", return_value=["C:/tex/body_d.png"]):
            result = self.tool.run(
                client, _make_cache(), {"target_object": "Body", "texture_dir": "C:/tex"}
            )
        assert result.success
        assert result.state_diff["materials"] == materials
        assert result.state_diff["texture_files"] == ["C:/tex/body_d.png"]
        assert result.state_diff["existing_connections"] == connections

    def test_scan_texture_dir_filters_by_extension(self, tmp_path):
        (tmp_path / "tex.png").write_bytes(b"")
        (tmp_path / "tex.tga").write_bytes(b"")
        (tmp_path / "readme.txt").write_bytes(b"")
        (tmp_path / "model.fbx").write_bytes(b"")
        result = MaterialInspect._scan_texture_dir(str(tmp_path))
        basenames = {Path(p).name for p in result}
        assert "tex.png" in basenames
        assert "tex.tga" in basenames
        assert "readme.txt" not in basenames
        assert "model.fbx" not in basenames

    def test_scan_texture_dir_nonexistent_returns_none(self):
        assert MaterialInspect._scan_texture_dir("Z:/no_such_dir_xyz") is None

    def test_scan_texture_dir_empty_dir_returns_empty_list(self, tmp_path):
        result = MaterialInspect._scan_texture_dir(str(tmp_path))
        assert result == []


# ── MaterialSetup ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestMaterialSetup:
    tool = MaterialSetup()

    def test_name(self):
        assert self.tool.name == "material_setup"

    def test_tool_schema_x_preset_enum(self):
        props = MaterialSetup.tool_schema()["input_schema"]["properties"]
        assert set(props["x_preset"]["enum"]) == {"VRChat", "終末地"}

    def test_missing_target_object_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {"x_preset": "VRChat", "texture_mapping": {"Hair": {"Base Color": "a.png"}}},
        )
        assert not result.success
        assert result.error.category == "precondition"

    def test_invalid_x_preset_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {
                "target_object": "Body",
                "x_preset": "MMD",
                "texture_mapping": {"Hair": {"Base Color": "a.png"}},
            },
        )
        assert not result.success
        assert result.error.category == "precondition"
        assert "MMD" in result.error.message

    def test_empty_texture_mapping_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {"target_object": "Body", "x_preset": "VRChat", "texture_mapping": {}},
        )
        assert not result.success
        assert result.error.category == "precondition"

    def test_object_not_found_precondition(self):
        client = _make_client(["PRECONDITION:object_not_found:Body"])
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_object": "Body",
                "x_preset": "VRChat",
                "texture_mapping": {"Hair": {"Base Color": "a.png"}},
            },
        )
        assert not result.success
        assert result.error.category == "precondition"

    def test_empty_blender_output_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {
                "target_object": "Body",
                "x_preset": "VRChat",
                "texture_mapping": {"Hair": {"Base Color": "a.png"}},
            },
        )
        assert not result.success
        assert result.error.category == "operator_failed"

    def test_vchat_normal_wiring_contains_subtract(self):
        client = _make_client([_wired_response(["Hair.Normal"])])
        self.tool.run(
            client,
            _make_cache(),
            {
                "target_object": "Body",
                "x_preset": "VRChat",
                "texture_mapping": {"Hair": {"Normal": "hair_n.png"}},
            },
        )
        code = client.execute_and_extract.call_args[0][0]
        assert "SUBTRACT" in code
        assert "ShaderNodeSeparateXYZ" in code
        assert "ShaderNodeCombineXYZ" in code

    def test_zenmo_normal_wiring_no_subtract(self):
        client = _make_client([_wired_response(["Body.Normal"])])
        self.tool.run(
            client,
            _make_cache(),
            {
                "target_object": "Body",
                "x_preset": "終末地",
                "texture_mapping": {"Body": {"Normal": "body_n.png"}},
            },
        )
        code = client.execute_and_extract.call_args[0][0]
        assert "SUBTRACT" not in code
        assert "ShaderNodeNormalMap" in code

    def test_null_slot_does_not_appear_in_wiring_for(self):
        client = _make_client([_wired_response(["Hair.Base Color"])])
        self.tool.run(
            client,
            _make_cache(),
            {
                "target_object": "Body",
                "x_preset": "VRChat",
                "texture_mapping": {"Hair": {"Base Color": "hair_d.png", "Normal": None}},
            },
        )
        # The code should still work (no crash); the None slot is handled by Blender code
        code = client.execute_and_extract.call_args[0][0]
        assert "hair_d.png" in code

    def test_successful_wiring_populates_state_diff(self):
        wired = ["Body.Base Color", "Body.Normal", "Hair.Base Color"]
        client = _make_client([_wired_response(wired)])
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_object": "Body",
                "x_preset": "VRChat",
                "texture_mapping": {
                    "Body": {"Base Color": "body_d.png", "Normal": "body_n.png"},
                    "Hair": {"Base Color": "hair_d.png"},
                },
            },
        )
        assert result.success
        assert result.state_diff["materials_wired"] == wired

    def test_skipped_slots_recorded_in_state_diff(self):
        skipped = ["Hair.Alpha:(some error)"]
        client = _make_client([_wired_response(["Hair.Base Color"], skipped)])
        result = self.tool.run(
            client,
            _make_cache(),
            {
                "target_object": "Body",
                "x_preset": "VRChat",
                "texture_mapping": {"Hair": {"Base Color": "hair_d.png", "Alpha": "hair_a.png"}},
            },
        )
        assert result.success
        assert result.state_diff["slots_skipped"] == skipped

    def test_zenmo_generates_different_code_from_vchat(self):
        """x_preset resolution happens in Python; VRChat and 終末地 produce distinct code strings."""
        def _run(preset):
            client = _make_client([_wired_response([])])
            MaterialSetup().run(
                client,
                _make_cache(),
                {
                    "target_object": "Mesh",
                    "x_preset": preset,
                    "texture_mapping": {"Mat": {"Normal": "n.png"}},
                },
            )
            return client.execute_and_extract.call_args[0][0]

        vchat_code = _run("VRChat")
        zenmo_code = _run("終末地")
        assert vchat_code != zenmo_code
        assert "SUBTRACT" in vchat_code
        assert "SUBTRACT" not in zenmo_code


# ── MaterialGenerate ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestMaterialGenerate:
    tool = MaterialGenerate()

    def test_name(self):
        assert self.tool.name == "material_generate"

    # Common params for happy-path tests (natives_root is now required).
    _PARAMS = {
        "mesh_collection": "MeshCol",
        "texture_base_path": "Author/Char/",
        "natives_root": "E:/mod/root",
        "preset_mapping": {},
    }

    def test_tool_schema_shape(self):
        schema = MaterialGenerate.tool_schema()
        assert schema["name"] == "material_generate"
        required = schema["input_schema"]["required"]
        assert "mesh_collection" in required
        assert "texture_base_path" in required
        assert "preset_mapping" in required
        assert "natives_root" in required

    def test_missing_mesh_collection_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {"texture_base_path": "Author/Char/", "natives_root": "E:/m", "preset_mapping": {}},
        )
        assert not result.success
        assert result.error.category == "precondition"

    def test_missing_natives_root_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {"mesh_collection": "MeshCol", "texture_base_path": "Author/Char/", "preset_mapping": {}},
        )
        assert not result.success
        assert result.error.category == "precondition"
        assert "natives_root" in result.error.message

    def test_missing_texture_base_path_fails(self):
        result = self.tool.run(
            _make_client([]),
            _make_cache(),
            {"mesh_collection": "MeshCol", "natives_root": "E:/m", "preset_mapping": {}},
        )
        assert not result.success
        assert result.error.category == "precondition"

    def test_collection_not_found_precondition(self):
        client = _make_client(["PRECONDITION:collection_not_found:MeshCol"])
        result = self.tool.run(client, _make_cache(), self._PARAMS)
        assert not result.success
        assert result.error.category == "precondition"
        assert "MeshCol" in result.error.message

    def test_empty_blender_output_fails(self):
        result = self.tool.run(_make_client([]), _make_cache(), self._PARAMS)
        assert not result.success
        assert result.error.category == "operator_failed"

    def test_exception_in_process_fails(self):
        client = _make_client(["EXCEPTION:RE Mesh Editor not installed"])
        result = self.tool.run(client, _make_cache(), self._PARAMS)
        assert not result.success
        assert result.error.category == "unexpected"
        assert "RE Mesh Editor not installed" in result.error.message

    def test_cancelled_process_fails(self):
        client = _make_client(["CANCELLED:{'CANCELLED'}"])
        result = self.tool.run(client, _make_cache(), self._PARAMS)
        assert not result.success
        assert result.error.category == "operator_failed"

    def test_stderr_b64_captured_into_raw(self):
        """Captured stdout/stderr from the operator must flow into PhaseError.raw."""
        import base64
        msg = "Bake failed: texconv.exe not found"
        stderr_line = "STDERR_B64:" + base64.b64encode(msg.encode("utf-8")).decode("ascii")
        client = _make_client(["CANCELLED:{'CANCELLED'}", stderr_line])
        result = self.tool.run(client, _make_cache(), self._PARAMS)
        assert not result.success
        assert msg in result.error.raw

    def test_successful_result_populates_state_diff(self):
        client = _make_client([
            _result_response("MeshCol.mdf2", ["Body", "Hair"], [])
        ])
        params = {**self._PARAMS, "preset_mapping": {"Body": "Skin", "Hair": "Hair"}}
        result = self.tool.run(client, _make_cache(), params)
        assert result.success
        assert result.state_diff["mdf_collection"] == "MeshCol.mdf2"
        assert result.state_diff["materials_processed"] == ["Body", "Hair"]
        assert result.state_diff["presets_auto_guessed"] == []

    def test_auto_guessed_materials_recorded(self):
        client = _make_client([
            _result_response("MeshCol.mdf2", ["Body", "Hair", "Face"], ["Face"])
        ])
        params = {**self._PARAMS, "preset_mapping": {"Body": "Skin", "Hair": "Hair"}}
        result = self.tool.run(client, _make_cache(), params)
        assert result.success
        assert "Face" in result.state_diff["presets_auto_guessed"]

    def test_preset_mapping_injected_into_blender_code(self):
        client = _make_client([_result_response("Col.mdf2", [], [])])
        params = {**self._PARAMS, "preset_mapping": {"Body": "Skin", "Hair": "NoPDO Hair"}}
        self.tool.run(client, _make_cache(), params)
        code = client.execute_and_extract.call_args[0][0]
        assert "Skin" in code
        assert "NoPDO Hair" in code

    def test_natives_root_injected_into_blender_code(self):
        client = _make_client([_result_response("Col.mdf2", [], [])])
        self.tool.run(client, _make_cache(), self._PARAMS)
        code = client.execute_and_extract.call_args[0][0]
        assert "E:/mod/root" in code

    def test_optional_mdf_collection_name_injected_when_provided(self):
        client = _make_client([_result_response("CustomName.mdf2", [], [])])
        params = {**self._PARAMS, "mdf_collection_name": "CustomName.mdf2"}
        self.tool.run(client, _make_cache(), params)
        code = client.execute_and_extract.call_args[0][0]
        assert "CustomName.mdf2" in code

    def test_empty_preset_mapping_accepted(self):
        client = _make_client([_result_response("Col.mdf2", ["Body"], ["Body"])])
        result = self.tool.run(client, _make_cache(), self._PARAMS)
        assert result.success
        assert "Body" in result.state_diff["presets_auto_guessed"]


# ── suggest_texture_mapping (issue #19 over-fill regression) ──────────────────


def _stub_llm(content: str) -> MagicMock:
    """Stub LLMClient whose `chat()` returns `content` as the only message."""
    llm = MagicMock()
    response = MagicMock()
    response.content = content
    llm.chat.return_value = response
    return llm


@pytest.mark.unit
class TestHasSlotToken:
    """Pure-function tests for the suffix-token gate (issue #19)."""

    from app.phases.material import _has_slot_token  # type: ignore

    def test_base_color_always_passes(self):
        from app.phases.material import _has_slot_token
        # Base Color has no token gate — any filename is allowed.
        assert _has_slot_token("BML_body.dds", "Base Color")
        assert _has_slot_token("random.png", "Base Color")

    def test_normal_with_underscore_n_passes(self):
        from app.phases.material import _has_slot_token
        assert _has_slot_token("body_n.png", "Normal")
        assert _has_slot_token("char_nrm.tga", "Normal")
        assert _has_slot_token("face_normal.png", "Normal")

    def test_normal_with_infix_dot_token_passes(self):
        from app.phases.material import _has_slot_token
        # 'char.nrm.dds' → stem='char.nrm' → split → {'char', 'nrm'} → match.
        assert _has_slot_token("char.nrm.dds", "Normal")
        assert _has_slot_token("char.normal.png", "Normal")

    def test_bml_body_rejected_as_normal(self):
        """The reported issue #19 case: BML_body.dds is a basecolor but the
        LLM hallucinated it into the Normal slot. The token gate must
        reject it."""
        from app.phases.material import _has_slot_token
        assert not _has_slot_token("BML_body.dds", "Normal")

    def test_plain_basename_rejected_as_non_basecolor(self):
        from app.phases.material import _has_slot_token
        for slot in ("Normal", "Roughness", "Metallic", "Emission", "Alpha"):
            assert not _has_slot_token("body.png", slot), slot

    def test_roughness_metallic_emission_alpha_suffix(self):
        from app.phases.material import _has_slot_token
        assert _has_slot_token("body_r.png", "Roughness")
        assert _has_slot_token("body_rgh.dds", "Roughness")
        assert _has_slot_token("body_m.png", "Metallic")
        assert _has_slot_token("body_metallic.tga", "Metallic")
        assert _has_slot_token("body_e.png", "Emission")
        assert _has_slot_token("body_glow.png", "Emission")
        assert _has_slot_token("body_a.png", "Alpha")
        assert _has_slot_token("body_mask.png", "Alpha")

    def test_case_insensitivity(self):
        from app.phases.material import _has_slot_token
        assert _has_slot_token("Body_N.PNG", "Normal")
        assert _has_slot_token("BODY_NRM.dds", "Normal")


@pytest.mark.unit
class TestSuggestTextureMapping:
    """End-to-end tests for suggest_texture_mapping with stubbed LLM.

    Sync tests using asyncio.run so they work without pytest-asyncio
    being installed (the conda env on the maintainer's box lacks it)."""

    def test_bml_body_not_suggested_as_normal(self):
        """Issue #19 repro: even if the LLM ignores the prompt and tries
        to put BML_body.dds in the Normal slot, the server-side filter
        drops it."""
        from app.phases.material import suggest_texture_mapping
        materials = ["body"]
        texture_files = ["body.png", "BML_body.dds"]
        llm = _stub_llm(json.dumps({
            "body": {"Base Color": "body.png", "Normal": "BML_body.dds"},
        }))
        result = asyncio.run(suggest_texture_mapping(llm, materials, texture_files, {}))
        # Base Color survives; Normal filtered out by the token gate.
        assert result == {"body": {"Base Color": "body.png"}}

    def test_valid_normal_with_suffix_passes_through(self):
        """A correctly-named normal map must NOT be filtered."""
        from app.phases.material import suggest_texture_mapping
        materials = ["body"]
        texture_files = ["body.png", "body_n.png"]
        llm = _stub_llm(json.dumps({
            "body": {"Base Color": "body.png", "Normal": "body_n.png"},
        }))
        result = asyncio.run(suggest_texture_mapping(llm, materials, texture_files, {}))
        assert result == {"body": {"Base Color": "body.png", "Normal": "body_n.png"}}

    def test_empty_inputs_skip_llm_call(self):
        from app.phases.material import suggest_texture_mapping
        llm = MagicMock()
        assert asyncio.run(suggest_texture_mapping(llm, [], ["x.png"], {})) == {}
        assert asyncio.run(suggest_texture_mapping(llm, ["m"], [], {})) == {}
        llm.chat.assert_not_called()

    def test_malformed_llm_response_returns_empty(self):
        from app.phases.material import suggest_texture_mapping
        llm = _stub_llm("not json at all")
        result = asyncio.run(suggest_texture_mapping(llm, ["body"], ["body.png"], {}))
        assert result == {}

    def test_invented_filepath_dropped(self):
        """The LLM occasionally hallucinates a filename not in the
        candidate list. Existing behavior — drop it."""
        from app.phases.material import suggest_texture_mapping
        llm = _stub_llm(json.dumps({
            "body": {"Base Color": "body.png", "Normal": "ghost_n.png"},
        }))
        result = asyncio.run(suggest_texture_mapping(llm, ["body"], ["body.png"], {}))
        assert result == {"body": {"Base Color": "body.png"}}


# ── Stage 3 — reverse texture inference (flag-gated) ─────────────────────────


@pytest.mark.unit
class TestReverseInferenceFlagGate:
    """Stage 3 is OFF unless BOTH settings flags are set."""

    def test_disabled_when_flag_off_even_if_vision_available(self):
        from app.phases import material as material_mod

        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod, "settings") as mock_settings,
        ):
            mock_settings.vision_reverse_inference = False
            out = asyncio.run(material_mod.infer_textures_by_reverse_uv_layout(
                client=MagicMock(),
                target_object="Mesh",
                materials=["body"],
                texture_files=["body.png"],
            ))
        assert out == {}

    def test_disabled_when_vision_unavailable_even_if_flag_on(self):
        from app.phases import material as material_mod

        with (
            patch.object(material_mod, "vision_available", return_value=False),
            patch.object(material_mod, "settings") as mock_settings,
        ):
            mock_settings.vision_reverse_inference = True
            out = asyncio.run(material_mod.infer_textures_by_reverse_uv_layout(
                client=MagicMock(),
                target_object="Mesh",
                materials=["body"],
                texture_files=["body.png"],
            ))
        assert out == {}

    def test_empty_inputs_short_circuit(self):
        from app.phases import material as material_mod

        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod, "settings") as mock_settings,
        ):
            mock_settings.vision_reverse_inference = True
            assert asyncio.run(material_mod.infer_textures_by_reverse_uv_layout(
                MagicMock(), "Mesh", [], ["x.png"],
            )) == {}
            assert asyncio.run(material_mod.infer_textures_by_reverse_uv_layout(
                MagicMock(), "Mesh", ["m"], [],
            )) == {}


@pytest.mark.unit
class TestReverseInferenceRouting:
    """End-to-end with mocked VLM and overlay renderer."""

    def test_vlm_picks_material_routes_texture_to_base_color(self):
        from app.phases import material as material_mod

        vc_stub = MagicMock()
        vc_stub.classify_image.return_value = "head"
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod, "settings") as mock_settings,
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod, "_render_uv_layout_colored",
                         return_value=("ZmFrZQ==", "image/jpeg")),
            patch.object(material_mod, "_composite_texture_with_layout",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            mock_settings.vision_reverse_inference = True
            out = asyncio.run(material_mod.infer_textures_by_reverse_uv_layout(
                client=MagicMock(),
                target_object="Mesh",
                materials=["body", "head"],
                texture_files=["something_01.png"],
            ))
        # Texture routed to "head" → goes into Base Color (experimental).
        assert out == {"head": {"Base Color": "something_01.png"}}

    def test_vlm_unknown_reply_skips_texture(self):
        from app.phases import material as material_mod

        vc_stub = MagicMock()
        vc_stub.classify_image.return_value = "unknown"
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod, "settings") as mock_settings,
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod, "_render_uv_layout_colored",
                         return_value=("ZmFrZQ==", "image/jpeg")),
            patch.object(material_mod, "_composite_texture_with_layout",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            mock_settings.vision_reverse_inference = True
            out = asyncio.run(material_mod.infer_textures_by_reverse_uv_layout(
                MagicMock(), "Mesh", ["body"], ["x.png"],
            ))
        assert out == {}

    def test_layout_render_failure_returns_empty(self):
        from app.phases import material as material_mod

        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod, "settings") as mock_settings,
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=MagicMock()),
            patch.object(material_mod, "_render_uv_layout_colored",
                         side_effect=RuntimeError("blender hiccup")),
        ):
            mock_settings.vision_reverse_inference = True
            out = asyncio.run(material_mod.infer_textures_by_reverse_uv_layout(
                MagicMock(), "Mesh", ["body"], ["x.png"],
            ))
        assert out == {}

    def test_per_texture_vlm_exception_skipped(self):
        from app.phases import material as material_mod

        vc_stub = MagicMock()
        # First call raises, second succeeds.
        vc_stub.classify_image.side_effect = [
            RuntimeError("502"), "body",
        ]
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod, "settings") as mock_settings,
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod, "_render_uv_layout_colored",
                         return_value=("ZmFrZQ==", "image/jpeg")),
            patch.object(material_mod, "_composite_texture_with_layout",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            mock_settings.vision_reverse_inference = True
            out = asyncio.run(material_mod.infer_textures_by_reverse_uv_layout(
                MagicMock(), "Mesh", ["body"], ["a.png", "b.png"],
            ))
        # First texture skipped (exception), second routed successfully.
        assert out == {"body": {"Base Color": "b.png"}}


@pytest.mark.unit
class TestParseReverseInferenceReply:
    def test_exact_material_match(self):
        from app.phases.material import _parse_reverse_inference_reply
        assert _parse_reverse_inference_reply("body", ["body", "head"]) == "body"

    def test_case_insensitive_match(self):
        from app.phases.material import _parse_reverse_inference_reply
        assert _parse_reverse_inference_reply("BODY", ["body", "head"]) == "body"

    def test_extracts_material_from_verbose_reply(self):
        """Models often reply 'The texture belongs to body' despite instruction."""
        from app.phases.material import _parse_reverse_inference_reply
        assert _parse_reverse_inference_reply(
            "This texture belongs to head.", ["body", "head"],
        ) == "head"

    def test_unknown_reply_returns_none(self):
        from app.phases.material import _parse_reverse_inference_reply
        assert _parse_reverse_inference_reply("unknown", ["body"]) is None

    def test_garbage_returns_none(self):
        from app.phases.material import _parse_reverse_inference_reply
        assert _parse_reverse_inference_reply("???", ["body"]) is None


# ── _scan_groups UV-assist (issue #22 Stage 2) ───────────────────────────────


@pytest.mark.unit
class TestFindPartialOverlapCandidates:
    """Pure-function tests for partial-overlap group detection."""

    def test_no_overlap_returns_empty(self):
        from app.phases.material import _find_partial_overlap_candidates
        groups = [
            {"keeper": "head", "texture_set": ["head_d.png"]},
            {"keeper": "body", "texture_set": ["body_d.png"]},
        ]
        assert _find_partial_overlap_candidates(groups) == []

    def test_identical_sets_excluded(self):
        """Existing exact-match grouping already merged identical sets; if
        somehow two groups arrive with identical texture sets, they aren't
        partial-overlap candidates (they would just merge directly)."""
        from app.phases.material import _find_partial_overlap_candidates
        groups = [
            {"keeper": "a", "texture_set": ["x.png"]},
            {"keeper": "b", "texture_set": ["x.png"]},
        ]
        assert _find_partial_overlap_candidates(groups) == []

    def test_partial_overlap_returned(self):
        from app.phases.material import _find_partial_overlap_candidates
        groups = [
            {"keeper": "body_a", "texture_set": ["body_d.png", "body_n.png"]},
            {"keeper": "body_b", "texture_set": ["body_d.png"]},
        ]
        result = _find_partial_overlap_candidates(groups)
        assert result == [("body_a", "body_b", ["body_d.png"])]

    def test_singletons_with_no_texture_skipped(self):
        from app.phases.material import _find_partial_overlap_candidates
        groups = [
            {"keeper": "skin", "texture_set": ["d.png"]},
            {"keeper": "empty", "texture_set": []},
        ]
        assert _find_partial_overlap_candidates(groups) == []


@pytest.mark.unit
class TestParseUvOverlapReply:
    """VLM reply normalization for the YES/NO + confidence prompt."""

    def test_yes_with_confidence(self):
        from app.phases.material import _parse_uv_overlap_reply
        assert _parse_uv_overlap_reply("YES 0.9") == ("yes", 0.9)

    def test_no_with_confidence(self):
        from app.phases.material import _parse_uv_overlap_reply
        assert _parse_uv_overlap_reply("NO 0.65") == ("no", 0.65)

    def test_verbose_yes_confidence(self):
        """Models sometimes wrap with punctuation despite instructions."""
        from app.phases.material import _parse_uv_overlap_reply
        v, c = _parse_uv_overlap_reply("YES, confidence: 0.85")
        assert v == "yes" and abs(c - 0.85) < 1e-6

    def test_yes_without_score_defaults_to_half(self):
        from app.phases.material import _parse_uv_overlap_reply
        assert _parse_uv_overlap_reply("YES") == ("yes", 0.5)

    def test_garbage_returns_no_zero(self):
        from app.phases.material import _parse_uv_overlap_reply
        assert _parse_uv_overlap_reply("???") == ("no", 0.0)

    def test_confidence_clamped(self):
        from app.phases.material import _parse_uv_overlap_reply
        # > 1.0 clamps down
        assert _parse_uv_overlap_reply("YES 1.5") == ("yes", 1.0)


@pytest.mark.unit
class TestProposeUvAssistMerges:
    """End-to-end behavior of MaterialConsolidate._propose_uv_assist_merges
    with a stubbed VisionClient and mocked UV overlay renderer."""

    def _groups(self) -> list[dict]:
        # Two distinct groups sharing one texture — the canonical Stage 2 case.
        return [
            {"keeper": "Body.001", "texture_set": ["body_d.png", "body_n.png"]},
            {"keeper": "Body.002", "texture_set": ["body_d.png"]},
        ]

    def test_vision_unavailable_returns_no_proposals(self):
        from app.phases import material as material_mod
        consolidator = material_mod.MaterialConsolidate()
        with patch.object(material_mod, "vision_available", return_value=False):
            out = consolidator._propose_uv_assist_merges(
                client=MagicMock(), target_object="Mesh", groups=self._groups(),
            )
        assert out == []

    def test_no_candidates_returns_empty(self):
        from app.phases import material as material_mod
        consolidator = material_mod.MaterialConsolidate()
        # Disjoint texture sets → no overlap candidates.
        groups = [
            {"keeper": "a", "texture_set": ["x.png"]},
            {"keeper": "b", "texture_set": ["y.png"]},
        ]
        with patch.object(material_mod, "vision_available", return_value=True):
            out = consolidator._propose_uv_assist_merges(
                client=MagicMock(), target_object="Mesh", groups=groups,
            )
        assert out == []

    def test_vision_yes_produces_proposal_with_confidence(self):
        from app.phases import material as material_mod
        consolidator = material_mod.MaterialConsolidate()
        vc_stub = MagicMock()
        vc_stub.classify_image.return_value = "YES 0.9"
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod.MaterialConsolidate, "_render_uv_overlay",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            out = consolidator._propose_uv_assist_merges(
                client=MagicMock(), target_object="Mesh", groups=self._groups(),
            )
        assert len(out) == 1
        prop = out[0]
        assert prop["keeper"] == "Body.001"
        assert prop["to_remove"] == ["Body.002"]
        assert prop["shared_texture"] == "body_d.png"
        assert abs(prop["confidence"] - 0.9) < 1e-6
        assert prop["vision_suggested"] is True

    def test_vision_no_skips_proposal(self):
        from app.phases import material as material_mod
        consolidator = material_mod.MaterialConsolidate()
        vc_stub = MagicMock()
        vc_stub.classify_image.return_value = "NO 0.85"
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod.MaterialConsolidate, "_render_uv_overlay",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            out = consolidator._propose_uv_assist_merges(
                client=MagicMock(), target_object="Mesh", groups=self._groups(),
            )
        assert out == []

    def test_render_exception_skipped(self):
        from app.phases import material as material_mod
        consolidator = material_mod.MaterialConsolidate()
        vc_stub = MagicMock()
        vc_stub.classify_image.return_value = "YES 0.9"
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod.MaterialConsolidate, "_render_uv_overlay",
                         side_effect=RuntimeError("blender hiccup")),
        ):
            out = consolidator._propose_uv_assist_merges(
                client=MagicMock(), target_object="Mesh", groups=self._groups(),
            )
        # Render failure must not crash the scan; just skip the candidate.
        assert out == []

    def test_vlm_exception_skipped(self):
        from app.phases import material as material_mod
        consolidator = material_mod.MaterialConsolidate()
        vc_stub = MagicMock()
        vc_stub.classify_image.side_effect = RuntimeError("network 502")
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod.MaterialConsolidate, "_render_uv_overlay",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            out = consolidator._propose_uv_assist_merges(
                client=MagicMock(), target_object="Mesh", groups=self._groups(),
            )
        assert out == []


@pytest.mark.unit
class TestScanGroupsVisionMergeProposals:
    """Integration of UV-assist merges into _scan_groups output."""

    def test_scan_groups_appends_proposals_when_vision_yes(self):
        from app.phases import material as material_mod
        consolidator = material_mod.MaterialConsolidate()

        # Stub the Blender exchange to return a 2-group payload with overlap.
        fake_lines = [
            "GROUPS:" + json.dumps({
                "consolidation_groups": [
                    {"keeper": "A", "to_remove": [], "is_singleton": True,
                     "materials": ["A"], "texture_set": ["shared.png", "a.png"]},
                    {"keeper": "B", "to_remove": [], "is_singleton": True,
                     "materials": ["B"], "texture_set": ["shared.png"]},
                ],
                "material_count_before": 2,
            }),
        ]
        client = MagicMock()
        client.execute_and_extract.return_value = fake_lines

        vc_stub = MagicMock()
        vc_stub.classify_image.return_value = "YES 0.95"
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod.MaterialConsolidate, "_render_uv_overlay",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            err, payload = consolidator._scan_groups(client, "Mesh")
        assert err is None
        assert "vision_merge_proposals" in payload
        assert len(payload["vision_merge_proposals"]) == 1
        prop = payload["vision_merge_proposals"][0]
        assert {prop["keeper"], prop["to_remove"][0]} == {"A", "B"}

    def test_scan_groups_omits_field_when_no_proposals(self):
        """When vision is off OR no candidates, the field is absent — keeps
        the legacy payload shape for downstream consumers."""
        from app.phases import material as material_mod
        consolidator = material_mod.MaterialConsolidate()
        fake_lines = [
            "GROUPS:" + json.dumps({
                "consolidation_groups": [
                    {"keeper": "Only", "to_remove": [], "is_singleton": True,
                     "materials": ["Only"], "texture_set": ["x.png"]},
                ],
                "material_count_before": 1,
            }),
        ]
        client = MagicMock()
        client.execute_and_extract.return_value = fake_lines
        with patch.object(material_mod, "vision_available", return_value=False):
            err, payload = consolidator._scan_groups(client, "Mesh")
        assert err is None
        assert "vision_merge_proposals" not in payload


# ── suggest_texture_mapping — Layer 3 vision fallback (issue #22 Stage 1) ────


@pytest.mark.unit
class TestSuggestTextureMappingVisionFallback:
    """Layer 3 fallback: when vision_model is configured, classify by-pixel
    PBR channel for texture files that Layer 2 (filename LLM) left unused.

    Bypasses `_has_slot_token` for vision-derived slots — the VLM saw the
    pixels, which is stronger evidence than filename suffix matching.

    All tests run sync via asyncio.run for parity with the Layer 2 tests.
    """

    def test_vision_unavailable_skips_layer_3(self):
        """When vision_model is empty, Layer 2 result is returned unchanged
        and no VisionClient is ever built."""
        from app.phases import material as material_mod

        llm = _stub_llm(json.dumps({"body": {"Base Color": "body.png"}}))
        with (
            patch.object(material_mod, "vision_available", return_value=False),
            patch.object(material_mod, "VisionClient") as vc_cls,
        ):
            result = asyncio.run(material_mod.suggest_texture_mapping(
                llm, ["body"], ["body.png", "body_extra.png"], {},
            ))
        assert result == {"body": {"Base Color": "body.png"}}
        vc_cls.from_settings.assert_not_called()

    def test_vision_fills_unfilled_normal_slot(self):
        """VLM classifies an unused texture as a normal map — the Normal
        slot fills even though the filename has no `_n` suffix token."""
        from app.phases import material as material_mod

        llm = _stub_llm(json.dumps({"body": {"Base Color": "body.png"}}))
        vc_stub = MagicMock()
        vc_stub.classify_image.return_value = "normal"
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod, "image_to_base64",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            result = asyncio.run(material_mod.suggest_texture_mapping(
                llm, ["body"], ["body.png", "body_extra.png"], {},
            ))
        assert result == {
            "body": {"Base Color": "body.png", "Normal": "body_extra.png"},
        }

    def test_vision_alias_diffuse_maps_to_base_color(self):
        """Common synonyms (diffuse, albedo, basecolor) all collapse to
        the canonical 'Base Color' slot."""
        from app.phases import material as material_mod

        # Layer 2 returns nothing — sole texture is a candidate for Layer 3.
        llm = _stub_llm("{}")
        vc_stub = MagicMock()
        vc_stub.classify_image.return_value = "diffuse"
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod, "image_to_base64",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            result = asyncio.run(material_mod.suggest_texture_mapping(
                llm, ["body"], ["body.png"], {},
            ))
        assert result == {"body": {"Base Color": "body.png"}}

    def test_vision_unrecognized_response_is_dropped(self):
        """If the VLM replies with a non-PBR token, the slot stays unfilled
        rather than being polluted with garbage."""
        from app.phases import material as material_mod

        llm = _stub_llm(json.dumps({"body": {"Base Color": "body.png"}}))
        vc_stub = MagicMock()
        vc_stub.classify_image.return_value = "elephant"
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod, "image_to_base64",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            result = asyncio.run(material_mod.suggest_texture_mapping(
                llm, ["body"], ["body.png", "body_extra.png"], {},
            ))
        assert result == {"body": {"Base Color": "body.png"}}

    def test_vision_exception_is_swallowed(self):
        """Any VLM call failure (network, auth, decode) must NOT crash the
        widget pre-fill — Layer 2 output survives untouched."""
        from app.phases import material as material_mod

        llm = _stub_llm(json.dumps({"body": {"Base Color": "body.png"}}))
        vc_stub = MagicMock()
        vc_stub.classify_image.side_effect = RuntimeError("HTTP 502")
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod, "image_to_base64",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            result = asyncio.run(material_mod.suggest_texture_mapping(
                llm, ["body"], ["body.png", "body_extra.png"], {},
            ))
        assert result == {"body": {"Base Color": "body.png"}}

    def test_layer_3_does_not_reclassify_used_textures(self):
        """Files already assigned by Layer 2 are skipped — Layer 3 only
        targets the leftovers, so VLM cost scales with miss count."""
        from app.phases import material as material_mod

        llm = _stub_llm(json.dumps({
            "body": {"Base Color": "body.png", "Normal": "body_n.png"},
        }))
        vc_stub = MagicMock()
        vc_stub.classify_image.return_value = "roughness"
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod, "image_to_base64",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            result = asyncio.run(material_mod.suggest_texture_mapping(
                llm, ["body"], ["body.png", "body_n.png", "body_extra.png"], {},
            ))
        # body.png + body_n.png used by Layer 2 → only body_extra.png is
        # passed to the VLM (exactly one classify_image call).
        assert vc_stub.classify_image.call_count == 1
        assert result == {"body": {
            "Base Color": "body.png",
            "Normal": "body_n.png",
            "Roughness": "body_extra.png",
        }}

    def test_layer_3_routes_by_material_name_in_filename(self):
        """With multiple materials, an unused texture is routed to whichever
        material's name appears in its filename. Files matching no material
        name are skipped (no VLM call) — we have nowhere to put them."""
        from app.phases import material as material_mod

        # Layer 2 returns nothing; Layer 3 must pick the right material per file.
        llm = _stub_llm("{}")
        vc_stub = MagicMock()
        # Two files: hair_x.png belongs to 'hair'; orphan.png matches nobody.
        vc_stub.classify_image.return_value = "normal"
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod, "image_to_base64",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            result = asyncio.run(material_mod.suggest_texture_mapping(
                llm,
                ["body", "hair"],
                ["hair_x.png", "orphan.png"],
                {},
            ))
        # Only the file with an embedded material name is classified.
        assert vc_stub.classify_image.call_count == 1
        assert result == {"hair": {"Normal": "hair_x.png"}}

    def test_vision_known_unmapped_tokens_dropped_no_assignment(self):
        """ao / packed_orm / specular are real PBR channels but Principled
        BSDF has no slot for them. VLM correctly returning one of these
        must NOT be assigned to ANY slot (especially not 'other')."""
        from app.phases import material as material_mod

        llm = _stub_llm(json.dumps({"body": {"Base Color": "body.png"}}))
        for token in ("ao", "ambient_occlusion", "packed_orm", "orm", "specular"):
            vc_stub = MagicMock()
            vc_stub.classify_image.return_value = token
            with (
                patch.object(material_mod, "vision_available", return_value=True),
                patch.object(material_mod.VisionClient, "from_settings",
                             return_value=vc_stub),
                patch.object(material_mod, "image_to_base64",
                             return_value=("ZmFrZQ==", "image/jpeg")),
            ):
                result = asyncio.run(material_mod.suggest_texture_mapping(
                    llm, ["body"], ["body.png", "body_extra.png"], {},
                ))
            assert result == {"body": {"Base Color": "body.png"}}, (
                f"token {token!r} must not produce any slot assignment"
            )

    def test_vision_alpha_token_maps_first(self):
        """Alpha is at the top of the prompt vocabulary and must route
        cleanly — common Layer 2 miss for stylized models."""
        from app.phases import material as material_mod

        llm = _stub_llm("{}")
        vc_stub = MagicMock()
        vc_stub.classify_image.return_value = "alpha"
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod, "image_to_base64",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            result = asyncio.run(material_mod.suggest_texture_mapping(
                llm, ["body"], ["body_mask_xxx.png"], {},
            ))
        assert result == {"body": {"Alpha": "body_mask_xxx.png"}}

    def test_vision_marks_populates_provenance_map(self):
        """When the caller passes `vision_marks={}`, the dict is populated
        with {mat: [slot, ...]} for slots Layer 3 filled. Layer 2 slots
        are NOT included."""
        from app.phases import material as material_mod

        # Layer 2 fills Base Color; Layer 3 fills Normal via VLM.
        llm = _stub_llm(json.dumps({"body": {"Base Color": "body.png"}}))
        vc_stub = MagicMock()
        vc_stub.classify_image.return_value = "normal"
        marks: dict[str, list[str]] = {}
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod, "image_to_base64",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            asyncio.run(material_mod.suggest_texture_mapping(
                llm, ["body"], ["body.png", "body_extra.png"], {},
                vision_marks=marks,
            ))
        # Only Normal — Base Color came from Layer 2.
        assert marks == {"body": ["Normal"]}

    def test_vision_marks_unused_when_caller_passes_none(self):
        """Default `vision_marks=None` keeps the legacy signature working
        — no provenance, no exception."""
        from app.phases import material as material_mod

        llm = _stub_llm(json.dumps({"body": {"Base Color": "body.png"}}))
        vc_stub = MagicMock()
        vc_stub.classify_image.return_value = "normal"
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod, "image_to_base64",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            # No vision_marks kwarg → silent provenance.
            result = asyncio.run(material_mod.suggest_texture_mapping(
                llm, ["body"], ["body.png", "body_extra.png"], {},
            ))
        assert "Normal" in result["body"]

    def test_layer_3_single_material_routes_orphan_files(self):
        """Single-material models often have generic texture names (tex_01,
        ch_d, etc.) that don't carry the material name. With only one
        material to assign to, ambiguity disappears and the file IS routed.
        """
        from app.phases import material as material_mod

        llm = _stub_llm("{}")
        vc_stub = MagicMock()
        vc_stub.classify_image.return_value = "normal"
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
            patch.object(material_mod, "image_to_base64",
                         return_value=("ZmFrZQ==", "image/jpeg")),
        ):
            result = asyncio.run(material_mod.suggest_texture_mapping(
                llm,
                ["Body"],                          # only one material
                ["tex_01.png"],                    # filename has no 'body'
                {},
            ))
        # Single-material fallback overrides the name-match heuristic.
        assert result == {"Body": {"Normal": "tex_01.png"}}

    def test_layer_3_skips_when_no_unfilled_slots_left(self):
        """If Layer 2 already filled every slot for every material, Layer 3
        has nothing to add and shouldn't waste a VLM call."""
        from app.phases import material as material_mod

        # Layer 2 fills all six PBS slots — but we only need to assert
        # that vc.classify_image is NOT called when there's no slot to fill.
        llm = _stub_llm(json.dumps({
            "body": {
                "Base Color": "body.png",
                "Alpha":      "body_a.png",
                "Roughness":  "body_r.png",
                "Metallic":   "body_m.png",
                "Emission":   "body_e.png",
                "Normal":     "body_n.png",
            },
        }))
        vc_stub = MagicMock()
        with (
            patch.object(material_mod, "vision_available", return_value=True),
            patch.object(material_mod.VisionClient, "from_settings",
                         return_value=vc_stub),
        ):
            asyncio.run(material_mod.suggest_texture_mapping(
                llm,
                ["body"],
                ["body.png", "body_a.png", "body_r.png", "body_m.png",
                 "body_e.png", "body_n.png", "body_extra.png"],
                {},
            ))
        vc_stub.classify_image.assert_not_called()
