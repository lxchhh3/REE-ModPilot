"""modpilot_host.session: a private headless Blender serving the blender-mcp bridge on a free port,
with the pinned add-ons and the modpilot package linked in. The same transport then drives it
exactly as it drives kevin's own Blender on 9876."""
from pathlib import Path

import pytest

from modpilot.core.errors import StepError
from modpilot_host.session import HeadlessSession

pytestmark = pytest.mark.blender

CHECKPOINTS = (Path(__file__).resolve().parents[4] / "tools-5.2" / "runtime" / "cache" / "legacy"
               / "claude_run1" / "5.2.2-checkpoints")


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    with HeadlessSession("5.2.2", tmp_path_factory.mktemp("hs")) as s:
        yield s


def test_a_call_goes_through_the_bridge(session):
    r = session.call("doctor", {"require": ["re_chain", "modder"]})
    assert r["ok"] and r["data"]["background"] is True and r["data"]["blender"].startswith("5.2.2")


def test_a_step_error_reaches_the_host_unchanged(session):
    with pytest.raises(StepError) as e:
        session.call("doctor", {"require": ["no_such_ns"]})
    assert e.value.category == "environment" and e.value.step == "doctor"
    assert e.value.details["missing"] == ["no_such_ns"]


def test_the_session_opens_a_checkpoint(session):
    ck = CHECKPOINTS / "06_vertex_groups.blend"
    if not ck.is_file():
        pytest.skip(f"no legacy checkpoint at {ck} (python -m compat.legacy_baseline checkpoints)")
    session.open(ck)
    names = {o["name"] for o in session.call("list_objects", {"type_filter": "ARMATURE"})["data"]["objects"]}
    assert "MHWilds_Female Armature" in names
