"""The step registry.

A step is a function `fn(params, ctx) -> dict` registered under a name with a frozen params
dataclass. `mutates=False` marks read-only steps (queries); `needs` names the bpy.ops namespaces
the step calls, which `doctor` checks.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass

from modpilot.core.errors import StepError


@dataclass(frozen=True)
class Step:
    name: str
    fn: Callable
    params_cls: type
    mutates: bool = True
    needs: tuple[str, ...] = ()
    doc: str = ""


class Registry:
    def __init__(self) -> None:
        self._steps: dict[str, Step] = {}

    def step(self, name: str, params_cls: type, *, mutates: bool = True, needs: tuple[str, ...] = ()):
        if not dataclasses.is_dataclass(params_cls):
            raise TypeError(f"step {name!r}: params class {params_cls!r} must be a dataclass")

        def register(fn):
            if name in self._steps:
                raise ValueError(f"step {name!r} is already registered")
            self._steps[name] = Step(name, fn, params_cls, mutates, tuple(needs), (fn.__doc__ or "").strip())
            return fn
        return register

    def get(self, name: str) -> Step:
        try:
            return self._steps[name]
        except KeyError:
            raise StepError("params", f"no step named {name!r}", details={"known": self.names()}) from None

    def names(self) -> list[str]:
        return sorted(self._steps)

    def remove(self, name: str) -> None:
        """For tests that register a temporary step."""
        self._steps.pop(name, None)


REGISTRY = Registry()
step = REGISTRY.step
