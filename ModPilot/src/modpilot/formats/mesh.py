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


TEX_VERSION = 241106027        # MH Wilds .tex


def tex_file(path):
    """The natives path of a texture the material names by `path` (e.g. 'Art/kevin/MayaGG/x_ALBD.tex')."""
    return f"natives/STM/{path}.{TEX_VERSION}"


def read_with_blend_payload(path):
    """(ParsedREMesh, REMesh, LOD0's blend-shape payload as the parser read it): every LOD and the blend
    shapes parsed, and the raw rows the per-key normals sit in (modpilot.formats.keyrows)."""
    re_mesh = reader().readREMesh(str(path))
    pm = parser()
    parsed = pm.ParsedREMesh()
    raws, read_rows = [], pm.ReadBlendShapeType7Buffer

    def capture(buffer, tags):
        raws.append(bytes(buffer))
        return read_rows(buffer, tags)

    pm.ReadBlendShapeType7Buffer = capture
    try:
        parsed.ParseREMesh(re_mesh, {"importAllLOD": True, "importBlendShapes": True})
    finally:
        pm.ReadBlendShapeType7Buffer = read_rows
    return parsed, re_mesh, raws[0]


def group0_vertices(parsed, shift=None):
    """[(material, position (+ shift), uv, own int8 normal)] of LOD0's group-0 vertices, in sub-mesh order
    (the order the per-key normal rows index them)."""
    import numpy as np
    out, mats = [], list(parsed.materialNameList)
    for g in parsed.mainMeshLODList[0].visconGroupList:
        if g.visconGroupNum == 0:
            for s in g.subMeshList:
                for i in range(len(s.vertexPosList)):
                    pos = (tuple(float(x) for x in s.vertexPosList[i]) if shift is None else
                           tuple(float(x) + c for x, c in zip(s.vertexPosList[i], shift, strict=True)))
                    out.append((mats[s.materialIndex], pos, tuple(float(x) for x in s.uvList[i]),
                                tuple(int(c) for c in np.rint(np.asarray(s.normalList[i][:3]) * 127))))
    return out
