"""RE Chain Editor's and RE Mesh Editor's own file modules (chain2, clsp, mesh, mdf, tex, ...), bpy-free.

Inside Blender they come from the enabled add-on; outside it from tools-5.2's pinned clones, each
editor under its own package name ("rechain", "remesh") so the two "modules" packages never collide
(Blender-MHWilds lesson #74) and the add-ons' __init__ (which needs bpy) never runs. The build scripts
had five copies of this (og_collar/collar_lib.py, marette/meshio.py, gg/relocate_slot.py,
marette/gpuc/gpuc_skirt.py, marette/rebuild/tests/mrcheck.py).

    module("chain", "file_re_chain2"), module("chain", "file_re_clsp"), module("chain", "pymmh3")
    module("mesh", "mesh.file_re_mesh"), module("mesh", "mesh.re_mesh_parse"), module("mesh", "mdf.file_re_mdf")
"""
from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path

from modpilot.core.errors import StepError

# editor -> (clone folder under tools-5.2/upstream, private package name, a module only that editor has)
EDITORS = {"chain": ("RE-Chain-Editor", "rechain", "modules.file_re_chain2"),
           "mesh": ("RE-Mesh-Editor-BlendShape", "remesh", "modules.mesh.file_re_mesh")}
_LOADED: dict[tuple[str, str], types.ModuleType] = {}


def tools52() -> Path:
    """tools-5.2 (MODPILOT_TOOLS52, or the sibling of the REE-ModPilot checkout)."""
    env = os.environ.get("MODPILOT_TOOLS52")
    return Path(env) if env else Path(__file__).resolve().parents[5] / "tools-5.2"


def _addon_root(marker: str, private: str) -> str | None:
    """The package of an editor the running Blender has loaded (its marker module imported), preferring
    the enabled add-on over a private clone package."""
    roots = [name[: -len(marker) - 1] for name in list(sys.modules) if name.endswith("." + marker)]
    roots.sort(key=lambda r: r == private)
    return roots[0] if roots else None


def _private_root(folder: str, private: str) -> str:
    if private not in sys.modules:
        clone = tools52() / "upstream" / folder
        if not clone.is_dir():
            raise StepError("environment", f"{folder} is neither loaded nor at {clone}")
        pkg = types.ModuleType(private)
        pkg.__path__ = [str(clone)]
        sys.modules[private] = pkg
    return private


def module(editor: str, rel: str) -> types.ModuleType:
    """The editor's module `modules.<rel>` (rel like "file_re_chain2" or "mdf.file_re_mdf")."""
    if editor not in EDITORS:
        raise StepError("params", f"unknown editor {editor!r}; known: {sorted(EDITORS)}")
    key = (editor, rel)
    if key not in _LOADED:
        folder, private, marker = EDITORS[editor]
        root = _addon_root(marker, private) or _private_root(folder, private)
        _LOADED[key] = importlib.import_module(f"{root}.modules.{rel}")
    return _LOADED[key]


def hash_name(name: str) -> int:
    """RE Engine's name hash (murmur3, wide), as chain2 / clsp files store bone names."""
    return module("chain", "pymmh3").hash_wide(name)
