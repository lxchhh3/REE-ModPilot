"""The body colliders of full_body.clsp.3 and their mask bits (data/clsp_body_bits.json), bpy-free.

A chain group's clspFlags0 / clspFlags1 are masks over these colliders: the 20 body regions
0x1..0x80000 plus the wide hip sphere 0x800000 (bit 23, ModPilot lesson #50). A mask with any other
bit selects nothing. Ported from the legacy app/phases/physics_colliders.py.
"""
from __future__ import annotations

import json
from functools import lru_cache

from modpilot import datafiles
from modpilot.core.errors import StepError

FLAG_KEYS = ("clspFlags0", "clspFlags1")


@lru_cache(maxsize=1)
def _bits() -> dict:
    return json.loads(datafiles.path("clsp_body_bits.json").read_text(encoding="utf-8"))["bits"]


def body_bit_keys() -> list[str]:
    """Every body-region key, in catalog order (one per collider of full_body.clsp.3)."""
    return list(_bits())


def mask_for_keys(keys: list[str]) -> int:
    bits = _bits()
    unknown = [k for k in keys if k not in bits]
    if unknown:
        raise StepError("params", f"unknown body-bit key(s): {unknown}", details={"known": list(bits)})
    mask = 0
    for k in keys:
        mask |= bits[k]["bit"]
    return mask


def keys_for_mask(mask: int) -> list[str]:
    return [k for k, e in _bits().items() if mask & e["bit"]]


def _full_mask() -> int:
    mask = 0
    for e in _bits().values():
        mask |= e["bit"]
    return mask


FULL_MASK = _full_mask()


def valid_mask(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0 and value & ~FULL_MASK == 0


def flag_pair(value) -> tuple[int, int] | None:
    """A chain_flags entry as (clspFlags0, clspFlags1), or None when it isn't one: an int sets
    clspFlags0 (clspFlags1 0); a dict takes clspFlags0 / clspFlags1 (each defaults to 0, no other
    keys). Only the collider bits are allowed."""
    if isinstance(value, dict):
        if set(value) - set(FLAG_KEYS):
            return None
        pair = tuple(value.get(k, 0) for k in FLAG_KEYS)
    elif isinstance(value, int) and not isinstance(value, bool):
        pair = (value, 0)
    else:
        return None
    return pair if all(valid_mask(v) for v in pair) else None
