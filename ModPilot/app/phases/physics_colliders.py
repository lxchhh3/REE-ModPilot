"""Phase 4C — body collider creation + chain-group collision-mask wiring.

Phase 4B leaves every chain group with `clspFlags0 = -1` (all-collide) but
the scene has no collider objects at all, so the masks are inert. Phase 4C
fills both halves:

  Step 1  ColliderCreate (sub-step, advances_phase=False)
    Imports ModPilot's bundled `app/data/full_body.clsp.3` (byte-identical to
    the preset the MHWilds_Chain_Editor fork shipped behind its
    `re_chain.create_full_body_clsp`, an operator RE Chain Editor never had)
    through RE Chain Editor's `re_clsp.importfile`, bound to the MH Wilds
    armature (`target_armature`). That materialises one capsule/sphere per MHWilds body bone and
    CHILD_OF-constrains each to its bone. Then scans the scene for the new colliders + every existing
    RE_CHAIN_CHAINGROUP (with parent_bone + current clspFlags0/1) so the
    LLM has the data needed for Step 2 classification.

  Step 2  (LLM in chat, no tool call)
    The LLM proposes a `chain_flags` map keyed by chain-group name, using
    the body-bit catalog in `app/data/clsp_body_bits.json`. The proposal
    is surfaced to the user for confirmation per the existing widget
    protocol (chat-level for MVP; structured widget may follow later).

  Step 3  ColliderApply (advancing, phase_slot=phase_4c)
    Writes the confirmed `clspFlags0` / `clspFlags1` onto each chain
    group's `re_chain_chaingroup` PropertyGroup and advances the phase.

Why two separate tools (instead of one big phase tool): Step 2 is a pure
LLM classification step. Wrapping Steps 1+3 around it preserves the
"bounded LLM" rule from project_python_over_llm — deterministic Python
on either side, LLM judgment only at the classification seam.
"""

from __future__ import annotations

import json
from typing import Any

from app.blender.client import BLENDER_SENTINEL, BlenderClient, BlenderError
from app.blender.state import SceneCache
from app.phases.base import PhaseError, PhaseResult, PhaseTool
from app.phases.setup import _MHWILDS_ARMATURE
from app.resources import app_data_dir

# ── body-bit catalog ────────────────────────────────────────────────────────

_BITS_PATH = app_data_dir() / "clsp_body_bits.json"
_BITS_CACHE: dict | None = None


def _load_bits() -> dict:
    global _BITS_CACHE
    if _BITS_CACHE is None:
        _BITS_CACHE = json.loads(_BITS_PATH.read_text(encoding="utf-8"))
    return _BITS_CACHE


def list_body_bit_keys() -> list[str]:
    """All body-part keys in catalog order (one per collider of full_body.clsp.3)."""
    return list(_load_bits()["bits"].keys())


def mask_for_keys(keys: list[str]) -> int:
    """OR together the bit values for the given catalog keys.

    Raises KeyError on unknown keys so callers (and LLM proposals) get a
    loud failure instead of a silently dropped body region.
    """
    bits = _load_bits()["bits"]
    mask = 0
    for k in keys:
        if k not in bits:
            raise KeyError(f"unknown body-bit key: {k!r}")
        mask |= bits[k]["bit"]
    return mask


def keys_for_mask(mask: int) -> list[str]:
    """Inverse of `mask_for_keys` — return catalog keys present in the mask."""
    bits = _load_bits()["bits"]
    return [k for k, e in bits.items() if mask & e["bit"]]


# Every bit a collider of full_body.clsp.3 carries: the 20 body regions 0x1..0x80000 plus the
# wide hip sphere 0x800000 (bit 23, ModPilot lesson #50). A mask with any other bit selects nothing.
_FULL_MASK = 0
for _entry in _load_bits()["bits"].values():
    _FULL_MASK |= _entry["bit"]


def _valid_mask(value: int) -> bool:
    return value >= 0 and value & ~_FULL_MASK == 0


