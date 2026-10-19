"""
Phase 3 — Vertex Group Conversion (plan.md video 3).

Three-step pipeline applied after skeleton alignment (Phase 2):

  Step 1 — Mesh prep & merge  (_prep_and_merge)
    - Ensure every mesh has at least one material slot (create placeholder if missing).
    - Make the parts join-safe (JOIN_PREP_SRC): each part's shape-key mix into its basis
      (keys kept), UV layers named by position after the active part's, colour layers
      a part lacks added white.
    - Join all source meshes into a single object (bpy.ops.object.join).
    - MMD only: remove functional vertex groups mmd_edge_scale / mmd_vertex_order.
    - Clean zero-weight entries (vertex_group_clean).
    - Normalise all vertex weights to sum=1 (vertex_group_normalize_all).

  Step 2 — Vertex group rename  (_convert_vertex_groups)
    - Set X/Y presets, run modder.direct_convert on the merged mesh.
    - Converts vertex group names from source convention to MHWilds bone names.

  Step 3 — Re-parent to MHWilds armature  (_reparent_to_target)
    - parent_clear(CLEAR_KEEP_TRANSFORM) bakes current world transform locally.
    - Remove all existing Armature modifiers from the merged mesh.
    - Set merged.parent = target armature with corrected matrix_parent_inverse
      so world position is preserved exactly.
    - Add a fresh Armature modifier pointing to the MHWilds armature.

Source armature is left untouched; it is still needed for physics bone work (Phase 4).

Required params:
  x_preset        : str        — "MMD" | "VRChat" | "arknights"
  mesh_objects    : list[str]  — source MESH object names to process
  target_armature : str        — MHWilds ARMATURE object name (re-parent destination)

Optional params:
  y_preset        : str        — default "mhws"
"""

from __future__ import annotations

import json
from typing import Any

from app.blender.client import BLENDER_SENTINEL, BlenderClient, BlenderError
from app.blender.state import SceneCache
from app.phases.base import (
    DEFAULT_Y_PRESET,
    X_PRESETS,
    Y_PRESETS,
    PhaseError,
    PhaseResult,
    PhaseTool,
    require_finished,
)

_OP_JOIN = "object.join"
_OP_CONVERT = "modder.direct_convert"

# Blender-side preparation run on every source mesh right before the join (ModPilot lesson #48,
# Blender-MHWilds lessons #11 / #42). The join keeps ONE value per shape key (the active object's)
# and merges UV / colour layers by NAME, while the exporter ships each vertex's BASIS position
# (keys are muted before export) and writes UV layers by INDEX. Unprepared, the BHS shoes lost
# High heeled = 1 (soles 4.3 cm into the floor) and the GG garments' 'UVマップ' went to a third
# layer the exporter never writes (every UV at (0, 0), colour zero-filled: the clothes did not draw).
#   1. each part's current shape-key mix becomes its basis; every key block moves by the same
#      offset, so each key still adds what it added, and every value goes to 0
#   2. each part's UV layers take the active part's names by position (missing ones are added,
#      zero-filled), so each part exports the UVs it would have exported alone
#   3. a colour layer some part lacks is added to it white (MultiBlend cloth reads vertex colour,
#      and black cut the clothes away in game, Blender-MHWilds lesson #73)
JOIN_PREP_SRC = '''
import json


def _bake_mix_keep_keys(obj):
    keys = obj.data.shape_keys
    if keys is None or not keys.use_relative:
        return None
    live = {kb.name: round(kb.value, 6) for kb in keys.key_blocks[1:] if kb.value != 0.0 and not kb.mute}
    if not live:
        return None
    n = len(obj.data.vertices)
    ref_co, mix_co = [0.0] * (3 * n), [0.0] * (3 * n)
    keys.reference_key.data.foreach_get("co", ref_co)
    tmp = obj.shape_key_add(name="__modpilot_mix", from_mix=True)
    tmp.data.foreach_get("co", mix_co)
    obj.shape_key_remove(tmp)
    shift = [m - r for m, r in zip(mix_co, ref_co)]
    co = [0.0] * (3 * n)
    for kb in keys.key_blocks:
        kb.data.foreach_get("co", co)
        kb.data.foreach_set("co", [c + s for c, s in zip(co, shift)])
    for kb in keys.key_blocks[1:]:
        kb.value = 0.0
    obj.data.vertices.foreach_set("co", mix_co)
    obj.data.update()
    return live


def _match_uv_layers(obj, names):
    uv = obj.data.uv_layers
    old = [u.name for u in uv]
    k = min(len(old), len(names))
    renamed = {old[i]: names[i] for i in range(k) if old[i] != names[i]}
    if renamed:
        for i in range(k):  # through temporary names: a part's 'UVMap' may have to become 'UV 맵' first
            uv[i].name = "__modpilot_uv%d" % i
        for i in range(k):
            uv[i].name = names[i]
    added = []
    for name in names[k:]:
        layer = uv.new(name=name)
        layer.data.foreach_set("uv", [0.0] * (2 * len(layer.data)))
        added.append(name)
    return renamed, added


def _prepare_for_join(objs):
    report = {"baked_keys": {}, "uv_renamed": {}, "uv_added": {}, "colour_added": {}}
    for obj in objs:
        live = _bake_mix_keep_keys(obj)
        if live:
            report["baked_keys"][obj.name] = live
    names = [u.name for u in objs[0].data.uv_layers]
    for obj in objs[1:]:
        renamed, added = _match_uv_layers(obj, names)
        if renamed:
            report["uv_renamed"][obj.name] = renamed
        if added:
            report["uv_added"][obj.name] = added
    colours = {}
    for obj in objs:
        for ca in obj.data.color_attributes:
            colours.setdefault(ca.name, (ca.domain, ca.data_type))
    for obj in objs:
        for name, (domain, data_type) in colours.items():
            if name in obj.data.color_attributes:
                continue
            ca = obj.data.color_attributes.new(name=name, type=data_type, domain=domain)
            ca.data.foreach_set("color", [1.0] * (4 * len(ca.data)))
            report["colour_added"].setdefault(obj.name, []).append(name)
    return report
'''


