"""
Phase 5A — MaterialInspect  (scene + filesystem reader; no LLM calls)
Phase 5B — MaterialSetup    (Principled BSDF node wiring)
Phase 5C — MaterialGenerate (MDF2 generator pipeline)

Data flow:
  MaterialInspect  → returns materials list + texture_files + existing_connections
                    (agent loop runs LLM classification + user confirmation between tools)
  MaterialSetup    → receives confirmed {mat_name: {slot: filepath}} mapping, wires nodes
  MaterialGenerate → receives confirmed {mat_name: preset_display_name} mapping,
                     runs mdf_gen_refresh + mdf_gen_process

MMD models skip MaterialSetup — their textures are already wired by the MMD importer.
They enter Phase 5 at MaterialGenerate directly.

Normal slot handling is x_preset-dependent:
  VRChat  — OpenGL normals: ImageTexture → SepXYZ → Math(1-Y) → CombXYZ → NormalMap → Normal
  終末地  — DirectX normals (no inversion): ImageTexture → NormalMap → Normal

Generator preset paths are dynamic (RE Mesh Editor Presets/MHWILDS/*.json).
load_preset_enum_items("MHWILDS") is resolved at runtime by scanning sys.modules
for the RE Mesh Editor addon function; falls back to empty lookup on import failure.
"""

from __future__ import annotations

import asyncio
import json
import textwrap
from pathlib import Path
from typing import Any

from app.blender.client import BLENDER_SENTINEL, BlenderClient, BlenderError
from app.blender.state import SceneCache
from app.config import settings
from app.llm.client import LLMClient, LLMResponse, Message
from app.llm.vision_client import VisionClient, image_to_base64, vision_available
from app.phases.base import PhaseError, PhaseResult, PhaseTool

# ── constants ─────────────────────────────────────────────────────────────────

#: X presets that require MaterialSetup node wiring; MMD skips this tool
VALID_SETUP_PRESETS: frozenset[str] = frozenset({"VRChat", "終末地"})

IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".tga", ".dds", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"
})

#: Blender-side lookup of a ModPilot slot name on a Principled BSDF. Blender 4.0 renamed the
#: 'Emission' socket to 'Emission Color' and gave 'Emission Strength' a default of 0, which the
#: Toolkit's generator reads as "not emissive" (core/mdf_generator_base.py): material_setup
#: skipped every emission texture as an unknown slot and claude_run1's eye glow was wired by hand.
SLOT_SOCKET_SRC = '''
_SLOT_SOCKETS = {"Emission": ("Emission Color", "Emission")}


def _slot_socket(pbs, slot):
    for name in _SLOT_SOCKETS.get(slot, (slot,)):
        sock = pbs.inputs.get(name)
        if sock is not None:
            return sock
    return None


def _emission_on(pbs):
    strength = pbs.inputs.get("Emission Strength")
    if strength is not None and not strength.is_linked and strength.default_value == 0.0:
        strength.default_value = 1.0
'''

PRINCIPLED_SLOTS: tuple[str, ...] = (
    "Base Color", "Alpha", "Roughness", "Metallic", "Emission", "Normal"
)

_OP_MDF_REFRESH = "mhws.mdf_gen_refresh"
_OP_MDF_PROCESS = "mhws.mdf_gen_process"

# Normal chain code fragments injected at Python time (20-space indent = inside if slot==Normal).
# Generated per-x_preset so the Blender code string itself is preset-specific and testable.
_I20 = " " * 20
_VCHAT_NORMAL_CHAIN: str = (
    f"{_I20}sep = nodes.new('ShaderNodeSeparateXYZ')\n"
    f"{_I20}sep.location = (-700, y)\n"
    f"{_I20}mth = nodes.new('ShaderNodeMath')\n"
    f"{_I20}mth.operation = 'SUBTRACT'\n"
    f"{_I20}mth.inputs[0].default_value = 1.0\n"
    f"{_I20}mth.location = (-500, y - 120)\n"
    f"{_I20}cmb = nodes.new('ShaderNodeCombineXYZ')\n"
    f"{_I20}cmb.location = (-350, y)\n"
    f"{_I20}links.new(tex.outputs['Color'], sep.inputs['Vector'])\n"
    f"{_I20}links.new(sep.outputs['X'], cmb.inputs['X'])\n"
    f"{_I20}links.new(sep.outputs['Y'], mth.inputs[1])\n"
    f"{_I20}links.new(mth.outputs[0], cmb.inputs['Y'])\n"
    f"{_I20}links.new(sep.outputs['Z'], cmb.inputs['Z'])\n"
    f"{_I20}links.new(cmb.outputs[0], nm.inputs['Color'])\n"
)
_ZENMO_NORMAL_CHAIN: str = (
    f"{_I20}links.new(tex.outputs['Color'], nm.inputs['Color'])\n"
)


# ── Phase 5 LLM pre-fill ──────────────────────────────────────────────────────


# Suffix-token taxonomy for non-Base-Color slots (issue #19). Each tuple is a
# set of lowercase tokens that must appear in the filename's stem delimited
# by `_` or `.` for the LLM's suggestion to survive the server-side filter.
# Base Color stays lenient — it's overwhelmingly the default texture and a
# leading prefix tag (e.g. "BML_body") is still a basecolor in practice.
_SLOT_SUFFIX_TOKENS: dict[str, frozenset[str]] = {
    "Normal":    frozenset({"n", "nrm", "nm", "norm", "normal"}),
    "Roughness": frozenset({"r", "rgh", "roughness", "gloss"}),
    "Metallic":  frozenset({"m", "mtl", "metal", "metallic"}),
    "Emission":  frozenset({"e", "emit", "emission", "glow"}),
    "Alpha":     frozenset({"a", "alpha", "opacity", "mask"}),
}


# Layer 3 (vision fallback, issue #22 Stage 1). The VLM is prompted to reply
# with one canonical PBR token; we accept common synonyms because different
# VLMs spell the same channel differently (Qwen-VL prefers "base_color",
# LLaVA leans toward "diffuse" or "albedo").
#
# alpha is listed first in the prompt because transparency maps are the most
# common Layer 2 miss for stylized models (single-channel grayscale masks
# that fail every filename-token rule). Spec keeps base_color/normal/etc.
_VISION_TOKEN_TO_SLOT: dict[str, str] = {
    # Alpha (top priority — common Layer 2 miss)
    "alpha":      "Alpha",
    "opacity":    "Alpha",
    "transparency": "Alpha",
    "mask":       "Alpha",
    # Base Color synonyms
    "base_color": "Base Color",
    "basecolor":  "Base Color",
    "diffuse":    "Base Color",
    "albedo":     "Base Color",
    "color":      "Base Color",
    # Normal
    "normal":     "Normal",
    "normalmap":  "Normal",
    "nrm":        "Normal",
    # Roughness
    "roughness":  "Roughness",
    "gloss":      "Roughness",
    # Metallic
    "metallic":   "Metallic",
    "metal":      "Metallic",
    # Emission
    "emission":   "Emission",
    "emissive":   "Emission",
    "glow":       "Emission",
    "emit":       "Emission",
}

# Channels the VLM may legitimately return but that the Principled BSDF
# slots can't consume directly. We RECOGNIZE them (instead of letting them
# fall through to the "other"/garbage bucket) so a future addition of AO
# or ORM-aware wiring only needs to map these to real slots — and so that
# correctly classified textures aren't accidentally treated as garbage and
# misrouted on a retry. Currently dropped, but the drop is documented.
_VISION_KNOWN_UNMAPPED: frozenset[str] = frozenset({
    "ao", "ambient_occlusion", "occlusion",
    "orm", "packed_orm", "rma", "arm",
    "specular", "spec",
})

_VISION_PROMPT: str = (
    "What PBR texture channel is this image? Reply with EXACTLY ONE of: "
    "alpha, base_color, normal, roughness, metallic, emission, "
    "ao, packed_orm, other. "
    "No prose, no punctuation."
)

# Issue #22 Stage 2 — UV-assist mesh dedup prompt for MaterialConsolidate.
# Asks whether two materials sharing one texture actually occupy the SAME UV
# region (= mesh dedup candidate) or just happen to reference the file (=
# legitimately separate meshes that load the same atlas).
_UV_OVERLAP_PROMPT_TMPL: str = (
    "Two UV wireframes are overlaid on texture '{tex_name}': "
    "RED is material '{mat_a}', BLUE is material '{mat_b}'. "
    "Do these two meshes share the same texture space (occupy the same UV "
    "regions on this texture)? Reply with EXACTLY: YES or NO, then a "
    "confidence score between 0.0 and 1.0. "
    "Examples: 'YES 0.9' or 'NO 0.6'. No other text."
)


