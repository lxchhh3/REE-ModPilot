"""Skin-weight recipes the builds share (pure python): the point of a triangle soup nearest a vertex, mixing
corner weights, fading thigh weight out above the hip joint, and riding a surface's weights. Moved from
Known_Good_mod_test/scripts/gg/gg_tail.py, arithmetic unchanged (the GG build reproduces byte for byte);
ride's skirt-bone test became its `follows` argument."""
from __future__ import annotations

MAX_WEIGHTS = 6        # MH Wilds stores 6 per vertex; a 7th switches the whole mesh to the extended weight buffer


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def closest_barycentric(p, a, b, c):
    """Barycentric (u, v, w) on triangle abc of the point of it closest to p (Ericson, Real-Time Collision
    Detection 5.1.5): corners and edges clamp."""
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(p, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return (1.0, 0.0, 0.0)
    bp = _sub(p, b)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return (0.0, 1.0, 0.0)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        t = d1 / (d1 - d3)
        return (1.0 - t, t, 0.0)
    cp = _sub(p, c)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return (0.0, 0.0, 1.0)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        t = d2 / (d2 - d6)
        return (1.0 - t, 0.0, t)
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return (0.0, 1.0 - t, t)
    den = 1.0 / (va + vb + vc)
    v, w = vb * den, vc * den
    return (1.0 - v - w, v, w)


def nearest_on_triangles(p, pts, tris):
    """(triangle index, barycentric, distance) of the point of these triangles closest to p (brute force)."""
    best = None
    for k, (i, j, m) in enumerate(tris):
        bary = closest_barycentric(p, pts[i], pts[j], pts[m])
        q = tuple(bary[0] * pts[i][x] + bary[1] * pts[j][x] + bary[2] * pts[m][x] for x in range(3))
        d = _dot(_sub(p, q), _sub(p, q)) ** 0.5
        if best is None or d < best[2]:
            best = (k, bary, d)
    return best


def mix(weights, coeffs):
    """sum_k coeffs[k] * weights[k], bone by bone."""
    out = {}
    for w, c in zip(weights, coeffs, strict=True):
        for b, x in w.items():
            out[b] = out.get(b, 0.0) + c * x
    return {b: x for b, x in out.items() if x > 0.0}


THIGHS = ("L_Thigh", "R_Thigh")
HEM_RAMP_M = 0.03
HIP_HELPER = "Hip_HJ_00"


def hem_keep(below_hip_m, ramp=HEM_RAMP_M):
    """How much of its thigh weight a garment vertex keeps (gg14, kevin's option A): none at or above her hip
    joint, all from `ramp` below it, linear between. Thigh weight above the joint turns a vertex BACK into her
    belly when the leg swings forward -- the uniform's flaps and tag went up to 25 mm into her at a 90 deg lift."""
    return min(1.0, max(0.0, below_hip_m / ramp))


def fade_thighs(weights, keep):
    """weights with the thigh share scaled by keep and the whole renormalised (the other weights fill the gap); a
    vertex on the thighs alone hands what it loses to the hip's helper joint."""
    th = sum(w for b, w in weights.items() if b in THIGHS)
    if th <= 0.0 or keep >= 1.0:
        return dict(weights)
    out = {b: (w * keep if b in THIGHS else w) for b, w in weights.items()}
    out = {b: w for b, w in out.items() if w > 0.0}
    if sum(w for b, w in out.items() if b not in THIGHS) <= 0.0:
        out[HIP_HELPER] = out.get(HIP_HELPER, 0.0) + th * (1.0 - keep)
    t = sum(out.values())
    return {b: w / t for b, w in out.items()}


def ride(own, under, follows, cap=MAX_WEIGHTS):
    """A vertex riding a surface: its own weights on bones `follows` does not pick are kept, its share s on
    the ones it picks is replaced by s x the (normalised) weights of the surface under it. Both sides
    normalised; at most `cap` weights, the largest, renormalised. (GG's shirt flaps ride its skirt.)"""
    tot = sum(own.values())
    s = sum(w for b, w in own.items() if follows(b)) / tot
    out = {b: w / tot for b, w in own.items() if not follows(b)}
    if s > 0.0:
        ut = sum(under.values())
        for b, w in under.items():
            out[b] = out.get(b, 0.0) + s * w / ut
    if len(out) > cap:
        out = dict(sorted(out.items(), key=lambda kv: -kv[1])[:cap])
    t = sum(out.values())
    return {b: w / t for b, w in out.items()}
