"""MH Wilds .mesh files through RE Mesh Editor's own pure-python reader, and where each LOD's sub-meshes
and vertex streams sit inside the file bytes, so a fix can patch vertex data in place (Blender-MHWilds
lesson #27: patch the bytes, do not re-encode through the exporter). Moved from
Known_Good_mod_test/scripts/marette/meshio.py unchanged; bpy-free (numpy)."""
from __future__ import annotations

import io
from contextlib import redirect_stdout

from modpilot.formats import editors


def reader():
    return editors.module("mesh", "mesh.file_re_mesh")


def parser():
    return editors.module("mesh", "mesh.re_mesh_parse")


def read(path):
    """(REMesh, ParsedREMesh) for a mesh file, every LOD and the blend shapes, reader chatter suppressed."""
    with redirect_stdout(io.StringIO()):
        re_mesh = reader().readREMesh(str(path))
        parsed = parser().ParsedREMesh()
        parsed.ParseREMesh(re_mesh, {"importAllLOD": True, "importShadowMesh": False,
                                     "importOcclusionMesh": False, "importBlendShapes": True})
    return re_mesh, parsed


def element_layout(re_mesh):
    """[(element name, stride, start offset inside the vertex buffer)] in file order."""
    hdr = re_mesh.meshBufferHeader
    return [(parser().typeNameMapping[e.typing], int(e.stride), int(e.posStartOffset)) for e in hdr.vertexElementList]


def vertex_buffer_base(re_mesh, file_bytes):
    """File offset of the vertex buffer the reader parsed (asserted to occur exactly once)."""
    buf = bytes(re_mesh.meshBufferHeader.vertexBuffer)
    probe = buf[:4096]
    base = file_bytes.find(probe)
    if base < 0 or file_bytes.find(probe, base + 1) >= 0:
        raise ValueError("vertex buffer prefix not found exactly once in the file")
    if file_bytes[base:base + len(buf)] != buf:
        raise ValueError("vertex buffer differs from the file bytes at its offset")
    return base
