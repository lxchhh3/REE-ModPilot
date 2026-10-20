"""modpilot.call inside Blender (T1, runs in headless 5.2.2 through modpilot_host.bpytest).

The contract every channel relies on: a call returns a plain-JSON report and prints it as one
MODPILOT_REPORT= line; any failure raises StepError, whose text is MODPILOT_ERROR=<json>; nothing
fails silently (the legacy tools swallowed errors in `except: pass`, "non-fatal" steps and
fallbacks).
"""
import json
import os
import sys
from dataclasses import dataclass

import bpy
import pytest

import modpilot
from modpilot.core.errors import StepError
from modpilot.core.step import REGISTRY


@dataclass(frozen=True)
class AddEmptyParams:
    name: str = "Probe"


@dataclass(frozen=True)
class NoParams:
    pass


@pytest.fixture
def temp_steps():
    """Register test-only steps; removed afterwards."""
    added = []

    def add(name, params_cls, fn, mutates=True):
        REGISTRY.remove(name)
        REGISTRY.step(name, params_cls, mutates=mutates)(fn)
        added.append(name)
    yield add
    for n in added:
        REGISTRY.remove(n)


def _last_line(out, prefix):
    lines = [ln for ln in out.splitlines() if ln.startswith(prefix)]
    assert lines, out[-2000:]
    return json.loads(lines[-1][len(prefix):])


def test_a_call_returns_its_report_and_prints_it(capsys):
    r = modpilot.call("doctor")
    assert r["ok"] is True and r["step"] == "doctor"
    assert r["blender"] == bpy.app.version_string
    assert _last_line(capsys.readouterr().out, "MODPILOT_REPORT=") == r


def test_the_report_says_what_the_step_added_to_the_scene(temp_steps):
    def add_empty(p, ctx):
        o = bpy.data.objects.new(p.name, None)
        bpy.context.scene.collection.objects.link(o)
        return {"added": o.name}
    temp_steps("t_add_empty", AddEmptyParams, add_empty)
    r = modpilot.call("t_add_empty", {"name": "Probe"})
    assert r["data"] == {"added": "Probe"}
    assert r["scene_diff"]["objects_added"] == ["Probe"]
    assert r["scene_diff"]["object_count"] == {"before": 0, "after": 1}


def test_an_unknown_step_fails_loudly(capsys):
    with pytest.raises(StepError) as e:
        modpilot.call("doktor")
    assert e.value.category == "params" and "doctor" in e.value.details["known"]
    assert _last_line(capsys.readouterr().out, "MODPILOT_ERROR=")["category"] == "params"


def test_a_misspelt_param_fails_before_the_step_runs(temp_steps):
    ran = []
    temp_steps("t_record", AddEmptyParams, lambda p, ctx: ran.append(p) or {})
    with pytest.raises(StepError) as e:
        modpilot.call("t_record", {"nmae": "x"})
    assert e.value.category == "params" and e.value.step == "t_record" and ran == []


def test_a_step_error_keeps_its_category_and_gains_the_step_name(temp_steps):
    def refuse(p, ctx):
        raise StepError("precondition", "no armature")
    temp_steps("t_refuse", NoParams, refuse)
    with pytest.raises(StepError) as e:
        modpilot.call("t_refuse")
    assert (e.value.category, e.value.step, e.value.message) == ("precondition", "t_refuse", "no armature")


def test_any_other_exception_becomes_an_internal_step_error_with_its_traceback(temp_steps):
    temp_steps("t_bug", NoParams, lambda p, ctx: {}["missing"])
    with pytest.raises(StepError) as e:
        modpilot.call("t_bug")
    assert e.value.category == "internal" and "KeyError" in e.value.message
    assert "Traceback" in e.value.details["traceback"]


def test_an_error_popup_from_an_add_on_fails_the_call(temp_steps, monkeypatch):
    # an add-on module that reports failure through a popup, as RE Mesh / Chain Editor do
    fake = type(sys)("fake_re_addon")

    def showErrorMessageBox(message="", title="", icon="ERROR"):
        raise AssertionError("the real popup must not run in background mode")
    fake.showErrorMessageBox = showErrorMessageBox
    monkeypatch.setitem(sys.modules, "fake_re_addon", fake)

    def complain(p, ctx):
        sys.modules["fake_re_addon"].showErrorMessageBox("Export failed: no meshes in collection")
        return {}
    temp_steps("t_complain", NoParams, complain)
    with pytest.raises(StepError) as e:
        modpilot.call("t_complain")
    assert e.value.category == "operator" and "no meshes in collection" in e.value.message
    assert sys.modules["fake_re_addon"].showErrorMessageBox is showErrorMessageBox   # restored


def test_a_step_returning_non_json_data_is_an_internal_error(temp_steps):
    temp_steps("t_set", NoParams, lambda p, ctx: {"bones": {"a"}})
    with pytest.raises(StepError) as e:
        modpilot.call("t_set")
    assert e.value.category == "internal"


def test_an_edited_module_is_reloaded_on_the_next_call():
    src = os.path.join(os.path.dirname(modpilot.__file__), "steps", "doctor.py")
    first = modpilot.call("doctor", quiet=True)
    assert first["code"]["reloaded"] is False
    st = os.stat(src)
    os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    try:
        again = sys.modules["modpilot"].call("doctor", quiet=True)
        assert again["code"]["reloaded"] is True and again["ok"]
        assert sys.modules["modpilot"].call("doctor", quiet=True)["code"]["reloaded"] is False
    finally:
        os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns))


def test_the_report_names_the_code_that_ran():
    code = modpilot.call("doctor", quiet=True)["code"]
    assert len(code["sha"]) == 40 and isinstance(code["dirty"], bool)


def test_tests_run_with_blenders_window_context_as_sessions_and_live_blender_do():
    # operators that need a UI context (uv.select_all, inside re_mesh.solve_repeated_uvs) poll on it
    import bpy
    assert bpy.context.window is not None and bpy.context.screen is not None
    bpy.ops.mesh.primitive_plane_add()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    assert bpy.ops.uv.select_all(action="SELECT") == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")