# ── operator constants ──────────────────────────────────────────────────────

_OP_IMPORT_CLSP = "re_clsp.importfile"
_FULL_BODY_CLSP_PATH = app_data_dir() / "full_body.clsp.3"


# ── Step 1: ColliderCreate ──────────────────────────────────────────────────


class ColliderCreate(PhaseTool):
    """Phase 4C Step 1 — import the full-body collider preset and scan."""

    @property
    def name(self) -> str:
        return "collider_create"

    @property
    def advances_phase(self) -> bool:
        return False  # sub-step; collider_apply does the phase advance

    @property
    def phase_slot(self) -> str | None:
        # Slot is irrelevant when advances_phase=False, but declaring it
        # documents intent and matches PhysicsChains' prepare_only pattern.
        return "phase_4c"

    @classmethod
    def tool_schema(cls) -> dict[str, Any]:
        return {
            "name": "collider_create",
            "description": (
                "Phase 4C Step 1: Import the MHWilds full-body collider preset "
                "(capsules/spheres CHILD_OF-constrained to body bones) via "
                "RE Chain Editor's re_clsp.importfile (bundled full_body.clsp.3, "
                "bound to target_armature). "
                "Returns the list of created colliders plus every existing "
                "RE_CHAIN_CHAINGROUP with its parent_bone — feed that into a "
                "user-confirmation step, then call collider_apply with the "
                "agreed clspFlags0/clspFlags1 per chain group. Does NOT advance "
                "the phase on its own."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "target_armature": {
                        "type": "string",
                        "description": (
                            "MHWilds ARMATURE object the colliders bind to. Defaults to "
                            f"'{_MHWILDS_ARMATURE}' (what setup_import_mhwilds creates)."
                        ),
                    },
                    "chain_collection": {
                        "type": "string",
                        "description": (
                            "Optional hint: the chain collection name from "
                            "Phase 4B (used to filter chain groups in the scan "
                            "result). If omitted, all RE_CHAIN_CHAINGROUP "
                            "objects in the scene are returned."
                        ),
                    },
                },
            },
        }

    def run(
        self,
        client: BlenderClient,
        cache: SceneCache,
        params: dict,
    ) -> PhaseResult:
        chain_col = params.get("chain_collection", "") or ""
        target_arm = params.get("target_armature", "") or _MHWILDS_ARMATURE

        state_before = cache.refresh()

        try:
            err, info = self._run_full_body_clsp(client, chain_col, target_arm)
        except BlenderError as exc:
            return PhaseResult.fail(
                PhaseError(
                    category="unexpected",
                    operator=_OP_IMPORT_CLSP,
                    message="Blender error during full-body collider import.",
                    raw=str(exc),
                )
            )
        except OSError as exc:
            return PhaseResult.fail(
                PhaseError(
                    category="timeout",
                    operator=_OP_IMPORT_CLSP,
                    message="Lost connection to Blender during collider import.",
                    raw=str(exc),
                )
            )

        if err is not None:
            return PhaseResult.fail(err)

        state_after = cache.refresh()
        diff = state_before.diff(state_after)
        diff["collider_info"] = info
        return PhaseResult.ok(diff)

    def _run_full_body_clsp(
        self,
        client: BlenderClient,
        chain_col_hint: str,
        target_armature: str,
    ) -> tuple[PhaseError | None, dict]:
        """Import the bundled full_body.clsp.3 via re_clsp.importfile + scan the scene.

        Output line shape (one of):
          MISSING_OP:re_clsp.importfile
          NO_ARMATURE:<target_armature>
          CANCELLED:<ret>
          FULL_BODY:<json with colliders, chain_groups, clsp_collection>
        """
        code = (
            f"import bpy, json\n"
            # getattr(bpy.ops.<ns>, '<op>', None) is never None (bpy.ops hands back a
            # stub for any name), so registration must be checked with dir().
            f"_has_op = 'importfile' in dir(bpy.ops.re_clsp)\n"
            f"if not _has_op:\n"
            f"    print({BLENDER_SENTINEL!r})\n"
            f"    print('MISSING_OP:re_clsp.importfile')\n"
            f"else:\n"
            # Snapshot collision-shape objects before import so we can diff.
            f"    before = {{o.name for o in bpy.data.objects\n"
            f"              if o.get('TYPE') in ('RE_CHAIN_COLLISION_CAPSULE',\n"
            f"                                   'RE_CHAIN_COLLISION_SPHERE',\n"
            f"                                   'RE_CHAIN_COLLISION_OBB',\n"
            f"                                   'RE_CHAIN_COLLISION_SHAPE')}}\n"
            # Bind to the named MH Wilds armature, never the active object: after Phase 4B
            # the avatar's armature is in the scene too and none is active, so RE Chain
            # Editor cancelled ("More than one armature was found"; tools-5.2 L3, 2026-10-12).
            f"    _arm = bpy.data.objects.get({target_armature!r})\n"
            f"    try:\n"
            f"        if _arm is None or _arm.type != 'ARMATURE':\n"
            f"            ret = None\n"
            f"        else:\n"
            f"            ret = bpy.ops.re_clsp.importfile(\n"
            f"                filepath={str(_FULL_BODY_CLSP_PATH)!r}, targetArmature=_arm.data.name)\n"
            f"    except Exception as _e:\n"
            f"        print({BLENDER_SENTINEL!r})\n"
            f"        print('OP_ERR:' + str(_e)[:160])\n"
            f"    else:\n"
            f"        if ret is None:\n"
            f"            print({BLENDER_SENTINEL!r})\n"
            f"            print('NO_ARMATURE:' + {target_armature!r})\n"
            f"        elif 'FINISHED' not in str(ret):\n"
            f"            print({BLENDER_SENTINEL!r})\n"
            f"            print('CANCELLED:' + str(ret))\n"
            f"        else:\n"
            # Scan: new colliders + existing chain groups.
            f"            colliders = []\n"
            f"            clsp_col_name = ''\n"
            f"            for o in bpy.data.objects:\n"
            f"                t = o.get('TYPE') or ''\n"
            f"                if not t.startswith('RE_CHAIN_COLLISION'): continue\n"
            f"                if o.name in before: continue\n"
            # Pull the constraint target bone if a CHILD_OF constraint exists.
            f"                bone = ''\n"
            f"                for c in o.constraints:\n"
            f"                    if c.type == 'CHILD_OF' and c.subtarget:\n"
            f"                        bone = c.subtarget\n"
            f"                        break\n"
            f"                colliders.append({{'name': o.name, 'bone': bone,\n"
            f"                                   'type': t.replace('RE_CHAIN_COLLISION_', '') or 'SHAPE'}})\n"
            # Find the clsp collection (the one carrying the new colliders).
            f"            if colliders:\n"
            f"                first = bpy.data.objects.get(colliders[0]['name'])\n"
            f"                if first and first.users_collection:\n"
            f"                    clsp_col_name = first.users_collection[0].name\n"
            # Chain groups: limit to the hinted chain collection if given.
            f"            hint = {chain_col_hint!r}\n"
            f"            hint_obj_names = None\n"
            f"            if hint:\n"
            f"                _hc = bpy.data.collections.get(hint)\n"
            f"                if _hc is not None:\n"
            f"                    hint_obj_names = {{o.name for o in _hc.all_objects}}\n"
            f"            chain_groups = []\n"
            f"            for o in bpy.data.objects:\n"
            f"                if o.get('TYPE') != 'RE_CHAIN_CHAINGROUP': continue\n"
            f"                if hint_obj_names is not None and o.name not in hint_obj_names:\n"
            f"                    continue\n"
            # The group's head bone: its first RE_CHAIN_NODE child's BoneName constraint
            # (RE Chain Editor's own read). The old scan looked for 'RE_CHAIN_CHAINNODE'
            # children with a parent_bone property, neither of which exists: every head read ''.
            f"                parent_bone = ''\n"
            f"                node = next((c for c in o.children if c.get('TYPE') == 'RE_CHAIN_NODE'), None)\n"
            f"                con = node.constraints.get('BoneName') if node is not None else None\n"
            f"                if con is not None:\n"
            f"                    parent_bone = con.subtarget\n"
            f"                cg_pg = getattr(o, 're_chain_chaingroup', None)\n"
            f"                f0 = getattr(cg_pg, 'clspFlags0', -1) if cg_pg else -1\n"
            f"                f1 = getattr(cg_pg, 'clspFlags1', 0) if cg_pg else 0\n"
            f"                chain_groups.append({{\n"
            f"                    'name': o.name, 'parent_bone': parent_bone,\n"
            f"                    'clspFlags0': int(f0), 'clspFlags1': int(f1),\n"
            f"                }})\n"
            f"            print({BLENDER_SENTINEL!r})\n"
            f"            print('FULL_BODY:' + json.dumps({{\n"
            f"                'colliders': colliders,\n"
            f"                'chain_groups': chain_groups,\n"
            f"                'clsp_collection': clsp_col_name,\n"
            f"            }}))\n"
        )

        lines = client.execute_and_extract(code, timeout=300)
        if not lines:
            return (
                PhaseError(
                    category="operator_failed",
                    operator=_OP_IMPORT_CLSP,
                    message="collider_create returned no output from Blender.",
                ),
                {},
            )

        head = lines[0]
        if head.startswith("MISSING_OP:"):
            return (
                PhaseError(
                    category="precondition",
                    operator=_OP_IMPORT_CLSP,
                    message=(
                        "Operator 're_clsp.importfile' is not registered. "
                        "RE Chain Editor is required for Phase 4C."
                    ),
                    suggestion=(
                        "Install and enable RE Chain Editor (NSACloud/RE-Chain-Editor) "
                        "in Blender's Add-ons preferences, then retry. ModPilot imports "
                        "its bundled full_body.clsp.3 through re_clsp.importfile."
                    ),
                ),
                {},
            )
        if head.startswith("NO_ARMATURE:"):
            name = head[len("NO_ARMATURE:"):]
            return (
                PhaseError(
                    category="precondition",
                    operator=_OP_IMPORT_CLSP,
                    message=f"Target armature {name!r} is not an ARMATURE object in the scene.",
                    suggestion=(
                        "Pass target_armature: the MH Wilds armature the chains were built on "
                        f"('{_MHWILDS_ARMATURE}' after setup_import_mhwilds)."
                    ),
                ),
                {},
            )
        if head.startswith("OP_ERR:"):
            return (
                PhaseError(
                    category="operator_failed",
                    operator=_OP_IMPORT_CLSP,
                    message="re_clsp.importfile raised an exception.",
                    raw=head[len("OP_ERR:"):],
                ),
                {},
            )
        if head.startswith("CANCELLED:"):
            return (
                PhaseError(
                    category="operator_failed",
                    operator=_OP_IMPORT_CLSP,
                    message=f"re_clsp.importfile did not FINISH: {head}",
                    suggestion=(
                        "Check Blender's Info editor for the error message. "
                        "Common causes: target_armature is not the MH Wilds armature, "
                        "missing preset file, "
                        "or naming collision with an existing clsp collection."
                    ),
                ),
                {},
            )
        if head.startswith("FULL_BODY:"):
            try:
                payload = json.loads(head[len("FULL_BODY:"):])
                return None, payload
            except json.JSONDecodeError as exc:
                return (
                    PhaseError(
                        category="unexpected",
                        operator=_OP_IMPORT_CLSP,
                        message="Could not parse collider_create scan output.",
                        raw=str(exc),
                    ),
                    {},
                )
        return (
            PhaseError(
                category="unexpected",
                operator=_OP_IMPORT_CLSP,
                message=f"Unexpected collider_create output: {head!r}",
            ),
            {},
        )


