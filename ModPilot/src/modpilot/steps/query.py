"""Read-only query steps (the legacy app/phases/query_tools.py, as data instead of JSON strings).

Changes from the legacy query tools: a name that isn't in the scene fails (precondition) instead of
answering {"error": ...} (the bridged legacy tool still answers that way); scene_info lists every
object (blender-mcp's get_scene_info, which the legacy tool called, stops at the first 10: ModPilot
lesson #57); physics_read refuses unknown fields (they were dropped) and list_mdf_presets a missing
generator or preset folder (it answered an empty list).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from modpilot.core.errors import StepError
from modpilot.core.step import step

PHYSICS_READ_DEFAULT = ("damping", "minDamping", "reduceSelfDistanceRate", "gravity", "springForce",
                        "shockAbsorptionRate", "windEffectCoef", "envWindEffectCoef", "motionForce",
                        "colliderFilterInfoPath")


def _plain(v):
    return v if isinstance(v, str | int | float | bool | type(None)) else str(v)


def _custom(idprops) -> dict:
    return {k: _plain(v) for k, v in idprops.items() if not k.startswith("_")}


def _object(name: str, type_: str | None = None):
    import bpy
    obj = bpy.data.objects.get(name)
    if obj is None or (type_ and obj.type != type_):
        what = type_ or "object"
        raise StepError("precondition", f"{what} {name!r} not found" + (f" (or not a {type_})" if type_ else ""))
    return obj


@dataclass(frozen=True)
class NoParams:
    pass


@dataclass(frozen=True)
class ListObjectsParams:
    type_filter: str = ""


@step("list_objects", ListObjectsParams, mutates=False)
def list_objects(p: ListObjectsParams, ctx) -> dict:
    """Objects in the file (optionally one Blender type), with the three visibility flags that
    decide whether an operator can select them: visible_get, hide_viewport, hide_get."""
    import bpy
    objs = list(bpy.data.objects)
    if p.type_filter:
        objs = [o for o in objs if o.type == p.type_filter.upper()]
    return {"objects": [{"name": o.name, "type": o.type, "visible": o.visible_get(),
                         "hide_viewport": o.hide_viewport, "hide_get": o.hide_get()} for o in objs]}


@step("scene_info", NoParams, mutates=False)
def scene_info(p: NoParams, ctx) -> dict:
    """The scene's name, object and material counts, and every object's name, type and location."""
    import bpy
    s = bpy.context.scene
    return {"name": s.name, "object_count": len(s.objects), "materials_count": len(bpy.data.materials),
            "objects": [{"name": o.name, "type": o.type, "location": [round(float(c), 2) for c in o.location]}
                        for o in s.objects]}


@dataclass(frozen=True)
class BoneInfoParams:
    armature_name: str
    filter_custom_prop: str = ""


@step("get_bone_info", BoneInfoParams, mutates=False)
def get_bone_info(p: BoneInfoParams, ctx) -> dict:
    """Pose bones with parent and custom properties (filter_custom_prop: only bones that have it)."""
    arm = _object(p.armature_name, "ARMATURE")
    bones = []
    for pb in arm.pose.bones:
        custom = _custom(pb)
        if p.filter_custom_prop and p.filter_custom_prop not in custom:
            continue
        bones.append({"name": pb.name, "parent": pb.parent.name if pb.parent else None, "custom_props": custom})
    return {"armature": p.armature_name, "total_bones": len(arm.pose.bones), "returned_bones": len(bones),
            "bones": bones}


@dataclass(frozen=True)
class CollectionsParams:
    chain_only: bool = False


@step("list_collections", CollectionsParams, mutates=False)
def list_collections(p: CollectionsParams, ctx) -> dict:
    """Collections with object count, children and custom properties (chain_only: '.chain' / '.clsp')."""
    import bpy
    return {"collections": [
        {"name": c.name, "object_count": len(c.objects), "children": [ch.name for ch in c.children],
         "custom_props": {k: _plain(v) for k, v in c.items()}}
        for c in bpy.data.collections if not p.chain_only or ".chain" in c.name or ".clsp" in c.name]}


@dataclass(frozen=True)
class MeshInfoParams:
    mesh_name: str
    max_vgroups: int = 50


@step("get_mesh_info", MeshInfoParams, mutates=False)
def get_mesh_info(p: MeshInfoParams, ctx) -> dict:
    """A mesh's parent armature, vertex count, vertex groups (first max_vgroups), materials, UV maps."""
    obj = _object(p.mesh_name, "MESH")
    groups = [g.name for g in obj.vertex_groups]
    return {"mesh": p.mesh_name,
            "parent_armature": obj.parent.name if obj.parent and obj.parent.type == "ARMATURE" else None,
            "vertex_count": len(obj.data.vertices), "vertex_group_count": len(groups),
            "vertex_groups": groups[:p.max_vgroups],
            "material_slots": [s.material.name if s.material else None for s in obj.material_slots],
            "uv_layers": [u.name for u in obj.data.uv_layers]}


@dataclass(frozen=True)
class MaterialInfoParams:
    mesh_name: str


