"""setup_import_source's source-rig fixes (Blender-MHWilds lesson #44; Marette's mfbase_to_base.py).

A garment the FBX hangs rigidly on a bone has no vertex groups, so the join and re-parent dropped
it onto Hip (the GG headset); MochiFitter's '<bone>_MFBase' helper bones have no MH Wilds bone,
so the clothes weighted to them did not follow the body. Both are turned into what the pipeline
handles right after the import, whether ModPilot imported the FBX or the user did. Behaviour in
Blender is pinned by tools-5.2 tests/test_l3_fixes.py.
"""

import ast
import json
from unittest.mock import MagicMock

import pytest

from app.blender.state import SceneCache
from app.phases.setup import SOURCE_FIX_SRC, SetupImportSource

pytestmark = pytest.mark.unit

FIXES = {"rigid_to_skinned": {"Headset": "Neck"}, "mfbase_folded": {"breast_L_MFBase": "breast_L"},
         "mfbase_skipped": {}}


def _client(payload):
    client = MagicMock()
    client.execute_and_extract.return_value = [json.dumps(payload)]
    client.get_scene_info.return_value = {"name": "Scene", "object_count": 0, "objects": [], "materials_count": 0}
    return client


def test_source_fix_source_is_valid_python():
    ast.parse(SOURCE_FIX_SRC)


def test_fixes_run_on_both_paths():
    client = _client({"status": "already_imported", "source_armature": "Armature", "source_fixes": FIXES})
    SetupImportSource().run(client, SceneCache(client), {"file_path": "C:/m.fbx"})
    code = client.execute_and_extract.call_args_list[0].args[0]
    assert SOURCE_FIX_SRC in code
    assert code.count("_fix_source_rig(") >= 3  # the definition + the already-imported + the imported path


@pytest.mark.parametrize("status", ["already_imported", "imported"])
def test_fixes_reach_the_result(status):
    client = _client({"status": status, "source_armature": "Armature", "imported_objects": [],
                      "source_fixes": FIXES})
    result = SetupImportSource().run(client, SceneCache(client), {"file_path": "C:/m.fbx"})
    assert result.success
    assert result.state_diff["source_fixes"] == FIXES
