"""T2 for the material tools, on modpilot.testing.materials' textured avatar: claude_run1's replay
cannot reach its material calls (they name materials run1's restructure_mesh.py regrouped first;
tools-5.2 compat.legacy_baseline.run1_steps). Legacy tool and new step start from the same saved
scene; results, scene fingerprints and, for material_generate, the files written must agree, apart
from INTENDED below.
"""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tests.diff.diffkit import (
    VERSIONS,
    differing_sections,
    fingerprint,
    result_differences,
    run_legacy,
    session_and_client,
)

pytestmark = pytest.mark.blender

# The legacy material_generate returned the generator's *setting* (empty unless given), not the
# collection it wrote into; batch_export callers guessed the name.
INTENDED = {"material_generate": {"mdf_collection": ("", "MHWilds_Female.mdf2")}}

GENERATE = {"mesh_collection": "MHWilds_Female.mesh", "texture_base_path": "test/Avatar/",
            "preset_mapping": {"MatA": "Character", "MatB": "Skin"}}


@pytest.fixture(scope="module", params=VERSIONS)
def env(request, tmp_path_factory):
    work = tmp_path_factory.mktemp(f"mat-{request.param}")
    with session_and_client(request.param, work) as (s, c):
        out = s.execute("import json\nfrom modpilot.testing.materials import textured_avatar\n"
                        f"print('TEX=' + json.dumps(textured_avatar({str(work / 'tex')!r})))\n")
        tex = json.loads(next(ln for ln in out.splitlines() if ln.startswith("TEX="))[4:])
        ck = work / "avatar.blend"
        s.execute(f"import bpy\nbpy.ops.wm.save_as_mainfile(filepath={str(ck)!r}, copy=True)\n")
        yield s, c, work, tex, ck


def _both(session, client, ck, tool, params, before_new=None):
    session.open(ck)
    legacy = run_legacy(client, tool, params)
    assert legacy.success, (tool, legacy.error)
    fp_old = fingerprint(session)
    if before_new:
        before_new()
    session.open(ck)
    report = session.call(tool, params)
    return legacy, fp_old, report, fingerprint(session)


@pytest.mark.parametrize("x_preset", ["VRChat", "終末地"])
def test_material_setup_does_what_the_legacy_tool_did(env, x_preset):
    session, client, _, tex, ck = env
    params = {"target_object": "Body", "x_preset": x_preset, "texture_mapping": tex}
    legacy, fp_old, report, fp_new = _both(session, client, ck, "material_setup", params)
    assert result_differences(legacy.state_diff, report) == {}
    assert differing_sections(fp_old, fp_new) == {}


def _manifest(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_material_generate_does_what_the_legacy_tool_did(env):
    session, client, work, tex, ck = env
    session.open(ck)
    session.call("material_setup", {"target_object": "Body", "x_preset": "VRChat",
                                    "texture_mapping": {m: {"Base Color": s["Base Color"]} for m, s in tex.items()}})
    ck2 = work / "wired.blend"
    session.execute(f"import bpy\nbpy.ops.wm.save_as_mainfile(filepath={str(ck2)!r}, copy=True)\n")
    root = work / "mod"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir()
    params = {**GENERATE, "natives_root": str(root)}
    files = {}

    def keep_legacy_files():
        files["legacy"] = _manifest(root)
        shutil.rmtree(root)
        root.mkdir()
    legacy, fp_old, report, fp_new = _both(session, client, ck2, "material_generate", params, keep_legacy_files)
    assert files["legacy"], "the legacy tool wrote nothing"
    assert result_differences(legacy.state_diff, report) == INTENDED["material_generate"]
    assert differing_sections(fp_old, fp_new) == {}
    assert _manifest(root) == files["legacy"]
