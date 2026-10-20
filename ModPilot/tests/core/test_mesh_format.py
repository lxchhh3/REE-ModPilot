"""modpilot.formats.mesh on a verified build's body mesh: RE Mesh Editor's reader parses it and the vertex
buffer it read sits in the file exactly once, so vertex data can be patched in place (lesson #27)."""
import pytest

from modpilot.formats import editors as E
from modpilot.formats import mesh as M

MESH = (E.tools52().parent / "Known_Good_mod_test/Output/og_collar1B/mod/natives/STM/Art/Model/Character/ch03/024/001/2/"
        "ch03_024_0012.mesh.241111606")

pytestmark = pytest.mark.skipif(not MESH.is_file(), reason="the og_collar1B build is not here")


def test_a_verified_mesh_parses_and_its_vertex_buffer_is_found_once():
    data = MESH.read_bytes()
    re_mesh, parsed = M.read(MESH)
    base = M.vertex_buffer_base(re_mesh, data)
    layout = M.element_layout(re_mesh)
    assert base > 0 and parsed is not None
    assert [(name, stride) for name, stride, _ in layout] == [
        ("Position", 12), ("NorTan", 8), ("UV", 4), ("UV2", 4), ("Weight", 16), ("Color", 4)]
    assert [start for _, _, start in layout] == sorted(start for _, _, start in layout)


def test_a_buffer_that_is_not_in_the_file_is_refused():
    re_mesh, _ = M.read(MESH)
    with pytest.raises(ValueError):
        M.vertex_buffer_base(re_mesh, b"\x00" * 64)


def test_the_blend_payload_is_the_one_in_the_file_and_group0_follows_sub_mesh_order():
    parsed, re_mesh, raw = M.read_with_blend_payload(MESH)
    assert MESH.read_bytes().count(raw) == 1
    verts = M.group0_vertices(parsed)
    assert verts and all(len(v[1]) == 3 and len(v[2]) == 2 and len(v[3]) == 3 for v in verts[:50])
    shifted = M.group0_vertices(parsed, shift=(0.0, 0.0, 0.5))
    assert shifted[0][1][2] == pytest.approx(verts[0][1][2] + 0.5) and shifted[0][2:] == verts[0][2:]
    assert all(-127 <= c <= 127 for v in verts[:50] for c in v[3])


def test_tex_file_is_the_natives_path():
    assert M.tex_file("Art/kevin/MayaGG/GG_Main_ALBD.tex") == "natives/STM/Art/kevin/MayaGG/GG_Main_ALBD.tex.241106027"
