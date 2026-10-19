"""Read-only query steps (the legacy app/phases/query_tools.py, as data instead of JSON strings)."""
from __future__ import annotations

from dataclasses import dataclass

from modpilot.core.step import step


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
