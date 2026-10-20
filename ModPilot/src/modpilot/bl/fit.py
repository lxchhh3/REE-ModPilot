"""The ICP similarity fit and vertex matching the build recipes map one model onto another with
(needs Blender's mathutils KDTree). Moved from Known_Good_mod_test/scripts/og_sks/og_lib.py with its
arithmetic and KDTree use unchanged: the GG and Marette builds reproduce byte for byte.

A frame f is {s, R, t, residual, start, iterations}; see modpilot.geom.similarity.
"""
from __future__ import annotations

import numpy as np

from modpilot.geom.similarity import from_frame, rz, umeyama


def _tree(points):
    from mathutils.kdtree import KDTree
    tree = KDTree(len(points))
    for i, p in enumerate(points):
        tree.insert(p, i)
    tree.balance()
    return tree


def fit(src_pts, dst_pts, iters=80):
    """Similarity mapping src_pts onto dst_pts (nearest-neighbour ICP, trimmed to 3x the median
    distance after 4 rounds), from a 0 and a 180 degree start about Z; the start with the smaller
    median residual wins. Returns {s, R, t, residual: {p50, p90, p99, max} (dst units), start,
    iterations}."""
    best = None
    ext_s = src_pts[:, 2].max() - src_pts[:, 2].min()
    ext_d = dst_pts[:, 2].max() - dst_pts[:, 2].min()
    for start in (180, 0):
        r = rz(start)
        s = ext_d / ext_s
        t = dst_pts.mean(0) - s * r @ src_pts.mean(0)
        for it in range(iters):
            moved = (s * (r @ src_pts.T)).T + t
            tree = _tree(moved)
            nn = np.array([tree.find(p)[1] for p in dst_pts])
            dist = np.linalg.norm(moved[nn] - dst_pts, axis=1)
            keep = dist <= max(np.median(dist) * 3, 1e-6) if it > 3 else np.ones(len(dist), bool)
            s2, r2, t2 = umeyama(src_pts[nn[keep]], dst_pts[keep])
            change = abs(s2 - s) + np.abs(r2 - r).max() + np.abs(t2 - t).max()
            s, r, t = s2, r2, t2
            if change < 1e-9:
                break
        moved = (s * (r @ src_pts.T)).T + t
        tree = _tree(moved)
        dist = np.array([tree.find(p)[2] for p in dst_pts])
        res = {k: float(np.percentile(dist, q)) for k, q in (("p50", 50), ("p90", 90), ("p99", 99))}
        res["max"] = float(dist.max())
        cand = {"s": float(s), "R": r, "t": t, "residual": res, "start": start, "iterations": it + 1}
        if best is None or res["p50"] < best["residual"]["p50"]:
            best = cand
    return best


def world_verts(obj):
    """An object's vertex positions in world space, (n, 3)."""
    mw = obj.matrix_world
    return np.array([tuple(mw @ v.co) for v in obj.data.vertices])


def uv_by_vertex(obj, layer="UVMap0"):
    """Vertex -> its UV on `layer` (the last loop's, where a vertex has several)."""
    me = obj.data
    out = {}
    for lp in me.loops:
        out[lp.vertex_index] = tuple(me.uv_layers[layer].data[lp.index].uv)
    return out


def nearest_source(tree, f, p, radius=2e-5):
    """Source vertex indices at the frame-f point p: every one within `radius` (source units) of the
    nearest, nearest first. Returns (indices, distance of the nearest in frame units)."""
    q = from_frame(f, p)
    co, i0, d0 = tree.find(q)
    hits = sorted(tree.find_range(q, d0 + radius), key=lambda h: h[2])
    return [h[1] for h in hits], d0 * f["s"]


def match(tree, uvs, f, p, uv, max_mm=4.0, uv_tol=1e-3):
    """The source vertex a frame-f vertex came from: among source vertices within max_mm of its
    position, the nearest one carrying its UV (uvs: source vertex -> set of UVs; twins at one
    position differ only by UV), else the nearest position. Returns (index, 'uv' | 'pos',
    distance in frame units)."""
    q = from_frame(f, p)
    hits = sorted(tree.find_range(q, max_mm / 1000 / f["s"]), key=lambda h: h[2])
    for _, i, d in hits:
        if any(abs(uv[0] - a) < uv_tol and abs(uv[1] - b) < uv_tol for a, b in uvs.get(i, ())):
            return i, "uv", d * f["s"]
    if hits:
        return hits[0][1], "pos", hits[0][2] * f["s"]
    _, i, d = tree.find(q)
    return i, "pos", d * f["s"]
