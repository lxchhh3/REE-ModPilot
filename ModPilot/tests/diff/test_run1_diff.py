"""T2: claude_run1's own calls (tests/golden/claude_run1.jsonl), legacy tool vs new step, each from
the checkpoint before it. Results must agree on every key the legacy tool reported, and the two
scenes must fingerprint the same (the new steps' scene config aside). A port joins
app.phases._bridge.PORTED only once its calls are listed here and pass in both Blender versions.

claude_run1's replay (tools-5.2 compat.legacy_baseline.run1_steps) runs calls 0-10, 14 and 15;
the setup calls 0-3 are in test_setup_diff.py.
"""
import pytest

from tests.diff.diffkit import (
    VERSIONS,
    checkpoint_before,
    differing_sections,
    fingerprint,
    golden_params,
    result_differences,
    run_legacy,
    session_and_client,
    start,
)

pytestmark = pytest.mark.blender

# replay step index (the checkpoint numbering) -> call index in claude_run1.jsonl
CALLS = {
    4: 4,     # pose_correction
    5: 5,     # skeleton_align
    6: 6,     # vertex_groups (the BHS outfit's 12 meshes)
    7: 7,     # physics_transplant
    8: 8,     # physics_classification
    9: 9,     # physics_chains prepare_only
    10: 10,   # physics_chains: 66 heads typed, 18 bones merged, SEPARATE settings
    11: 14,   # collider_create
    12: 15,   # collider_apply: every chain group's masks off
}


@pytest.fixture(scope="module", params=VERSIONS)
def env(request, tmp_path_factory):
    with session_and_client(request.param, tmp_path_factory.mktemp(f"run1-{request.param}")) as (s, c):
        yield request.param, s, c


@pytest.mark.parametrize("step_index", sorted(CALLS))
def test_the_new_step_does_what_the_legacy_tool_did(env, step_index):
    version, session, client = env
    tool, params = golden_params("claude_run1", CALLS[step_index])
    ck = checkpoint_before(version, step_index)
    start(session, ck)
    legacy = run_legacy(client, tool, params)
    assert legacy.success, (tool, legacy.error)
    fp_old = fingerprint(session)
    start(session, ck)
    report = session.call(tool, params)
    fp_new = fingerprint(session)
    assert result_differences(legacy.state_diff, report) == {}, tool
    assert differing_sections(fp_old, fp_new) == {}, tool
