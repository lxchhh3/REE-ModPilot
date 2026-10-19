"""Mode and selection, done explicitly. Toolkit and RE Chain Editor operators act on the active
and selected objects; a step sets exactly what an operator needs instead of relying on whatever
was selected (the legacy tools' main source of "works in the GUI, not headless")."""
from __future__ import annotations

from contextlib import contextmanager


def object_mode() -> None:
    import bpy
    if bpy.context.mode != "OBJECT" and bpy.context.view_layer.objects.active is not None:
        bpy.ops.object.mode_set(mode="OBJECT")


def select_only(objects, active=None) -> None:
    """Exactly `objects` selected, `active` (default: the first) active; hidden ones unhidden."""
    import bpy
    object_mode()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objects:
        if o.hide_get():
            o.hide_set(False)
        o.hide_viewport = False
        o.select_set(True)
    bpy.context.view_layer.objects.active = active if active is not None else (objects[0] if objects else None)


@contextmanager
def edit_mode(arm):
    """Edit mode on armature `arm` (unhidden and active for the duration), back to object mode
    after; the previous active object and `arm`'s hide state are restored."""
    import bpy
    object_mode()
    was_active = bpy.context.view_layer.objects.active
    hidden = arm.hide_get()
    arm.hide_set(False)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        yield arm.data.edit_bones
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        arm.hide_set(hidden)
        bpy.context.view_layer.objects.active = was_active
