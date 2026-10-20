"""Phase 3.5-4B (plan.md video 4): physics bones onto the MH Wilds armature, their chain heads, the
RE Chain structures with calibrated settings. Ported from the legacy app/phases/physics_bones.py.

Changes from the legacy tools (no silent paths): the `_End` cascade, the settings consolidation, the
angle ramp and the header calibration ran in `except: pass` blocks or dropped their errors; here
they report what they did or raise. Merge / clear bones that don't exist, a re-run that created no
new settings, and SHARED consolidation leftovers are warnings. A chain_collection hint that isn't a
chain collection fails instead of being ignored. The reconnect-after-drop recovery is gone: a step
runs inside Blender and has no socket to lose. The chain collection created when none exists is
named from the scene's mesh collection (it was hard-coded 'MHWilds_Female').
"""
from __future__ import annotations

from dataclasses import dataclass, field

from modpilot import physics
from modpilot.core.config import resolve
from modpilot.core.errors import StepError
from modpilot.core.step import step

PREPARE_MESSAGE = (
    "Chain role marks refreshed. Strict verification (no body bones "
    "marked, every chain head has _End descendants) is deferred to "
    "the chain-creation step where bones_to_merge will have been "
    "applied. Proceed by classifying chains in the widget; "
    "physics_chains will re-run validation against the post-merge "
    "state and surface any real anomalies in its result."
)
RAMP_MAX_ANGLE = 1.047198      # 60 degrees
RAMP_ITERATIONS = 4
# RE Chain Editor's create_chain_header writes generic defaults; MH Wilds ships these (issue #21)
WILDS_HEADER = (("calculateMode", "3"), ("chainAttrFlags", "4"), ("calculateStepTime", 2.0),
                ("modelCollisionSearch", 1), ("highFPSCalculateMode", "2"), ("wilds_unkn1", 1), ("wilds_unkn2", 1))


def _armature(name: str, role: str):
    import bpy
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "ARMATURE":
        raise StepError("precondition", f"{role} armature {name!r} not found (or not an ARMATURE)")
    return obj


def _pose_mode(arm):
    from modpilot.bl import context
    from modpilot.core import ops
    context.select_only([arm], active=arm)
    ops.run("object.mode_set", mode="POSE")


def _object_mode():
    from modpilot.core import ops
    ops.run("object.mode_set", mode="OBJECT")


# ── physics_transplant ────────────────────────────────────────────────────


@dataclass(frozen=True)
class TransplantParams:
    source_armature: str | None = None
    target_armature: str | None = None
    x_preset: str | None = None
    y_preset: str | None = None


def add_missing_end_bones(src, tgt) -> list[str]:
    """smart_graft gives a physics leaf its '<leaf>_End' only when the leaf carries weights in a mesh
    still on the SOURCE armature; vertex_groups has already moved every mesh, so no leaf got one and
    physics_chains (which closes a chain only at an '_End') skipped single-bone chains (ModPilot
    lesson #49). Its own rule, reading the weights where the meshes are now; its own geometry: head
    on the source leaf's world tail, 5 cm straight up, roll 0, parented to the grafted leaf."""
    import json

    import bpy
    import mathutils

    from modpilot.bl import context
    try:
        protected = set(json.loads(tgt.get("transplant_protected_bones", "[]")))
    except (TypeError, ValueError):
        protected = set()
    grafted = {b.name for b in src.data.bones if b.name in tgt.data.bones and b.name not in protected
               and not b.name.endswith("_End")}
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and (o.parent is tgt or any(
        m.type == "ARMATURE" and m.object is tgt for m in o.modifiers))]

    def weighted(name):
        for o in meshes:
            g = o.vertex_groups.get(name)
            if g is not None and any(e.group == g.index and e.weight > 0 for v in o.data.vertices for e in v.groups):
                return True
        return False

    leaves = [n for n in sorted(grafted) if not any(c.name in grafted for c in src.data.bones[n].children)
              and n + "_End" not in tgt.data.bones and weighted(n)]
    if leaves:
        inv = tgt.matrix_world.inverted()
        with context.edit_mode(tgt) as eb:
            for n in leaves:
                end = eb.new(n + "_End")
                end.head = inv @ (src.matrix_world @ src.pose.bones[n].tail)
                end.tail = end.head + mathutils.Vector((0.0, 0.0, 0.05))
                end.roll = 0.0
                end.parent = eb[n]
                end.use_connect = False
    return [n + "_End" for n in leaves]