class VertexGroups(PhaseTool):
    """Phase 3: Mesh merge, weight normalisation, VG rename, armature re-parent."""

    @property
    def name(self) -> str:
        return "vertex_groups"

    @property
    def phase_slot(self) -> str | None:
        return "phase_3"

    @classmethod
    def tool_schema(cls) -> dict[str, Any]:
        return {
            "name": "vertex_groups",
            "description": (
                "Phase 3: Merge source meshes into one object, normalize vertex weights, "
                "rename vertex groups to MHWs bone naming convention, and re-parent "
                "the merged mesh to the MHWs armature. Run after skeleton_align."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "x_preset": {
                        "type": "string",
                        "enum": ["MMD", "VRChat", "arknights"],
                        "description": "Source model type preset.",
                    },
                    "mesh_objects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Source MESH object names to merge and convert (not armature names).",
                    },
                    "target_armature": {
                        "type": "string",
                        "description": "Blender ARMATURE object name for the MHWs reference skeleton.",
                    },
                    "y_preset": {
                        "type": "string",
                        "enum": ["mhws"],
                        "description": "Target game preset. Always mhws for MHWs.",
                    },
                },
                "required": ["x_preset", "mesh_objects", "target_armature"],
            },
        }

    def run(
        self,
        client: BlenderClient,
        cache: SceneCache,
        params: dict,
    ) -> PhaseResult:
        # ── param validation ───────────────────────────────────────────────
        x_preset = params.get("x_preset", "")
        if x_preset not in X_PRESETS:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message=f"Unknown X preset {x_preset!r}. Valid: {sorted(X_PRESETS)}",
                    suggestion="Choose from MMD, VRChat, or arknights.",
                )
            )

        y_preset = params.get("y_preset", DEFAULT_Y_PRESET)
        if y_preset not in Y_PRESETS:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message=f"Unknown Y preset {y_preset!r}. Valid: {sorted(Y_PRESETS)}",
                )
            )

        mesh_objects: list[str] = params.get("mesh_objects", [])
        if not mesh_objects:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message="'mesh_objects' must be a non-empty list of MESH object names.",
                    suggestion="Provide body/hair/clothing mesh names, not the armature.",
                )
            )

        target_arm = params.get("target_armature", "")
        if not target_arm:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message="'target_armature' param is required (MHWilds reference skeleton).",
                    suggestion="Import MHWilds_Female skeleton via mbt.import_mhwilds_fmesh first.",
                )
            )

        # ── entry spot-check ───────────────────────────────────────────────
        state_before = cache.refresh()

        # ── pipeline ───────────────────────────────────────────────────────
        try:
            # Step 1 — prep & merge; returns merged object name on success
            err, merged_name, join_prep = self._prep_and_merge(client, mesh_objects, x_preset)
            if err is not None:
                return PhaseResult.fail(err)

            # Step 2 — vertex group rename via toolkit operator
            err = self._convert_vertex_groups(client, merged_name, x_preset, y_preset)
            if err is not None:
                return PhaseResult.fail(err)

            # Step 3 — re-parent merged mesh to MHWilds armature
            err = self._reparent_to_target(client, merged_name, target_arm)
            if err is not None:
                return PhaseResult.fail(err)

        except BlenderError as exc:
            return PhaseResult.fail(
                PhaseError(
                    category="unexpected",
                    operator="vertex_groups pipeline",
                    message="Blender returned an error during vertex group conversion.",
                    raw=str(exc),
                )
            )
        except OSError as exc:
            return PhaseResult.fail(
                PhaseError(
                    category="timeout",
                    operator="vertex_groups pipeline",
                    message="Lost connection to Blender during vertex group conversion.",
                    raw=str(exc),
                )
            )

        # ── cleanup: remove MHWilds reference meshes ───────────────────────
        # Source meshes are now merged and reparented; reference meshes that
        # came with the MHWilds skeleton import are no longer needed.
        self._delete_mhwilds_reference_meshes(client, target_arm, merged_name)

        # ── exit cache update ──────────────────────────────────────────────
        state_after = cache.refresh()
        diff = state_before.diff(state_after)
        if join_prep is not None:
            diff["join_prep"] = join_prep
        return PhaseResult.ok(diff)

    # ── private helpers ────────────────────────────────────────────────────

    def _prep_and_merge(
        self,
        client: BlenderClient,
        mesh_objects: list[str],
        x_preset: str,
    ) -> tuple[PhaseError | None, str, dict | None]:
        """
        1. Validate all objects exist and are MESH type.
        2. Add a placeholder material to any mesh that has no material slots.
        3. Make the parts join-safe (JOIN_PREP_SRC): shape-key mix into the basis,
           UV layers named by position, missing colour layers added white.
        4. Join all meshes (active = first in list; result retains its name).
        5. MMD: remove mmd_edge_scale and mmd_vertex_order vertex groups.
        6. Clean zero-weight entries, then normalise all vertex weights.

        Returns (None, merged_name, join-prep report or None) on success,
        (PhaseError, "", None) on failure.
        """
        lookup_lines = "\n".join(
            f"obj = bpy.data.objects.get({name!r})\n"
            f"if obj is None:\n"
            f"    missing.append({name!r})\n"
            f"elif obj.type != 'MESH':\n"
            f"    not_mesh.append({name!r})\n"
            f"else:\n"
            f"    mesh_objs.append(obj)"
            for name in mesh_objects
        )

        code = (
            f"import bpy\n"
            f"{JOIN_PREP_SRC}\n"
            f"mesh_objs = []\n"
            f"missing = []\n"
            f"not_mesh = []\n"
            f"{lookup_lines}\n"
            f"if missing or not_mesh:\n"
            f"    print({BLENDER_SENTINEL!r})\n"
            f"    problems = []\n"
            f"    if missing: problems.append('not_found:' + ','.join(missing))\n"
            f"    if not_mesh: problems.append('not_mesh:' + ','.join(not_mesh))\n"
            f"    print('PRECONDITION:' + '|'.join(problems))\n"
            f"else:\n"
            # Ensure every mesh has at least one material slot
            f"    for obj in mesh_objs:\n"
            f"        if len(obj.material_slots) == 0:\n"
            f"            mat = bpy.data.materials.new(name=obj.name + '_mat')\n"
            f"            obj.data.materials.append(mat)\n"
            f"    bpy.ops.object.mode_set(mode='OBJECT')\n"
            # Shape-key mix, UV and colour layers made join-safe (JOIN_PREP_SRC)
            f"    _join_prep = _prepare_for_join(mesh_objs)\n"
            # Merge: first object is active; joined result keeps its name
            f"    bpy.ops.object.select_all(action='DESELECT')\n"
            f"    for obj in mesh_objs:\n"
            f"        obj.select_set(True)\n"
            f"    bpy.context.view_layer.objects.active = mesh_objs[0]\n"
            f"    bpy.ops.object.join()\n"
            f"    merged = bpy.context.active_object\n"
            # MMD: strip functional vertex groups that must not influence deformation
            f"    if {x_preset!r} == 'MMD':\n"
            f"        for vg_name in ['mmd_edge_scale', 'mmd_vertex_order']:\n"
            f"            vg = merged.vertex_groups.get(vg_name)\n"
            f"            if vg:\n"
            f"                merged.vertex_groups.remove(vg)\n"
            # Clean zero-weight entries, then normalise
            f"    bpy.context.view_layer.objects.active = merged\n"
            f"    merged.select_set(True)\n"
            f"    bpy.ops.object.vertex_group_clean(\n"
            f"        group_select_mode='ALL', limit=0.0)\n"
            f"    bpy.ops.object.vertex_group_normalize_all(lock_active=False)\n"
            f"    print({BLENDER_SENTINEL!r})\n"
            f"    print(f'PREP_OK:{{merged.name}}')\n"
            f"    print('JOIN_PREP:' + json.dumps(_join_prep, ensure_ascii=False))\n"
        )
        lines = client.execute_and_extract(code)
        if not lines:
            return (
                PhaseError(
                    category="operator_failed",
                    operator=_OP_JOIN,
                    message="Mesh prep returned no output from Blender.",
                ),
                "",
                None,
            )
        if lines[0].startswith("PRECONDITION:"):
            detail = lines[0][len("PRECONDITION:"):]
            return (
                PhaseError(
                    category="precondition",
                    operator=_OP_JOIN,
                    message=f"Mesh object issue: {detail}",
                    suggestion=(
                        "Provide MESH object names visible in the Outliner. "
                        "Armature objects are not valid here."
                    ),
                ),
                "",
                None,
            )
        if lines[0].startswith("PREP_OK:"):
            merged_name = lines[0][len("PREP_OK:"):]
            join_prep = None
            for line in lines[1:]:
                if line.startswith("JOIN_PREP:"):
                    try:
                        join_prep = json.loads(line[len("JOIN_PREP:"):])
                    except json.JSONDecodeError:
                        join_prep = {"unparsed": line[len("JOIN_PREP:"):]}
            return None, merged_name, join_prep
        return (
            PhaseError(
                category="unexpected",
                operator=_OP_JOIN,
                message=f"Unexpected output from mesh prep: {lines[0]!r}",
            ),
            "",
            None,
        )

    def _convert_vertex_groups(
        self,
        client: BlenderClient,
        merged_name: str,
        x_preset: str,
        y_preset: str,
    ) -> PhaseError | None:
        """
        Set X/Y presets, select the merged mesh, run modder.direct_convert.
        Converts all vertex group names from source convention to MHWilds bone names.
        """
        code = (
            f"import bpy\n"
            f"settings = bpy.context.scene.mhw_suite_settings\n"
            f"settings.import_preset_enum = {(x_preset + '.json')!r}\n"
            f"settings.target_preset_enum = {(y_preset + '.json')!r}\n"
            f"merged = bpy.data.objects.get({merged_name!r})\n"
            f"if merged is None:\n"
            f"    print({BLENDER_SENTINEL!r})\n"
            f"    print('PRECONDITION:merged_mesh_not_found')\n"
            f"else:\n"
            f"    bpy.ops.object.mode_set(mode='OBJECT')\n"
            f"    bpy.ops.object.select_all(action='DESELECT')\n"
            f"    merged.select_set(True)\n"
            f"    bpy.context.view_layer.objects.active = merged\n"
            f"    ret = bpy.ops.{_OP_CONVERT}()\n"
            f"    print({BLENDER_SENTINEL!r})\n"
            f"    print(ret)\n"
        )
        lines = client.execute_and_extract(code)
        if lines and lines[0].startswith("PRECONDITION:"):
            return PhaseError(
                category="precondition",
                operator=_OP_CONVERT,
                message=f"Merged mesh {merged_name!r} not found when running direct_convert.",
                suggestion="This is unexpected after a successful merge; check Blender state.",
            )
        return require_finished(lines, _OP_CONVERT)

    def _reparent_to_target(
        self,
        client: BlenderClient,
        merged_name: str,
        target_arm: str,
    ) -> PhaseError | None:
        """
        Move the merged mesh under the MHWilds armature without introducing
        any positional transform:

          1. parent_clear(CLEAR_KEEP_TRANSFORM) — bakes world transform locally.
          2. Remove all existing Armature modifiers.
          3. Set .parent + correct matrix_parent_inverse — world position unchanged.
          4. Add fresh Armature modifier using existing (renamed) vertex groups.
        """
        code = (
            f"import bpy\n"
            f"merged = bpy.data.objects.get({merged_name!r})\n"
            f"tgt_arm = bpy.data.objects.get({target_arm!r})\n"
            f"missing = []\n"
            f"if merged is None: missing.append({merged_name!r})\n"
            f"if tgt_arm is None: missing.append({target_arm!r})\n"
            f"if missing:\n"
            f"    print({BLENDER_SENTINEL!r})\n"
            f"    print('PRECONDITION:objects_not_found:' + ','.join(missing))\n"
            f"else:\n"
            # Clear parent, bake world transform into local transform
            f"    bpy.ops.object.select_all(action='DESELECT')\n"
            f"    merged.select_set(True)\n"
            f"    bpy.context.view_layer.objects.active = merged\n"
            f"    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')\n"
            # Remove modifiers that pointed to the old source armature
            f"    for mod in list(merged.modifiers):\n"
            f"        if mod.type == 'ARMATURE':\n"
            f"            merged.modifiers.remove(mod)\n"
            # Parent with corrected inverse matrix — no positional shift
            f"    merged.parent = tgt_arm\n"
            f"    merged.matrix_parent_inverse = tgt_arm.matrix_world.inverted()\n"
            # Fresh Armature modifier: vertex groups only, no bone envelopes
            f"    arm_mod = merged.modifiers.new(name='Armature', type='ARMATURE')\n"
            f"    arm_mod.object = tgt_arm\n"
            f"    arm_mod.use_vertex_groups = True\n"
            f"    arm_mod.use_bone_envelopes = False\n"
            # Move merged mesh into MHWilds_Female.mesh collection
            f"    mhwilds_col = bpy.data.collections.get('MHWilds_Female.mesh')\n"
            f"    if mhwilds_col:\n"
            f"        for _c in list(merged.users_collection):\n"
            f"            _c.objects.unlink(merged)\n"
            f"        mhwilds_col.objects.link(merged)\n"
            f"    print({BLENDER_SENTINEL!r})\n"
            f"    print('REPARENT_OK')\n"
        )
        lines = client.execute_and_extract(code)
        if lines and lines[0].startswith("PRECONDITION:"):
            detail = lines[0][len("PRECONDITION:"):]
            return PhaseError(
                category="precondition",
                operator="object.parent_clear / parent_set",
                message=f"Re-parent failed: {detail}",
                suggestion=(
                    f"Ensure {target_arm!r} exists in the scene. "
                    "Import MHWilds_Female skeleton via mbt.import_mhwilds_fmesh first."
                ),
            )
        if lines and lines[0] == "REPARENT_OK":
            return None
        return PhaseError(
            category="unexpected",
            operator="object.parent_set",
            message=f"Unexpected output from re-parent step: {lines!r}",
        )

    def _delete_mhwilds_reference_meshes(
        self,
        client: BlenderClient,
        target_arm: str,
        keep_name: str,
    ) -> None:
        """
        Delete MESH objects that are children of the MHWilds armature and
        belong to the MHWilds_Female.mesh collection, excluding keep_name
        (the merged source mesh that was just moved there).  Failures are
        silently ignored.
        """
        code = (
            f"import bpy\n"
            f"tgt = bpy.data.objects.get({target_arm!r})\n"
            f"col = bpy.data.collections.get('MHWilds_Female.mesh')\n"
            f"if tgt and col:\n"
            f"    to_del = [\n"
            f"        obj for obj in list(col.objects)\n"
            f"        if obj.type == 'MESH' and obj.parent == tgt\n"
            f"        and obj.name != {keep_name!r}\n"
            f"    ]\n"
            f"    for obj in to_del:\n"
            f"        bpy.data.objects.remove(obj, do_unlink=True)\n"
            f"print({BLENDER_SENTINEL!r})\n"
            f"print('CLEANUP_OK')\n"
        )
        client.execute_and_extract(code)
