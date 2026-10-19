"""T2: the setup tools, legacy vs new, on claude_run1's own calls 0-3 (each from the checkpoint
before it) and on both preset writers. Results must agree on every key the legacy tool reported;
scenes must fingerprint the same (the new steps' scene config aside)."""
import json
from pathlib import Path

import pytest

from tests.diff.diffkit import (
    VERSIONS,
    checkpoint_before,
    differing_sections,
    fingerprint,
    golden_params,
    run_legacy,
    session_and_client,
    start,
)

pytestmark = pytest.mark.blender

SCENE_DIFF_KEYS = {"object_count", "objects_added", "objects_removed", "materials_count"}


def _compare_results(legacy_diff: dict, report: dict) -> dict:
    new = {**report["data"], **report["scene_diff"]}
    return {k: (v, new.get(k, "<missing>")) for k, v in legacy_diff.items() if new.get(k, "<missing>") != v}


@pytest.mark.parametrize("version", VERSIONS)
def test_setup_tools_agree_on_claude_run1(version, tmp_path):
    checked = []
    with session_and_client(version, tmp_path) as (session, client):
        for i in range(4):
            tool, params = golden_params("claude_run1", i)
            ck = checkpoint_before(version, i)
            start(session, ck)
            legacy = run_legacy(client, tool, params)
            assert legacy.success, (tool, legacy.error)
            fp_old = fingerprint(session)
            start(session, ck)
            report = session.call(tool, params)
            fp_new = fingerprint(session)
            assert _compare_results(legacy.state_diff, report) == {}, tool
            assert differing_sections(fp_old, fp_new) == {}, tool
            checked.append(tool)
    assert checked == ["setup_import_source", "setup_validate_scene", "setup_infer_model_type",
                       "setup_import_mhwilds"]


@pytest.mark.parametrize("version", VERSIONS)
def test_preset_writers_write_the_same_files(version, tmp_path):
    cases = [("setup_preset_supplement_write", {"base_preset_name": "VRChat", "mappings": {"head": "Kopf",
                                                                                           "upperarm_L": "Arm.L"}}),
             ("setup_preset_custom_write", {"character_name": "Probe", "mappings": {"pelvis": "Root", "head": "Kopf"},
                                            "description": "d"})]
    with session_and_client(version, tmp_path) as (session, client):
        for tool, params in cases:
            legacy = run_legacy(client, tool, params)
            assert legacy.success, legacy.error
            path = Path(legacy.state_diff["new_preset_path"])
            old_file = json.loads(path.read_text(encoding="utf-8"))
            path.unlink()
            report = session.call(tool, params)
            assert Path(report["data"]["new_preset_path"]) == path
            assert json.loads(path.read_text(encoding="utf-8")) == old_file, tool
            assert _compare_results(legacy.state_diff, report) == {}, tool
            path.unlink()
