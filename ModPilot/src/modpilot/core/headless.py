"""Make a background Blender safe for the pinned add-ons.

Two add-on behaviours crash `blender --background` (Blender-MHWilds lessons #5 and #7):
RE Mesh Editor's `showConsole` preference wraps imports in `wm.console_toggle`, and add-on
popups end in UI_popup_menu_end. In background mode this turns the preference off and installs
the popup recorders for the session; with a UI it does nothing.
"""
from __future__ import annotations


def ensure_background_safe() -> dict:
    import bpy

    from modpilot.core import popups
    if not bpy.app.background:
        return {"background": False}
    consoles = []
    for addon in bpy.context.preferences.addons:
        prefs = getattr(addon, "preferences", None)
        if prefs is not None and hasattr(prefs, "showConsole"):
            prefs.showConsole = False
            consoles.append(addon.module)
    return {"background": True, "show_console_off": consoles, "popup_helpers": popups.install_background_guard()}
