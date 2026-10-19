"""modpilot.presets: the Modding-Toolkit X-preset catalog and the two preset writers, bpy-free
(the legacy app/blender/preset_catalog.py + app/phases/preset_write.py, whose unit tests these
carry over). Changes from the legacy code: a preset file that can't be read is reported instead of
skipped silently, and a slot whose `main` isn't a list is repaired in the right key (the legacy
writer assigned it to slot[slot_key])."""
import json
from pathlib import Path

import pytest

from modpilot.core.errors import StepError
from modpilot.presets import (
    OPTIONAL_SLOTS,
    PresetMeta,
    compute_coverage,
    decide,
    enumerate_x_presets,
    pick_best_preset,
    write_custom,
    write_supplement,
)

pytestmark = pytest.mark.unit


def _write(folder: Path, name: str, body) -> Path:
    p = folder / f"{name}.json"
    p.write_text(body if isinstance(body, str) else json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def preset_dir(tmp_path: Path) -> Path:
    _write(tmp_path, "MMD", {"preset_info": {"name": "MMD", "type": "X_PRESET"}, "exclude": ["センター"],
                             "mappings": {"pelvis": {"main": ["Hips", "下半身"], "aux": []},
                                          "spine_01": {"main": ["Spine", "上半身"], "aux": []},
                                          "head": {"main": ["Head", "頭"], "aux": []}}})
    _write(tmp_path, "VRChat", {"preset_info": {"name": "VRChat", "type": "X_PRESET"},
                                "mappings": {"pelvis": {"main": ["Hips"], "aux": []},
                                             "spine_01": {"main": ["Spine"], "aux": []},
                                             "head": {"main": ["Head"], "aux": []}}})
    _write(tmp_path, "OneSlot", {"preset_info": {"name": "OneSlot", "type": "X_PRESET"},
                                 "mappings": {"pelvis": {"main": ["root"], "aux": []}}})
    _write(tmp_path, "NotAnX", {"preset_info": {"name": "NotAnX", "type": "Y_PRESET"},
                                "mappings": {"pelvis": {"main": ["Hips"], "aux": []}}})
    _write(tmp_path, "broken", "{not valid json")
    return tmp_path


# ── catalog ───────────────────────────────────────────────────────────────


def test_only_x_presets_load_and_an_unreadable_file_is_reported(preset_dir):
    catalog, unreadable = enumerate_x_presets(preset_dir)
    assert sorted(catalog) == ["MMD", "OneSlot", "VRChat"]
    assert catalog["MMD"].exclude == ["センター"] and catalog["MMD"].path == preset_dir / "MMD.json"
    assert [Path(u["path"]).name for u in unreadable] == ["broken.json"]


def test_a_missing_folder_is_an_environment_error(tmp_path):
    with pytest.raises(StepError) as e:
        enumerate_x_presets(tmp_path / "nope")
    assert e.value.category == "environment"


def _meta(name, mappings):
    return PresetMeta(name=name, path=Path(f"{name}.json"), mappings=mappings)


def test_coverage_full_partial_and_none():
    p = _meta("P", {"pelvis": {"main": ["Hips"]}, "spine_01": {"main": ["Spine"]}, "head": {"main": ["Head"]}})
    full = compute_coverage(p, {"Hips", "Spine", "Head", "Extra"})
    assert (full.coverage, full.covered_slots) == (1.0, {"pelvis": "Hips", "spine_01": "Spine", "head": "Head"})
    part = compute_coverage(p, {"Hips"})
    assert part.coverage == pytest.approx(1 / 3) and sorted(part.uncovered_slots) == ["head", "spine_01"]
    assert compute_coverage(p, {"X"}).coverage == 0.0


def test_coverage_matches_exact_then_normalised_then_aux():
    p = _meta("P", {"pelvis": {"main": ["Hip_s"], "aux": ["Root"]}, "head": {"main": ["Nope"], "aux": ["Head"]}})
    r = compute_coverage(p, {"hips", "Head"})
    assert r.covered_slots == {"pelvis": "hips", "head": "Head"}


def test_a_malformed_slot_is_uncovered_and_an_absent_optional_slot_does_not_count():
    assert "spine_03" in OPTIONAL_SLOTS
    p = _meta("P", {"pelvis": "Hips", "head": {"main": ["Head"]}, "spine_03": {"main": ["Chest2"]}})
    r = compute_coverage(p, {"Head"})
    assert r.uncovered_slots == ["pelvis"] and r.optional_skipped == ["spine_03"] and r.total_slots == 2


def test_pick_best_is_highest_coverage_ties_by_name():
    a = _meta("A", {"pelvis": {"main": ["Hips"]}})
    b = _meta("B", {"pelvis": {"main": ["Hips"]}})
    c = _meta("C", {"pelvis": {"main": ["Root"]}})
    winner, reports = pick_best_preset([c, b, a], {"Hips"})
    assert winner.preset_name == "A" and [r.preset_name for r in reports] == ["A", "B", "C"]
    assert pick_best_preset([], {"Hips"}) == (None, [])


@pytest.mark.parametrize("coverage,decision", [(1.0, "exact"), (0.8, "supplement"), (0.99, "supplement"),
                                               (0.79, "custom"), (0.01, "custom"), (0.0, "unsupported")])
def test_the_decision_thresholds(coverage, decision):
    assert decide(coverage) == decision


# ── writers ───────────────────────────────────────────────────────────────


def test_supplement_writes_extended_beside_the_base_and_never_touches_it(preset_dir):
    before = (preset_dir / "VRChat.json").read_bytes()
    out = write_supplement(preset_dir, "VRChat", {"head": "Kopf", "upperarm_L": "Arm.L"})
    assert (preset_dir / "VRChat.json").read_bytes() == before
    data = json.loads((preset_dir / "VRChat_extended.json").read_text(encoding="utf-8"))
    assert data["mappings"]["head"]["main"] == ["Head", "Kopf"]
    assert data["mappings"]["upperarm_L"] == {"main": ["Arm.L"], "aux": []}
    assert data["preset_info"]["derived_from"] == "VRChat" and data["preset_info"]["type"] == "X_PRESET"
    assert out["new_preset_name"] == "VRChat_extended" and out["added_slots"] == ["upperarm_L"]
    assert out["added_candidates"] == [{"slot": "head", "bone": "Kopf"}, {"slot": "upperarm_L", "bone": "Arm.L"}]


def test_supplement_merges_into_an_existing_extended_without_duplicates(preset_dir):
    write_supplement(preset_dir, "VRChat", {"head": "Kopf"})
    out = write_supplement(preset_dir, "VRChat", {"head": "Kopf", "pelvis": "Becken"})
    data = json.loads((preset_dir / "VRChat_extended.json").read_text(encoding="utf-8"))
    assert data["mappings"]["head"]["main"] == ["Head", "Kopf"]
    assert data["mappings"]["pelvis"]["main"] == ["Hips", "Becken"]
    assert out["added_candidates"] == [{"slot": "pelvis", "bone": "Becken"}]


def test_supplement_repairs_a_main_that_is_not_a_list(preset_dir):
    _write(preset_dir, "Odd", {"preset_info": {"type": "X_PRESET"}, "mappings": {"head": {"main": "Head"}}})
    write_supplement(preset_dir, "Odd", {"head": "Kopf"})
    data = json.loads((preset_dir / "Odd_extended.json").read_text(encoding="utf-8"))
    assert data["mappings"]["head"]["main"] == ["Head", "Kopf"] and "head" not in data["mappings"]["head"]


@pytest.mark.parametrize("base,mappings,category", [
    ("Missing", {"head": "H"}, "precondition"),
    ("VRChat", {}, "params"),
    ("VRChat", {"head": 3}, "params"),
    ("VRChat", {"head": "  "}, "params"),
    ("../evil", {"head": "H"}, "params"),
])
def test_supplement_refusals(preset_dir, base, mappings, category):
    with pytest.raises(StepError) as e:
        write_supplement(preset_dir, base, mappings)
    assert e.value.category == category
    assert not list(preset_dir.glob("*_extended.json"))


def test_custom_writes_a_new_preset_and_overwrites_its_own_file(preset_dir):
    out = write_custom(preset_dir, "Maya", {"pelvis": "Hips", "head": "Head"})
    data = json.loads((preset_dir / "Maya_custom.json").read_text(encoding="utf-8"))
    assert data["preset_info"]["type"] == "X_PRESET" and "Maya" in data["preset_info"]["description"]
    assert data["mappings"] == {"pelvis": {"main": ["Hips"], "aux": []}, "head": {"main": ["Head"], "aux": []}}
    assert out == {"new_preset_name": "Maya_custom", "new_preset_path": str(preset_dir / "Maya_custom.json"),
                   "character_name": "Maya", "slot_count": 2}
    write_custom(preset_dir, "Maya", {"pelvis": "Root"}, description="v2")
    data = json.loads((preset_dir / "Maya_custom.json").read_text(encoding="utf-8"))
    assert data["mappings"] == {"pelvis": {"main": ["Root"], "aux": []}} and data["preset_info"]["description"] == "v2"


@pytest.mark.parametrize("name,mappings", [("", {"a": "b"}), ("Maya", {}), ("a/b", {"a": "b"})])
def test_custom_refusals(preset_dir, name, mappings):
    with pytest.raises(StepError) as e:
        write_custom(preset_dir, name, mappings)
    assert e.value.category == "params"