def _find_partial_overlap_candidates(
    groups: list[dict],
) -> list[tuple[str, str, list[str]]]:
    """Find material pairs across exact-match groups whose texture sets
    overlap but aren't identical — UV-assist merge candidates.

    Returns [(keeper_a, keeper_b, [shared_paths_sorted]), ...]. Groups with
    no textures (singleton placeholders) are excluded — they can't share
    UV space if there's no shared image to compare against.
    """
    annotated: list[tuple[str, frozenset[str]]] = []
    for grp in groups:
        tex = frozenset(grp.get("texture_set") or [])
        if not tex:
            continue
        annotated.append((grp.get("keeper", ""), tex))

    out: list[tuple[str, str, list[str]]] = []
    for i in range(len(annotated)):
        kname_a, tex_a = annotated[i]
        for j in range(i + 1, len(annotated)):
            kname_b, tex_b = annotated[j]
            if tex_a == tex_b:
                # Identical sets would already be merged by exact-match.
                continue
            shared = sorted(tex_a & tex_b)
            if shared:
                out.append((kname_a, kname_b, shared))
    return out


def _parse_uv_overlap_reply(text: str) -> tuple[str, float]:
    """Normalize a VLM reply to (verdict, confidence).

    Accepts 'YES 0.9', 'NO 0.5', 'YES, confidence: 0.85', plain 'YES'/'NO',
    and falls back to ('no', 0.0) for anything unparseable. Confidence is
    clamped to [0.0, 1.0].
    """
    import re
    norm = (text or "").strip().lower()
    if not norm:
        return ("no", 0.0)
    m = re.search(r"\b(yes|no)\b.*?(\d+(?:\.\d+)?)", norm)
    if m:
        verdict = m.group(1)
        try:
            conf = max(0.0, min(1.0, float(m.group(2))))
        except ValueError:
            conf = 0.0
        return (verdict, conf)
    if re.search(r"\byes\b", norm):
        return ("yes", 0.5)
    if re.search(r"\bno\b", norm):
        return ("no", 0.5)
    return ("no", 0.0)


def _has_slot_token(path: str, slot: str) -> bool:
    """Defense-in-depth check for the suffix-token rule in the LLM prompt.

    Returns True when the filename stem of `path` contains a token from
    `_SLOT_SUFFIX_TOKENS[slot]` as a `_`/`.`-delimited piece. Base Color
    has no entry and always returns True (no token gate).

    Examples (slot='Normal'):
        body_n.png         -> True   (token 'n' at end)
        body_normal.tga    -> True
        char.nrm.dds       -> True
        BML_body.dds       -> False  (no normal token anywhere)
        body.png           -> False
    """
    tokens = _SLOT_SUFFIX_TOKENS.get(slot)
    if tokens is None:
        return True
    stem = Path(path).stem.lower()
    # Split on both `_` and `.` so `char.nrm.dds` → ['char', 'nrm', 'dds'].
    # Stem strips the final extension but inner dots remain (e.g. 'char.nrm').
    pieces: set[str] = set()
    for chunk in stem.split("_"):
        pieces.update(chunk.split("."))
    return bool(pieces & tokens)


async def suggest_texture_mapping(
    llm: LLMClient,
    materials: list[str],
    texture_files: list[str],
    existing_connections: dict[str, dict[str, str]],
    *,
    vision_marks: dict[str, list[str]] | None = None,
) -> dict[str, dict[str, str]]:
    """Ask the LLM to pre-fill slot→texture suggestions for the Phase 5
    material confirmation widget (issue #11).

    Returns a {material_name: {slot_name: file_path}} dict; missing keys
    mean "no suggestion, leave the row blank". The user can accept or
    override each cell in the widget UI.

    Best-effort: if there are no texture files, the LLM call is skipped
    (nothing to pick from). Any LLM exception or non-JSON reply returns
    {} so the widget still renders with bare rows — equivalent to the
    pre-issue-#11 behavior.

    Note: file_path values are full paths from texture_files; the widget
    template still resolves them against the <option value="..."> list.

    Provenance (issue #22 Stage 1): pass an empty dict as `vision_marks`
    to receive a parallel `{material_name: [slot_name, ...]}` map naming
    the slots that came from the Layer 3 vision pass (spec calls these
    "medium-confidence" — the widget should badge them for user review).
    Leave `vision_marks=None` to skip provenance bookkeeping entirely.
    """
    if not texture_files or not materials:
        return {}

    prompt = (
        "You are matching mesh materials to texture files for a Blender "
        "Principled BSDF setup. Pick the most plausible texture for each "
        "slot of each material, using the candidate file list.\n"
        "\n"
        "## Hard rule — default is OMIT, fill is the exception\n"
        "Filling a wrong texture into a slot (especially Normal) ruins the "
        "shading worse than leaving it empty. Only suggest a texture when "
        "the evidence is strong. When in doubt, OMIT the slot.\n"
        "\n"
        "## Base Color (lenient)\n"
        "May match by material-name prefix or by tokens like 'diffuse', "
        "'albedo', 'basecolor', 'bc', 'col', 'd'. Example: material "
        "'Body.001' pairs with 'body.png', 'body_diffuse.tga', or "
        "'BML_body.dds' (BML = base map layer, still a basecolor).\n"
        "\n"
        "## Non-basecolor slots (STRICT — suffix-token evidence required)\n"
        "Only fill these slots when the filename contains one of the listed "
        "tokens as a suffix or infix delimited by '_' or '.'. A token "
        "embedded inside an arbitrary prefix (e.g. 'BML_body') does NOT "
        "count. If no listed token is present, leave the slot empty.\n"
        "- Normal:    '_n', '_nrm', '_nm', '_norm', '_normal'        "
        "(also '.nrm', '.normal')\n"
        "- Roughness: '_r', '_rgh', '_roughness', '_gloss'\n"
        "- Metallic:  '_m', '_mtl', '_metal', '_metallic'\n"
        "- Emission:  '_e', '_emit', '_emission', '_glow'\n"
        "- Alpha:     '_a', '_alpha', '_opacity', '_mask'\n"
        "\n"
        "## Anti-examples (do NOT suggest these)\n"
        "- 'BML_body.dds' as Normal — 'BML' is a prefix tag, not a normal "
        "  suffix token. This file is a Base Color candidate, not Normal.\n"
        "- 'body.png' as Roughness — no '_r'/'_rgh' token present.\n"
        "- Inventing a slot for a material when none of the candidate "
        "  files carry the required suffix token.\n"
        "\n"
        f"Materials: {json.dumps(materials, ensure_ascii=False)}\n"
        f"Principled BSDF slots: {json.dumps(list(PRINCIPLED_SLOTS))}\n"
        f"Existing wired connections: {json.dumps(existing_connections, ensure_ascii=False)}\n"
        f"Candidate texture files (use these exact strings as values):\n"
        f"{json.dumps(texture_files, ensure_ascii=False)}\n"
        "\n"
        "Reply with ONLY a JSON object of shape "
        '{"material_name": {"slot_name": "file_path", ...}, ...}. '
        "Use exactly the file paths from the candidate list — no renames, "
        "no inventions. Omit slots entirely rather than guessing. "
        "No prose, no markdown, no code fences."
    )
    messages: list[Message] = [{"role": "user", "content": prompt}]
    try:
        response: LLMResponse = await asyncio.to_thread(
            llm.chat, messages, system="", tools=None
        )
    except Exception:
        return {}

    text = (response.content or "").strip()
    # Strip a ```json ... ``` fence if the model added one despite the
    # instruction — common with smaller models.
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}

    # Filter: drop entries for unknown materials/slots; keep only file paths
    # the inspector actually surfaced (LLM occasionally invents).
    material_set = set(materials)
    slot_set = set(PRINCIPLED_SLOTS)
    file_set = set(texture_files)
    clean: dict[str, dict[str, str]] = {}
    for mat, slots in parsed.items():
        if mat not in material_set or not isinstance(slots, dict):
            continue
        row: dict[str, str] = {}
        for slot, path in slots.items():
            if slot not in slot_set:
                continue
            if not isinstance(path, str) or path not in file_set:
                continue
            # Suffix-token gate (issue #19): non-Base-Color slots need
            # evidence in the filename. Drops the BML_body-as-Normal case.
            if not _has_slot_token(path, slot):
                continue
            row[slot] = path
        if row:
            clean[mat] = row

    _apply_vision_fallback(
        clean, materials, texture_files, slot_set, marks=vision_marks,
    )
    return clean


def _route_file_to_material(path: str, materials: list[str]) -> str | None:
    """Pick which material an unclassified file belongs to.

    Single-material models (most VRChat/MMD avatars after consolidation):
    every unused texture must belong to the only material, regardless of
    filename. Returning early skips the name-match heuristic entirely.

    Multi-material: take the first material whose name (lowercased) appears
    in the file stem. Returns None if no material matches — the caller
    skips rather than guess, since misrouting wastes a VLM call AND
    pollutes the wrong material's slots.
    """
    if len(materials) == 1:
        return materials[0] or None
    base = Path(path).stem.lower()
    for mat in materials:
        if mat and mat.lower() in base:
            return mat
    return None


