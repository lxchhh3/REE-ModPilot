"""T2 for the last three legacy tools (ported before M6 deletes app/): physics_adjust on
modpilot.testing.rigs' exportable avatar, with the shape of tools-5.2's coverage call (scenarios/maya_coverage.json:
one scalar on one chain-settings object; 0.35, as the rig already has its 0.2) and a vector; material_inspect and material_consolidate (dry
run and merge) on modpilot.testing.materials' textured avatar. Legacy tool and new step start from the
same saved scene; results and scene fingerprints must agree."""
import json

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


def _save(session, path):
    session.execute(f"import bpy\nbpy.ops.wm.save_as_mainfile(filepath={str(path)!r}, copy=True)\n")
    return path


@pytest.fixture(scope="module", params=VERSIONS)
def env(request, tmp_path_factory):
    work = tmp_path_factory.mktemp(f"last-{request.param}")
    with session_and_client(request.param, work) as (s, c):
        out = s.execute("import bpy\nfrom modpilot.testing.rigs import exportable\n"
                        f"exportable({str(work / 'scene')!r})\n"
                        "print('CS=' + next(o.name for o in bpy.data.objects if o.get('TYPE') == 'RE_CHAIN_CHAINSETTINGS'))\n")
        cs = next(ln for ln in out.splitlines() if ln.startswith("CS="))[3:]
        rig = _save(s, work / "rig.blend")
        # the textured avatar, with MatA and MatB on one base colour and normal texture and a texture-less third slot
        out = s.execute("import bpy, json\nimport modpilot\n"
                        "from modpilot.testing.materials import node_material, textured_avatar\n"
                        "bpy.ops.wm.read_homefile(use_empty=True)\n"
                        f"tex = textured_avatar({str(work / 'tex')!r})\n"
                        "bc = tex['MatA']['Base Color']\n"
                        "modpilot.call('material_setup', {'target_object': 'Body', 'x_preset': 'VRChat', 'texture_mapping':"
                        " {'MatA': {'Base Color': bc, 'Normal': tex['MatA']['Normal']}, 'MatB': {'Base Color': bc, 'Normal': tex['MatA']['Normal']}}}, quiet=True)\n"
                        "bpy.data.objects['Body'].data.materials.append(node_material('Plain'))\n"
                        "print('OK')\n")
        assert "OK" in out, out
        mats = _save(s, work / "materials.blend")
        yield s, c, work, cs, rig, mats


def _both(session, client, ck, tool, params):
    session.open(ck)
    legacy = run_legacy(client, tool, params)
    assert legacy.success, (tool, legacy.error)
    fp_old = fingerprint(session)
    session.open(ck)
    report = session.call(tool, params)
    return legacy, fp_old, report, fingerprint(session)


@pytest.mark.parametrize("properties", [{"damping": 0.35}, {"gravity": [0, -3.0, 0], "springForce": 0.4}])
def test_physics_adjust_does_what_the_legacy_tool_did(env, properties):
    session, client, _, cs, rig, _ = env
    legacy, fp_old, report, fp_new = _both(session, client, rig, "physics_adjust",
                                           {"targets": [cs], "properties": properties})
    assert legacy.state_diff == {"adjusted_targets": [cs]}
    assert result_differences(legacy.state_diff, report) == {}
    assert differing_sections(fp_old, fp_new) == {}
    assert fp_old != fingerprint_of(session, rig), "the adjustment changed nothing the fingerprint sees"


def fingerprint_of(session, ck):
    session.open(ck)
    return fingerprint(session)


@pytest.mark.parametrize("purpose", ["classify", "verify"])
def test_material_inspect_answers_what_the_legacy_tool_did(env, purpose):
    session, client, work, _, _, mats = env
    params = {"target_object": "Body", "texture_dir": str(work / "tex"), "purpose": purpose}
    legacy, fp_old, report, fp_new = _both(session, client, mats, "material_inspect", params)
    assert legacy.state_diff["existing_connections"]["MatA"]["Normal"], legacy.state_diff
    assert result_differences(legacy.state_diff, report) == {}
    assert differing_sections(fp_old, fp_new) == {}


@pytest.mark.parametrize("params", [
    {"dry_run": True},
    {"dry_run": False, "groups": [{"keeper": "MatA", "to_remove": ["MatB"]}]},
    {"dry_run": False, "groups": [{"keeper": "MatB", "to_remove": ["MatA"]}]},
], ids=["dry-run", "merge-down", "merge-up"])
def test_material_consolidate_does_what_the_legacy_tool_did(env, params):
    session, client, _, _, _, mats = env
    legacy, fp_old, report, fp_new = _both(session, client, mats, "material_consolidate",
                                           {"target_object": "Body", **params})
    if params["dry_run"]:
        assert [g["materials"] for g in legacy.state_diff["consolidation_groups"]] == [["MatA", "MatB"], ["Plain"]]
        assert "vision_merge_proposals" not in legacy.state_diff
    assert result_differences(legacy.state_diff, report) == {}, json.dumps(report["data"])
    assert differing_sections(fp_old, fp_new) == {}
