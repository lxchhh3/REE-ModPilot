"""A particle grid over Marette's skirt for the game's GPU cloth (via.dynamics.GpuCloth, .gpuc): NC columns round her,
NR rows from the skirt's top edge to its hem, one GCJ bone per particle, laid out as the vanilla full skirts are
(Dimi's REE-GpuC-Research, references/01-proxy-grid.md). The grid is read off the skirt's own vertices: a particle is
the skirt's mean radius in its sector at its row's height, on its column's exact angle. Pure numpy; Blender armature
space (z up), azimuth 0 = her front (-y), growing towards her left (+x), as prep_belt / gg_legs measure it.

kevin's call (2026-10-18): the chain2 skirt's front crease is the seam between thigh-weight carry and strand physics,
which no chain2 setting removes without the thighs clipping, so the skirt moves to the game's own sheet solver.

Moved from Known_Good_mod_test/scripts/marette/gpuc/gcj_grid.py unchanged (ModPilot restructure M3, 2026-10-20)."""
import math

import numpy as np


def azimuth(points, axis):
    """Degrees round the vertical axis at `axis` (x, y): 0 at -y (her front), 90 at +x (her left)."""
    p = np.asarray(points, float).reshape(-1, 3)
    return np.degrees(np.arctan2(p[:, 0] - axis[0], -(p[:, 1] - axis[1]))) % 360.0


def angle_gap(a, b):
    """|a - b| the shortest way round (degrees)."""
    d = np.abs((np.asarray(a, float) - b) % 360.0)
    return np.minimum(d, 360.0 - d)


def column_angles(nc):
    return 360.0 * np.arange(nc) / nc


def pid(r, k, nc):
    """Particle index of row r, column k (the ring wraps)."""
    return r * nc + (k % nc)


def column_edges(points, az, nc, hem_margin=0.02, top_margin=0.0):
    """Per column: the sector's highest vertex (minus top_margin) and its lowest (plus hem_margin). A sector is the
    column's angle +- half a column; refuses an empty one."""
    p = np.asarray(points, float)
    half = 180.0 / nc
    top, hem = np.zeros(nc), np.zeros(nc)
    for k, a in enumerate(column_angles(nc)):
        m = angle_gap(az, a) <= half
        if not m.any():
            raise ValueError(f"no skirt vertex in the sector of column {k} ({a:.1f} deg)")
        top[k], hem[k] = p[m, 2].max() - top_margin, p[m, 2].min() + hem_margin
    return top, hem


def sector_grid(points, az, nc, nr, top, hem, axis=(0.0, 0.0), dz=0.012, min_pts=3):
    """(nr * nc, 3) particles, row by row, row 0 at the top edge: column k sits on its angle, row r at
    top[k] + (hem[k] - top[k]) * r / (nr - 1), at the median radius of the sector's vertices within dz of that height
    (the band widens up to 4x when fewer than min_pts vertices fall in it)."""
    p = np.asarray(points, float)
    r_all = np.hypot(p[:, 0] - axis[0], p[:, 1] - axis[1])
    half = 180.0 / nc
    out = np.zeros((nr * nc, 3))
    for k, a in enumerate(column_angles(nc)):
        sector = angle_gap(az, a) <= half
        for r in range(nr):
            z = top[k] + (hem[k] - top[k]) * r / (nr - 1)
            for widen in (1.0, 2.0, 3.0, 4.0):
                m = sector & (np.abs(p[:, 2] - z) <= dz * widen)
                if m.sum() >= min_pts:
                    break
            else:
                raise ValueError(f"no skirt vertices near row {r} column {k} (z {z:.3f}, {a:.1f} deg)")
            rad = float(np.median(r_all[m]))
            out[pid(r, k, nc)] = (axis[0] + rad * math.sin(math.radians(a)), axis[1] - rad * math.cos(math.radians(a)), z)
    return out


def spacing(P, nc, nr):
    """Particle spacing round the ring and down the cloth, (min, median, max) in cm."""
    P = np.asarray(P, float)
    hs = [np.linalg.norm(P[pid(r, k, nc)] - P[pid(r, k + 1, nc)]) for r in range(nr) for k in range(nc)]
    vs = [np.linalg.norm(P[pid(r, k, nc)] - P[pid(r + 1, k, nc)]) for r in range(nr - 1) for k in range(nc)]
    stat = lambda v: [round(float(x) * 100, 2) for x in (min(v), float(np.median(v)), max(v))]  # noqa: E731
    return {"around_cm": stat(hs), "down_cm": stat(vs)}


def frames(P, nc, nr, axis=(0.0, 0.0)):
    """Per particle the bone frame (rows x, y, n), as Dimi's make_gcj_grid.bones builds it and the vanilla majority
    convention has it: n the outward normal of the grid, y up the cloth (towards the row above), x = y cross n."""
    P = np.asarray(P, float)
    out = np.zeros((nr * nc, 3, 3))
    for r in range(nr):
        for k in range(nc):
            i = pid(r, k, nc)
            p = P[i]
            up = (P[pid(r - 1, k, nc)] - p) if r > 0 else (p - P[pid(1, k, nc)])
            around = P[pid(r, k + 1, nc)] - P[pid(r, k - 1, nc)]
            n = np.cross(around, up)
            n /= np.linalg.norm(n)
            if n @ np.array([p[0] - axis[0], p[1] - axis[1], 0.0]) < 0:
                n = -n
            y = up - n * (n @ up)
            y /= np.linalg.norm(y)
            out[i] = (np.cross(y, n), y, n)
    return out


def ring_interp(values, u):
    """values[u] linearly, u in column units round the ring (wraps)."""
    v = np.asarray(values, float)
    nc = len(v)
    k0 = int(math.floor(u))
    f = u - k0
    return float(v[k0 % nc] * (1.0 - f) + v[(k0 + 1) % nc] * f)


def bilinear(az_deg, z, nc, nr, top, hem):
    """{particle: weight} of a point at azimuth az_deg and height z: linear between its two columns and its two rows,
    the rows measured on the top edge and hem interpolated between those columns; clamped to the top row above the
    edge and the last row under the hem. Weights sum to 1; zero ones are left out."""
    u = (az_deg % 360.0) / 360.0 * nc
    t_top, t_hem = ring_interp(top, u), ring_interp(hem, u)
    t = (t_top - z) / (t_top - t_hem) * (nr - 1)
    t = min(max(t, 0.0), float(nr - 1))
    k0, r0 = int(math.floor(u)), min(int(t), nr - 2)
    fu, ft = u - k0, t - r0
    out = {}
    for (r, k), w in (((r0, k0), (1 - fu) * (1 - ft)), ((r0, k0 + 1), fu * (1 - ft)),
                      ((r0 + 1, k0), (1 - fu) * ft), ((r0 + 1, k0 + 1), fu * ft)):
        if w > 1e-9:
            out[pid(r, k, nc)] = out.get(pid(r, k, nc), 0.0) + w
    return out
