"""T2 for the query tools: on modpilot.testing.rigs' exportable avatar (chains, colliders, materials),
each legacy query's JSON against the new step's data in the legacy shape
(app.phases._bridge.QUERY_SHAPES), apart from INTENDED."""
import json

import pytest

from app.phases._bridge import QUERY_SHAPES
from tests.diff.diffkit import VERSIONS, run_legacy, session_and_client

pytestmark = pytest.mark.blender

ARM = "MHWilds_Female Armature"


def _intended_scene_info(legacy, new):
    # blender-mcp's get_scene_info lists the first 10 objects only (ModPilot lesson #57)
    assert len(legacy["objects"]) == 10 and new["objects"][:10] == legacy["objects"]
    return {**new, "objects": new["objects"][:10]}


INTENDED = {"scene_info": _intended_scene_info}


@pytest.fixture(scope="module", params=VERSIONS)
def env(request, tmp_path_factory):
    work = tmp_path_factory.mktemp(f"query-{request.param}")
    with session_and_client(request.param, work) as (s, c):
        out = s.execute("import bpy, json\nfrom modpilot.testing.rigs import exportable\n"
                        f"exportable({str(work / 'scene')!r})\n"
                        "mesh = next(o.name for o in bpy.data.collections['MHWilds_Female.mesh'].objects if o.type == 'MESH')\n"
                        "cs = next(o.name for o in bpy.data.objects if o.get('TYPE') == 'RE_CHAIN_CHAINSETTINGS')\n"
                        "print('NAMES=' + json.dumps([mesh, cs]))\n")
        mesh, cs = json.loads(next(ln for ln in out.splitlines() if ln.startswith("NAMES="))[6:])
        yield s, c, mesh, cs


CASES = [
    ("scene_info", {}),
    ("list_objects", {"type_filter": "MESH"}),
    ("get_bone_info", {"armature_name": ARM, "filter_custom_prop": "chain_role"}),
    ("list_collections", {}),
    ("list_collections", {"chain_only": True}),
    ("get_mesh_info", {"mesh_name": "<mesh>", "max_vgroups": 5}),
    ("get_material_info", {"mesh_name": "<mesh>"}),
    ("get_object_props", {"object_name": "<cs>"}),
    ("inspect_material_nodes", {"material_name": "BodyMat"}),
    ("physics_read", {}),
    ("physics_read", {"targets": ["<cs>"], "properties": ["damping", "gravity"]}),
    ("list_mdf_presets", {}),
]


@pytest.mark.parametrize("tool, params", CASES, ids=[f"{t}-{i}" for i, (t, _) in enumerate(CASES)])
def test_the_new_query_answers_what_the_legacy_one_did(env, tool, params):
    session, client, mesh, cs = env
    params = {k: ([cs if x == "<cs>" else x for x in v] if isinstance(v, list)
                  else {"<mesh>": mesh, "<cs>": cs}.get(v, v)) for k, v in params.items()}
    legacy = run_legacy(client, tool, params)
    assert not (isinstance(legacy, dict) and "error" in legacy), legacy
    new = QUERY_SHAPES[tool](session.call(tool, params)["data"])
    if tool in INTENDED:
        new = INTENDED[tool](legacy, new)
    assert json.loads(json.dumps(new)) == legacy
