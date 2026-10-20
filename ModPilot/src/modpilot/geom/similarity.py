"""Similarity transforms  x' = s R x + t  between two models' frames (bpy-free).

The build recipes map one model onto another (ModPilot's frame onto a verified mod's, an FBX onto a
mod mesh) with a similarity fitted by ICP (modpilot.bl.fit) around this Umeyama step. A frame is a
dict {s, R, t} (plus the fit's residual / start / iterations). Moved from
Known_Good_mod_test/scripts/og_sks/og_lib.py with its arithmetic unchanged (the GG and Marette builds
reproduce byte for byte); marette/fit.py and marette/rebuild/tests/mrcheck.py had copies of it.
"""
from __future__ import annotations

import math

import numpy as np


def umeyama(src, dst):
    """(s, R, t) minimising |s R src + t - dst|^2 over a proper rotation R (no reflection)."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    xs, xd = src - mu_s, dst - mu_d
    cov = xd.T @ xs / len(src)
    u, dv, vt = np.linalg.svd(cov)
    sgn = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sgn[2, 2] = -1
    r = u @ sgn @ vt
    s = np.trace(np.diag(dv) @ sgn) / ((xs ** 2).sum() / len(src))
    return s, r, mu_d - s * r @ mu_s


def rz(deg):
    """The rotation by `deg` degrees about Z."""
    a = math.radians(deg)
    return np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])


def to_frame(f, p):
    return f["s"] * (f["R"] @ np.asarray(p)) + f["t"]


def from_frame(f, p):
    return f["R"].T @ ((np.asarray(p) - f["t"]) / f["s"])


def delta_to_frame(f, d):
    """A displacement (a shape-key delta, an offset): scaled and turned, not moved."""
    return f["s"] * (f["R"] @ np.asarray(d))


def matrix_json(f):
    return {"s": f["s"], "R": f["R"].tolist(), "t": f["t"].tolist(), "residual": f["residual"],
            "start": f["start"], "iterations": f["iterations"]}