@step("physics_transplant", TransplantParams, needs=("modder",))
def physics_transplant(p: TransplantParams, ctx) -> dict:
    """modder.smart_graft: the source's physics bones onto the MH Wilds armature (with chain_role
    marks); then the '_End' bones it couldn't see; the source armature hidden; the Toolkit's X preset
    switched to the target's for the steps after."""
    from modpilot.bl import context, toolkit
    from modpilot.core import ops
    src = _armature(resolve(p.source_armature, ctx.config, "source_armature"), "source")
    tgt = _armature(resolve(p.target_armature, ctx.config, "target_armature"), "target")
    x = resolve(p.x_preset, ctx.config, "x_preset")
    y = resolve(p.y_preset, ctx.config, "y_preset")
    toolkit.set_presets(x, y)
    context.select_only([src, tgt], active=tgt)
    ops.run("modder.smart_graft")
    ends = add_missing_end_bones(src, tgt)
    src.hide_viewport = True
    toolkit.set_presets(x_preset=y)
    return {"end_bones_added": ends}


# ── physics_classification ────────────────────────────────────────────────


@dataclass(frozen=True)
class ClassificationParams:
    target_armature: str | None = None


@step("physics_classification", ClassificationParams, needs=("modder",))
def physics_classification(p: ClassificationParams, ctx) -> dict:
    """Refresh the chain_role marks (bones not in the target preset are physics bones) and list the
    chain heads with their depth and parent, for classification."""
    from modpilot.bl import toolkit
    from modpilot.core import ops
    tgt = _armature(resolve(p.target_armature, ctx.config, "target_armature"), "target")
    toolkit.set_presets(x_preset=resolve(None, ctx.config, "y_preset"))
    _pose_mode(tgt)
    ops.run("modder.refresh_physics_bone_colors")
    _object_mode()
    heads = []
    for bone in tgt.data.bones:
        pb = tgt.pose.bones.get(bone.name)
        role = pb.get("chain_role", "") if pb is not None else ""
        if role not in ("head", "branch_head"):
            continue
        depth, cur = 0, bone
        while cur is not None:
            depth += 1
            cont = [c for c in cur.children if tgt.pose.bones.get(c.name) is not None
                    and tgt.pose.bones[c.name].get("chain_role", "") not in ("head", "branch_head")]
            cur = cont[0] if cont else None
        heads.append({"name": bone.name, "role": role, "depth": depth,
                      "parent": bone.parent.name if bone.parent else ""})
    return {"chain_topology": {"chain_heads": heads}}


# ── physics_chains ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChainsParams:
    target_armature: str | None = None
    chain_collection: str = ""
    bones_to_clear: list[str] = field(default_factory=list)
    bones_to_merge: list[str] = field(default_factory=list)
    inferred_types: dict[str, str] = field(default_factory=dict)
    settings_mode: str = "SEPARATE"
    prepare_only: bool = False


def _prepare(tgt) -> None:
    from modpilot.core import ops
    _pose_mode(tgt)
    ops.run("pose.select_all", action="SELECT")
    ops.run("modder.clear_chain_role")
    for pb in tgt.pose.bones:          # clear_chain_role leaves the colours
        pb.color.palette = "DEFAULT"
    ops.run("modder.refresh_physics_bone_colors")
    _object_mode()


