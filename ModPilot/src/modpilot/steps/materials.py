"""Phase 5B-5C (plan.md video 5): textures into each material's Principled BSDF, then MH Wilds
.mdf2 materials and .tex textures from the Modding Toolkit's MDF2 generator. Ported from the
legacy app/phases/material.py (its deterministic paths; the LLM / vision suggestion helpers are not
steps).

Changes from the legacy tools (no silent paths):
- material_setup checks the whole mapping first (x_preset, the mesh, every material, every slot name,
  every file) and changes nothing on a bad entry; the legacy tool skipped unknown materials, unknown
  slots and unloadable files and reported them under slots_skipped. A material without a Principled
  BSDF is a precondition (the legacy tool added one, unconnected, which the generator never reads).
- material_generate fails on a preset_mapping entry that names no preset or no material the
  generator lists (the legacy tool fell back to the generator's guess), on a missing natives_root,
  and on every material the generator could not make: the generator prints those and its operator
  still returns FINISHED. It returns the MDF2 collection it wrote into (the legacy tool returned the
  setting, empty unless given) and records it in the scene config.
- material_consolidate checks every merge group (keeper and each name to remove on the mesh, none
  both) before it merges any; the legacy tool skipped unknown names. Its dry run no longer asks a
  vision model about partly overlapping groups (vision_merge_proposals).
- material_inspect fails on an unknown `purpose` (the legacy tool ignored it; the agent loop read it).
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from modpilot.core.config import resolve
from modpilot.core.errors import StepError
from modpilot.core.step import step

SETUP_PRESETS = ("VRChat", "終末地")
SLOTS = ("Base Color", "Alpha", "Roughness", "Metallic", "Emission", "Normal")
# Blender 4.0 renamed 'Emission' to 'Emission Color'; its strength now defaults to 0, which the
# generator reads as "not emissive" (claude_run1's eye glow was wired by hand)
SOCKET_NAMES = {"Emission": ("Emission Color", "Emission")}
PRESET_GAME = "MHWILDS"          # RE Mesh Editor's Presets/ subfolder (Toolkit MHWS_GEN_GAME)
GENERATOR_MODULE_SUFFIX = "core.mdf_generator_base"


def _socket(bsdf, slot):
    for name in SOCKET_NAMES.get(slot, (slot,)):
        sock = bsdf.inputs.get(name)
        if sock is not None:
            return sock
    return None


def _bsdf(mat):
    if mat.node_tree is None:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


# ── material_setup ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SetupParams:
    target_object: str
    x_preset: str
    texture_mapping: dict[str, dict[str, str | None]]


def _wire_normal(nodes, links, tex, target, y, flip_green: bool):
    nm = nodes.new("ShaderNodeNormalMap")
    nm.location = (-150, y)
    if flip_green:               # OpenGL (VRChat) normal map: G -> 1 - G
        sep = nodes.new("ShaderNodeSeparateXYZ")
        sep.location = (-700, y)
        sub = nodes.new("ShaderNodeMath")
        sub.operation = "SUBTRACT"
        sub.inputs[0].default_value = 1.0
        sub.location = (-500, y - 120)
        cmb = nodes.new("ShaderNodeCombineXYZ")
        cmb.location = (-350, y)
        links.new(tex.outputs["Color"], sep.inputs["Vector"])
        links.new(sep.outputs["X"], cmb.inputs["X"])
        links.new(sep.outputs["Y"], sub.inputs[1])
        links.new(sub.outputs[0], cmb.inputs["Y"])
        links.new(sep.outputs["Z"], cmb.inputs["Z"])
        links.new(cmb.outputs[0], nm.inputs["Color"])
    else:                        # DirectX (Endfield): straight in
        links.new(tex.outputs["Color"], nm.inputs["Color"])
    links.new(nm.outputs[0], target)


@step("material_setup", SetupParams)
def material_setup(p: SetupParams, ctx) -> dict:
    """Wire each {material: {slot: image path}} into the material's Principled BSDF: an Image
    Texture per slot; Normal through a Normal Map node (VRChat's OpenGL maps get their green flipped);
    Emission into 'Emission Color' with its strength set to 1 if it was 0. A null path leaves the slot
    alone. MMD models don't use this step."""
    import bpy
    if p.x_preset not in SETUP_PRESETS:
        raise StepError("params", f"x_preset must be one of {list(SETUP_PRESETS)} (MMD models skip material_setup), "
                        f"got {p.x_preset!r}")
    if not p.texture_mapping:
        raise StepError("params", "texture_mapping is empty: map materials to {slot: image path}")
    unknown = sorted({f"{m}.{s}" for m, slots in p.texture_mapping.items() for s in slots if s not in SLOTS})
    if unknown:
        raise StepError("params", f"unknown slot(s) {unknown}; slots are {list(SLOTS)}", details={"unknown": unknown})
    obj = bpy.data.objects.get(p.target_object)
    if obj is None or obj.type != "MESH":
        raise StepError("precondition", f"target_object {p.target_object!r} not found (or not a MESH)")
    missing = [m for m in p.texture_mapping if bpy.data.materials.get(m) is None]
    no_bsdf = [m for m in p.texture_mapping if m not in missing and _bsdf(bpy.data.materials[m]) is None]
    files = sorted({f for slots in p.texture_mapping.values() for f in slots.values() if f and not os.path.isfile(f)})
    if missing or no_bsdf or files:
        raise StepError("precondition", f"materials not found {missing}, without a Principled BSDF {no_bsdf}, "
                        f"image files missing {files}",
                        details={"materials_not_found": missing, "no_principled_bsdf": no_bsdf, "files_missing": files})
    on_target = {s.material.name for s in obj.material_slots if s.material}
    elsewhere = [m for m in p.texture_mapping if m not in on_target]
    if elsewhere:
        ctx.warn(f"materials not on {obj.name}, wired anyway: {', '.join(elsewhere)}")

    wired = []
    for mat_name, slots in p.texture_mapping.items():
        mat = bpy.data.materials[mat_name]
        nodes, links, bsdf = mat.node_tree.nodes, mat.node_tree.links, _bsdf(mat)
        y = 300
        for slot, path in slots.items():
            if not path:
                continue
            target = _socket(bsdf, slot)
            if target is None:
                raise StepError("environment", f"{mat_name}: this Blender's Principled BSDF has no {slot} input",
                                partial={"materials_wired": wired})
            tex = nodes.new("ShaderNodeTexImage")
            tex.image = bpy.data.images.load(path, check_existing=True)
            if slot == "Normal":
                tex.location = (-900, y)
                _wire_normal(nodes, links, tex, target, y, flip_green=p.x_preset == "VRChat")
            else:
                tex.location = (-500, y)
                links.new(tex.outputs["Color"], target)
                if slot == "Emission":
                    strength = bsdf.inputs.get("Emission Strength")
                    if strength is not None and not strength.is_linked and strength.default_value == 0.0:
                        strength.default_value = 1.0
            wired.append(f"{mat_name}.{slot}")
            y -= 300
    return {"materials_wired": wired}


# ── material_generate ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class GenerateParams:
    natives_root: str
    texture_base_path: str
    preset_mapping: dict[str, str] = field(default_factory=dict)
    mesh_collection: str | None = None
    mdf_collection_name: str = ""


def _generator():
    """The Toolkit's core.mdf_generator_base module (its package name is the add-on's folder)."""
    for name, mod in list(sys.modules.items()):
        if name.endswith(GENERATOR_MODULE_SUFFIX) and hasattr(mod, "load_preset_enum_items"):
            if not hasattr(mod, "MdfGenProcessBase"):
                break
            return mod
    raise StepError("environment", "the Modding Toolkit's MDF2 generator (core.mdf_generator_base) is not loaded")


@contextmanager
def _recording_failures(gen):
    """Record each material the generator fails on: it catches the error, prints it and carries
    on, and its operator still returns FINISHED."""
    base = gen.MdfGenProcessBase
    inner = base.__dict__["_process_one_material"]
    fn = inner.__func__ if isinstance(inner, staticmethod) else inner
    failed: dict[str, str] = {}

    def recorded(runner, context, entry, *args, **kwargs):
        try:
            return fn(runner, context, entry, *args, **kwargs)
        except Exception as exc:
            failed[entry.blender_material] = str(exc)
            raise
    base._process_one_material = staticmethod(recorded)
    try:
        yield failed
    finally:
        base._process_one_material = inner


@step("material_generate", GenerateParams, needs=("mhws",))
def material_generate(p: GenerateParams, ctx) -> dict:
    """The Toolkit's MDF2 generator over the mesh collection: refresh (it lists the materials and
    guesses presets), set the agreed presets (display names from RE Mesh Editor's
    Presets/MHWILDS), generate (.tex under natives/STM/Art/<texture_base_path>, one MDF2 entry per
    material, meshes separated per material as Group_0_Sub_N__<material>)."""
    import bpy

    from modpilot.bl import context
    from modpilot.core import ops
    col_name = resolve(p.mesh_collection, ctx.config, "mesh_collection")
    col = bpy.data.collections.get(col_name)
    if col is None:
        raise StepError("precondition", f"mesh collection {col_name!r} not found")
    if not os.path.isdir(p.natives_root):
        raise StepError("precondition", f"natives_root {p.natives_root!r} is not a folder")
    if not p.texture_base_path.strip():
        raise StepError("params", "texture_base_path is required (e.g. 'Author/CharName/')")
    gen = _generator()
    items = gen.load_preset_enum_items(PRESET_GAME)
    presets = {item[1]: item[0] for item in items if item[0] != "NONE"}
    if not presets:
        raise StepError("environment", f"no RE Mesh Editor presets for {PRESET_GAME}: {items[0][1] if items else ''}")
    unknown = {m: d for m, d in p.preset_mapping.items() if d not in presets}
    if unknown:
        raise StepError("params", f"unknown preset name(s) {unknown}", details={"unknown": unknown, "known": sorted(presets)})

    scene = bpy.context.scene
    s = scene.mhws_mdf_generator
    context.object_mode()
    scene["mhws_natives_root"] = p.natives_root
    s.mesh_collection = col
    s.texture_base_path = p.texture_base_path
    s.mdf_collection_name = p.mdf_collection_name
    # bake config, as the legacy tool set it: Cycles, GPU, 4 samples
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"
    scene.cycles.samples = 4
    scene.cycles.preview_samples = 4
    ops.run("mhws.mdf_gen_refresh")
    listed = [e.blender_material for e in s.material_list if e.blender_material]
    not_listed = [m for m in p.preset_mapping if m not in listed]
    if not_listed:
        raise StepError("precondition", f"preset_mapping names materials the generator does not list for "
                        f"{col.name}: {not_listed}", details={"not_listed": not_listed, "listed": listed})
    auto = []
    for entry in s.material_list:
        name = entry.blender_material or ""
        if name in p.preset_mapping:
            entry.material_preset = presets[p.preset_mapping[name]]
        else:
            auto.append(name)
    if auto:
        ctx.warn(f"generator-guessed presets for {', '.join(auto)}")

    before = set(bpy.data.collections.keys())
    with _recording_failures(gen) as failed:
        ops.run("mhws.mdf_gen_process")
    new = [c for c in bpy.data.collections.keys() if c not in before and ".mdf2" in c]  # noqa: SIM118 (names, not IDs)
    mdf_name = p.mdf_collection_name.strip() or (new[0] if new else col.name.replace(".mesh", ".mdf2"))
    if bpy.data.collections.get(mdf_name) is None:
        raise StepError("postcondition", f"the generator made no MDF2 collection {mdf_name!r}")
    ctx.set_config(mdf2_collection=mdf_name)
    data = {"mdf_collection": mdf_name, "materials_processed": [m for m in listed if m not in failed],
            "presets_auto_guessed": auto}
    if failed:
        raise StepError("postcondition", f"the generator failed on {len(failed)} material(s): {failed}",
                        details={"failed": failed}, partial=data)
    return data


# ── material_inspect ──────────────────────────────────────────────────────

IMAGE_EXTENSIONS = frozenset({".png", ".tga", ".dds", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"})
PURPOSES = ("classify", "verify")


@dataclass(frozen=True)
class InspectParams:
    target_object: str
    texture_dir: str
    purpose: str = "classify"     # the old agent loop's widget switch; no effect on the step


def _mesh(name):
    import bpy
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "MESH":
        raise StepError("precondition", f"no mesh object named {name!r}", details={"target_object": name})
    return obj


def _trace_to_image(node, depth=0):
    """The absolute path of the image feeding `node` through its first linked input, else 'connected_no_image'."""
    import bpy
    if depth > 6:
        return "connected_no_image"
    if node.type == "TEX_IMAGE":
        return bpy.path.abspath(node.image.filepath) if node.image else "connected_no_image"
    for inp in node.inputs:
        if inp.is_linked:
            return _trace_to_image(inp.links[0].from_node, depth + 1)
    return "connected_no_image"


@step("material_inspect", InspectParams)
def material_inspect(p: InspectParams, ctx) -> dict:
    """The mesh's materials, the image files in texture_dir (not its subfolders), and per material
    which Principled BSDF slots are wired, to which image."""
    if p.purpose not in PURPOSES:
        raise StepError("params", f"purpose must be one of {PURPOSES}, not {p.purpose!r}")
    folder = Path(p.texture_dir)
    if not folder.is_dir():
        raise StepError("precondition", f"texture_dir is not a folder: {p.texture_dir!r}")
    obj = _mesh(p.target_object)
    files = sorted(str(f) for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS)
    connections = {}
    for mat in obj.data.materials:
        if mat is None:
            continue
        state = dict.fromkeys(SLOTS)
        bsdf = _bsdf(mat)
        if bsdf is not None:
            for slot in SLOTS:
                sock = _socket(bsdf, slot)
                if sock is not None and sock.is_linked:
                    state[slot] = _trace_to_image(sock.links[0].from_node)
        connections[mat.name] = state
    return {"materials": [m.name for m in obj.data.materials if m is not None], "texture_files": files,
            "existing_connections": connections}


# ── material_consolidate ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ConsolidateParams:
    target_object: str
    dry_run: bool = True
    groups: list[dict] = field(default_factory=list)


def _texture_set(mat) -> tuple[str, ...]:
    """Every image file the material's node tree references, linked or not (normalized, sorted)."""
    import bpy
    paths = set()
    if mat.node_tree is not None:
        for n in mat.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image is not None and n.image.filepath:
                paths.add(os.path.normcase(os.path.normpath(bpy.path.abspath(n.image.filepath))))
    return tuple(sorted(paths))


def _scan(obj) -> dict:
    by_set: dict[tuple, list[str]] = {}
    mats = [m for m in obj.data.materials if m is not None]
    for m in mats:
        by_set.setdefault(_texture_set(m), []).append(m.name)
    groups = []
    for key, members in by_set.items():
        if not key:                       # no textures: never merged
            groups += [{"texture_set": [], "materials": [m], "keeper": m, "to_remove": [], "is_singleton": True}
                       for m in members]
            continue
        groups.append({"texture_set": sorted({os.path.basename(x) for x in key}), "materials": list(members),
                       "keeper": members[0], "to_remove": members[1:], "is_singleton": len(members) == 1})
    return {"consolidation_groups": groups, "material_count_before": len(mats)}


def _check_groups(groups, names) -> list[tuple[str, list[str]]]:
    out = []
    for g in groups:
        if set(g) - {"keeper", "to_remove"} or not isinstance(g.get("keeper"), str) \
                or not isinstance(g.get("to_remove"), list):
            raise StepError("params", f"a group is {{keeper: name, to_remove: [names]}}, not {g!r}")
        keeper, remove = g["keeper"], g["to_remove"]
        if keeper in remove:
            raise StepError("params", f"{keeper!r} is both the keeper and to be removed")
        missing = [n for n in [keeper, *remove] if n not in names]
        if missing:
            raise StepError("precondition", f"material(s) not on the mesh: {missing}",
                            details={"missing": missing, "materials": sorted(names)})
        out.append((keeper, list(remove)))
    return out


@step("material_consolidate", ConsolidateParams)
def material_consolidate(p: ConsolidateParams, ctx) -> dict:
    """Dry run: group the mesh's materials by the image files they reference (a proposal; nothing
    changes). Otherwise: for each given group, move the faces of every material in to_remove to the
    keeper and drop that slot."""
    obj = _mesh(p.target_object)
    if p.dry_run:
        return _scan(obj)
    if not p.groups:
        raise StepError("params", "groups is required when dry_run is false (run a dry run for a proposal)")
    mesh = obj.data
    plan = _check_groups(p.groups, {m.name for m in mesh.materials if m is not None})
    before = len([m for m in mesh.materials if m is not None])

    def index(name):
        return next(i for i, m in enumerate(mesh.materials) if m is not None and m.name == name)

    merged = []
    for keeper, remove in plan:
        done = []
        for name in remove:
            k, r = index(keeper), index(name)
            idx = [0] * len(mesh.polygons)
            mesh.polygons.foreach_get("material_index", idx)
            idx = [k if i == r else i for i in idx]
            mesh.materials.pop(index=r)
            idx = [i - 1 if i > r else i for i in idx]
            mesh.polygons.foreach_set("material_index", idx)
            done.append(name)
        if done:
            merged.append({"keeper": keeper, "removed": done})
    mesh.update()
    return {"merged_groups": merged, "skipped": [], "material_count_before": before,
            "material_count_after": len([m for m in mesh.materials if m is not None])}
