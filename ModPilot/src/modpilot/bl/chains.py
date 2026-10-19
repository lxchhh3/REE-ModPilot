"""RE Chain Editor's scene objects, read the way the editor itself reads them.

A chain group (TYPE RE_CHAIN_CHAINGROUP) belongs to the chain-settings object (TYPE
RE_CHAIN_CHAINSETTINGS) it is PARENTED to (its exporter writes that parent's id as the group's
settingID); its head bone is its first RE_CHAIN_NODE child's "BoneName" constraint subtarget. There
is no 'RE_CHAIN_CHAINNODE' type, no node `parent_bone` and no group `chainSetting` property: the
legacy tools looked those up and got nothing back (ModPilot lesson #55).
"""
from __future__ import annotations

from modpilot import physics


def objects_of(type_name: str, within=None) -> list:
    import bpy
    pool = within.all_objects if within is not None else bpy.data.objects
    return [o for o in pool if o.get("TYPE") == type_name]


def chain_head(group) -> str:
    node = next((c for c in group.children if c.get("TYPE") == "RE_CHAIN_NODE"), None)
    con = node.constraints.get("BoneName") if node is not None else None
    return con.subtarget if con is not None else ""


def groups_of(settings_obj) -> list:
    return [g for g in settings_obj.children if g.get("TYPE") == "RE_CHAIN_CHAINGROUP"]


def apply_settings(settings_obj, values: dict) -> list[str]:
    """Set chain-settings fields; returns the keys that could not be set (reported, not dropped)."""
    pg = settings_obj.re_chain_chainsettings
    failed = []
    for key, val in values.items():
        if isinstance(val, list):
            val = tuple(val)
        if key in physics.ENUM_FIELDS:
            val = str(int(val))
        try:
            setattr(pg, key, val)
        except (AttributeError, TypeError, ValueError):
            failed.append(key)
    return failed


def select_bones(arm, names) -> list[str]:
    """In pose mode on `arm`: select exactly the bones named; returns the names not found. Blender 4
    keeps pose selection on Bone, Blender 5 on PoseBone (Blender-MHWilds lesson #9)."""
    import bpy
    bpy.ops.pose.select_all(action="DESELECT")
    missing = []
    for name in names:
        pb = arm.pose.bones.get(name)
        if pb is None:
            missing.append(name)
        elif hasattr(pb, "select"):
            pb.select = True
        else:
            pb.bone.select = True
    return missing
