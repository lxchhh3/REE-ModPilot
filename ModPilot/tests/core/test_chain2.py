"""modpilot.formats.chain2: chain2 files through RE Chain Editor's own reader/writer (moved from
Known_Good_mod_test/scripts/og_collar/collar_lib.py). A verified build's chain2 must round-trip byte for
byte; records compare with their file offsets zeroed (they move when groups are added)."""
from pathlib import Path

import pytest

from modpilot.formats import chain2 as C2
from modpilot.formats import editors as E

KG = E.tools52().parent / "Known_Good_mod_test"
OG_CHAIN = KG / "Output/og_collar1B/mod/natives/STM/Art/Model/Character/ch03/024/001/2/ch03_024_0012.chain2.14"

pytestmark = pytest.mark.skipif(not OG_CHAIN.is_file(), reason="the og_collar1B build is not here")


def test_a_verified_chain2_round_trips_byte_for_byte():
    data = OG_CHAIN.read_bytes()
    assert C2.to_bytes(C2.load_bytes(data)) == data
    assert C2.to_bytes(C2.load(OG_CHAIN)) == data


def test_record_bytes_ignore_file_offsets():
    cf = C2.load(OG_CHAIN)
    g = cf.ChainGroupList[0]
    rec, nodes = C2.group_bytes(g)
    moved = C2.copy(g)
    moved.nodeOffset += 4096
    assert C2.group_bytes(moved) == (rec, nodes) and len(nodes) == len(g.nodeList)
    if cf.ChainLinkList:
        assert C2.link_bytes(cf.ChainLinkList[0])[0]


def test_copy_does_not_share_lists():
    g = C2.load(OG_CHAIN).ChainGroupList[0]
    c = C2.copy(g)
    c.nodeList.append(None)
    assert len(c.nodeList) == len(g.nodeList) + 1


def test_the_reader_is_the_chain_editors():
    assert C2.editor() is E.module("chain", "file_re_chain2")
    assert Path(C2.editor().__file__).name == "file_re_chain2.py"
