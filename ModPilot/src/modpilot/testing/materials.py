"""A small textured avatar on the MH Wilds armature for the material T1/T2 tests: one mesh "Body"
with two quads on two Principled BSDF materials (MatA, MatB) and a UV map, in the scene's mesh
collection, plus PNG textures written to a folder."""
from pathlib import Path

import bpy

import modpilot
from modpilot.core.config import load_config
from modpilot.testing import scenes

MATERIALS = ("MatA", "MatB")


def node_material(name):
    """A material whose Principled BSDF drives the Material Output (Blender 4 needs use_nodes;
    Blender 5 gives every new material its node tree)."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True
    assert any(n.type == "BSDF_PRINCIPLED" for n in mat.node_tree.nodes), name
    return mat


def png(path, rgba, size=8):
    """An RGBA PNG of one colour at `path`."""
    img = bpy.data.images.new(Path(path).stem, size, size, alpha=True)
    img.pixels.foreach_set(list(rgba) * size * size)
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return str(path)


def textured_avatar(folder):
    """The avatar plus textures in `folder`: {"MatA": {slot: png}, "MatB": {...}}."""
    modpilot.call("setup_import_mhwilds", quiet=True)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    body = scenes.make_quads("Body", [[(-0.1, 0, 1.0), (0.0, 0, 1.0), (0.0, 0, 1.1), (-0.1, 0, 1.1)],
                                      [(0.0, 0, 1.0), (0.1, 0, 1.0), (0.1, 0, 1.1), (0.0, 0, 1.1)]], "MatA")
    node_material("MatA")
    body.data.materials.append(node_material("MatB"))
    body.data.polygons[1].material_index = 1
    uv = body.data.uv_layers.new(name="UVMap")
    uv.data.foreach_set("uv", [0, 0, 0.5, 0, 0.5, 1, 0, 1, 0.5, 0, 1, 0, 1, 1, 0.5, 1])
    arm = bpy.data.objects[load_config(bpy.context.scene).target_armature]
    scenes.skin(body, arm, {arm.data.bones[0].name: [(i, 1.0) for i in range(8)]})
    col = bpy.data.collections[load_config(bpy.context.scene).mesh_collection]
    for o in [o for o in col.all_objects if o.type == "MESH"]:   # as vertex_groups deletes them
        bpy.data.objects.remove(o)
    bpy.context.scene.collection.objects.unlink(body)
    col.objects.link(body)
    return {
        "MatA": {"Base Color": png(folder / "MatA_BC.png", (0.8, 0.2, 0.2, 1.0)),
                 "Normal": png(folder / "MatA_N.png", (0.5, 0.5, 1.0, 1.0)),
                 "Emission": png(folder / "MatA_E.png", (1.0, 1.0, 0.0, 1.0))},
        "MatB": {"Base Color": png(folder / "MatB_BC.png", (0.2, 0.2, 0.8, 1.0))},
    }
