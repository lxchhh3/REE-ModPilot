"""The body-collider bit catalog (data/clsp_body_bits.json) and the chain_flags entries, host side."""
import pytest

from modpilot import colliders
from modpilot.core.errors import StepError


def test_the_catalog_has_the_twenty_regions_and_the_wide_hip():
    keys = colliders.body_bit_keys()
    assert len(keys) == 21 and keys[0] == "hip"
    assert colliders.mask_for_keys(["hip_wide"]) == 0x800000
    assert colliders.FULL_MASK == 0xFFFFF | 0x800000


def test_masks_and_keys_round_trip():
    keys = ["hip", "spine_0", "hip_wide"]
    assert colliders.keys_for_mask(colliders.mask_for_keys(keys)) == keys


def test_an_unknown_key_is_a_params_error():
    with pytest.raises(StepError) as e:
        colliders.mask_for_keys(["hip", "tail"])
    assert e.value.category == "params"


@pytest.mark.parametrize("value, pair", [
    (0, (0, 0)), (0x800001, (0x800001, 0)),
    ({"clspFlags0": 3, "clspFlags1": 0}, (3, 0)), ({"clspFlags0": 2}, (2, 0)), ({}, (0, 0)),
])
def test_good_entries(value, pair):
    assert colliders.flag_pair(value) == pair


@pytest.mark.parametrize("value", [
    True, -1, 0x100000, "3", 1.0, [1, 0], {"clspFlags0": True}, {"clspFlags0": 0x400000},
    {"clspFlags0": 1, "clspFlag1": 0},
])
def test_bad_entries(value):
    assert colliders.flag_pair(value) is None
