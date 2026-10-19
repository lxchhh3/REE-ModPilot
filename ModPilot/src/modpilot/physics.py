"""Chain-settings presets per inferred chain type (data/physics_presets.json), bpy-free.

Each type ("hair_short", "cloth_skirt_waist", "accessory_ribbon", ...) carries the RE Chain
Editor chain-settings values calibrated from MH Wilds' own presets; types starting with "_" are
reference-only. Ported from the legacy app/phases/physics_bones.py loader.
"""
from __future__ import annotations

import json
from functools import lru_cache

from modpilot import datafiles

DEFAULT_COLLIDER_PATH = "System/Collision/Filter/Character/Character_Chain.cfil"
# RE Chain Editor stores these chain-settings fields as enum strings of ints
ENUM_FIELDS = frozenset({"windDelayType", "springCalcType", "chainType", "muzzleDirection", "motionForceCalcType"})


@lru_cache(maxsize=1)
def _presets() -> dict:
    return json.loads(datafiles.path("physics_presets.json").read_text(encoding="utf-8"))


def inferred_types() -> list[str]:
    """The usable types (reference-only '_' types left out)."""
    return [k for k in _presets().get("types", {}) if not k.startswith("_")]


def params_for(itype: str) -> dict | None:
    """A copy of type `itype`'s chain-settings values, or None for an unknown type."""
    entry = _presets().get("types", {}).get(itype)
    return None if entry is None else dict(entry.get("params", {}))


def collider_default() -> str:
    return _presets().get("_usage_guide", {}).get("colliderFilterInfoPath_default", DEFAULT_COLLIDER_PATH)


def settings_for(itype: str) -> dict:
    """What a chain-settings object of type `itype` gets: its preset plus the collider filter path."""
    p = params_for(itype)
    if p is None:
        raise KeyError(itype)
    p.setdefault("colliderFilterInfoPath", collider_default())
    return p
