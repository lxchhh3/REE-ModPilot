"""A skirt carried by her legs as Dimi's in-game-verified BHS skirt is, by where each vertex sits around her
(moved from Known_Good_mod_test/scripts/gg/gg_legs.py, unchanged: the GG and Marette builds use it).

kevin 2026-10-16: the A/B showed the collider flag does nothing on this skirt (gg10A) and thigh weights work
(gg10B), but gg10B's front still clipped at the peak of a movement: its 0 -> 53% curve was Dimi's side-front
strand's (Skirt_3), while his FRONT is ~100% on the legs below the waist band and his side-to-back is left to
the chain ("Dimi's front, by sector"). Measured on sks4b's BHS_A (scripts/gg/probe_front_weights.py, 30-deg
sectors x 0.1 bands): the mean legs share per cell, below.

Coordinates are frame-free: `angle_from_front` takes the horizontal offset from the Hip head and her front
direction (toes minus ankle), `height` runs from the Hip head (0) to the knee (Shin head, 1). The thigh share goes
to L_Thigh / R_Thigh by x (+x is her left), blended across the middle so the centre stays continuous; it is taken
evenly from every other weight of the vertex. Pure python."""
from __future__ import annotations

import math

LEFT, RIGHT = "L_Thigh", "R_Thigh"
# cell centres: angle from her front (deg), height (hip head 0 .. knee 1)
_ANG = [15.0, 45.0, 75.0, 105.0, 135.0, 165.0]
_H = [-0.15, -0.05, 0.05, 0.15, 0.25, 0.35, 0.45]
# sks4b BHS_A legs share per cell. The waist band (-0.15) measured 0.00-0.01, taken as 0; 75 deg has no vertex in
# the 0.45 band, so its 0.35 value repeats; 105-165 deg (side to back) measured 0 everywhere
_SHARE = [[0.0, 0.20, 0.60, 0.86, 0.98, 1.00, 1.00],
          [0.0, 0.31, 0.45, 0.87, 0.97, 1.00, 1.00],
          [0.0, 0.10, 0.31, 0.58, 0.63, 0.96, 0.96],
          [0.0] * 7, [0.0] * 7, [0.0] * 7]


def _locate(xs, x):
    """(i, a): x lies a of the way from xs[i] to xs[i + 1], clamped to the ends."""
    if x <= xs[0]:
        return 0, 0.0
    if x >= xs[-1]:
        return len(xs) - 2, 1.0
    i = max(j for j in range(len(xs) - 1) if xs[j] <= x)
    return i, (x - xs[i]) / (xs[i + 1] - xs[i])


def sector_share(angle_deg, h):
    """Dimi's legs share at this angle from her front and height: bilinear between his cell centres, flat beyond.
    Nothing on the legs at or above the waist band."""
    if h <= _H[0]:
        return 0.0
    i, a = _locate(_ANG, angle_deg)
    j, b = _locate(_H, h)
    s = _SHARE
    return ((1 - a) * ((1 - b) * s[i][j] + b * s[i][j + 1])
            + a * ((1 - b) * s[i + 1][j] + b * s[i + 1][j + 1]))


def angle_from_front(d, front):
    """Angle (deg, 0..180) between a horizontal offset d = (u, v) and her horizontal front direction."""
    cross = d[0] * front[1] - d[1] * front[0]
    dot = d[0] * front[0] + d[1] * front[1]
    return math.degrees(math.atan2(abs(cross), dot))


def height(up, hip_up, knee_up):
    """0 at the Hip head, 1 at the knee, negative above the hip."""
    return (hip_up - up) / (hip_up - knee_up)


def left_share(x, x_thigh):
    """Of the thigh share, the part on L_Thigh: 1 at or beyond her left thigh's x, 0 at her right's, linear between."""
    return min(1.0, max(0.0, 0.5 + x / (2.0 * x_thigh)))


def blend(weights, f, left):
    """weights (bone -> normalised weight) with f of the total moved onto the thighs, `left` of it on L_Thigh:
    every existing weight scaled by (1 - f); weights that reach 0 and zero thigh entries are not kept."""
    if f <= 0.0:
        return dict(weights)
    out = {b: w * (1.0 - f) for b, w in weights.items() if w * (1.0 - f) > 0.0}
    for bone, share in ((LEFT, f * left), (RIGHT, f * (1.0 - left))):
        if share > 0.0:
            out[bone] = out.get(bone, 0.0) + share
    return out