def _chain_collection(hint: str, ctx, tgt):
    import bpy

    from modpilot.bl import context
    from modpilot.core import ops
    if hint:
        col = bpy.data.collections.get(hint)
        if col is None or not (".chain" in col.name or ".clsp" in col.name):
            raise StepError("params", f"chain_collection {hint!r} is not a chain collection in this scene")
        return col
    found = None
    for col in bpy.data.collections:
        if ".chain" in col.name or ".clsp" in col.name:
            if col.get("~TYPE") == "RE_CHAIN_COLLECTION":
                return col
            found = found or col
    if found is not None:
        return found
    base = (ctx.config.mesh_collection or "MHWilds_Female.mesh").removesuffix(".mesh")
    context.select_only([tgt], active=tgt)
    ops.run("re_chain.create_chain_header", collectionName=base, chainFormat=".chain2")
    col = bpy.data.collections.get(f"{base}.chain2")
    if col is None:
        raise StepError("postcondition", f"create_chain_header made no {base}.chain2 collection")
    return col


def _apply_separate(cs_names, inferred) -> list[str]:
    """Each settings object gets the type of the chain heads of the groups parented to it; untyped or
    disagreeing heads leave it untouched, reported (no positional fallback: pairing by list position
    gave GG's skirt strands other types' presets)."""
    import bpy

    from modpilot.bl import chains
    skipped = []
    for name in cs_names:
        cs = bpy.data.objects.get(name)
        if cs is None:
            skipped.append(f"{name}.(not found)")
            continue
        heads = [chains.chain_head(g) for g in chains.groups_of(cs)]
        if not heads:
            skipped.append(f"{name}.(untouched: no chain group uses it)")
            continue
        untyped = [h or "<no BoneName>" for h in heads if h not in inferred]
        if untyped:
            skipped.append(f"{name}.(untouched: no inferred_type for chain head {', '.join(untyped)})")
            continue
        types = sorted({inferred[h] for h in heads})
        if len(types) > 1:
            skipped.append(f"{name}.(untouched: chain heads {', '.join(heads)} have conflicting inferred_types "
                           f"{', '.join(types)})")
            continue
        skipped += [f"{name}.{k}" for k in chains.apply_settings(cs, physics.settings_for(types[0]))]
    return skipped


def _apply_shared(canonical: str, col, inferred, ctx) -> tuple[list[str], list[str], dict]:
    """The one shared settings object split into one per inferred type: groups move to their type's
    settings by PARENT, keeping their placement; untyped groups keep the canonical one, untouched."""
    import bpy

    from modpilot.bl import chains, context
    from modpilot.core import ops
    type_to_groups, unmapped = {}, []
    for g in chains.objects_of("RE_CHAIN_CHAINGROUP", within=col):
        head = chains.chain_head(g)
        itype = inferred.get(head)
        if itype:
            type_to_groups.setdefault(itype, []).append(g)
        else:
            unmapped.append(f"{g.name}:{head or '<no BoneName>'}")
    types = sorted(type_to_groups)
    cs_to_type, type_to_cs = {}, {}
    if unmapped:
        cs_to_type[canonical] = ""
        need_new = types
    elif types:
        cs_to_type[canonical], type_to_cs[types[0]] = types[0], canonical
        need_new = types[1:]
    else:
        need_new = []
    if need_new:
        context.object_mode()
        bpy.context.view_layer.objects.active = bpy.data.objects.get(canonical)
        bpy.context.scene.re_chain_toolpanel.chainCollection = col
    for itype in need_new:
        before = {o.name for o in chains.objects_of("RE_CHAIN_CHAINSETTINGS")}
        ops.run("re_chain.create_chain_settings")
        new = [o.name for o in chains.objects_of("RE_CHAIN_CHAINSETTINGS") if o.name not in before]
        if not new:
            raise StepError("postcondition", f"create_chain_settings made no settings object for {itype}")
        type_to_cs[itype], cs_to_type[new[0]] = new[0], itype
    for itype, groups in type_to_groups.items():
        target = bpy.data.objects[type_to_cs[itype]]
        for g in groups:
            if g.parent is not target:
                mw = g.matrix_world.copy()
                g.parent = target
                g.matrix_world = mw
    skipped = []
    for cs_name, itype in cs_to_type.items():
        cs = bpy.data.objects[cs_name]
        if not itype:
            heads = sorted(chains.chain_head(g) or "<no BoneName>" for g in chains.groups_of(cs))
            skipped.append(f"{cs_name}.(untouched: no inferred_type for chain head {', '.join(heads)})")
            continue
        skipped += [f"{cs_name}.{k}" for k in chains.apply_settings(cs, physics.settings_for(itype))]
    if unmapped:
        ctx.warn(f"{len(unmapped)} chain group(s) without an inferred type keep the shared settings, untouched")
    return list(cs_to_type), skipped, {"type_to_settings": type_to_cs, "unmapped": unmapped}


