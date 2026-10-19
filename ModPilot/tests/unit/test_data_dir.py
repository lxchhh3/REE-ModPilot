"""The legacy app reads its catalogs from the modpilot package's data folder, the only copy."""
from pathlib import Path

from app.resources import app_data_dir

SRC_DATA = Path(__file__).resolve().parents[2] / "src" / "modpilot" / "data"


def test_the_legacy_app_reads_the_package_data():
    assert app_data_dir() == SRC_DATA
    for name in ("physics_presets.json", "clsp_body_bits.json", "full_body.clsp.3", "armor_sets.json"):
        assert (app_data_dir() / name).is_file(), name


def test_there_is_no_second_copy():
    assert not (Path(__file__).resolve().parents[2] / "app" / "data").exists()
