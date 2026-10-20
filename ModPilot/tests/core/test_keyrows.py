"""Pure-python tests for key_rows.py: find and copy the per-key normals a Wilds keep-normals mesh stores
(the second 4-byte word of each 8-byte blend-shape row), so the GG build can give sks4b's face back the
exact driven-key normals kevin verified in game (a re-export recomputes them: 3% of the Face's rows came
out > 2 int8 steps off around the eyelids and mouth, up to ~20 degrees).
Run with tools-5.2's venv:  .venv/Scripts/python.exe -m pytest scripts/gg/tests -q
(Moved with modpilot.formats.keyrows from Known_Good_mod_test/scripts/gg/tests/test_key_rows.py.)"""
import struct
from types import SimpleNamespace as NS

import pytest

from modpilot.formats import keyrows as K


def mesh(targets, names):
    """A stand-in for the parser's reMesh: one LOD's blend data with the given targets."""
    remap = list(range(len(names)))
    return NS(blendShapeHeader=NS(blendShapeList=[NS(blendTargetList=targets, targetCount=len(targets))]),
              rawNameList=names, blendShapeNameRemapList=remap)


def target(channels, ss, entries):
    return NS(blendShapeNum=channels, blendSSIndex=ss,
              subMeshEntryList=[NS(vertCount=c, vertOffset=0, subMeshVertexStartIndex=s) for c, s in entries],
              vertCount=sum(c for c, _ in entries))


def raw_rows(n_rows, normal_of):
    """n_rows 8-byte rows: word 0 = 0xDDDD0000 + row (a stand-in delta), word 1 = int8 normal of row."""
    out = b""
    for r in range(n_rows):
        x, y, z = normal_of(r)
        out += struct.pack("<I", 0xDDDD0000 + r) + struct.pack("<bbbb", x, y, z, 0)
    return out


@pytest.fixture()
def two_channel():
    # one target: channels "a", "b"; two sub-mesh entries of 2 and 3 rows starting at group vertices 10, 20
    m = mesh([target(2, 0, [(2, 10), (3, 20)])], ["a", "b"])
    raw = raw_rows(10, lambda r: (r, -r, 1))
    return m, raw


def test_row_positions_map_vertices_to_second_words(two_channel):
    m, raw = two_channel
    pos = K.row_positions(m, raw)
    # rows are laid out channel by channel; within a channel, entry by entry
    assert pos["a"] == {10: 1, 11: 3, 20: 5, 21: 7, 22: 9}
    assert pos["b"] == {10: 11, 11: 13, 20: 15, 21: 17, 22: 19}


def test_normals_at_reads_signed_bytes(two_channel):
    m, raw = two_channel
    n = K.normals_at(raw, K.row_positions(m, raw))
    assert n["a"][11] == (1, -1, 1) and n["b"][22] == (9, -9, 1)


def test_second_target_continues_after_the_first():
    m = mesh([target(1, 0, [(2, 0)]), target(2, 1, [(1, 5)])], ["x", "y", "z"])
    raw = raw_rows(4, lambda r: (r, 0, 0))
    pos = K.row_positions(m, raw)
    assert pos == {"x": {0: 1, 1: 3}, "y": {5: 5}, "z": {5: 7}}


def test_patch_copies_only_the_normal_word(two_channel):
    m, raw_new = two_channel
    raw_src = raw_rows(10, lambda r: (100 - r, 50, -7))
    file_bytes = b"HEADER--" + raw_new + b"--TAIL"
    pos = K.row_positions(m, raw_new)
    out, n = K.patch_normals(file_bytes, raw_new, pos, raw_src, pos, {11: 10, 22: 20}, ["b"])
    assert n == 2
    patched = out[8:8 + len(raw_new)]
    got = K.normals_at(patched, pos)
    assert got["b"][11] == K.normals_at(raw_src, pos)["b"][10] == (95, 50, -7)   # "b" vertex 10 = row 5 (word 11)
    assert got["b"][22] == K.normals_at(raw_src, pos)["b"][20]
    assert got["b"][10] == K.normals_at(raw_new, pos)["b"][10]          # unpaired rows untouched
    assert got["a"] == K.normals_at(raw_new, pos)["a"]                  # other keys untouched
    words_old, words_new = struct.unpack(f"<{len(raw_new) // 4}I", raw_new), struct.unpack(f"<{len(patched) // 4}I", patched)
    assert words_old[0::2] == words_new[0::2]                           # every delta word untouched
    assert out[:8] == b"HEADER--" and out[-6:] == b"--TAIL" and len(out) == len(file_bytes)


def test_patch_refuses_a_payload_not_found_once(two_channel):
    m, raw = two_channel
    pos = K.row_positions(m, raw)
    with pytest.raises(ValueError):
        K.patch_normals(b"nothing here", raw, pos, raw, pos, {10: 10}, ["a"])
    with pytest.raises(ValueError):
        K.patch_normals(raw + raw, raw, pos, raw, pos, {10: 10}, ["a"])


def test_pair_twins_by_position_uv_then_own_normal():
    src = [("Face", (0, 0, 0), (0.5, 0.5), (0, 127, 0)),
           ("Face", (0, 0, 0), (0.5, 0.5), (127, 0, 0)),       # a seam twin: same position and UV
           ("Face", (1, 0, 0), (0.1, 0.1), (0, 0, 127)),
           ("Body", (2, 0, 0), (0.1, 0.1), (0, 0, 127))]
    new = [("Face", (0, 0, 0.000001), (0.5, 0.5), (126, 1, 0)),
           ("Face", (1, 0, 0), (0.1, 0.1), (0, 0, 127)),
           ("Face", (5, 5, 5), (0.1, 0.1), (0, 0, 127)),       # nothing there
           ("Body", (2, 0, 0), (0.1, 0.1), (0, 0, 127))]
    pairs, unmatched = K.pair_twins(new, src, mats={"Face"})
    assert pairs == {0: 1, 1: 2} and unmatched == [2]