def _apply_vision_fallback(
    clean: dict[str, dict[str, str]],
    materials: list[str],
    texture_files: list[str],
    slot_set: set[str],
    *,
    marks: dict[str, list[str]] | None = None,
) -> None:
    """Issue #22 Stage 1: PBR-classify Layer-2 leftovers via a vision LLM.

    Layer 2 (filename LLM + suffix-token gate) is conservative on purpose —
    it prefers an empty slot to a wrong texture. When a vision model is
    configured, this fallback inspects pixels of files Layer 2 didn't use
    and fills missing slots. Bypasses `_has_slot_token` deliberately: the
    VLM saw the actual image, which is stronger evidence than the filename.

    Silent on every failure: no vision_model, no routable file, VLM raises,
    unrecognized reply — the result is identical to Layer 2 alone. This
    matters because the widget pre-fill is non-blocking and a broken VLM
    must not interrupt the agent loop.

    Mutates `clean` in place.
    """
    if not vision_available():
        return

    used: set[str] = {p for slots in clean.values() for p in slots.values()}
    candidate_files = [f for f in texture_files if f not in used]
    if not candidate_files:
        return

    # Pre-route every candidate so we can bail before instantiating the
    # VisionClient when there's nothing to classify (skips network setup
    # in the all-slots-filled case).
    work: dict[str, list[str]] = {}
    for fp in candidate_files:
        mat = _route_file_to_material(fp, materials)
        if mat is None:
            continue
        unfilled = slot_set - set(clean.get(mat, {}).keys())
        if not unfilled:
            continue
        work.setdefault(mat, []).append(fp)
    if not work:
        return

    try:
        vc = VisionClient.from_settings()
    except Exception:
        return

    for mat, files in work.items():
        unfilled = slot_set - set(clean.get(mat, {}).keys())
        for fp in files:
            if not unfilled:
                break
            try:
                b64, mime = image_to_base64(fp)
                reply = vc.classify_image(_VISION_PROMPT, b64, mime)
            except Exception:
                continue
            token = reply.strip().lower().replace(" ", "_").replace("-", "_")
            slot = _VISION_TOKEN_TO_SLOT.get(token)
            if slot is None or slot not in unfilled:
                continue
            clean.setdefault(mat, {})[slot] = fp
            unfilled.discard(slot)
            if marks is not None:
                marks.setdefault(mat, []).append(slot)


# ── Stage 3: reverse texture inference (experimental, flag-gated) ─────────


# Distinct hues for material color-coding in the UV layout overlay. The
# VLM is told which material maps to which color via the prompt, so the
# concrete RGB values just need to be visually separable.
_REVERSE_PALETTE: tuple[tuple[int, int, int], ...] = (
    (255,   0,   0),  # red
    (  0,   0, 255),  # blue
    (  0, 200,   0),  # green
    (255, 165,   0),  # orange
    (160,   0, 200),  # purple
    (  0, 200, 200),  # cyan
    (255, 255,   0),  # yellow
    (255,   0, 200),  # magenta
)

_REVERSE_INFER_PROMPT_TMPL: str = (
    "Texture image: '{tex_name}'. The companion image shows the mesh's UV "
    "layout color-coded per material: {color_legend}. "
    "Which material does this texture belong to? "
    "Reply with EXACTLY ONE material name from this list: {mat_list}. "
    "If you cannot tell, reply 'unknown'. No prose."
)


def _parse_reverse_inference_reply(reply: str, materials: list[str]) -> str | None:
    """Extract a material name from a (possibly verbose) VLM reply.

    Tries an exact case-insensitive match first; falls back to scanning
    the reply for any material-name substring. Returns None for 'unknown'
    or any garbage that doesn't contain a known material name.
    """
    norm = (reply or "").strip().lower()
    if not norm or "unknown" in norm:
        return None
    # Exact match wins (handles the "EXACTLY ONE material name" case).
    for m in materials:
        if m.lower() == norm:
            return m
    # Substring scan for verbose replies.
    for m in materials:
        if m.lower() in norm:
            return m
    return None