def _angle_ramp(col, ctx) -> int:
    import bpy

    from modpilot.bl import chains, context
    from modpilot.core import ops
    groups = chains.objects_of("RE_CHAIN_CHAINGROUP", within=col)
    if not groups:
        ctx.warn(f"no chain groups in {col.name}: no angle ramp")
        return 0
    context.object_mode()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for g in groups:
        g.select_set(True)
    bpy.context.view_layer.objects.active = groups[-1]
    ops.run("re_chain.apply_angle_limit_ramp", maxAngleLimit=RAMP_MAX_ANGLE, maxIteration=RAMP_ITERATIONS)
    return len(groups)


def _tune_header(col, ctx) -> dict:
    from modpilot.bl import chains
    header_obj = next(iter(chains.objects_of("RE_CHAIN_HEADER", within=col)), None)
    if header_obj is None:
        ctx.warn(f"no chain header in {col.name}: MH Wilds calibration not applied")
        return {"header": None, "skipped": []}
    header, skipped = header_obj.re_chain_header, []
    for attr, val in WILDS_HEADER:
        try:
            setattr(header, attr, val)
        except (AttributeError, TypeError, ValueError):
            skipped.append(attr)
    if skipped:
        ctx.warn(f"chain header fields not set (older RE Chain Editor?): {', '.join(skipped)}")
    return {"header": header_obj.name, "skipped": skipped}


