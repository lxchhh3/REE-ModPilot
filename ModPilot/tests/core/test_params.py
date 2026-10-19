"""modpilot.core.params: step params are parsed strictly. The legacy tools read `params.get(...)`
with silent defaults, so a misspelt key was simply ignored; here an unknown key, a missing
required key or a wrong type fails the call before it touches the scene."""
from dataclasses import dataclass, field

import pytest

from modpilot.core.errors import StepError
from modpilot.core.params import parse

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class P:
    name: str
    count: int = 1
    ratio: float = 0.5
    flag: bool = False
    names: list[str] = field(default_factory=list)
    opt: str | None = None
    table: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Empty:
    pass


def _err(data, cls=P):
    with pytest.raises(StepError) as e:
        parse(cls, data)
    assert e.value.category == "params"
    return e.value


def test_defaults_fill_in():
    assert parse(P, {"name": "a"}) == P(name="a")


def test_every_field_is_taken():
    p = parse(P, {"name": "a", "count": 3, "ratio": 0.25, "flag": True, "names": ["x", "y"],
                  "opt": "o", "table": {"k": 1}})
    assert p == P("a", 3, 0.25, True, ["x", "y"], "o", {"k": 1})


def test_no_params_for_a_step_without_any():
    assert parse(Empty, None) == Empty()
    assert parse(Empty, {}) == Empty()


def test_an_unknown_key_is_refused_and_named():
    e = _err({"name": "a", "nmae": "b"})
    assert "nmae" in e.message and e.details["unknown"] == ["nmae"]


def test_a_missing_required_key_is_refused():
    e = _err({"count": 2})
    assert e.details["missing"] == ["name"]


@pytest.mark.parametrize("data", [
    {"name": 3},
    {"name": "a", "count": "1"},
    {"name": "a", "count": True},     # bool is an int subclass: not a count
    {"name": "a", "flag": 1},
    {"name": "a", "ratio": "0.5"},
    {"name": "a", "names": "xy"},
    {"name": "a", "names": ["x", 2]},
    {"name": "a", "table": []},
    {"name": "a", "opt": 5},
])
def test_a_wrong_type_is_refused(data):
    e = _err(data)
    assert e.details["field"] in data


def test_an_int_is_a_float_and_none_is_an_optional():
    assert parse(P, {"name": "a", "ratio": 2, "opt": None}) == P(name="a", ratio=2.0)


def test_params_must_be_a_mapping():
    _err(["name", "a"])
