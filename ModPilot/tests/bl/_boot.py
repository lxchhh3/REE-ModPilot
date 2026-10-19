"""Runs INSIDE Blender (started by modpilot_host.bpytest): enables the pinned add-ons, then runs
pytest in Blender's own Python and exits Blender with pytest's exit code (sys.exit sets Blender's
exit code; probed in 4.3.0 and 5.2.2, 2026-10-19).

    blender -b --factory-startup --python tests/bl/_boot.py -- <pytest args>

env: MODPILOT_BLDEPS  the folder holding pure-python pytest (ModPilot/.bldeps)
     MODPILOT_ADDONS  JSON list of add-on modules to enable
The modpilot package itself is importable through the session's junction
(<user scripts>/addons/modules/modpilot, tools-5.2 compat.runtime.link_modpilot).
"""
import json
import os
import sys

import addon_utils

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
sys.path.insert(0, os.environ["MODPILOT_BLDEPS"])
failed = [m for m in json.loads(os.environ.get("MODPILOT_ADDONS", "[]"))
          if addon_utils.enable(m, default_set=True) is None]
if failed:
    print("MODPILOT_BOOT_ERROR=" + json.dumps({"addons_not_enabled": failed}))
    sys.exit(3)

import pytest  # noqa: E402

sys.exit(int(pytest.main(args + ["-p", "modpilot.testing.plugin"])))