@step("get_material_info", MaterialInfoParams, mutates=False)
def get_material_info(p: MaterialInfoParams, ctx) -> dict:
    """Per material slot: the shader feeding Material Output and every Image Texture node (has_data
    False: the image is not loaded, likely a broken path)."""
    obj = _object(p.mesh_name, "MESH")
    slots = []
    for i, slot in enumerate(obj.material_slots):
        mat = slot.material
        entry = {"slot_index": i, "material_name": mat.name if mat else None,
                 "use_nodes": bool(mat and mat.node_tree), "shader_type": None, "textures": []}
        if mat and mat.node_tree:
            out = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
            surf = out.inputs.get("Surface") if out else None
            if surf is not None and surf.links:
                entry["shader_type"] = surf.links[0].from_node.bl_label
            entry["textures"] = [{"node": n.name, "image": n.image.name if n.image else None,
                                  "filepath": n.image.filepath if n.image else None,
                                  "is_packed": bool(n.image and n.image.packed_file),
                                  "has_data": bool(n.image and n.image.has_data)}
                                 for n in mat.node_tree.nodes if n.type == "TEX_IMAGE"]
        slots.append(entry)
    return {"mesh": p.mesh_name, "material_slots": slots}


@dataclass(frozen=True)
class ObjectPropsParams:
    object_name: str


@step("get_object_props", ObjectPropsParams, mutates=False)
def get_object_props(p: ObjectPropsParams, ctx) -> dict:
    """An object's type and custom properties ('_' keys left out)."""
    obj = _object(p.object_name)
    return {"object": obj.name, "type": obj.type, "custom_props": _custom(obj)}


@dataclass(frozen=True)
class MaterialNodesParams:
    material_name: str


@step("inspect_material_nodes", MaterialNodesParams, mutates=False)
def inspect_material_nodes(p: MaterialNodesParams, ctx) -> dict:
    """A material's whole node graph: nodes (Image Textures with {path, exists}), links, the shader
    feeding Material Output, and orphan nodes (in no link)."""
    import os

    import bpy
    mat = bpy.data.materials.get(p.material_name)
    if mat is None:
        raise StepError("precondition", f"material {p.material_name!r} not found")
    if mat.node_tree is None:
        return {"material": p.material_name, "node_count": 0, "nodes": [], "links": [], "output_shader": None,
                "orphan_nodes": [], "note": "material has no node_tree (use_nodes is False)"}
    nodes = list(mat.node_tree.nodes)
    idx = {n.name: i for i, n in enumerate(nodes)}

    def image(img):
        fp = bpy.path.abspath(img.filepath) if img and img.filepath else ""
        return {"path": fp, "exists": os.path.exists(fp)} if fp else None
    entries = []
    for i, n in enumerate(nodes):
        entry = {"id": i, "name": n.name, "type": n.type}
        if n.type == "TEX_IMAGE":
            entry["image"] = image(n.image)
        entries.append(entry)
    links, linked = [], set()
    for lk in mat.node_tree.links:
        a, b = idx.get(lk.from_node.name), idx.get(lk.to_node.name)
        if a is None or b is None:
            continue
        links.append({"from": f"{a}.{lk.from_socket.name}", "to": f"{b}.{lk.to_socket.name}"})
        linked |= {a, b}
    output = None
    out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
    surf = out.inputs.get("Surface") if out else None
    if surf is not None and surf.is_linked:
        up = surf.links[0].from_node
        output = {"node_id": idx.get(up.name), "type": up.type, "name": up.name}
    return {"material": p.material_name, "node_count": len(entries), "nodes": entries, "links": links,
            "output_shader": output, "orphan_nodes": [e for i, e in enumerate(entries) if i not in linked]}


@dataclass(frozen=True)
class PhysicsReadParams:
    targets: list[str] = field(default_factory=list)
    properties: list[str] = field(default_factory=list)


@step("physics_read", PhysicsReadParams, mutates=False, needs=("re_chain",))
def physics_read(p: PhysicsReadParams, ctx) -> dict:
    """Chain-settings values of the named chain-settings objects (all of them when targets is
    empty); properties: which fields (empty: the usual physics ones)."""
    import bpy

    from modpilot.bl import chains
    fields = bpy.types.Object.bl_rna.properties["re_chain_chainsettings"].fixed_type.properties
    props = p.properties or list(PHYSICS_READ_DEFAULT)
    unknown = [k for k in props if k not in fields.keys()]  # noqa: SIM118 (RNA collection)
    if unknown:
        raise StepError("params", f"unknown chain-settings field(s): {unknown}", details={"unknown": unknown})
    if p.targets:
        objs = []
        for name in p.targets:
            obj = bpy.data.objects.get(name)
            if obj is None or obj.get("TYPE") != "RE_CHAIN_CHAINSETTINGS":
                raise StepError("precondition", f"{name!r} is not a chain-settings object")
            objs.append(obj)
    else:
        objs = chains.objects_of("RE_CHAIN_CHAINSETTINGS")
    out = []
    for obj in objs:
        pg = obj.re_chain_chainsettings
        vals = {}
        for k in props:
            v = getattr(pg, k)
            vals[k] = list(v) if hasattr(v, "__len__") and not isinstance(v, str) else v
        out.append({"name": obj.name, "values": vals})
    return {"chain_settings": out}


@step("list_mdf_presets", NoParams, mutates=False)
def list_mdf_presets(p: NoParams, ctx) -> dict:
    """The MH Wilds material preset names material_generate's preset_mapping takes."""
    from modpilot.steps.materials import PRESET_GAME, _generator
    items = _generator().load_preset_enum_items(PRESET_GAME)
    names = [item[1] for item in items if item[0] != "NONE"]
    if not names:
        raise StepError("environment", f"no RE Mesh Editor presets for {PRESET_GAME}")
    return {"presets": names}
