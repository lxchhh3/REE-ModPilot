"""The chain-settings presets (data/physics_presets.json), host side."""
import pytest

from modpilot import datafiles, physics
from modpilot.core.errors import StepError


def test_every_usable_type_has_params_and_reference_types_are_hidden():
    types = physics.inferred_types()
    assert "hair_short" in types and "accessory_ribbon" in types
    assert not [t for t in types if t.startswith("_")]
    assert all(physics.params_for(t) for t in types)


def test_settings_carry_the_collider_filter_and_unknown_types_are_none():
    assert physics.settings_for("fur_tail")["colliderFilterInfoPath"].endswith(".cfil")
    assert physics.params_for("no_such_type") is None
    with pytest.raises(KeyError):
        physics.settings_for("no_such_type")


def test_params_are_copies():
    physics.params_for("fur_tail")["damping"] = -1
    assert physics.params_for("fur_tail").get("damping") != -1


def test_a_missing_data_file_is_an_environment_error():
    with pytest.raises(StepError) as e:
        datafiles.path("nope.json")
    assert e.value.category == "environment"