def _render_uv_layout_colored(
    client: BlenderClient,
    target_object: str,
    materials: list[str],
) -> tuple[str, str]:
    """Render the mesh's full UV layout color-coded per material slot.

    Returns (base64_jpeg, mime). Raises on any Blender / Pillow error so
    the caller knows to fall through. The overlay is a 512×512 JPEG so
    the wire payload stays small.
    """
    from PIL import Image, ImageDraw

    header = (
        f"import bpy, json\n"
        f"_target = {target_object!r}\n"
        f"_mats = {list(materials)!r}\n"
        f"_sentinel = {BLENDER_SENTINEL!r}\n"
    )
    body = textwrap.dedent("""\
        obj = bpy.data.objects.get(_target)
        if obj is None or obj.type != "MESH":
            print(_sentinel)
            print("PRECONDITION:object_not_found")
        else:
            mesh = obj.data
            uv_layer = mesh.uv_layers.active.data if mesh.uv_layers.active else None
            polys_by_mat = {m: [] for m in _mats}
            if uv_layer is not None:
                idx_for = {}
                for name in _mats:
                    idx_for[name] = -1
                    for i, mx in enumerate(mesh.materials):
                        if mx is not None and mx.name == name:
                            idx_for[name] = i
                            break
                for poly in mesh.polygons:
                    for name in _mats:
                        if idx_for[name] >= 0 and poly.material_index == idx_for[name]:
                            verts = []
                            for li in poly.loop_indices:
                                uv = uv_layer[li].uv
                                verts.append([float(uv[0]), float(uv[1])])
                            polys_by_mat[name].append(verts)
                            break
            print(_sentinel)
            print("UV:" + json.dumps(polys_by_mat))
    """)
    lines = client.execute_and_extract(header + body)
    if not lines or not lines[0].startswith("UV:"):
        raise RuntimeError("UV layout extraction failed")
    polys_by_mat = json.loads(lines[0][len("UV:"):])

    canvas = Image.new("RGB", (512, 512), (32, 32, 32))
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    for idx, name in enumerate(materials):
        color = _REVERSE_PALETTE[idx % len(_REVERSE_PALETTE)]
        for poly in polys_by_mat.get(name, []):
            if len(poly) < 2:
                continue
            pts = [(u * w, (1 - v) * h) for (u, v) in poly]
            for i in range(len(pts)):
                draw.line(
                    [pts[i], pts[(i + 1) % len(pts)]],
                    fill=color, width=1,
                )

    import base64 as _b64
    import io as _io
    buf = _io.BytesIO()
    canvas.save(buf, format="JPEG", quality=85)
    return (_b64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg")


def _composite_texture_with_layout(
    texture_path: str,
    layout_b64: str,
) -> tuple[str, str]:
    """Build a side-by-side JPEG of (texture | UV layout) for the VLM.

    Two distinct images would also work but a single composite halves
    the upload size and most VLMs pay better attention to a single image
    than to "compare these two" prompts.
    """
    import base64 as _b64
    import io as _io

    from PIL import Image

    tex = Image.open(texture_path)
    if tex.mode != "RGB":
        tex = tex.convert("RGB")
    if max(tex.size) > 512:
        scale = 512 / max(tex.size)
        tex = tex.resize(
            (max(1, int(tex.size[0] * scale)),
             max(1, int(tex.size[1] * scale))),
            Image.LANCZOS,
        )

    layout = Image.open(_io.BytesIO(_b64.b64decode(layout_b64)))
    if layout.mode != "RGB":
        layout = layout.convert("RGB")
    # Match heights for clean side-by-side stitching.
    if layout.size[1] != tex.size[1]:
        ratio = tex.size[1] / layout.size[1]
        layout = layout.resize(
            (max(1, int(layout.size[0] * ratio)), tex.size[1]),
            Image.LANCZOS,
        )

    out = Image.new("RGB", (tex.size[0] + layout.size[0], tex.size[1]),
                    (0, 0, 0))
    out.paste(tex, (0, 0))
    out.paste(layout, (tex.size[0], 0))

    buf = _io.BytesIO()
    out.save(buf, format="JPEG", quality=85)
    return (_b64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg")


async def infer_textures_by_reverse_uv_layout(
    client: BlenderClient,
    target_object: str,
    materials: list[str],
    texture_files: list[str],
) -> dict[str, dict[str, str]]:
    """Issue #22 Stage 3 — experimental reverse texture-to-material inference.

    Gated by BOTH `vision_available()` AND `settings.vision_reverse_inference`.
    When either is false, returns `{}` and makes no network/Blender calls.

    Algorithm:
      1. Render the mesh's UV layout once, color-coded per material slot.
      2. For each candidate texture, composite (texture | layout) and ask
         the VLM which material the texture belongs to.
      3. Returns {material_name: {"Base Color": file_path}}. Slot defaults
         to "Base Color" because this layer answers WHICH MATERIAL, not
         which PBR channel — channel classification is Layer 3's job.

    All results are SUGGESTIONS. The caller is responsible for marking
    them experimental in the widget payload and never auto-applying.

    Silent on every failure (vision off, flag off, render failure, VLM
    exception, unknown reply) — pre-existing pipeline keeps working.
    """
    if not vision_available() or not getattr(settings, "vision_reverse_inference", False):
        return {}
    if not materials or not texture_files:
        return {}

    try:
        vc = VisionClient.from_settings()
    except Exception:
        return {}

    try:
        layout_b64, _ = _render_uv_layout_colored(client, target_object, materials)
    except Exception:
        return {}

    color_legend = ", ".join(
        f"{m}={_REVERSE_PALETTE[i % len(_REVERSE_PALETTE)]}"
        for i, m in enumerate(materials)
    )

    out: dict[str, dict[str, str]] = {}
    for tex_path in texture_files:
        try:
            composite_b64, mime = _composite_texture_with_layout(tex_path, layout_b64)
        except Exception:
            continue
        prompt = _REVERSE_INFER_PROMPT_TMPL.format(
            tex_name=Path(tex_path).name,
            color_legend=color_legend,
            mat_list=", ".join(materials),
        )
        try:
            reply = vc.classify_image(prompt, composite_b64, mime)
        except Exception:
            continue
        mat = _parse_reverse_inference_reply(reply, materials)
        if mat is None:
            continue
        out.setdefault(mat, {})["Base Color"] = tex_path
    return out


# ── Phase 5pre ────────────────────────────────────────────────────────────────


class MaterialConsolidate(PhaseTool):
    """
    Phase 5pre: Deduplicate materials that share the same texture set.

    Many source models (especially VRChat community bases) split one logical
    material into many Blender materials (face.001/.002, body_a/body_b...) that
    all reference the same image files. Without consolidation, every downstream
    step (texture classification, node wiring, MDF2 generation) repeats the same
    work for each duplicate.

    Two modes:
      dry_run=True  (default): scan mesh, group materials by the set of image
                                filepaths referenced anywhere in their node tree,
                                return a proposal with keeper + to_remove for each
                                group. Does NOT mutate the scene.
      dry_run=False           : accept a confirmed `groups` list, reassign polygon
                                material_index, remove redundant slots.

    "Texture set" = sorted tuple of normalized absolute filepaths from every
    TEX_IMAGE node in a material's node tree (regardless of whether the node is
    connected to the Principled BSDF). Materials with no textures form their own
    singleton group (no merge).
    """

    @property
    def name(self) -> str:
        return "material_consolidate"

    @property
    def advances_phase(self) -> bool:
        return False

    @classmethod
    def tool_schema(cls) -> dict[str, Any]:
        return {
            "name": "material_consolidate",
            "description": (
                "Phase 5pre: Deduplicates Blender materials that share an identical "
                "texture set on a single mesh. "
                "INPUT: mesh with possibly many materials referencing the same image files. "
                "OUTPUT (dry_run=True): grouping proposal — list of {keeper, to_remove[]} "
                "per shared texture set; no scene mutation. "
                "OUTPUT (dry_run=False): scene mutated — for each group, polygons with "
                "material_index pointing to to_remove[] are reassigned to keeper, then "
                "redundant material slots are removed. "
                "Call this BEFORE material_inspect to shrink the material count the LLM "
                "must classify. VRChat community bases typically collapse from ~30 to ~6 materials."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "target_object": {
                        "type": "string",
                        "description": "Name of the MESH object in the Blender scene.",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": (
                            "True: scan and return grouping proposal without mutating scene. "
                            "False: execute merges from the supplied `groups` list."
                        ),
                        "default": True,
                    },
                    "groups": {
                        "type": "array",
                        "description": (
                            "Required when dry_run=False. List of confirmed merges: "
                            "[{keeper: <material_name>, to_remove: [<material_name>, ...]}, ...]. "
                            "Each to_remove material's faces are reassigned to keeper, "
                            "then the slot is removed from the mesh."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "keeper": {"type": "string"},
                                "to_remove": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["keeper", "to_remove"],
                        },
                    },
                },
                "required": ["target_object"],
            },
        }

    def run(
        self,
        client: BlenderClient,
        cache: SceneCache,
        params: dict,
    ) -> PhaseResult:
        target_object = params.get("target_object", "")
        dry_run = params.get("dry_run", True)
        groups: list = params.get("groups", [])

        if not target_object:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message="'target_object' is required.",
                )
            )
        if not dry_run and not groups:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message="'groups' is required when dry_run=False.",
                    suggestion="Run with dry_run=True first to obtain the grouping proposal.",
                )
            )

        state_before = cache.refresh()

        try:
            if dry_run:
                err, payload = self._scan_groups(client, target_object)
            else:
                err, payload = self._execute_merges(client, target_object, groups)
            if err is not None:
                return PhaseResult.fail(err)
        except BlenderError as exc:
            return PhaseResult.fail(
                PhaseError(
                    category="unexpected",
                    operator="",
                    message="Blender error during material consolidation.",
                    raw=str(exc),
                )
            )
        except OSError as exc:
            return PhaseResult.fail(
                PhaseError(
                    category="timeout",
                    operator="",
                    message="Lost connection to Blender during material consolidation.",
                    raw=str(exc),
                )
            )

        state_after = cache.refresh()
        diff = state_before.diff(state_after)
        diff.update(payload)
        return PhaseResult.ok(diff)

    # ── private helpers ────────────────────────────────────────────────────

    def _scan_groups(
        self,
        client: BlenderClient,
        target_object: str,
    ) -> tuple[PhaseError | None, dict]:
        header = (
            f"import bpy, json, os\n"
            f"_target = {target_object!r}\n"
            f"_sentinel = {BLENDER_SENTINEL!r}\n"
        )
        body = textwrap.dedent("""\
            def _norm(p):
                if not p:
                    return ""
                try:
                    return os.path.normcase(os.path.normpath(bpy.path.abspath(p)))
                except Exception:
                    return p

            obj = bpy.data.objects.get(_target)
            if obj is None or obj.type != "MESH":
                print(_sentinel)
                print("PRECONDITION:object_not_found:" + _target)
            else:
                mat_textures = {}
                mat_basenames = {}
                for mat in obj.data.materials:
                    if mat is None:
                        continue
                    paths = set()
                    if mat.node_tree is not None:
                        for n in mat.node_tree.nodes:
                            if n.type == "TEX_IMAGE" and n.image is not None:
                                fp = _norm(n.image.filepath)
                                if fp:
                                    paths.add(fp)
                    key = tuple(sorted(paths))
                    mat_textures[mat.name] = key
                    mat_basenames[mat.name] = sorted({os.path.basename(p) for p in paths})

                groups_dict = {}
                for mat in obj.data.materials:
                    if mat is None or mat.name not in mat_textures:
                        continue
                    key = mat_textures[mat.name]
                    groups_dict.setdefault(key, []).append(mat.name)

                groups_out = []
                for key, members in groups_dict.items():
                    if not key:
                        for m in members:
                            groups_out.append({
                                "texture_set": [],
                                "materials": [m],
                                "keeper": m,
                                "to_remove": [],
                                "is_singleton": True,
                            })
                        continue
                    keeper = members[0]
                    to_remove = members[1:]
                    groups_out.append({
                        "texture_set": mat_basenames[keeper],
                        "materials": list(members),
                        "keeper": keeper,
                        "to_remove": to_remove,
                        "is_singleton": len(members) == 1,
                    })

                print(_sentinel)
                print("GROUPS:" + json.dumps({
                    "consolidation_groups": groups_out,
                    "material_count_before": len([m for m in obj.data.materials if m is not None]),
                }))
        """)
        code = header + body
        lines = client.execute_and_extract(code)
        err, payload = self._parse_scan_result(lines)
        if err is None and isinstance(payload, dict):
            # Issue #22 Stage 2: ask VLM whether partial-overlap groups
            # actually share UV space. Silent skip on every failure path.
            groups = payload.get("consolidation_groups") or []
            try:
                proposals = self._propose_uv_assist_merges(
                    client, target_object, groups,
                )
            except Exception:
                proposals = []
            if proposals:
                payload["vision_merge_proposals"] = proposals
        return err, payload

    # ── Stage 2: UV-assist vision merge ────────────────────────────────────

    def _propose_uv_assist_merges(
        self,
        client: BlenderClient,
        target_object: str,
        groups: list[dict],
    ) -> list[dict]:
        """Ask the configured VLM whether each partial-overlap material pair
        actually shares the same UV region on their shared texture.

        Returns [{keeper, to_remove, shared_texture, confidence,
        vision_suggested}] for every pair the VLM said YES to (any
        confidence). The agent loop is responsible for thresholding /
        surfacing for user confirmation — see spec §"Stage 2 验收标准".

        Silent on every failure path (vision unavailable, no candidates,
        render error, network error, unparseable reply). The legacy
        exact-match merge pipeline always still works.
        """
        if not vision_available():
            return []
        candidates = _find_partial_overlap_candidates(groups)
        if not candidates:
            return []
        try:
            vc = VisionClient.from_settings()
        except Exception:
            return []

        proposals: list[dict] = []
        for mat_a, mat_b, shared in candidates:
            if not shared:
                continue
            texture_path = shared[0]
            try:
                image_b64, mime = self._render_uv_overlay(
                    client, target_object, mat_a, mat_b, texture_path,
                )
            except Exception:
                continue
            prompt = _UV_OVERLAP_PROMPT_TMPL.format(
                tex_name=Path(texture_path).name,
                mat_a=mat_a, mat_b=mat_b,
            )
            try:
                reply = vc.classify_image(prompt, image_b64, mime)
            except Exception:
                continue
            verdict, confidence = _parse_uv_overlap_reply(reply)
            if verdict == "yes":
                proposals.append({
                    "keeper": mat_a,
                    "to_remove": [mat_b],
                    "shared_texture": Path(texture_path).name,
                    "confidence": confidence,
                    "vision_suggested": True,
                })
        return proposals

    def _render_uv_overlay(
        self,
        client: BlenderClient,
        target_object: str,
        mat_a: str,
        mat_b: str,
        texture_path: str,
    ) -> tuple[str, str]:
        """Render a JPEG (base64, mime) of the texture with both materials'
        UV wireframes overlaid — mat_a in red, mat_b in blue.

        Blender returns the per-material UV polygons; we composite on the
        server with Pillow so the Blender side doesn't need PIL (it's not
        guaranteed in every Blender bundle).
        """
        from PIL import Image, ImageDraw

        # 1) Ask Blender for per-material UV polygons.
        uv_data = self._extract_uv_polygons(client, target_object, mat_a, mat_b)
        if uv_data is None:
            raise RuntimeError("UV extraction returned no data")

        # 2) Open the shared texture and downsize for the VLM.
        img = Image.open(texture_path)
        if img.mode != "RGB":
            img = img.convert("RGB")
        if max(img.size) > 512:
            scale = 512 / max(img.size)
            img = img.resize(
                (max(1, int(img.size[0] * scale)),
                 max(1, int(img.size[1] * scale))),
                Image.LANCZOS,
            )

        # 3) Draw wireframes. UV (0,0) is bottom-left in Blender — flip Y.
        draw = ImageDraw.Draw(img)
        w, h = img.size
        for mat_name, color in ((mat_a, (255, 0, 0)), (mat_b, (0, 0, 255))):
            for poly in uv_data.get(mat_name, []):
                if len(poly) < 2:
                    continue
                pts = [(u * w, (1 - v) * h) for (u, v) in poly]
                for i in range(len(pts)):
                    draw.line(
                        [pts[i], pts[(i + 1) % len(pts)]],
                        fill=color, width=1,
                    )

        # 4) JPEG-encode, base64.
        import base64 as _b64
        import io as _io
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return (_b64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg")

    @staticmethod
    def _extract_uv_polygons(
        client: BlenderClient,
        target_object: str,
        mat_a: str,
        mat_b: str,
    ) -> dict[str, list[list[list[float]]]] | None:
        """Run a Blender script that emits per-material UV polygons.

        Returns {mat_name: [[[u,v], [u,v], ...], ...]} — list of polygons,
        each polygon a list of (u,v) vertex pairs. None on any error.
        """
        header = (
            f"import bpy, json\n"
            f"_target = {target_object!r}\n"
            f"_mat_a = {mat_a!r}\n"
            f"_mat_b = {mat_b!r}\n"
            f"_sentinel = {BLENDER_SENTINEL!r}\n"
        )
        body = textwrap.dedent("""\
            obj = bpy.data.objects.get(_target)
            if obj is None or obj.type != "MESH":
                print(_sentinel)
                print("PRECONDITION:object_not_found")
            else:
                mesh = obj.data
                uv_layer = mesh.uv_layers.active.data if mesh.uv_layers.active else None
                polys_by_mat = {_mat_a: [], _mat_b: []}
                if uv_layer is not None:
                    mat_idx = {}
                    for name in (_mat_a, _mat_b):
                        mat_idx[name] = -1
                        for i, m in enumerate(mesh.materials):
                            if m is not None and m.name == name:
                                mat_idx[name] = i
                                break
                    for poly in mesh.polygons:
                        for name in (_mat_a, _mat_b):
                            if mat_idx[name] >= 0 and poly.material_index == mat_idx[name]:
                                verts = []
                                for li in poly.loop_indices:
                                    uv = uv_layer[li].uv
                                    verts.append([float(uv[0]), float(uv[1])])
                                polys_by_mat[name].append(verts)
                                break
                print(_sentinel)
                print("UV:" + json.dumps(polys_by_mat))
        """)
        try:
            lines = client.execute_and_extract(header + body)
        except Exception:
            return None
        if not lines or not lines[0].startswith("UV:"):
            return None
        try:
            return json.loads(lines[0][len("UV:"):])
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _parse_scan_result(lines: list[str]) -> tuple[PhaseError | None, dict]:
        if not lines:
            return (
                PhaseError(
                    category="operator_failed",
                    operator="",
                    message="Material consolidation scan returned no output from Blender.",
                ),
                {},
            )
        if lines[0].startswith("PRECONDITION:"):
            detail = lines[0][len("PRECONDITION:"):]
            return (
                PhaseError(
                    category="precondition",
                    operator="",
                    message=f"Target object not found or not a mesh: {detail}",
                ),
                {},
            )
        if lines[0].startswith("GROUPS:"):
            try:
                return None, json.loads(lines[0][len("GROUPS:"):])
            except json.JSONDecodeError:
                return (
                    PhaseError(
                        category="unexpected",
                        operator="",
                        message="Could not parse consolidation scan JSON from Blender.",
                    ),
                    {},
                )
        return (
            PhaseError(
                category="unexpected",
                operator="",
                message=f"Unexpected output from consolidation scan: {lines[0]!r}",
            ),
            {},
        )

    def _execute_merges(
        self,
        client: BlenderClient,
        target_object: str,
        groups: list,
    ) -> tuple[PhaseError | None, dict]:
        groups_json = json.dumps(groups, ensure_ascii=False)
        header = (
            f"import bpy, json\n"
            f"_target = {target_object!r}\n"
            f"_groups = json.loads({groups_json!r})\n"
            f"_sentinel = {BLENDER_SENTINEL!r}\n"
        )
        body = textwrap.dedent("""\
            obj = bpy.data.objects.get(_target)
            if obj is None or obj.type != "MESH":
                print(_sentinel)
                print("PRECONDITION:object_not_found:" + _target)
            else:
                mesh = obj.data
                merged = []
                skipped = []
                count_before = len([m for m in mesh.materials if m is not None])

                for grp in _groups:
                    keeper = grp.get("keeper", "")
                    to_remove = list(grp.get("to_remove", []))
                    if not keeper or not to_remove:
                        continue

                    def _idx(name):
                        for i, m in enumerate(mesh.materials):
                            if m is not None and m.name == name:
                                return i
                        return -1

                    keeper_idx = _idx(keeper)
                    if keeper_idx < 0:
                        skipped.append(keeper + ":keeper_not_found")
                        continue

                    removed_here = []
                    for rm_name in to_remove:
                        rm_idx = _idx(rm_name)
                        if rm_idx < 0:
                            skipped.append(rm_name + ":not_found")
                            continue
                        if rm_idx == keeper_idx:
                            skipped.append(rm_name + ":same_as_keeper")
                            continue

                        for poly in mesh.polygons:
                            if poly.material_index == rm_idx:
                                poly.material_index = keeper_idx

                        mesh.materials.pop(index=rm_idx)

                        for poly in mesh.polygons:
                            if poly.material_index > rm_idx:
                                poly.material_index -= 1

                        if rm_idx < keeper_idx:
                            keeper_idx -= 1
                        removed_here.append(rm_name)

                    if removed_here:
                        merged.append({"keeper": keeper, "removed": removed_here})

                count_after = len([m for m in mesh.materials if m is not None])
                print(_sentinel)
                print("MERGED:" + json.dumps({
                    "merged_groups": merged,
                    "skipped": skipped,
                    "material_count_before": count_before,
                    "material_count_after": count_after,
                }))
        """)
        code = header + body
        lines = client.execute_and_extract(code)
        return self._parse_merge_result(lines)

    @staticmethod
    def _parse_merge_result(lines: list[str]) -> tuple[PhaseError | None, dict]:
        if not lines:
            return (
                PhaseError(
                    category="operator_failed",
                    operator="",
                    message="Material consolidation merge returned no output from Blender.",
                ),
                {},
            )
        if lines[0].startswith("PRECONDITION:"):
            detail = lines[0][len("PRECONDITION:"):]
            return (
                PhaseError(
                    category="precondition",
                    operator="",
                    message=f"Target object not found or not a mesh: {detail}",
                ),
                {},
            )
        if lines[0].startswith("MERGED:"):
            try:
                return None, json.loads(lines[0][len("MERGED:"):])
            except json.JSONDecodeError:
                return (
                    PhaseError(
                        category="unexpected",
                        operator="",
                        message="Could not parse consolidation merge JSON from Blender.",
                    ),
                    {},
                )
        return (
            PhaseError(
                category="unexpected",
                operator="",
                message=f"Unexpected output from consolidation merge: {lines[0]!r}",
            ),
            {},
        )


# ── Phase 5A ──────────────────────────────────────────────────────────────────


class MaterialInspect(PhaseTool):
    """
    Phase 5A: Read-only inspector.

    Returns the data the agent loop needs to classify textures:
      - materials: list of material names on the target mesh
      - texture_files: list of absolute paths to image files in texture_dir
      - existing_connections: {mat_name: {slot: path_or_status}}
        slot status: absolute path string | "connected_no_image" | null

    The agent loop performs LLM filename classification + vision model fallback +
    user confirmation between this tool and MaterialSetup.
    """

    @property
    def name(self) -> str:
        return "material_inspect"

    @property
    def advances_phase(self) -> bool:
        return False

    @classmethod
    def tool_schema(cls) -> dict[str, Any]:
        return {
            "name": "material_inspect",
            "description": (
                "Phase 5A: Inspect a mesh object's materials and scan a texture directory. "
                "Returns material names, texture file paths, and existing Principled BSDF "
                "node connections. Use this before MaterialSetup to gather classification data."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "target_object": {
                        "type": "string",
                        "description": "Name of the MESH object in the Blender scene.",
                    },
                    "texture_dir": {
                        "type": "string",
                        "description": (
                            "Absolute path to the directory containing source texture files "
                            "(.png, .tga, .dds, .jpg, .tif, .bmp). All files in this "
                            "directory are included regardless of subdirectory."
                        ),
                    },
                    "purpose": {
                        "type": "string",
                        "enum": ["classify", "verify"],
                        "description": (
                            "Call intent. 'classify' (default) — initial scan or re-do loop "
                            "entry; the agent loop emits the material confirmation widget so "
                            "the user can pick texture assignments. 'verify' — post-wire "
                            "read-back at Phase 5A Step 6; the widget is suppressed so the "
                            "LLM can render a text summary and ask Yes/No directly. Use "
                            "'verify' immediately after a material_setup call; use 'classify' "
                            "otherwise."
                        ),
                    },
                },
                "required": ["target_object", "texture_dir"],
            },
        }

    def run(
        self,
        client: BlenderClient,
        cache: SceneCache,
        params: dict,
    ) -> PhaseResult:
        target_object = params.get("target_object", "")
        texture_dir = params.get("texture_dir", "")

        if not target_object:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message="'target_object' is required.",
                )
            )
        if not texture_dir:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message="'texture_dir' is required.",
                )
            )

        tex_files = self._scan_texture_dir(texture_dir)
        if tex_files is None:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message=f"texture_dir not found or is not a directory: {texture_dir!r}",
                    suggestion="Provide an absolute path to the folder containing texture files.",
                )
            )

        state_before = cache.refresh()

        try:
            err, materials, connections = self._inspect_scene(client, target_object)
            if err is not None:
                return PhaseResult.fail(err)
        except BlenderError as exc:
            return PhaseResult.fail(
                PhaseError(
                    category="unexpected",
                    operator="",
                    message="Blender error during material inspection.",
                    raw=str(exc),
                )
            )
        except OSError as exc:
            return PhaseResult.fail(
                PhaseError(
                    category="timeout",
                    operator="",
                    message="Lost connection to Blender during material inspection.",
                    raw=str(exc),
                )
            )

        state_after = cache.refresh()
        diff = state_before.diff(state_after)
        diff["materials"] = materials
        diff["texture_files"] = tex_files
        diff["existing_connections"] = connections
        return PhaseResult.ok(diff)

    # ── private helpers ────────────────────────────────────────────────────

    @staticmethod
    def _scan_texture_dir(texture_dir: str) -> list[str] | None:
        p = Path(texture_dir)
        if not p.is_dir():
            return None
        return sorted(
            str(f) for f in p.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        )

    def _inspect_scene(
        self,
        client: BlenderClient,
        target_object: str,
    ) -> tuple[PhaseError | None, list[str], dict]:
        header = (
            f"import bpy, json\n"
            f"_target = {target_object!r}\n"
            f"_sentinel = {BLENDER_SENTINEL!r}\n"
            f"{SLOT_SOCKET_SRC}\n"
        )
        body = textwrap.dedent("""\
            def _trace_to_image(node, depth=0):
                if depth > 6:
                    return "connected_no_image"
                if node.type == "TEX_IMAGE":
                    return bpy.path.abspath(node.image.filepath) if node.image else "connected_no_image"
                for inp in node.inputs:
                    if inp.is_linked:
                        r = _trace_to_image(inp.links[0].from_node, depth + 1)
                        if r:
                            return r
                return "connected_no_image"

            obj = bpy.data.objects.get(_target)
            if obj is None or obj.type != "MESH":
                print(_sentinel)
                print("PRECONDITION:object_not_found:" + _target)
            else:
                SLOTS = ("Base Color", "Alpha", "Roughness", "Metallic", "Emission", "Normal")
                materials = [m.name for m in obj.data.materials if m is not None]
                connections = {}
                for mat in obj.data.materials:
                    if mat is None:
                        continue
                    slot_state = {s: None for s in SLOTS}
                    if mat.node_tree is not None:
                        pbs = next(
                            (n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"),
                            None,
                        )
                        if pbs is not None:
                            for slot in SLOTS:
                                inp = _slot_socket(pbs, slot)
                                if inp is not None and inp.is_linked:
                                    slot_state[slot] = _trace_to_image(inp.links[0].from_node)
                    connections[mat.name] = slot_state
                print(_sentinel)
                print("INSPECT:" + json.dumps({"materials": materials, "connections": connections}))
        """)
        code = header + body
        lines = client.execute_and_extract(code)
        if not lines:
            return (
                PhaseError(
                    category="operator_failed",
                    operator="",
                    message="Material inspection returned no output from Blender.",
                ),
                [],
                {},
            )
        if lines[0].startswith("PRECONDITION:"):
            detail = lines[0][len("PRECONDITION:"):]
            return (
                PhaseError(
                    category="precondition",
                    operator="",
                    message=f"Target object not found or not a mesh: {detail}",
                    suggestion="Ensure the mesh object name is correct and exists in the scene.",
                ),
                [],
                {},
            )
        if lines[0].startswith("INSPECT:"):
            try:
                data = json.loads(lines[0][len("INSPECT:"):])
                return None, data.get("materials", []), data.get("connections", {})
            except json.JSONDecodeError:
                return (
                    PhaseError(
                        category="unexpected",
                        operator="",
                        message="Could not parse material inspection JSON from Blender.",
                    ),
                    [],
                    {},
                )
        return (
            PhaseError(
                category="unexpected",
                operator="",
                message=f"Unexpected output from material inspection: {lines[0]!r}",
            ),
            [],
            {},
        )


