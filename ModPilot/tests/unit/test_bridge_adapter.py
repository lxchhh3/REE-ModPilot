"""app.phases._bridge: the strangler adapter of the restructure (M1). A tool named in PORTED runs as
the new in-Blender step (modpilot.call over the same client) while keeping the legacy tool's
name, schema and result shape, so the agent loop and tools-5.2's L3 replays run the new code
unchanged. Everything not ported stays the legacy tool."""
import json
from unittest.mock import MagicMock

import pytest

from app.blender.client import BlenderError
from app.phases import _bridge
from app.phases.base import PhaseResult, PhaseTool
from app.phases.query_tools import ListObjects, QueryTool
from modpilot.core.errors import StepError

pytestmark = pytest.mark.unit


def _report(step, data, scene_diff=None):
    return {"ok": True, "step": step, "params": {}, "data": data, "warnings": [], "skipped": [],
            "scene_diff": scene_diff or {}, "popups": [], "seconds": 0.1, "code": {}, "blender": "5.2.2"}


def _client_ok(report):
    c = MagicMock()
    c.execute.return_value = "add-on chatter\nMODPILOT_REPORT=" + json.dumps(report) + "\n"
    return c


def _client_err(err: StepError):
    c = MagicMock()
    c.execute.side_effect = BlenderError(json.dumps({"exception_type": "StepError", "message": str(err),
                                                     "traceback": "..."}))
    return c


class Legacy(PhaseTool):
    @property
    def name(self):
        return "legacy_x"

    @property
    def phase_slot(self):
        return "phase_9"

    @classmethod
    def tool_schema(cls):
        return {"name": "legacy_x", "description": "d", "input_schema": {"type": "object", "properties": {}}}

    def run(self, client, cache, params):
        raise AssertionError("a ported tool must not run its legacy code")


def test_only_ported_names_are_replaced():
    catalog = {"list_objects": ListObjects(), "scene_info": object()}
    wrapped = _bridge.wrap(catalog, ported={"list_objects"})
    assert isinstance(wrapped["list_objects"], _bridge.BridgedQueryTool)
    assert isinstance(wrapped["list_objects"], QueryTool)
    assert wrapped["scene_info"] is catalog["scene_info"]
    assert wrapped["list_objects"].tool_schema() == ListObjects.tool_schema()


@pytest.mark.bridged_catalog
def test_the_legacy_catalog_is_still_reachable_for_differential_tests():
    from app.agent.phase_loop import build_full_tool_catalog, legacy_tool_catalog
    for name in _bridge.PORTED:
        assert not isinstance(legacy_tool_catalog()[name], (_bridge.BridgedQueryTool, _bridge.BridgedPhaseTool))
        assert isinstance(build_full_tool_catalog()[name], (_bridge.BridgedQueryTool, _bridge.BridgedPhaseTool))


def test_a_bridged_query_returns_the_legacy_json_shape():
    objs = [{"name": "A", "type": "MESH", "visible": True, "hide_viewport": False, "hide_get": False}]
    client = _client_ok(_report("list_objects", {"objects": objs}))
    out = _bridge.BridgedQueryTool(ListObjects()).run(client, {"type_filter": "MESH"})
    assert json.loads(out) == objs
    sent = client.execute.call_args.args[0]
    assert "modpilot.call('list_objects', {'type_filter': 'MESH'})" in sent


def test_a_bridged_query_that_fails_returns_the_legacy_error_json():
    client = _client_err(StepError("params", "unknown param(s) x", step="list_objects"))
    out = json.loads(_bridge.BridgedQueryTool(ListObjects()).run(client, {"x": 1}))
    assert "unknown param" in out["error"] and out["step_error"]["category"] == "params"


def test_a_bridged_phase_tool_returns_data_and_scene_diff_as_state_diff():
    client = _client_ok(_report("legacy_x", {"end_bones_added": ["A_End"]}, {"objects_added": ["X"]}))
    tool = _bridge.BridgedPhaseTool(Legacy())
    assert (tool.name, tool.phase_slot, tool.tool_schema()) == ("legacy_x", "phase_9", Legacy.tool_schema())
    r = tool.run(client, MagicMock(), {})
    assert isinstance(r, PhaseResult) and r.success
    assert r.state_diff == {"end_bones_added": ["A_End"], "objects_added": ["X"]}


@pytest.mark.parametrize("category,legacy", [("params", "precondition"), ("precondition", "precondition"),
                                             ("environment", "precondition"), ("operator", "operator_failed"),
                                             ("postcondition", "operator_failed"), ("internal", "unexpected")])
def test_a_step_error_becomes_the_legacy_phase_error(category, legacy):
    err = StepError(category, "went wrong", step="legacy_x", operator="mhws.x", details={"k": 1})
    r = _bridge.BridgedPhaseTool(Legacy()).run(_client_err(err), MagicMock(), {})
    assert not r.success
    assert (r.error.category, r.error.operator, r.error.message) == (legacy, "mhws.x", "went wrong")
    assert json.loads(r.error.raw) == err.to_dict()


def test_a_bridge_failure_that_is_not_a_step_error_is_unexpected():
    c = MagicMock()
    c.execute.side_effect = BlenderError("No module named 'modpilot'")
    r = _bridge.BridgedPhaseTool(Legacy()).run(c, MagicMock(), {})
    assert not r.success and r.error.category == "unexpected" and "modpilot" in r.error.message


def test_a_step_error_can_carry_the_legacy_category_the_agent_loop_keys_on():
    # setup_infer_model_type's no-match failure: the legacy loop offers [Force Custom] on it
    err = StepError("precondition", "No X-preset matched", step="legacy_x",
                    details={"legacy_category": "unsupported_rig", "result": {"decision": "unsupported"}})
    r = _bridge.BridgedPhaseTool(Legacy()).run(_client_err(err), MagicMock(), {})
    assert r.error.category == "unsupported_rig"
