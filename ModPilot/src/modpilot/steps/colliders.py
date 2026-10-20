"""Phase 4C (plan.md video 4): body colliders and the chain groups' collision masks. Ported from the
legacy app/phases/physics_colliders.py.

collider_create imports ModPilot's full_body.clsp.3 through RE Chain Editor's re_clsp.importfile,
bound to the MH Wilds armature by name (after physics_chains the avatar's armature is in the scene
too, and the editor cancels on "More than one armature"), then lists the chain groups to classify.
collider_apply writes the agreed clspFlags0/1.

Changes from the legacy tools (no silent paths): a chain_collection hint that isn't a collection
fails (it was ignored); collider_apply checks every entry and every group before writing any
(unknown groups were reported under not_found after the others were written, a failed clspFlags1
under errors); the imported collection is recorded in the scene config.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modpilot import colliders, datafiles
from modpilot.core.config import resolve
from modpilot.core.errors import StepError
from modpilot.core.step import step

COLLIDER_TYPE_PREFIX = "RE_CHAIN_COLLISION"


def _armature(name: str):
    import bpy
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "ARMATURE":
        raise StepError("precondition", f"target armature {name!r} not found (or not an ARMATURE)")
    return obj


def _collider_objects() -> set[str]:
    import bpy
    return {o.name for o in bpy.data.objects if (o.get("TYPE") or "").startswith(COLLIDER_TYPE_PREFIX)}


def chain_groups(hint: str = "") -> list[dict]:
    """Every chain group (within collection `hint` when given) with its head bone and masks."""
    import bpy

    from modpilot.bl import chains
    if hint:
        col = bpy.data.collections.get(hint)
        if col is None:
            raise StepError("params", f"chain_collection {hint!r} is not a collection in this scene")
        pool = chains.objects_of("RE_CHAIN_CHAINGROUP", within=col)
    else:
        pool = chains.objects_of("RE_CHAIN_CHAINGROUP")
    names = {o.name for o in pool}
    out = []
    for o in bpy.data.objects:          # bpy.data order, as the legacy scan listed them
        if o.name not in names:
            continue
        pg = o.re_chain_chaingroup
        out.append({"name": o.name, "parent_bone": chains.chain_head(o),
                    "clspFlags0": int(pg.clspFlags0), "clspFlags1": int(pg.clspFlags1)})
    return out


@dataclass(frozen=True)
class CreateParams:
    target_armature: str | None = None
    chain_collection: str = ""


@step("collider_create", CreateParams, needs=("re_clsp",))
def collider_create(p: CreateParams, ctx) -> dict:
    """Import full_body.clsp.3 (one capsule/sphere per MH Wilds body bone, CHILD_OF its bone) onto
    the target armature; list the new colliders and the chain groups."""
    import bpy

    from modpilot.bl import context
    from modpilot.core import ops
    arm = _armature(resolve(p.target_armature, ctx.config, "target_armature"))
    if p.chain_collection and bpy.data.collections.get(p.chain_collection) is None:
        raise StepError("params", f"chain_collection {p.chain_collection!r} is not a collection in this scene")
    before = _collider_objects()
    context.object_mode()
    ops.run("re_clsp.importfile", filepath=str(datafiles.path("full_body.clsp.3")), targetArmature=arm.data.name)
    found = []
    for o in bpy.data.objects:
        t = o.get("TYPE") or ""
        if not t.startswith(COLLIDER_TYPE_PREFIX) or o.name in before:
            continue
        bone = next((c.subtarget for c in o.constraints if c.type == "CHILD_OF" and c.subtarget), "")
        found.append({"name": o.name, "bone": bone, "type": t.replace(COLLIDER_TYPE_PREFIX + "_", "") or "SHAPE"})
    if not found:
        raise StepError("postcondition", "re_clsp.importfile finished but created no colliders")
    # a capsule's root carries no bone; its start and end spheres are CHILD_OF theirs
    unbound = [c["name"] for c in found if not c["type"].endswith("_ROOT") and c["bone"] not in arm.data.bones]
    if unbound:
        ctx.warn(f"{len(unbound)} collider(s) not bound to a bone of {arm.name}: {', '.join(unbound[:5])}")
    first = bpy.data.objects[found[0]["name"]]
    clsp_col = first.users_collection[0].name if first.users_collection else ""
    if clsp_col:
        ctx.set_config(clsp_collection=clsp_col)
    return {"collider_info": {"colliders": found, "chain_groups": chain_groups(p.chain_collection),
                              "clsp_collection": clsp_col}}


@dataclass(frozen=True)
class ApplyParams:
    chain_flags: dict[str, Any]
    # accepted because the call logs pass it (claude_run1 call 15); checked, not otherwise used
    target_armature: str | None = None


@step("collider_apply", ApplyParams)
def collider_apply(p: ApplyParams, ctx) -> dict:
    """Write clspFlags0 / clspFlags1 onto each named chain group: an int is clspFlags0 (clspFlags1
    0), a dict gives both; 0 turns the group's collisions off. Masks use only the collider bits of
    data/clsp_body_bits.json."""
    import bpy
    if not p.chain_flags:
        raise StepError("params", "chain_flags must map chain-group names to masks (call collider_create first)")
    if p.target_armature is not None:
        _armature(p.target_armature)
    pairs, bad = {}, []
    for name, value in p.chain_flags.items():
        pair = colliders.flag_pair(value)
        if pair is None:
            bad.append(f"{name!r}={value!r}")
        else:
            pairs[name] = pair
    if bad:
        raise StepError("params", f"invalid chain_flags entries (an int using only the collider bits "
                        f"0x{colliders.FULL_MASK:X}, or a dict with clspFlags0/1): {', '.join(bad)}",
                        details={"invalid": bad})
    missing = [n for n in pairs if (bpy.data.objects.get(n) is None
                                    or bpy.data.objects[n].get("TYPE") != "RE_CHAIN_CHAINGROUP")]
    if missing:
        raise StepError("precondition", f"not chain groups in this scene: {missing}", details={"not_found": missing})
    applied = []
    for name, (f0, f1) in pairs.items():
        pg = bpy.data.objects[name].re_chain_chaingroup
        pg.clspFlags0, pg.clspFlags1 = f0, f1
        applied.append({"name": name, "clspFlags0": f0, "clspFlags1": f1, "status": "ok"})
    return {"applied": applied}
