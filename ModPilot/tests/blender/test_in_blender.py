"""Every in-Blender test file (tests/bl/test_*.py), run in headless Blender 5.2.2 through
modpilot_host.bpytest, so a plain `uv run pytest -m blender` covers them too."""
from pathlib import Path

import pytest

from modpilot_host import bpytest

pytestmark = pytest.mark.blender

BL = Path(__file__).resolve().parents[1] / "bl"
FILES = sorted(BL.glob("test_*.py"))


@pytest.mark.parametrize("version", bpytest.VERSIONS)
@pytest.mark.parametrize("file", FILES, ids=lambda p: p.stem)
def test_in_blender(file, version):
    r = bpytest.run_file(file, version)
    assert r.ok, f"{r.summary}\n{r.tail()}"


def test_a_failing_test_inside_blender_fails_the_run(tmp_path):
    f = tmp_path / "test_fails.py"
    f.write_text("import bpy\n\ndef test_fails():\n    assert bpy.app.version >= (99, 0, 0)\n", encoding="utf-8")
    r = bpytest.run_file(f, "5.2.2")
    assert r.rc == 1 and "1 failed" in r.summary, r.tail()


def test_a_test_file_that_crashes_on_import_fails_the_run(tmp_path):
    f = tmp_path / "test_broken.py"
    f.write_text("import no_such_module\n", encoding="utf-8")
    r = bpytest.run_file(f, "5.2.2")
    assert not r.ok, r.tail()
