"""The data files modpilot ships (src/modpilot/data): physics_presets.json, clsp_body_bits.json,
full_body.clsp.3, armor_sets.json. bpy-free."""
from __future__ import annotations

from pathlib import Path

from modpilot.core.errors import StepError

DATA = Path(__file__).resolve().parent / "data"


def path(name: str) -> Path:
    p = DATA / name
    if not p.is_file():
        raise StepError("environment", f"modpilot data file {name!r} is missing from {DATA}")
    return p