# ── Step 3: ColliderApply ───────────────────────────────────────────────────


def _normalise_flag_entry(value: Any) -> tuple[int, int] | None:
    """Coerce a chain_flags entry to (clspFlags0, clspFlags1) or None on bad input.

    Accepts:
      - int           → (value, 0)            shorthand for "only mask flags0"
      - dict          → ({"clspFlags0", "clspFlags1"} ; both default to 0)

    Rejects strings, floats, non-dict iterables, or out-of-range values.
    """
    if isinstance(value, bool):  # bool is a subclass of int in Python
        return None
    if isinstance(value, int):
        if not _valid_mask(value):
            return None
        return value, 0
    if isinstance(value, dict):
        f0 = value.get("clspFlags0", 0)
        f1 = value.get("clspFlags1", 0)
        if isinstance(f0, bool) or isinstance(f1, bool):
            return None
        if not isinstance(f0, int) or not isinstance(f1, int):
            return None
        if not _valid_mask(f0) or not _valid_mask(f1):
            return None
        return f0, f1
    return None


class ColliderApply(PhaseTool):
    """Phase 4C Step 3 — write confirmed clspFlags0/1 onto each chain group."""

    @property
    def name(self) -> str:
        return "collider_apply"

    @property
    def advances_phase(self) -> bool:
        return True

    @property
    def phase_slot(self) -> str | None:
        return "phase_4c"

    @property
    def requires_user_pause(self) -> bool:
        # Phase 4C is the last physics step before materials. Pause so the
        # user can confirm collisions look right in the viewport before
        # Phase 5 burns a lot of LLM context on materials.
        return True

    @classmethod
    def tool_schema(cls) -> dict[str, Any]:
        return {
            "name": "collider_apply",
            "description": (
                "Phase 4C Step 3: Write the user-confirmed clspFlags0 / "
                "clspFlags1 collision masks onto each RE_CHAIN_CHAINGROUP "
                "object. Advances the phase. Values are masks over the "
                "colliders of full_body.clsp.3: the 20 body regions plus "
                "hip_wide (0x800000); see app/data/clsp_body_bits.json for the bit layout."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "chain_flags": {
                        "type": "object",
                        "description": (
                            "Map of RE_CHAIN_CHAINGROUP object name → flag "
                            "value. Each value is either an int (sets "
                            "clspFlags0 only; clspFlags1 stays 0) or a dict "
                            "{\"clspFlags0\": int, \"clspFlags1\": int}. "
                            "Both fields are collider masks (bits from "
                            "clsp_body_bits.json only); pass 0 to disable "
                            "all collisions for that group (the recommended "
                            "default for unsure cases)."
                        ),
                    },
                },
                "required": ["chain_flags"],
            },
        }

    def run(
        self,
        client: BlenderClient,
        cache: SceneCache,
        params: dict,
    ) -> PhaseResult:
        raw_flags = params.get("chain_flags")
        if not isinstance(raw_flags, dict) or not raw_flags:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message="'chain_flags' must be a non-empty dict of chain_group_name → mask.",
                    suggestion=(
                        "Call collider_create first, present the proposed masks "
                        "to the user for confirmation, then call collider_apply "
                        "with the agreed dict."
                    ),
                )
            )

        normalised: dict[str, dict[str, int]] = {}
        bad_entries: list[str] = []
        for name, value in raw_flags.items():
            pair = _normalise_flag_entry(value)
            if pair is None:
                bad_entries.append(f"{name!r}={value!r}")
                continue
            normalised[name] = {"clspFlags0": pair[0], "clspFlags1": pair[1]}
        if bad_entries:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message=(
                        "Invalid chain_flags entries (each value must be an int using "
                        f"only the collider bits 0x{_FULL_MASK:X} or a dict with clspFlags0/1): "
                        + ", ".join(bad_entries)
                    ),
                )
            )

        state_before = cache.refresh()

        try:
            err, applied = self._write_flags(client, normalised)
        except BlenderError as exc:
            return PhaseResult.fail(
                PhaseError(
                    category="unexpected",
                    operator="re_chain_chaingroup",
                    message="Blender error while applying clsp flags.",
                    raw=str(exc),
                )
            )
        except OSError as exc:
            return PhaseResult.fail(
                PhaseError(
                    category="timeout",
                    operator="re_chain_chaingroup",
                    message="Lost connection to Blender during collider_apply.",
                    raw=str(exc),
                )
            )

        if err is not None:
            return PhaseResult.fail(err)

        state_after = cache.refresh()
        diff = state_before.diff(state_after)
        diff["applied"] = applied["applied"]
        if applied.get("not_found"):
            diff["not_found"] = applied["not_found"]
        if applied.get("errors"):
            diff["errors"] = applied["errors"]
        return PhaseResult.ok(diff)

    def _write_flags(
        self,
        client: BlenderClient,
        flags: dict[str, dict[str, int]],
    ) -> tuple[PhaseError | None, dict]:
        flags_json = json.dumps(flags)
        code = (
            f"import bpy, json\n"
            f"flags = json.loads({flags_json!r})\n"
            f"applied = []\n"
            f"not_found = []\n"
            f"errors = []\n"
            f"for name, vals in flags.items():\n"
            f"    obj = bpy.data.objects.get(name)\n"
            f"    if obj is None or obj.get('TYPE') != 'RE_CHAIN_CHAINGROUP':\n"
            f"        not_found.append(name)\n"
            f"        continue\n"
            f"    pg = getattr(obj, 're_chain_chaingroup', None)\n"
            f"    if pg is None:\n"
            f"        errors.append(name + ':no_chaingroup_pg')\n"
            f"        continue\n"
            f"    f0 = int(vals.get('clspFlags0', 0))\n"
            f"    f1 = int(vals.get('clspFlags1', 0))\n"
            f"    try:\n"
            f"        pg.clspFlags0 = f0\n"
            f"    except Exception as _e:\n"
            f"        errors.append(name + ':clspFlags0:' + str(_e)[:80])\n"
            f"        continue\n"
            f"    try:\n"
            f"        pg.clspFlags1 = f1\n"
            f"    except Exception as _e:\n"
            # clspFlags1 missing on older RE Chain Editor versions — non-fatal.
            f"        errors.append(name + ':clspFlags1:' + str(_e)[:80])\n"
            f"    applied.append({{'name': name, 'clspFlags0': f0,\n"
            f"                     'clspFlags1': f1, 'status': 'ok'}})\n"
            f"print({BLENDER_SENTINEL!r})\n"
            f"print('APPLIED:' + json.dumps({{\n"
            f"    'applied': applied, 'not_found': not_found, 'errors': errors,\n"
            f"}}))\n"
        )
        lines = client.execute_and_extract(code, timeout=120)
        if not lines:
            return (
                PhaseError(
                    category="operator_failed",
                    operator="re_chain_chaingroup",
                    message="collider_apply returned no output from Blender.",
                ),
                {},
            )
        head = lines[0]
        if not head.startswith("APPLIED:"):
            return (
                PhaseError(
                    category="unexpected",
                    operator="re_chain_chaingroup",
                    message=f"Unexpected collider_apply output: {head!r}",
                ),
                {},
            )
        try:
            payload = json.loads(head[len("APPLIED:"):])
        except json.JSONDecodeError as exc:
            return (
                PhaseError(
                    category="unexpected",
                    operator="re_chain_chaingroup",
                    message="Could not parse collider_apply result.",
                    raw=str(exc),
                ),
                {},
            )
        return None, payload
