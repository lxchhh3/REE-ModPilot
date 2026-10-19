"""scene_fingerprint: a stable digest of what a build changes in the scene, per section.

The yardstick of the restructure's differential tests (M2): open the same checkpoint, run the
legacy tool and the new step, compare fingerprints. Floats are rounded to `precision` decimals
(default 4: 0.1 mm, 1e-4 weight); bulk arrays (positions, shape-key deltas) become sha256
digests of the rounded values. Read-only.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from modpilot.core.step import step

SECTIONS = ("objects", "armatures", "meshes", "collections", "chain", "materials", "scene")


@dataclass(frozen=True)
class FingerprintParams:
    precision: int = 4
    include: list[str] = field(default_factory=list)   # empty: every section


def _r(x, n):
    return round(float(x), n) + 0.0


def _vec(v, n):
    return [_r(c, n) for c in v]


def _digest(arr, n) -> str:
    import numpy as np
    a = np.round(np.asarray(arr, dtype=np.float64), n) + 0.0
    return hashlib.sha256(a.tobytes()).hexdigest()[:16]


def _rna_values(pg, n) -> dict:
    out = {}
    for prop in pg.bl_rna.properties:
        name = prop.identifier
        if name == "rna_type":
            continue
        try:
            value = getattr(pg, name)
        except AttributeError:
            continue
        if prop.type in {"BOOLEAN", "INT", "ENUM", "STRING"} and getattr(prop, "array_length", 0) == 0:
            out[name] = value if not isinstance(value, set) else sorted(value)
        elif prop.type == "FLOAT":
            out[name] = _vec(value, n) if getattr(prop, "array_length", 0) else _r(value, n)
        elif prop.type in {"INT", "BOOLEAN"}:
            out[name] = list(value)
        elif prop.type == "POINTER" and value is not None and hasattr(value, "name"):
            out[name] = value.name
    return out


def _objects(bpy, n):
    return {o.name: {"type": o.type, "parent": o.parent.name if o.parent else None,
                     "parent_type": o.parent_type, "parent_bone": o.parent_bone,
                     "collections": sorted(c.name for c in o.users_collection),
                     "matrix": [_r(x, n) for row in o.matrix_world for x in row],
                     "modifiers": [[m.type, getattr(getattr(m, "object", None), "name", None)] for m in o.modifiers]}
            for o in bpy.data.objects}


def _armatures(bpy, n):
    out = {}
    for o in bpy.data.objects:
        if o.type != "ARMATURE":
            continue
        bones = {}
        for b in o.data.bones:
            pb = o.pose.bones.get(b.name)
            bones[b.name] = {"head": _vec(b.head_local, n), "tail": _vec(b.tail_local, n),
                             "parent": b.parent.name if b.parent else None,
                             "z_axis": _vec(b.matrix_local.col[2][:3], n),
                             "chain_role": pb.get("chain_role") if pb is not None else None}
        out[o.name] = bones
    return out


def _meshes(bpy, n):
    import numpy as np
    out = {}
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        me = o.data
        nv = len(me.vertices)
        co = np.empty(nv * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        groups = {g.index: g.name for g in o.vertex_groups}
        sums: dict[str, float] = {}
        for v in me.vertices:
            for e in v.groups:
                name = groups.get(e.group, f"#{e.group}")
                sums[name] = sums.get(name, 0.0) + e.weight
        keys = {}
        if me.shape_keys:
            ref = me.shape_keys.reference_key
            base = np.empty(nv * 3, dtype=np.float32)
            ref.data.foreach_get("co", base)
            for kb in me.shape_keys.key_blocks:
                k = np.empty(nv * 3, dtype=np.float32)
                kb.data.foreach_get("co", k)
                keys[kb.name] = {"value": _r(kb.value, n), "mute": kb.mute,
                                 "relative_to": kb.relative_key.name, "delta": _digest(k - base, n)}
        out[o.name] = {"vertices": nv, "faces": len(me.polygons), "co": _digest(co, n),
                       "materials": [m.name if m else None for m in me.materials],
                       "face_materials": _digest(np.array([p.material_index for p in me.polygons]), 0),
                       "uv_layers": [u.name for u in me.uv_layers],
                       "colors": [[c.name, c.domain, c.data_type] for c in me.color_attributes],
                       "groups": {k: _r(v, n) for k, v in sorted(sums.items())}, "keys": keys}
    return out


def _collections(bpy, n):
    return {c.name: {"objects": sorted(o.name for o in c.objects), "children": sorted(ch.name for ch in c.children),
                     "props": {k: c[k] for k in c.keys() if isinstance(c[k], (str, int, float))}}  # noqa: SIM118 (an ID's custom props, not a dict)
            for c in bpy.data.collections}


def _chain(bpy, n):
    out = {}
    for o in bpy.data.objects:
        t = o.get("TYPE")
        if not (isinstance(t, str) and t.startswith("RE_CHAIN")):
            continue
        entry = {"type": t, "parent": o.parent.name if o.parent else None,
                 "constraints": {c.name: getattr(c, "subtarget", "") for c in o.constraints}}
        for pg_name in ("re_chain_chainsettings", "re_chain_chaingroup", "re_chain_chainnode",
                        "re_chain_header", "re_chain_chainlink", "re_chain_collision"):
            pg = getattr(o, pg_name, None)
            if pg is not None and hasattr(pg, "bl_rna"):
                entry[pg_name] = _rna_values(pg, n)
        out[o.name] = entry
    return out


def _materials(bpy, n):
    out = {}
    for m in bpy.data.materials:
        # not m.use_nodes: deprecated in Blender 5 (removed in 6.0); the node tree says the same
        entry = {"node_tree": m.node_tree is not None}
        if m.node_tree:
            nodes = m.node_tree.nodes
            entry["nodes"] = sorted(node.bl_idname for node in nodes)
            entry["links"] = sorted(f"{lk.from_node.bl_idname}.{lk.from_socket.identifier}->"
                                    f"{lk.to_node.bl_idname}.{lk.to_socket.identifier}" for lk in m.node_tree.links)
            entry["images"] = sorted(node.image.name for node in nodes if getattr(node, "image", None))
        out[m.name] = entry
    return out


def _scene(bpy, n):
    s = bpy.context.scene
    return {k: s[k] for k in sorted(s.keys()) if isinstance(s[k], (str, int, float, bool))}


@step("scene_fingerprint", FingerprintParams, mutates=False)
def scene_fingerprint(p: FingerprintParams, ctx) -> dict:
    """Per-section digest of objects, bones, mesh data, collections, chain objects, materials and
    scene properties; `digest` covers every section computed."""
    import bpy

    from modpilot.core.errors import StepError
    unknown = sorted(set(p.include) - set(SECTIONS))
    if unknown:
        raise StepError("params", f"unknown section(s) {', '.join(unknown)}; known: {', '.join(SECTIONS)}",
                        details={"unknown": unknown, "known": list(SECTIONS)})
    wanted = p.include or list(SECTIONS)
    builders = {"objects": _objects, "armatures": _armatures, "meshes": _meshes, "collections": _collections,
                "chain": _chain, "materials": _materials, "scene": _scene}
    sections = {name: builders[name](bpy, p.precision) for name in wanted}
    text = json.dumps(sections, sort_keys=True, ensure_ascii=False, default=str)
    return {"digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "section_digests": {k: hashlib.sha256(json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)
                                                  .encode("utf-8")).hexdigest()[:16] for k, v in sections.items()},
            "sections": json.loads(text)}