# ── Phase 5B ──────────────────────────────────────────────────────────────────


class MaterialSetup(PhaseTool):
    """
    Phase 5B: Wire confirmed texture mapping into Principled BSDF nodes.

    Receives the agent-loop-confirmed texture_mapping and executes node
    wiring for all materials. Normal slot wiring is x_preset-dependent:
      VRChat  — inserts Y-inversion chain (1-Y on green channel)
      終末地  — direct connection via NormalMap node

    MMD models skip this tool entirely.
    """

    @property
    def name(self) -> str:
        return "material_setup"

    @property
    def advances_phase(self) -> bool:
        return False

    @classmethod
    def tool_schema(cls) -> dict[str, Any]:
        return {
            "name": "material_setup",
            "description": (
                "Phase 5B: Wires texture image files into Principled BSDF (PBS) nodes. "
                "THIS TOOL IS FOR PRINCIPLED BSDF MATERIALS ONLY. "
                "Do NOT call this for Emission or MMDShaderDev materials — those shader types "
                "have their own relevant sockets (Emission: Color only; MMDShaderDev: Base Tex / "
                "Base Alpha) and are never wired via this tool. "
                "Call this only when material_inspect reports output_shader=BSDF and "
                "existing_connections shows null (blank) slots. "
                "LLM texture classification (filename rules + user confirmation) runs before "
                "calling this tool. "
                "Normal slot wiring is x_preset-dependent: VRChat (OpenGL normals) inserts a "
                "1-Y inversion chain; 終末地 (DirectX) connects directly. "
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "target_object": {
                        "type": "string",
                        "description": "Name of the MESH object in the Blender scene.",
                    },
                    "x_preset": {
                        "type": "string",
                        "enum": ["VRChat", "終末地"],
                        "description": (
                            "Source model preset. Controls Normal slot wiring: "
                            "VRChat=OpenGL (Y-inversion inserted), 終末地=DirectX (direct)."
                        ),
                    },
                    "texture_mapping": {
                        "type": "object",
                        "description": (
                            "Confirmed mapping: {mat_name: {slot: filepath_or_null}}. "
                            "Slot keys: 'Base Color', 'Alpha', 'Roughness', 'Metallic', "
                            "'Emission', 'Normal'. A null value skips that slot."
                        ),
                    },
                },
                "required": ["target_object", "x_preset", "texture_mapping"],
            },
        }

    def run(
        self,
        client: BlenderClient,
        cache: SceneCache,
        params: dict,
    ) -> PhaseResult:
        target_object = params.get("target_object", "")
        x_preset = params.get("x_preset", "")
        texture_mapping: dict = params.get("texture_mapping", {})

        if not target_object:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message="'target_object' is required.",
                )
            )
        if x_preset not in VALID_SETUP_PRESETS:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message=(
                        f"'x_preset' must be one of {sorted(VALID_SETUP_PRESETS)}, "
                        f"got {x_preset!r}. MMD models skip MaterialSetup."
                    ),
                )
            )
        if not texture_mapping:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message="'texture_mapping' must be a non-empty dict.",
                    suggestion="Run material_inspect first, then confirm the mapping with the user.",
                )
            )

        state_before = cache.refresh()

        try:
            err, wired, skipped = self._wire_all_materials(
                client, target_object, x_preset, texture_mapping
            )
            if err is not None:
                return PhaseResult.fail(err)
        except BlenderError as exc:
            return PhaseResult.fail(
                PhaseError(
                    category="unexpected",
                    operator="",
                    message="Blender error during material node wiring.",
                    raw=str(exc),
                )
            )
        except OSError as exc:
            return PhaseResult.fail(
                PhaseError(
                    category="timeout",
                    operator="",
                    message="Lost connection to Blender during material setup.",
                    raw=str(exc),
                )
            )

        state_after = cache.refresh()
        diff = state_before.diff(state_after)
        diff["materials_wired"] = wired
        if skipped:
            diff["slots_skipped"] = skipped
        return PhaseResult.ok(diff)

    # ── private helpers ────────────────────────────────────────────────────

    def _wire_all_materials(
        self,
        client: BlenderClient,
        target_object: str,
        x_preset: str,
        texture_mapping: dict,
    ) -> tuple[PhaseError | None, list[str], list[str]]:
        mapping_json = json.dumps(texture_mapping, ensure_ascii=False)
        normal_chain = _VCHAT_NORMAL_CHAIN if x_preset == "VRChat" else _ZENMO_NORMAL_CHAIN
        header = (
            f"import bpy, json\n"
            f"_target = {target_object!r}\n"
            f"_mapping = json.loads({mapping_json!r})\n"
            f"_sentinel = {BLENDER_SENTINEL!r}\n"
            f"{SLOT_SOCKET_SRC}\n"
        )
        # __NC__ is at 32 spaces in the source string; after dedent removes the
        # 12-space common indent it lands at 20 spaces, matching the indent level
        # inside `if slot == _NORMAL:`. It is replaced with the x_preset-specific
        # normal chain fragment built above.
        body = textwrap.dedent("""\
            obj = bpy.data.objects.get(_target)
            if obj is None or obj.type != "MESH":
                print(_sentinel)
                print("PRECONDITION:object_not_found:" + _target)
            else:
                _NORMAL = "Normal"
                _wired = []
                _skipped = []
                for mat_name, slot_map in _mapping.items():
                    mat = bpy.data.materials.get(mat_name)
                    if mat is None:
                        _skipped.append(mat_name + ".(material_not_found)")
                        continue
                    if not mat.use_nodes:
                        mat.use_nodes = True
                    nodes = mat.node_tree.nodes
                    links = mat.node_tree.links
                    pbs = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
                    if pbs is None:
                        pbs = nodes.new("ShaderNodeBsdfPrincipled")
                        pbs.location = (0, 0)
                    y = 300
                    for slot, fp in slot_map.items():
                        if not fp:
                            continue
                        target_inp = _slot_socket(pbs, slot)
                        if target_inp is None:
                            _skipped.append(mat_name + "." + slot + ".(unknown_slot)")
                            continue
                        try:
                            if slot == _NORMAL:
                                tex = nodes.new("ShaderNodeTexImage")
                                tex.image = bpy.data.images.load(fp, check_existing=True)
                                tex.location = (-900, y)
                                nm = nodes.new("ShaderNodeNormalMap")
                                nm.location = (-150, y)
                                __NC__
                                links.new(nm.outputs[0], target_inp)
                            else:
                                tex = nodes.new("ShaderNodeTexImage")
                                tex.image = bpy.data.images.load(fp, check_existing=True)
                                tex.location = (-500, y)
                                links.new(tex.outputs["Color"], target_inp)
                                if slot == "Emission":
                                    _emission_on(pbs)
                            _wired.append(mat_name + "." + slot)
                        except Exception as e:
                            _skipped.append(mat_name + "." + slot + ":" + str(e))
                        y -= 300
                print(_sentinel)
                print("WIRED:" + json.dumps({"wired": _wired, "skipped": _skipped}))
        """).replace("                    __NC__\n", normal_chain)
        code = header + body
        lines = client.execute_and_extract(code)
        if not lines:
            return (
                PhaseError(
                    category="operator_failed",
                    operator="",
                    message="Material node wiring returned no output from Blender.",
                ),
                [],
                [],
            )
        if lines[0].startswith("PRECONDITION:"):
            detail = lines[0][len("PRECONDITION:"):]
            return (
                PhaseError(
                    category="precondition",
                    operator="",
                    message=f"Target object not found or not a mesh: {detail}",
                ),
                [],
                [],
            )
        if lines[0].startswith("WIRED:"):
            try:
                data = json.loads(lines[0][len("WIRED:"):])
                return None, data.get("wired", []), data.get("skipped", [])
            except json.JSONDecodeError:
                return (
                    PhaseError(
                        category="unexpected",
                        operator="",
                        message="Could not parse wiring result JSON from Blender.",
                    ),
                    [],
                    [],
                )
        return (
            PhaseError(
                category="unexpected",
                operator="",
                message=f"Unexpected output from material setup: {lines[0]!r}",
            ),
            [],
            [],
        )


