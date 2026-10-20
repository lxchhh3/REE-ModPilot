"""MH Wilds chain angle-limit frames and cones (bpy-free).

A chain node's angle limit is a cone around the X axis of a frame stored as angleLimitDirection,
(x, y, z, w), relative to the rest rotation of the bone the GAME measures it from: the node's parent
(Blender-MHWilds lesson #59). RE Chain Editor's "Align Angle Limits to Next Node" points X from a node's
head to the next node's head, turned 90 deg about X (lesson #36). angleLimitRad is the FULL cone (lesson
#57); angle modes 3 (cone cut to a slab) and 4 (oval) squeeze the frame's Z.

Moved from Known_Good_mod_test/scripts/og_collar/collar_lib.py (align_frames and its rotation helpers)
and gg/gg_cones.py (tilted / squeezed / resting frames, walls), arithmetic unchanged: the GG and
Marette builds reproduce byte for byte. GG's own tilt table stays in gg_cones.py.
"""
from __future__ import annotations

import math

import numpy as np

X_AXIS = np.array([1.0, 0.0, 0.0])


def axis_angle(axis, angle):
    """The rotation matrix by `angle` radians about `axis` (identity for a zero axis)."""
    axis = np.asarray(axis, float)
    n = np.linalg.norm(axis)
    if n < 1e-12:
        return np.eye(3)
    x, y, z = axis / n
    c, s = math.cos(angle), math.sin(angle)
    k = 1 - c
    return np.array([[c + x * x * k, x * y * k - z * s, x * z * k + y * s],
                     [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
                     [z * x * k - y * s, z * y * k + x * s, c + z * z * k]])


def mat_to_quat(m):
    """A rotation matrix as (x, y, z, w), the order chain2 stores."""
    w = math.sqrt(max(0.0, 1 + m[0, 0] + m[1, 1] + m[2, 2])) / 2
    x = math.copysign(math.sqrt(max(0.0, 1 + m[0, 0] - m[1, 1] - m[2, 2])) / 2, m[2, 1] - m[1, 2])
    y = math.copysign(math.sqrt(max(0.0, 1 - m[0, 0] + m[1, 1] - m[2, 2])) / 2, m[0, 2] - m[2, 0])
    z = math.copysign(math.sqrt(max(0.0, 1 - m[0, 0] - m[1, 1] + m[2, 2])) / 2, m[1, 0] - m[0, 1])
    return (x, y, z, w)


def qmat(q):
    """(x, y, z, w) as a rotation matrix."""
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


RX90 = axis_angle((1, 0, 0), math.pi / 2)


def align_frames(rots, heads, armature_world):
    """RE Chain Editor's "Align Angle Limits to Next Node" (re_chain.align_frames): each node's cone
    points from its head to the next node's head, X axis first, then turned 90 deg about its own X,
    expressed in the node's frame (= the bone's rest matrix). The last node repeats the one before.
    Returns (x, y, z, w) per node, as chain2 stores angleLimitDirection."""
    A = np.asarray(armature_world, float)
    out, R = [], None
    for i, rot in enumerate(rots):
        if i < len(rots) - 1:
            a = A[:3, :3] @ np.asarray(heads[i]) + A[:3, 3]
            b = A[:3, :3] @ np.asarray(heads[i + 1]) + A[:3, 3]
            d = (b - a) / np.linalg.norm(b - a)
            R = axis_angle(np.cross(X_AXIS, d), math.acos(max(-1.0, min(1.0, float(X_AXIS @ d))))) @ RX90
        node = A[:3, :3] @ np.asarray(rot, float)
        out.append(mat_to_quat(node.T @ R))
    return out


def cone_axis(rot, q):
    """World axis of a stored cone (rot = the rest rotation, world space, of the node's parent bone)."""
    a = np.asarray(rot, float) @ qmat(q) @ np.array([1.0, 0.0, 0.0])
    return a / np.linalg.norm(a)


def outward(point, hip):
    """Horizontal unit vector from the vertical line through `hip` to `point`."""
    o = np.asarray(point, float) - np.asarray(hip, float)
    o[2] = 0.0
    return o / np.linalg.norm(o)


def tilted_quats(rots, heads, out_dir, tilt):
    """angleLimitDirection (x, y, z, w) per node: the aligned direction (to the next node's head; the
    last node repeats the one before) turned by `tilt` radians toward `out_dir`. rots / heads are
    world-space. A cone tilted by t against a top limit L leaves (L - t) deg of inward swing; the BHS
    skirt is held off her hips this way (Dimi turned his back strands' cones 10.3-12.8 deg outward)."""
    X = np.array([1.0, 0.0, 0.0])
    out_dir = np.asarray(out_dir, float)
    res = []
    for i, rot in enumerate(rots):
        j = i if i < len(rots) - 1 else i - 1
        d = np.asarray(heads[j + 1], float) - np.asarray(heads[j], float)
        d /= np.linalg.norm(d)
        side = np.cross(d, out_dir)
        if tilt and np.linalg.norm(side) > 1e-9:
            d = axis_angle(side / np.linalg.norm(side), tilt) @ d
        R = axis_angle(np.cross(X, d), math.acos(max(-1.0, min(1.0, float(X @ d))))) @ RX90
        res.append(mat_to_quat(np.asarray(rot, float).T @ R))
    return res


def squeezed_quat(rot, d, squeeze):
    """angleLimitDirection (x, y, z, w) of a frame with X along d (the cone axis), Z the direction of
    `squeeze` made square to d and Y = Z x X (modes 3 and 4 squeeze Z). rot = the rest rotation, world
    space, of the bone the game measures the frame from: the node's PARENT (node 0: the joint the chain
    hangs from)."""
    x = np.asarray(d, float) / np.linalg.norm(d)
    z = np.asarray(squeeze, float) - (np.asarray(squeeze, float) @ x) * x
    z /= np.linalg.norm(z)
    R = np.column_stack([x, np.cross(z, x), z])
    return mat_to_quat(np.asarray(rot, float).T @ R)


def resting_quat(rot, d, up, mode, full_deg, dist):
    """squeezed_quat for a node that RESTS on its lower wall (gravity holds it there): X is d turned
    toward `up` (made square to d) by the squeezed axis's wall angle (walls()), so d lies on the frame's
    -Z wall and the node can only swing from it upward (2 x the wall) and sideways."""
    x = np.asarray(d, float) / np.linalg.norm(d)
    u = np.asarray(up, float) - (np.asarray(up, float) @ x) * x
    u /= np.linalg.norm(u)
    w = math.radians(walls(mode, full_deg, dist)[1])
    return squeezed_quat(rot, math.cos(w) * x + math.sin(w) * u, up)


def walls(mode, full_deg, dist):
    """(swing toward frame Y, swing toward frame Z), deg, that MH Wilds allows a node with this
    angleMode, angleLimitRad (as deg: the FULL cone) and angleLimitDistance -- read from the exe and
    measured in its solver (Physics_Sim/re/notes/angle_limits.md)."""
    h = math.radians(full_deg) / 2.0
    hd = math.degrees(h)
    if mode in (1, 5):
        return hd, hd
    if mode == 2:
        return hd, 0.0
    if mode == 3:
        return hd, math.degrees(math.atan(min(dist, math.sin(h)) / math.cos(h)))
    if mode == 4:
        return hd, math.degrees(math.asin(dist * math.sin(h)))
    raise ValueError(mode)
