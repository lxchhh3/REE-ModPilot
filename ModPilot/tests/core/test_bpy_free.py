"""The parts of modpilot that run on the host as well as in Blender never import Blender's
modules, so they can be tested here in seconds; `modpilot/__init__.py` imports them only inside
the functions that need Blender, so `import modpilot.core.params` works on the host."""
import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[2] / "src" / "modpilot"
BLENDER_MODULES = {"bpy", "mathutils", "bmesh", "addon_utils", "bpy_extras", "gpu", "idprop"}
PURE = ["core/errors.py", "core/params.py", "core/report.py", "core/step.py", "core/config.py", "presets.py",
        "datafiles.py", "physics.py", "colliders.py"]
PURE_PACKAGES = ["formats", "geom", "checks"]


def _imports(tree, top_level_only):
    nodes = tree.body if top_level_only else list(ast.walk(tree))
    for node in nodes:
        if isinstance(node, ast.Import):
            yield from (a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module.split(".")[0]


def _pure_files():
    files = [SRC / f for f in PURE]
    for pkg in PURE_PACKAGES:
        files += sorted((SRC / pkg).rglob("*.py")) if (SRC / pkg).is_dir() else []
    return files


@pytest.mark.parametrize("path", _pure_files(), ids=lambda p: p.relative_to(SRC).as_posix())
def test_pure_modules_never_import_blender(path):
    found = BLENDER_MODULES & set(_imports(ast.parse(path.read_text(encoding="utf-8")), False))
    assert not found, f"{path.name} imports {found}"


def test_the_package_root_imports_blender_only_inside_functions():
    tree = ast.parse((SRC / "__init__.py").read_text(encoding="utf-8"))
    assert not BLENDER_MODULES & set(_imports(tree, True))


@pytest.mark.parametrize("path", sorted((SRC / "steps").glob("*.py")), ids=lambda p: p.name)
def test_steps_import_blender_only_inside_functions(path):
    """So the host can import the registry: check params, describe steps, before sending anything."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not BLENDER_MODULES & set(_imports(tree, True)), path.name
