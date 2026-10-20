"""The per-key normals of a Wilds keep-normals mesh: where each (key, vertex) row's normal sits in the
blend-shape payload, and copying them from one mesh into another (kevin 2026-10-15: the GG build reuses
BHS_fixed_sks4b's face exactly).

Why: the importer drops the per-key normals and the exporter recomputes them from the imported face,
whose vertices it splits a little differently, so a re-export moved 3% of the Face's driven-key rows by
more than 2 int8 steps (up to ~20 degrees around the eyelids and mouth). Positions are unaffected. So
the build exports, then copies sks4b's stored normal words back for every paired row, in place
(Blender-MHWilds lesson #27: patch the bytes, do not re-encode).

Layout (after RE-Mesh-Editor-BlendShape tests/test_keep_authored_normals_blender.py): LOD0's payload is
8-byte rows; word 0 = the packed 11/10/11 delta, word 1 = int8 x, y, z normal and a zero byte. Rows run
target by target, channel by channel, sub-mesh entry by entry; a row's vertex is the entry's
subMeshVertexStartIndex + its index (a group-level vertex index, sub-meshes in order).
Pure python: runs in tools-5.2's venv and inside Blender.

Moved from Known_Good_mod_test/scripts/gg/key_rows.py unchanged (ModPilot restructure M3, 2026-10-20)."""
import struct


def row_positions(re_mesh, raw):
    """{key: {group vertex index: u32 word index of its normal word in raw}} for LOD0."""
    blend = re_mesh.blendShapeHeader.blendShapeList[0]
    out, cursor = {}, 0
    for t in list(blend.blendTargetList)[:int(blend.targetCount)]:
        channels = int(getattr(t, "blendShapeNum", 0) or 0)
        entries = list(getattr(t, "subMeshEntryList", []) or [])
        rows = sum(int(e.vertCount) for e in entries) if entries else int(t.vertCount)
        explicit = any(int(getattr(e, "vertOffset", 0) or 0) != 0 for e in entries)
        for ch in range(channels):
            name = re_mesh.rawNameList[re_mesh.blendShapeNameRemapList[int(getattr(t, "blendSSIndex", 0) or 0) + ch]]
            dst = out.setdefault(name, {})
            running = 0
            for e in entries:
                start = int(e.vertOffset) + ch * rows if explicit else cursor + ch * rows + running
                for i in range(int(e.vertCount)):
                    dst[int(e.subMeshVertexStartIndex) + i] = 2 * (start + i) + 1
                running += int(e.vertCount)
        cursor += rows * channels
    return out


def normals_at(raw, positions):
    """{key: {vertex: (x, y, z) int8}} read at the given word positions."""
    return {k: {v: struct.unpack_from("<bbb", raw, 4 * w) for v, w in rows.items()} for k, rows in positions.items()}


def patch_normals(file_bytes, raw_new, pos_new, raw_src, pos_src, pairs, keys):
    """file_bytes with, for every key in keys and every (new vertex -> source vertex) pair, the new row's
    normal word replaced by the source row's. raw_new must occur in file_bytes exactly once (it is the
    payload the parser read). Returns (bytes, rows patched)."""
    base = file_bytes.find(raw_new)
    if base < 0 or file_bytes.find(raw_new, base + 1) >= 0:
        raise ValueError("the blend-shape payload is not found exactly once in the file")
    out = bytearray(file_bytes)
    n = 0
    for k in keys:
        rn, rs = pos_new.get(k, {}), pos_src.get(k, {})
        for i, j in pairs.items():
            if i in rn and j in rs:
                w = base + 4 * rn[i]
                out[w:w + 4] = raw_src[4 * rs[j]:4 * rs[j] + 4]
                n += 1
    return bytes(out), n


def pair_twins(new, src, mats, radius=1e-5, uv_tol=1e-3):
    """Pair each new vertex (material, position, uv, own int8 normal) of the given materials with the
    source vertex of the same material at its position (<= radius) and UV; seam twins (same position
    and UV) are told apart by their own normal. Returns ({new index: src index}, [unmatched new indices])."""
    cell = radius * 4
    grid = {}
    for j, (m, p, _uv, _n) in enumerate(src):
        if m in mats:
            grid.setdefault(tuple(int(c // cell) for c in p), []).append(j)
    pairs, unmatched = {}, []
    for i, (m, p, uv, own) in enumerate(new):
        if m not in mats:
            continue
        c = tuple(int(x // cell) for x in p)
        cands = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for j in grid.get((c[0] + dx, c[1] + dy, c[2] + dz), ()):
                        sm, sp, suv, _ = src[j]
                        if (sm == m and sum((a - b) ** 2 for a, b in zip(sp, p, strict=True)) <= radius ** 2
                                and abs(suv[0] - uv[0]) < uv_tol and abs(suv[1] - uv[1]) < uv_tol):
                            cands.append(j)
        if not cands:
            unmatched.append(i)
            continue
        pairs[i] = min(cands, key=lambda j: (max(abs(a - b) for a, b in zip(src[j][3], own, strict=True)), j))
    return pairs, unmatched