# ── Phase 5C ──────────────────────────────────────────────────────────────────


class MaterialGenerate(PhaseTool):
    """
    Phase 5C: Configure and run the MDF2 generator.

    Steps:
      1. Set scene properties (natives_root, mesh_collection, texture_base_path).
      2. Call mdf_gen_refresh() — auto-detects node strategy + guesses presets.
      3. Resolve load_preset_enum_items("MHWILDS") to a {display_name: full_path} lookup.
      4. Apply agent-confirmed preset_mapping to material_list entries.
      5. Call mdf_gen_process().

    Returns mdf_collection name for use as mdf2_collection in Phase 6 (BatchExport).
    Materials not in preset_mapping are left with the auto-guessed preset from refresh
    and recorded in state_diff["presets_auto_guessed"].
    """

    @property
    def name(self) -> str:
        return "material_generate"

    @property
    def phase_slot(self) -> str | None:
        return "phase_5"

    @classmethod
    def tool_schema(cls) -> dict[str, Any]:
        return {
            "name": "material_generate",
            "description": (
                "Phase 5C: Reads each material's existing Blender shader node tree and produces "
                "MHWs-native .mdf2 material files and .tex texture files. No shader conversion "
                "or reformatting occurs — the generator reads whatever is already connected to "
                "Material Output. Call this once all material input sockets are wired "
                "(or confirmed already wired for Emission/MMD materials). "
                "OUTPUT: a new MDF2 collection of RE_MDF objects + .mdf2 / .tex files written "
                "under natives/STM/Art/<texture_base_path>/. The MDF2 collection name is "
                "returned for use as `mdf2_collection` in batch_export. "
                "\n"
                "Supported output shader types (auto-detected): Principled BSDF (each socket "
                "analyzed individually), Emission (Color socket read as emissive channel; toon "
                "mode auto-enabled), MMDShaderDev GROUP (Base Tex / Base Alpha sockets). "
                "For each connected socket the generator assigns: DIRECT if an Image Texture "
                "node is connected (path copied as-is), SOLID if a constant value is set "
                "(256×256 solid .tex generated), BAKE if a node chain drives the input "
                "(Cycles renders the result). "
                "PRESET CONCEPT: a preset is an MHWs game-side rendering material definition "
                "(a .json file in RE Mesh Editor's Presets/MHWILDS/ directory). It has NO "
                "relationship to Blender materials or shader types — it only tells the game "
                "engine how to render the mesh in-game. Each Blender material slot maps to "
                "exactly ONE preset (a plain string, never a list or combination). There is "
                "no mixing, stacking, or combining of presets for a single material slot."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "mesh_collection": {
                        "type": "string",
                        "description": (
                            "Blender collection name containing the mesh objects. "
                            "REQUIRED: call list_collections() first and use the exact name "
                            "returned — do not guess. This is the central collection created "
                            "in Phase 3, typically named 'MHWilds_Female.mesh'."
                        ),
                    },
                    "texture_base_path": {
                        "type": "string",
                        "description": (
                            "Sub-path under natives/STM/Art/ for texture output "
                            "(e.g. 'Author/CharName/'). User-specified; not derived from armor JSON."
                        ),
                    },
                    "preset_mapping": {
                        "type": "object",
                        "description": (
                            "Confirmed {mat_name: preset_display_name} map. "
                            "Display names are filenames without .json from "
                            "RE Mesh Editor's Presets/MHWILDS/ directory "
                            "(e.g. 'Hair', 'Skin', 'Character', 'cloth')."
                        ),
                    },
                    "mdf_collection_name": {
                        "type": "string",
                        "description": "Output MDF collection name. Generator auto-derives if omitted.",
                    },
                    "natives_root": {
                        "type": "string",
                        "description": (
                            "Absolute path to the user's mod root folder. "
                            "REQUIRED. Pass any folder path the user specifies — the toolkit "
                            "automatically creates the 'natives/' directory structure inside it "
                            "if it does not exist. Do not assume a 'natives/' subfolder must "
                            "already be present."
                        ),
                    },
                },
                "required": ["mesh_collection", "natives_root", "texture_base_path", "preset_mapping"],
            },
        }

    def run(
        self,
        client: BlenderClient,
        cache: SceneCache,
        params: dict,
    ) -> PhaseResult:
        mesh_collection = params.get("mesh_collection", "")
        texture_base_path = params.get("texture_base_path", "")
        preset_mapping: dict = params.get("preset_mapping", {})
        mdf_collection_name = params.get("mdf_collection_name", "")
        natives_root = params.get("natives_root", "")

        if not mesh_collection:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message="'mesh_collection' is required.",
                )
            )
        if not natives_root:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message=(
                        "'natives_root' is required. Ask the user for their mod root folder path "
                        "(any folder; the toolkit auto-creates the natives/ structure inside it)."
                    ),
                )
            )
        if not texture_base_path:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message="'texture_base_path' is required (e.g. 'Author/CharName/').",
                )
            )
        if preset_mapping is None:
            return PhaseResult.fail(
                PhaseError(
                    category="precondition",
                    operator="",
                    message="'preset_mapping' is required (may be empty dict if all presets are auto-guessed).",
                )
            )

        state_before = cache.refresh()

        try:
            err, result = self._run_generator(
                client,
                mesh_collection=mesh_collection,
                texture_base_path=texture_base_path,
                preset_mapping=preset_mapping,
                mdf_collection_name=mdf_collection_name,
                natives_root=natives_root,
            )
            if err is not None:
                return PhaseResult.fail(err)
        except BlenderError as exc:
            return PhaseResult.fail(
                PhaseError(
                    category="unexpected",
                    operator=_OP_MDF_PROCESS,
                    message="Blender error during MDF2 generation.",
                    raw=str(exc),
                )
            )
        except OSError as exc:
            return PhaseResult.fail(
                PhaseError(
                    category="timeout",
                    operator=_OP_MDF_PROCESS,
                    message="Lost connection to Blender during MDF2 generation.",
                    raw=str(exc),
                )
            )

        state_after = cache.refresh()
        diff = state_before.diff(state_after)
        diff.update(result)
        return PhaseResult.ok(diff)

    # ── private helpers ────────────────────────────────────────────────────

    def _run_generator(
        self,
        client: BlenderClient,
        *,
        mesh_collection: str,
        texture_base_path: str,
        preset_mapping: dict,
        mdf_collection_name: str,
        natives_root: str,
    ) -> tuple[PhaseError | None, dict]:
        mapping_json = json.dumps(preset_mapping, ensure_ascii=False)
        header = (
            f"import bpy, json, sys, io, contextlib, base64, traceback\n"
            f"_col_name = {mesh_collection!r}\n"
            f"_tex_base = {texture_base_path!r}\n"
            f"_mdf_name = {mdf_collection_name!r}\n"
            f"_natives = {natives_root!r}\n"
            f"_mapping = json.loads({mapping_json!r})\n"
            f"_sentinel = {BLENDER_SENTINEL!r}\n"
        )
        body = textwrap.dedent("""\
            # Top-level guard: any setup-phase exception (RE Mesh Editor missing,
            # property group not registered, mdf_gen_refresh failure, etc.) must
            # still reach the sentinel so the Python side gets a real traceback.
            _buf = io.StringIO()
            _exc_tb = ""
            _status = ""
            _result_data = None
            with contextlib.redirect_stdout(_buf), contextlib.redirect_stderr(_buf):
                try:
                    scene = bpy.context.scene
                    col = bpy.data.collections.get(_col_name)
                    if col is None:
                        _status = "PRECONDITION:collection_not_found:" + _col_name
                    else:
                        s = scene.mhws_mdf_generator
                        if _natives:
                            scene["mhws_natives_root"] = _natives
                        s.mesh_collection = col
                        s.texture_base_path = _tex_base
                        if _mdf_name:
                            s.mdf_collection_name = _mdf_name

                        # Pre-bake render config: Cycles + GPU + low samples.
                        # Without this Blender falls back to session defaults
                        # (often Eevee or Cycles+CPU+high samples), making bake
                        # an order of magnitude slower than necessary.
                        scene.render.engine = "CYCLES"
                        try:
                            scene.cycles.device = "GPU"
                            scene.cycles.samples = 4
                            scene.cycles.preview_samples = 4
                        except AttributeError:
                            # cycles addon not enabled — Cycles engine assignment
                            # above would have raised first; safe fallthrough.
                            pass

                        bpy.ops.mhws.mdf_gen_refresh()

                        _load_fn = None
                        for _mod in sys.modules.values():
                            try:
                                attr = getattr(_mod, "load_preset_enum_items", None)
                                if attr is not None and callable(attr):
                                    _load_fn = attr
                                    break
                            except Exception:
                                continue
                        preset_lookup = {}
                        if _load_fn is not None:
                            try:
                                for item in _load_fn("MHWILDS"):
                                    preset_lookup[item[1]] = item[0]
                            except Exception:
                                pass

                        auto_guessed = []
                        for entry in s.material_list:
                            mat_name = entry.blender_material or ""
                            dn = _mapping.get(mat_name)
                            if dn and dn in preset_lookup:
                                entry.material_preset = preset_lookup[dn]
                            else:
                                auto_guessed.append(mat_name)

                        ret = bpy.ops.mhws.mdf_gen_process()
                        processed = [e.blender_material for e in s.material_list if e.blender_material]
                        mdf_col = s.mdf_collection_name
                        if "FINISHED" not in str(ret):
                            _status = "CANCELLED:" + str(ret)
                        else:
                            _result_data = {
                                "mdf_collection": mdf_col,
                                "materials_processed": processed,
                                "presets_auto_guessed": auto_guessed,
                            }
                            _status = "RESULT:" + json.dumps(_result_data)
                except Exception:
                    _exc_tb = traceback.format_exc()

            _captured = _buf.getvalue()
            print(_sentinel)
            if _exc_tb:
                # Last non-blank traceback line is usually the exception summary.
                _tb_lines = [ln for ln in _exc_tb.splitlines() if ln.strip()]
                print("EXCEPTION:" + (_tb_lines[-1] if _tb_lines else "unknown"))
            else:
                print(_status)
            _payload = (_exc_tb + "\\n" + _captured) if _exc_tb else _captured
            print("STDERR_B64:" + base64.b64encode(_payload.encode("utf-8", "replace")).decode("ascii"))
        """)
        code = header + body
        # Bake can take several minutes on large meshes — far longer than the
        # 30s default socket timeout. Use a 10-minute window.
        lines = client.execute_and_extract(code, timeout=600)
        if not lines:
            return (
                PhaseError(
                    category="operator_failed",
                    operator=_OP_MDF_PROCESS,
                    message="MDF2 generator returned no output from Blender.",
                ),
                {},
            )

        # Pull out the captured stdout/stderr line (any position; usually last).
        import base64 as _b64
        captured = ""
        status_lines: list[str] = []
        for ln in lines:
            if ln.startswith("STDERR_B64:"):
                try:
                    captured = _b64.b64decode(ln[len("STDERR_B64:"):]).decode("utf-8", "replace")
                except Exception:
                    captured = ln[len("STDERR_B64:"):]
            else:
                status_lines.append(ln)

        status = status_lines[0] if status_lines else ""
        # Trim captured to keep PhaseError.raw reasonable in size.
        if len(captured) > 4000:
            captured = captured[-4000:]

        if status.startswith("PRECONDITION:"):
            detail = status[len("PRECONDITION:"):]
            return (
                PhaseError(
                    category="precondition",
                    operator="",
                    message=f"Required scene object not found: {detail}",
                    suggestion="Ensure the mesh collection exists and contains mesh objects.",
                    raw=captured,
                ),
                {},
            )
        if status.startswith("EXCEPTION:"):
            exc_msg = status[len("EXCEPTION:"):]
            return (
                PhaseError(
                    category="unexpected",
                    operator=_OP_MDF_PROCESS,
                    message=f"MDF2 generator raised an exception: {exc_msg}",
                    suggestion=(
                        "Check that RE Mesh Editor is installed and enabled in Blender, "
                        "and that the mesh collection contains valid RE MESH objects."
                    ),
                    raw=captured,
                ),
                {},
            )
        if status.startswith("CANCELLED:"):
            return (
                PhaseError(
                    category="operator_failed",
                    operator=_OP_MDF_PROCESS,
                    message=f"MDF2 generator did not finish: {status}",
                    raw=captured,
                ),
                {},
            )
        if status.startswith("RESULT:"):
            try:
                data = json.loads(status[len("RESULT:"):])
                return None, data
            except json.JSONDecodeError:
                return (
                    PhaseError(
                        category="unexpected",
                        operator=_OP_MDF_PROCESS,
                        message="Could not parse MDF2 generator result JSON from Blender.",
                        raw=captured,
                    ),
                    {},
                )
        return (
            PhaseError(
                category="unexpected",
                operator=_OP_MDF_PROCESS,
                message=f"Unexpected output from MDF2 generator: {status!r}",
                raw=captured,
            ),
            {},
        )
