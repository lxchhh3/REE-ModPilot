"""The body-bit catalog must be the bit layout of the clsp ModPilot imports (ModPilot lesson #50).

clsp_body_bits.json listed 20 bits (0x1..0x80000) while full_body.clsp.3 carries 21 colliders:
its entry 0 is a 0.2 m sphere on the hip with bit 0x800000 (bit 23), so collider_apply rejected
any mask using it and the catalog never showed it (claude_run1 set it by hand, and that sphere
held 41 of 53 skirt joints inside it at rest). Each clsp entry stores its bit at byte 16.
"""

import json
import struct

import pytest

from app.phases.physics_colliders import (
    _BITS_PATH,
    _FULL_BODY_CLSP_PATH,
    _normalise_flag_entry,
    mask_for_keys,
)

pytestmark = pytest.mark.unit


def _clsp_bits() -> list[int]:
    data = _FULL_BODY_CLSP_PATH.read_bytes()
    _magic, count, offset = struct.unpack_from("<IIQ", data, 0)
    stride = (len(data) - offset) // count
    assert stride * count == len(data) - offset
    return [struct.unpack_from("<i", data, offset + i * stride + 16)[0] for i in range(count)]


def test_the_catalog_lists_every_collider_bit_of_the_bundled_clsp():
    catalog = {e["bit"] for e in json.loads(_BITS_PATH.read_text(encoding="utf-8"))["bits"].values()}
    assert catalog == set(_clsp_bits())


def test_the_wide_hip_sphere_is_in_the_catalog():
    assert mask_for_keys(["hip_wide"]) == 0x800000


def test_collider_apply_accepts_a_mask_with_the_wide_hip_sphere():
    assert _normalise_flag_entry(0x800000 | 0x4000) == (0x800000 | 0x4000, 0)
    assert _normalise_flag_entry({"clspFlags0": 0x800000, "clspFlags1": 0}) == (0x800000, 0)


def test_collider_apply_rejects_a_bit_no_collider_has():
    assert _normalise_flag_entry(0x100000) is None
    assert _normalise_flag_entry({"clspFlags0": 0x4000, "clspFlags1": 0x200000}) is None
