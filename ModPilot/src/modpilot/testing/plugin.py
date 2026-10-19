"""pytest plugin for the tests that run inside Blender (loaded by tests/bl/_boot.py with -p).

- at session start in background mode: RE Mesh Editor's console toggle off, add-on popups
  recorded instead of shown (both crash --background; modpilot.core.headless)
- before every test: an empty scene (`wm.read_homefile(use_empty=True)`, which keeps the enabled
  add-ons and their operators: probed in 4.3.0 and 5.2.2, 2026-10-19)
"""
from __future__ import annotations

import pytest


def pytest_sessionstart(session):
    from modpilot.core import headless
    headless.ensure_background_safe()


@pytest.fixture(autouse=True)
def empty_scene():
    import bpy
    if bpy.context.mode != "OBJECT" and bpy.context.object is not None:
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.wm.read_homefile(use_empty=True)
    yield
