"""The Modding-Toolkit X-preset catalog and the two preset writers. bpy-free: the steps in
modpilot.steps.setup pass in the Toolkit's preset folder (modpilot.bl.toolkit.preset_dir).

Each X-preset JSON declares preset_info (type "X_PRESET"), an exclude list and mappings
{standard_key: {"main": [candidate bone names], "aux": [...]}}. Coverage of a preset against a
source rig mirrors the Toolkit's own matching (bone_mapper.get_matches_for_standard): exact, then
separator/case-normalised, `main` before `aux`; the first candidate present in the rig wins.

Ported from the legacy app/blender/preset_catalog.py and app/phases/preset_write.py. Changes: an
unreadable preset file is reported (it was skipped silently), the extended preset's name no longer
grows " (extended)" on every merge, and a slot whose `main` is not a list is repaired under "main"
(the legacy writer assigned it to slot[slot_key]).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from modpilot.core.errors import StepError

# Slots the target skeleton rarely or never has (no UpperChest in the RE rigs): an unmatched one
# is left out of the coverage denominator.
OPTIONAL_SLOTS = frozenset({"spine_03"})
THRESHOLD_EXACT = 1.0
THRESHOLD_SUPPLEMENT = 0.80
_VALID_STEM = re.compile(r"^[\w一-鿿\- ]+$")       # word chars / CJK / hyphen / space


@dataclass
class PresetMeta:
    name: str
    path: Path
    mappings: dict
    exclude: list = field(default_factory=list)
    description: str = ""


@dataclass
class CoverageReport:
    preset_name: str
    coverage: float
    covered_slots: dict
    uncovered_slots: list
    total_slots: int
    optional_skipped: list = field(default_factory=list)


def decide(coverage: float) -> str:
    """exact (100%) | supplement (80-99%: extend that preset) | custom (1-79%: a new preset) |
    unsupported (no slot matched)."""
    if coverage >= THRESHOLD_EXACT:
        return "exact"
    if coverage >= THRESHOLD_SUPPLEMENT:
        return "supplement"
    if coverage > 0:
        return "custom"
    return "unsupported"


def enumerate_x_presets(preset_dir: Path) -> tuple[dict[str, PresetMeta], list[dict]]:
    """({name: PresetMeta} of every X-preset in the folder, [{path, why}] of files that could not
    be read). Y-presets (e.g. sf6.json, which lives in the import folder) are not X-presets."""
    preset_dir = Path(preset_dir)
    if not preset_dir.is_dir():
        raise StepError("environment", f"the Toolkit's X-preset folder {preset_dir} does not exist",
                        details={"preset_dir": str(preset_dir)})
    catalog: dict[str, PresetMeta] = {}
    unreadable: list[dict] = []
    for p in sorted(preset_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            unreadable.append({"path": str(p), "why": str(exc)[:200]})
            continue
        info = data.get("preset_info") if isinstance(data, dict) else None
        if not isinstance(info, dict) or info.get("type") != "X_PRESET":
            continue
        mappings = data.get("mappings")
        if not isinstance(mappings, dict) or not mappings:
            unreadable.append({"path": str(p), "why": "no mappings"})
            continue
        catalog[p.stem] = PresetMeta(p.stem, p, mappings, list(data.get("exclude") or []),
                                     str(info.get("description") or ""))
    return catalog, unreadable


def _normalize(name: str) -> str:
    return re.sub(r"[_.\s]", "", name).lower()


def compute_coverage(preset: PresetMeta, source_bones: set[str]) -> CoverageReport:
    lookup: dict[str, str] = {}
    for b in sorted(source_bones):
        lookup.setdefault(_normalize(b), b)

    def find(name):
        if name in source_bones:
            return name
        return lookup.get(_normalize(name))

    covered, uncovered, optional = {}, [], []
    for key, slot in preset.mappings.items():
        match = None
        if isinstance(slot, dict):
            for cand in [*(slot.get("main") or []), *(slot.get("aux") or [])]:
                if isinstance(cand, str) and (match := find(cand)):
                    break
        if match:
            covered[key] = match
        elif key in OPTIONAL_SLOTS:
            optional.append(key)
        else:
            uncovered.append(key)
    total = len(preset.mappings) - len(optional)
    return CoverageReport(preset.name, (len(covered) / total) if total else 0.0, covered, uncovered, total, optional)


def pick_best_preset(presets, source_bones: set[str]):
    """(winner, all reports by coverage desc, ties by name)."""
    reports = sorted((compute_coverage(p, source_bones) for p in presets), key=lambda r: (-r.coverage, r.preset_name))
    return (reports[0] if reports else None), reports


# ── writers ───────────────────────────────────────────────────────────────


def _stem(stem: str) -> str:
    if not stem or stem in (".", "..") or "/" in stem or "\\" in stem or not _VALID_STEM.match(stem):
        raise StepError("params", f"preset name {stem!r} is not a plain file name "
                                  "(letters, digits, underscore, hyphen, space, CJK)", details={"name": stem})
    return stem


def _check_mappings(mappings) -> dict:
    if not isinstance(mappings, dict) or not mappings:
        raise StepError("params", "mappings must be a non-empty {slot: bone name} object")
    bad = [k for k, v in mappings.items() if not isinstance(v, str) or not v.strip()]
    if bad:
        raise StepError("params", f"each mapping must be a non-empty bone name; not: {bad}", details={"slots": bad})
    return mappings


def write_supplement(preset_dir: Path, base_name: str, mappings: dict) -> dict:
    """Extend preset `base_name` with source-rig bone names, as <base>_extended.json beside it (the
    shipped file is never written). An existing _extended file is merged into, not replaced."""
    preset_dir = Path(preset_dir)
    _check_mappings(mappings)
    base_path = preset_dir / f"{_stem(base_name)}.json"
    if not base_path.is_file():
        raise StepError("precondition", f"base preset {base_name!r} not found at {base_path}",
                        details={"preset_dir": str(preset_dir)})
    target = preset_dir / f"{base_name}_extended.json"
    source = target if target.is_file() else base_path
    try:
        merged = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StepError("precondition", f"cannot read {source}: {exc}") from exc
    info = merged.setdefault("preset_info", {})
    info["type"] = "X_PRESET"
    name = str(info.get("name") or base_name)
    info["name"] = name if name.endswith(" (extended)") else f"{name} (extended)"
    info["derived_from"] = base_name
    slots = merged.setdefault("mappings", {})
    if not isinstance(slots, dict):
        raise StepError("precondition", f"{source}: mappings is not an object")
    added_slots, added = [], []
    for key, bone in mappings.items():
        slot = slots.get(key)
        if not isinstance(slot, dict):
            slot = slots[key] = {"main": [], "aux": []}
            added_slots.append(key)
        main = slot.get("main")
        if not isinstance(main, list):
            main = slot["main"] = [main] if isinstance(main, str) and main else []
        if not isinstance(slot.get("aux"), list):
            slot["aux"] = []
        if bone not in main:
            main.append(bone)
            added.append({"slot": key, "bone": bone})
    target.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"new_preset_name": target.stem, "new_preset_path": str(target), "base_preset_name": base_name,
            "added_slots": added_slots, "added_candidates": added, "total_slot_count": len(slots)}


def write_custom(preset_dir: Path, character_name: str, mappings: dict, description: str = "") -> dict:
    """A new X-preset <character>_custom.json, one main candidate per slot (rewritten each time)."""
    target = Path(preset_dir) / f"{_stem(str(character_name).strip())}_custom.json"
    _check_mappings(mappings)
    preset = {
        "preset_info": {"name": f"{character_name} (custom)", "type": "X_PRESET", "version": "1.0",
                        "description": description or f"Custom X-preset synthesized by ModPilot for {character_name}.",
                        "derived_from": "custom"},
        "exclude": [],
        "mappings": {k: {"main": [v], "aux": []} for k, v in mappings.items()},
    }
    target.write_text(json.dumps(preset, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"new_preset_name": target.stem, "new_preset_path": str(target), "character_name": character_name,
            "slot_count": len(mappings)}
