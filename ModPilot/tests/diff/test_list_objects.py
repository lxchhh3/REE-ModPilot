"""T2: list_objects, legacy query tool vs the new step, on every claude_run1 checkpoint."""
import json

import pytest

from app.phases._bridge import BridgedQueryTool
from app.phases.query_tools import ListObjects
from tests.diff.diffkit import VERSIONS, checkpoints, session_and_client

pytestmark = pytest.mark.blender


@pytest.mark.parametrize("version", VERSIONS)
def test_list_objects_agrees_on_every_checkpoint(version, tmp_path):
    legacy, new = ListObjects(), BridgedQueryTool(ListObjects())
    seen = 0
    with session_and_client(version, tmp_path) as (session, client):
        for ck in checkpoints(version):
            session.open(ck)
            for params in ({}, {"type_filter": "ARMATURE"}, {"type_filter": "mesh"}):
                old = json.loads(legacy.run(client, params))
                assert isinstance(old, list), (ck.name, old)
                assert json.loads(new.run(client, params)) == old, (ck.name, params)
                seen += len(old)
    assert seen > 0
