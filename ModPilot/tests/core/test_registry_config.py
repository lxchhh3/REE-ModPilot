"""modpilot.core.step / config: steps register by name with a params dataclass; scene names come
from a SceneConfig stored on the scene (the legacy tools hard-coded 'MHWilds_Female Armature'
and 'MHWilds_Female.mesh' in a dozen places)."""
from dataclasses import dataclass

import pytest

from modpilot.core.config import SceneConfig, load_config, resolve, save_config
from modpilot.core.errors import StepError
from modpilot.core.step import Registry

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class NoParams:
    pass


def test_a_step_registers_under_its_name():
    reg = Registry()

    @reg.step("hello", NoParams, mutates=False)
    def hello(p, ctx):
        return {"hi": 1}

    s = reg.get("hello")
    assert s.name == "hello" and s.params_cls is NoParams and s.mutates is False and s.fn is hello
    assert reg.names() == ["hello"]


def test_a_name_is_registered_once():
    reg = Registry()
    reg.step("a", NoParams)(lambda p, ctx: {})
    with pytest.raises(ValueError):
        reg.step("a", NoParams)(lambda p, ctx: {})


def test_params_must_be_a_dataclass():
    with pytest.raises(TypeError):
        Registry().step("a", dict)


def test_an_unknown_step_is_a_params_error_listing_the_known_ones():
    reg = Registry()
    reg.step("doctor", NoParams)(lambda p, ctx: {})
    with pytest.raises(StepError) as e:
        reg.get("doktor")
    assert e.value.category == "params" and e.value.details["known"] == ["doctor"]


def test_a_scene_without_config_gets_the_template_names():
    cfg = load_config({})
    assert cfg == SceneConfig()
    assert cfg.target_armature == "MHWilds_Female Armature" and cfg.mesh_collection == "MHWilds_Female.mesh"


def test_config_round_trips_through_the_scene():
    scene = {}
    save_config(scene, SceneConfig(target_armature="Arm2", chain2_collection="X.chain2"))
    assert load_config(scene) == SceneConfig(target_armature="Arm2", chain2_collection="X.chain2")


def test_a_param_wins_over_config_and_neither_is_an_error():
    cfg = SceneConfig(chain2_collection=None)
    assert resolve("A", cfg, "target_armature") == "A"
    assert resolve(None, cfg, "target_armature") == "MHWilds_Female Armature"
    with pytest.raises(StepError) as e:
        resolve(None, cfg, "chain2_collection")
    assert e.value.category == "precondition" and "chain2_collection" in e.value.message
