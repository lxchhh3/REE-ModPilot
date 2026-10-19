"""Add-on popups, captured.

RE Mesh Editor, RE Chain Editor and the Toolkit report problems through module-level
`showMessageBox` / `showErrorMessageBox` helpers. In background mode those crash Blender
(ACCESS_VIOLATION in UI_popup_menu_end, Blender-MHWilds lesson #7), and in the GUI they are the
only place an operator says why it did nothing.

Every such helper loaded in Blender is replaced by a recorder that reports to the captures active
at that moment. `capture()` (around every modpilot call) installs recorders that still show the
popup when Blender has a UI and restores the helpers afterwards; `install_background_guard()`
installs silent recorders for a whole headless session, which report to captures just the same.
An error popup recorded during a call fails the call (modpilot.core.runtime).
"""
from __future__ import annotations

import sys
from contextlib import contextmanager

NAMES = ("showMessageBox", "showErrorMessageBox")
_ACTIVE: list = []          # the captures currently open (innermost last)


class Capture:
    def __init__(self) -> None:
        self.records: list[dict] = []

    @property
    def errors(self) -> list[dict]:
        return [r for r in self.records if r["kind"] == "error"]


def _helpers():
    for mod in list(sys.modules.values()):
        d = getattr(mod, "__dict__", None)
        if not isinstance(d, dict):
            continue
        for name in NAMES:
            fn = d.get(name)
            if callable(fn) and not getattr(fn, "_modpilot_recorder", False):
                yield mod, name, fn


def _recorder(mod_name, name, original, forward):
    def record(*args, **kwargs):
        message = kwargs.get("message", args[0] if args else "")
        title = kwargs.get("title", args[1] if len(args) > 1 else "")
        icon = kwargs.get("icon", args[2] if len(args) > 2 else "")
        kind = "error" if name == "showErrorMessageBox" or str(icon).upper() == "ERROR" else "info"
        entry = {"kind": kind, "message": str(message), "title": str(title), "module": mod_name}
        # looked up when the popup fires: a reload of modpilot replaces this module, and a guard
        # recorder installed before it must report to the captures of the module now loaded
        current = sys.modules.get(__name__)
        for cap in getattr(current, "_ACTIVE", ()):
            cap.records.append(entry)
        if forward:
            return original(*args, **kwargs)
        return None
    record._modpilot_recorder = True
    return record


@contextmanager
def capture(forward: bool | None = None):
    """Record every add-on popup raised inside the block; restore the helpers patched here.
    `forward` (default: when Blender has a UI) also shows them."""
    import bpy
    if forward is None:
        forward = not bpy.app.background
    cap = Capture()
    patched = []
    for mod, name, fn in _helpers():
        mod.__dict__[name] = _recorder(mod.__name__, name, fn, forward)
        patched.append((mod, name, fn))
    _ACTIVE.append(cap)
    try:
        yield cap
    finally:
        _ACTIVE.remove(cap)
        for mod, name, fn in patched:
            mod.__dict__[name] = fn


def install_background_guard() -> int:
    """For a headless session: replace every popup helper for good (never shown; still reported
    to the active captures). Returns how many were replaced. Call again after enabling add-ons."""
    n = 0
    for mod, name, fn in _helpers():
        mod.__dict__[name] = _recorder(mod.__name__, name, fn, False)
        n += 1
    return n
