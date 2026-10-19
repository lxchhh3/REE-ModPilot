"""Strict parsing of step params into a frozen dataclass.

The legacy tools read `params.get(key, default)`, so a misspelt key was silently ignored and the
default used. Here an unknown key, a missing required key or a value of the wrong type fails the
call (StepError "params") before anything in the scene is touched.

Supported field types: str, int, float (an int is accepted), bool, dict, list[T], dict[str, T],
T | None, and Any.
"""
from __future__ import annotations

import dataclasses
import types
import typing
from typing import Any

from modpilot.core.errors import StepError


def parse(cls, data):
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise StepError("params", f"params must be a mapping, got {type(data).__name__}",
                        details={"got": type(data).__name__})
    fields = {f.name: f for f in dataclasses.fields(cls)}
    unknown = sorted(set(data) - set(fields))
    if unknown:
        raise StepError("params", f"unknown param(s) {', '.join(unknown)}; known: {', '.join(fields)}",
                        details={"unknown": unknown, "known": list(fields)})
    missing = [n for n, f in fields.items() if n not in data
               and f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING]
    if missing:
        raise StepError("params", f"missing required param(s) {', '.join(missing)}", details={"missing": missing})
    hints = typing.get_type_hints(cls)
    values = {}
    for name, value in data.items():
        values[name] = _check(name, value, hints[name])
    return cls(**values)


def _fail(path, value, expected):
    """`path` is the field name, or the place inside it ('names[1]', "table['k']")."""
    field = path.split("[", 1)[0].split(" ", 1)[0]
    raise StepError("params", f"param {path!r} must be {expected}, got {type(value).__name__} {value!r}"[:300],
                    details={"field": field, "path": path, "expected": expected, "got": type(value).__name__})


def _check(name, value, tp):
    if tp is Any:
        return value
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        args = typing.get_args(tp)
        if value is None and type(None) in args:
            return None
        inner = [a for a in args if a is not type(None)]
        if len(inner) == 1:
            return _check(name, value, inner[0])
        for a in inner:
            try:
                return _check(name, value, a)
            except StepError:
                continue
        _fail(name, value, " or ".join(getattr(a, "__name__", str(a)) for a in inner))
    if origin is list:
        if not isinstance(value, list):
            _fail(name, value, "a list")
        (item,) = typing.get_args(tp) or (Any,)
        return [_check(f"{name}[{i}]", v, item) for i, v in enumerate(value)]
    if origin is dict or tp is dict:
        if not isinstance(value, dict):
            _fail(name, value, "a mapping")
        args = typing.get_args(tp)
        if args:
            return {_check(f"{name} key", k, args[0]): _check(f"{name}[{k!r}]", v, args[1]) for k, v in value.items()}
        return dict(value)
    if tp is bool:
        if not isinstance(value, bool):
            _fail(name, value, "true or false")
        return value
    if tp is int:
        if isinstance(value, bool) or not isinstance(value, int):
            _fail(name, value, "an integer")
        return value
    if tp is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _fail(name, value, "a number")
        return float(value)
    if tp is str:
        if not isinstance(value, str):
            _fail(name, value, "a string")
        return value
    raise TypeError(f"modpilot.core.params: unsupported field type {tp!r} for {name!r}")