@step("physics_chains", ChainsParams, needs=("modder", "mhws", "re_chain"))
def physics_chains(p: ChainsParams, ctx) -> dict:
    """prepare_only: clear and re-detect the chain_role marks. Otherwise: merge bones into their
    parents (with their '_End' leaves), clear marks on native bones, build the chains
    (mhws.auto_create_chains), give each chain-settings object its type's calibrated values, ramp the
    angle limits, calibrate the chain header for MH Wilds."""
    import bpy

    from modpilot.bl import chains, context, toolkit
    from modpilot.core import ops
    if p.settings_mode not in ("SEPARATE", "SHARED"):
        raise StepError("params", f"settings_mode must be SEPARATE or SHARED, got {p.settings_mode!r}")
    if not p.prepare_only:
        if not p.inferred_types:
            raise StepError("params", "inferred_types must map each chain head to a type")
        unknown = {b: t for b, t in p.inferred_types.items() if physics.params_for(t) is None}
        if unknown:
            raise StepError("params", f"unknown inferred_type(s): {unknown}",
                            details={"unknown": unknown, "known": physics.inferred_types()})
    tgt = _armature(resolve(p.target_armature, ctx.config, "target_armature"), "target")
    if p.prepare_only:
        _prepare(tgt)
        return {"message": PREPARE_MESSAGE}

    # merge (with the '_End' leaves of what is merged), then clear: the merge re-marks colours
    added: list[str] = []
    if p.bones_to_merge:
        merge = list(dict.fromkeys(p.bones_to_merge))
        for name in p.bones_to_merge:
            pb = tgt.pose.bones.get(name)
            for child in (pb.children if pb is not None else []):
                if child.name.endswith("_End") and child.name not in merge:
                    merge.append(child.name)
                    added.append(child.name)
        _pose_mode(tgt)
        missing = chains.select_bones(tgt, merge)
        if missing:
            ctx.warn(f"bones_to_merge not on the armature: {', '.join(missing)}")
        if len(missing) < len(merge):      # with nothing selected the operator returns CANCELLED
            ops.run("modder.merge_into_parent")
        _object_mode()
    if p.bones_to_clear:
        _pose_mode(tgt)
        missing = chains.select_bones(tgt, p.bones_to_clear)
        if missing:
            ctx.warn(f"bones_to_clear not on the armature: {', '.join(missing)}")
        if len(missing) < len(p.bones_to_clear):
            ops.run("modder.clear_chain_role")
        _object_mode()

    # every chain head must lead to an '_End'; a mark without one is reported, not fatal
    def has_end(bone):
        stack = list(bone.children)
        while stack:
            b = stack.pop()
            if b.name.endswith("_End"):
                return True
            stack.extend(b.children)
        return False
    suspicious = [b.name for b in tgt.data.bones if tgt.pose.bones[b.name].get("chain_role", "") in
                  ("head", "branch_head") and not has_end(b)]

    # build the chains
    existing = {o.name for o in chains.objects_of("RE_CHAIN_CHAINSETTINGS")}
    col = _chain_collection(p.chain_collection, ctx, tgt)
    bpy.context.scene.re_chain_toolpanel.chainCollection = col
    toolkit.set_presets(x_preset=resolve(None, ctx.config, "y_preset"))
    _pose_mode(tgt)
    ops.run("mhws.auto_create_chains", settings_mode=p.settings_mode)
    context.object_mode()
    ctx.set_config(chain2_collection=col.name)
    new_cs = [o.name for o in chains.objects_of("RE_CHAIN_CHAINSETTINGS") if o.name not in existing]
    if not new_cs:
        new_cs = [o.name for o in chains.objects_of("RE_CHAIN_CHAINSETTINGS", within=col)]
        ctx.warn(f"auto_create_chains made no new chain settings; applying to the {len(new_cs)} already in {col.name}")

    data = {"chain_collection": col.name, "end_cascade_added": added}
    if p.settings_mode == "SEPARATE":
        final_cs, skipped = new_cs, _apply_separate(new_cs, p.inferred_types)
    else:
        final_cs, skipped, data["consolidation"] = _apply_shared(new_cs[0], col, p.inferred_types, ctx)
    data["chain_groups_ramped"] = _angle_ramp(col, ctx)
    data["header_calibration"] = _tune_header(col, ctx)
    data["chain_settings_created"] = final_cs
    data["skipped_params"] = skipped
    if suspicious:
        data["mark_warning"] = ("Post-merge verification detected chain_role marks on "
                                "bones that lack _End descendants. Chain creation will "
                                "still proceed; inspect bone colors in Blender after the "
                                "phase completes and remove any spurious marks manually.")
        data["marks_without_end"] = suspicious
    return data


# ── physics_adjust ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AdjustParams:
    targets: list[str]
    properties: dict


@step("physics_adjust", AdjustParams)
def physics_adjust(p: AdjustParams, ctx) -> dict:
    """Set chain-settings fields on named chain-settings objects (scalar: number, vector: [x, y, z],
    enum: string int). Every target and field is checked before anything is changed."""
    import bpy
    if not p.targets or not p.properties:
        raise StepError("params", "targets and properties must both be non-empty")
    objs = []
    for name in p.targets:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.get("TYPE") != "RE_CHAIN_CHAINSETTINGS":
            raise StepError("precondition", f"{name!r} is not a chain-settings object", details={"target": name})
        objs.append(obj)
    pg0 = objs[0].re_chain_chainsettings
    unknown = [k for k in p.properties if k not in pg0.bl_rna.properties]
    if unknown:
        raise StepError("params", f"unknown chain-settings field(s): {unknown}", details={"unknown": unknown})
    results = []
    for obj in objs:
        pg = obj.re_chain_chainsettings
        for key, val in p.properties.items():
            cur = getattr(pg, key)
            try:
                if isinstance(val, list) and hasattr(cur, "__len__") and not isinstance(cur, str):
                    for i, v in enumerate(val):
                        cur[i] = v
                else:
                    setattr(pg, key, val)
            except (TypeError, ValueError, IndexError) as exc:
                raise StepError("params", f"{obj.name}.{key} = {val!r}: {exc}",
                                partial={"adjusted_targets": results}) from exc
        results.append(obj.name)
    return {"adjusted_targets": results}
