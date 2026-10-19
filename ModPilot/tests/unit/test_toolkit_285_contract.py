"""Modding-Toolkit 2.8.5 / RE Chain Editor v14 contract (tools-5.2 L0, 2026-10-11).

What changed upstream, measured in Blender 4.3.0 and 5.2.2 by tools-5.2:
  - Toolkit a31fb82 renamed bundled presets to ASCII file stems
    (怪猎荒野.json -> mhws.json, 终末地.json -> arknights.json). The enum values
    ModPilot assigns are file names, so the old literals raise TypeError.
  - Toolkit d872b9c renamed modder.tpose_direction -> modder.mmd_a_to_tpose.
  - re_chain.create_full_body_clsp only ever existed in the MHWilds_Chain_Editor
    fork; RE Chain Editor imports the same bundled preset via re_clsp.importfile.
  - getattr(bpy.ops.<ns>, '<op>', None) is never None, so a missing operator
    must be detected with `'<op>' in dir(bpy.ops.<ns>)`.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.blender.preset_catalog import SHIPPED_X_PRESETS
from app.phases import base
from app.phases.physics_bones import PhysicsChains, PhysicsClassification, PhysicsTransplant
from app.phases.physics_colliders import _FULL_BODY_CLSP_PATH, ColliderCreate
from app.phases.pose_correction import PoseCorrection
from app.phases.skeleton_align import SkeletonAlign
from app.phases.vertex_groups import VertexGroups

pytestmark = pytest.mark.unit

# X_PRESET stems in Modding-Toolkit 2.8.5 assets/presets/import/ (sf6 is a Y_PRESET).
TOOLKIT_285_X_STEMS = {
    "MMD", "RE6", "VRChat", "arknights", "dmc5", "dmc5_alt", "gbf", "hd2",
    "mhwi_world", "mhwr", "mhws", "re4", "re9", "uma", "valve", "vrm",
}


def _sent_code(client: MagicMock) -> str:
    return "\n".join(c.args[0] for c in client.execute_and_extract.call_args_list)


# ── preset identifiers ───────────────────────────────────────────────────────


def test_default_y_preset_is_the_mhws_stem():
    assert base.DEFAULT_Y_PRESET == "mhws"
    assert base.Y_PRESETS == frozenset({"mhws"})


def test_shipped_x_presets_match_toolkit_285():
    assert set(SHIPPED_X_PRESETS) == TOOLKIT_285_X_STEMS


@pytest.mark.parametrize("tool_cls", [SkeletonAlign, VertexGroups, PhysicsTransplant, PoseCorrection])
def test_schema_x_preset_enum_uses_stems(tool_cls):
    props = tool_cls.tool_schema()["input_schema"]["properties"]
    assert props["x_preset"]["enum"] == ["MMD", "VRChat", "arknights"]


@pytest.mark.parametrize("tool_cls", [SkeletonAlign, VertexGroups, PhysicsTransplant])
def test_schema_y_preset_enum_is_mhws(tool_cls):
    props = tool_cls.tool_schema()["input_schema"]["properties"]
    assert props["y_preset"]["enum"] == ["mhws"]


def test_no_old_chinese_preset_file_names_in_schemas():
    for tool_cls in (SkeletonAlign, VertexGroups, PhysicsTransplant, PoseCorrection):
        dumped = json.dumps(tool_cls.tool_schema(), ensure_ascii=False)
        assert "怪猎荒野" not in dumped and "终末地" not in dumped, tool_cls.__name__


# ── physics_bones: the two hardcoded MHWilds X-preset switches ───────────────


def test_physics_classification_switches_x_preset_to_mhws():
    client = MagicMock()
    client.execute_and_extract.return_value = ["PRECONDITION:not_found:Arm"]
    PhysicsClassification()._inspect_and_refresh(client, "Arm")
    code = _sent_code(client)
    assert "settings.import_preset_enum = 'mhws.json'" in code
    assert "怪猎荒野" not in code


def test_physics_chains_switches_x_preset_to_mhws():
    client = MagicMock()
    client.execute_and_extract.return_value = ["PRECONDITION:chain_collection_create_failed"]
    PhysicsChains()._create_chains(client, "Arm", "")
    code = _sent_code(client)
    assert "settings.import_preset_enum = 'mhws.json'" in code
    assert "怪猎荒野" not in code


# ── physics_colliders: full-body clsp through RE Chain Editor ────────────────


def test_bundled_full_body_clsp_exists():
    assert _FULL_BODY_CLSP_PATH.is_file()
    assert _FULL_BODY_CLSP_PATH.name == "full_body.clsp.3"


def test_collider_create_imports_bundled_preset_via_re_clsp_importfile():
    client = MagicMock()
    client.execute_and_extract.return_value = [
        "FULL_BODY:" + json.dumps({"colliders": [], "chain_groups": [], "clsp_collection": ""})
    ]
    cache = MagicMock()
    cache.refresh.return_value.diff.return_value = {}
    result = ColliderCreate().run(client, cache, {})
    assert result.success, result.error
    code = _sent_code(client)
    assert "bpy.ops.re_clsp.importfile(" in code
    assert repr(str(_FULL_BODY_CLSP_PATH)) in code
    assert "'importfile' in dir(bpy.ops.re_clsp)" in code
    assert "getattr(bpy.ops" not in code
    assert "create_full_body_clsp" not in code


def test_collider_create_missing_importer_is_a_precondition_error():
    client = MagicMock()
    client.execute_and_extract.return_value = ["MISSING_OP:re_clsp.importfile"]
    cache = MagicMock()
    result = ColliderCreate().run(client, cache, {})
    assert not result.success
    assert result.error.category == "precondition"
    assert "re_clsp.importfile" in result.error.message
    assert "RE Chain Editor" in result.error.suggestion
