"""T2 for batch_export, on modpilot.testing.rigs' exportable avatar (claude_run1's replay cannot
reach its export call; tools-5.2 compat.legacy_baseline.run1_steps). Legacy tool and new step
start from the same saved scene; results, scene fingerprints and the files written must agree."""
import hashlib
import json
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


def _manifest(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module", params=VERSIONS)
def env(request, tmp_path_factory):
    work = tmp_path_factory.mktemp(f"export-{request.param}")
    with session_and_client(request.param, work) as (s, c):
        out = s.execute("import json\nfrom modpilot.testing.rigs import exportable\n"
                        f"root, params = exportable({str(work / 'scene')!r})\n"
                        "print('PARAMS=' + json.dumps(params))\n")
        params = json.loads(next(ln for ln in out.splitlines() if ln.startswith("PARAMS="))[7:])
        ck = work / "exportable.blend"
        s.execute(f"import bpy\nbpy.ops.wm.save_as_mainfile(filepath={str(ck)!r}, copy=True)\n")
        yield s, c, params, ck


def test_batch_export_does_what_the_legacy_tool_did(env):
    session, client, params, ck = env
    root = Path(params["natives_root"])
    before = _manifest(root)          # material_generate's textures

    # the legacy tool needs every name (as the golden calls pass them)
    params = {**params, "mesh_collection": "MHWilds_Female.mesh", "mdf2_collection": "MHWilds_Female.mdf2",
              "chain2_collection": "MHWilds_Female.chain2", "target_armature": "MHWilds_Female Armature"}
    session.open(ck)
    legacy = run_legacy(client, "batch_export", params)
    assert legacy.success, legacy.error
    fp_old = fingerprint(session)
    files_old = {k: v for k, v in _manifest(root).items() if k not in before}
    for rel in files_old:
        (root / rel).unlink()
    session.open(ck)
    report = session.call("batch_export", params)
    fp_new = fingerprint(session)
    files_new = {k: v for k, v in _manifest(root).items() if k not in before}
    diffs = result_differences(legacy.state_diff, report)
    assert files_old, "the legacy tool wrote nothing"
    assert diffs == {}
    assert differing_sections(fp_old, fp_new) == {}
    assert files_new == files_old
