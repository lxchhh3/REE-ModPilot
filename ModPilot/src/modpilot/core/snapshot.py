"""What a step changed in the scene, at the level the legacy SceneState.diff reported it:
objects added / removed, and object / material counts (same keys, so call logs read alike)."""
from __future__ import annotations


def take() -> dict:
    import bpy
    return {"objects": sorted(o.name for o in bpy.data.objects), "materials": len(bpy.data.materials)}


def diff(before: dict, after: dict) -> dict:
    out: dict = {}
    if len(before["objects"]) != len(after["objects"]):
        out["object_count"] = {"before": len(before["objects"]), "after": len(after["objects"])}
    added = sorted(set(after["objects"]) - set(before["objects"]))
    removed = sorted(set(before["objects"]) - set(after["objects"]))
    if added:
        out["objects_added"] = added
    if removed:
        out["objects_removed"] = removed
    if before["materials"] != after["materials"]:
        out["materials_count"] = {"before": before["materials"], "after": after["materials"]}
    return out
