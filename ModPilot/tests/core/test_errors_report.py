"""modpilot.core.errors / report: every failure is a StepError whose text carries its structured
form (both Blender bridges hand an exception back to the host as text), and a report is plain
JSON (the legacy tools' results came back as printed lines after a sentinel)."""
import json

import pytest

from modpilot.core.errors import CATEGORIES, StepError
from modpilot.core.report import dumps_report, make_report

pytestmark = pytest.mark.unit


def test_a_step_error_carries_its_fields_in_its_text():
    e = StepError("operator", "auto_create_chains cancelled", step="physics_chains",
                  operator="mhws.auto_create_chains", details={"ret": "{'CANCELLED'}"}, partial={"chains": 3})
    text = str(e)
    assert text.startswith("MODPILOT_ERROR=")
    back = json.loads(text[len("MODPILOT_ERROR="):])
    assert back == e.to_dict()
    assert back["category"] == "operator" and back["step"] == "physics_chains"
    assert back["partial"] == {"chains": 3}


def test_a_step_error_is_found_again_in_any_text_around_it():
    e = StepError("precondition", "no armature 'X'", step="vertex_groups")
    wrapped = f"Traceback (most recent call last):\n  ...\nmodpilot.core.errors.StepError: {e}\n"
    again = StepError.from_text(wrapped)
    assert again is not None and again.to_dict() == e.to_dict()
    assert StepError.from_text("Python: KeyError: 'x'") is None


def test_an_unknown_category_is_a_programming_error():
    with pytest.raises(ValueError):
        StepError("oops", "x")
    assert {"params", "precondition", "operator", "postcondition", "environment", "internal"} == set(CATEGORIES)


def test_the_report_envelope():
    r = make_report(step="list_objects", params={"type_filter": ""}, data={"objects": []}, warnings=["w"],
                    skipped=[], scene_diff={"objects_added": ["A"]}, popups=[], seconds=0.1234,
                    code={"sha": "abc", "dirty": False, "reloaded": False}, blender="5.2.2")
    assert r["ok"] is True and r["step"] == "list_objects" and r["seconds"] == 0.123
    assert set(r) == {"ok", "step", "params", "data", "warnings", "skipped", "scene_diff", "popups",
                      "seconds", "code", "blender"}
    assert json.loads(dumps_report(r)) == r


def test_a_report_that_is_not_plain_json_is_an_internal_error():
    r = make_report(step="s", params={}, data={"bones": {"a", "b"}}, warnings=[], skipped=[], scene_diff={},
                    popups=[], seconds=0, code={}, blender="x")
    with pytest.raises(StepError) as e:
        dumps_report(r)
    assert e.value.category == "internal" and e.value.step == "s"
    r["data"] = {"x": float("nan")}
    with pytest.raises(StepError):
        dumps_report(r)
