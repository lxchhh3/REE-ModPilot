"""Where tools-5.2 is, and its pieces the host side reuses: the pinned add-on set, the isolated
per-session Blender profile (compat.runtime) and the headless blender-mcp server
(harness/mcp_headless.py).

tools-5.2 sits beside the REE-ModPilot checkout (Blender-MHWilds/tools-5.2); MODPILOT_TOOLS52
overrides that.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

MODPILOT = Path(__file__).resolve().parents[2]          # .../REE-ModPilot/ModPilot
SRC = MODPILOT / "src" / "modpilot"
BLDEPS = MODPILOT / ".bldeps"


def root() -> Path:
    path = Path(os.environ.get("MODPILOT_TOOLS52") or MODPILOT.parents[1] / "tools-5.2")
    if not (path / "pins.toml").is_file():
        raise FileNotFoundError(f"tools-5.2 not found at {path} (set MODPILOT_TOOLS52)")
    return path


def compat():
    """tools-5.2's `compat` package (imported from the tools-5.2 folder)."""
    r = str(root())
    if r not in sys.path:
        sys.path.insert(0, r)
    import compat
    import compat.config
    import compat.runtime  # noqa: F401
    return compat
