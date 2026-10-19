"""StepError: the one way a ModPilot step fails.

Both Blender bridges (Blender Lab MCP and the community blender-mcp add-on) hand an exception back
to the host as text, so the error's text IS its structured form: "MODPILOT_ERROR=<json>".
`StepError.from_text` finds it again inside whatever traceback or message wraps it.
"""
from __future__ import annotations

import json
import re

CATEGORIES = ("params", "precondition", "operator", "postcondition", "environment", "internal")
PREFIX = "MODPILOT_ERROR="
_FOUND = re.compile(re.escape(PREFIX) + r"(\{.*\})")


class StepError(Exception):
    """A step that could not do what it was asked.

    category  params | precondition | operator | postcondition | environment | internal
    message   one sentence for a person
    step      the step name (filled in by `modpilot.call` when the raiser didn't)
    operator  the Blender operator that failed, if any
    details   anything a caller can act on (JSON-safe)
    partial   what the step had already changed in the scene before it failed (JSON-safe)
    """

    def __init__(self, category: str, message: str, *, step: str = "", operator: str = "",
                 details: dict | None = None, partial: dict | None = None):
        if category not in CATEGORIES:
            raise ValueError(f"unknown StepError category {category!r}; one of {CATEGORIES}")
        self.category = category
        self.message = message
        self.step = step
        self.operator = operator
        self.details = details or {}
        self.partial = partial or {}
        super().__init__(self.__str__())

    def to_dict(self) -> dict:
        return {"category": self.category, "message": self.message, "step": self.step,
                "operator": self.operator, "details": self.details, "partial": self.partial}

    def __str__(self) -> str:
        return PREFIX + json.dumps(self.to_dict(), ensure_ascii=False, default=repr)

    @classmethod
    def from_dict(cls, d: dict) -> StepError:
        return cls(d["category"], d["message"], step=d.get("step", ""), operator=d.get("operator", ""),
                   details=d.get("details") or {}, partial=d.get("partial") or {})

    @classmethod
    def from_text(cls, text: str) -> StepError | None:
        """The StepError carried in `text` (the last one, if several), or None."""
        found = _FOUND.findall(text or "")
        for candidate in reversed(found):
            try:
                return cls.from_dict(json.loads(candidate))
            except (ValueError, KeyError):
                continue
        return None
