"""The Modding-Toolkit add-on as the steps see it: its X-preset folder and its preset settings."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from modpilot.core.errors import StepError

_ADDON_DIR_NAMES = ("Modding-Toolkit", "Modding-Toolkit-main", "Modder_Batch_Tool-main")


def preset_dir() -> Path:
    """The Toolkit's assets/presets/import folder: found from a loaded module of the add-on, else
    under the add-on folders of Blender's script paths."""
    import bpy
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None)
        if f:
            p = Path(os.path.dirname(os.path.abspath(f))) / "assets" / "presets" / "import"
            if p.is_dir():
                return p
    for scripts in bpy.utils.script_paths():
        for name in _ADDON_DIR_NAMES:
            p = Path(scripts) / "addons" / name / "assets" / "presets" / "import"
            if p.is_dir():
                return p
    raise StepError("environment", "the Modding-Toolkit's X-preset folder was not found "
                                   "(is the Modding-Toolkit add-on enabled?)")


def set_presets(x_preset: str | None = None, y_preset: str | None = None) -> None:
    """Set the Toolkit's source (X) and target (Y) preset enums, as its panel does."""
    import bpy
    settings = bpy.context.scene.mhw_suite_settings
    try:
        if x_preset is not None:
            settings.import_preset_enum = f"{x_preset}.json"
        if y_preset is not None:
            settings.target_preset_enum = f"{y_preset}.json"
    except TypeError as exc:
        raise StepError("params", f"the Toolkit has no such preset: {exc}",
                        details={"x_preset": x_preset, "y_preset": y_preset}) from exc
