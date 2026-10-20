"""modpilot.geom.cones: MH Wilds angle-limit frames (moved with Known_Good_mod_test/scripts/gg/tests/
test_gg_cones.py's generic tests; GG's tilt table and its tests stay there). The tilt is the BHS skirt's
"angle limiter": Dimi turned his back strands' cones 10.3-12.8 deg outward."""
import math

import numpy as np
import pytest

from modpilot.geom import cones as K


def strand(x=0.10, y=-0.06, roll=0.3):
    """A 5-node strand hanging down and a little forward/outward from (x, y, 1.1), with arbitrary bone rolls."""
    heads = [np.array([x * (1 + 0.05 * i), y * (1 + 0.05 * i), 1.1 - 0.06 * i]) for i in range(5)]
    rots = []
    for i in range(5):
        a = roll + 0.2 * i
        rots.append(np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]]))
    return rots, heads


def test_zero_tilt_is_the_editors_align():
    rots, heads = strand()
    out = np.array([0.1, -0.06, 0.0]) / np.linalg.norm([0.1, -0.06, 0.0])
    got = K.tilted_quats(rots, heads, out, 0.0)
    ref = K.align_frames(rots, heads, np.eye(4))
    for q, r in zip(got, ref, strict=True):
        # a quaternion and its negative are the same rotation
        assert np.allclose(q, r, atol=1e-9) or np.allclose(q, -np.array(r), atol=1e-9)


@pytest.mark.parametrize("deg", [13.0, 18.0, 24.0])
def test_tilt_is_exact_and_outward(deg):
    rots, heads = strand()
    out = np.array([0.1, -0.06, 0.0]) / np.linalg.norm([0.1, -0.06, 0.0])
    qs = K.tilted_quats(rots, heads, out, math.radians(deg))
    for i, (rot, q) in enumerate(zip(rots, qs, strict=True)):
        j = i if i < 4 else 3
        d = heads[j + 1] - heads[j]
        d /= np.linalg.norm(d)
        axis = K.cone_axis(rot, q)
        assert math.degrees(math.acos(np.clip(axis @ d, -1, 1))) == pytest.approx(deg, abs=1e-6)
        assert (axis - d) @ out > 0                                  # toward her outside
        # in the plane of the strand and the outward direction: no sideways twist
        assert abs(axis @ np.cross(d, out) / np.linalg.norm(np.cross(d, out))) < 1e-9


def test_mirrored_strands_tilt_mirrored():
    rots_l, heads_l = strand(x=0.10, roll=0.0)
    rots_r, heads_r = strand(x=-0.10, roll=0.0)
    out_l = np.array([0.1, -0.06, 0.0]) / np.linalg.norm([0.1, -0.06, 0.0])
    out_r = out_l * np.array([-1, 1, 1])
    al = [K.cone_axis(r, q) for r, q in zip(rots_l, K.tilted_quats(rots_l, heads_l, out_l, math.radians(18)), strict=True)]
    ar = [K.cone_axis(r, q) for r, q in zip(rots_r, K.tilted_quats(rots_r, heads_r, out_r, math.radians(18)), strict=True)]
    for a, b in zip(al, ar, strict=True):
        assert np.allclose(a * np.array([-1, 1, 1]), b, atol=1e-9)


def test_outward_is_horizontal_from_the_hip_line():
    o = K.outward(np.array([0.1, -0.05, 1.0]), np.array([0.0, 0.03, 0.95]))
    assert o[2] == 0.0 and np.linalg.norm(o) == pytest.approx(1.0)
    assert o[0] > 0 and o[1] < 0


def test_cone_axis_inverts_quaternion_storage():
    # the editor's frame for direction d is R = rot(X -> d) @ Rx90, stored as quat(rot^T @ R); the axis is R @ X
    rots, heads = strand()
    q = K.align_frames(rots, heads, np.eye(4))[0]
    d = heads[1] - heads[0]
    assert np.allclose(K.cone_axis(rots[0], q), d / np.linalg.norm(d), atol=1e-9)


def frame_axes(rot, q):
    """World X / Y / Z of a stored angle-limit frame (node_rot @ quat)."""
    m = np.asarray(rot, float) @ K.qmat(q)
    return m[:, 0], m[:, 1], m[:, 2]


@pytest.mark.parametrize("roll", [0.0, 0.7, -2.1])
def test_squeezed_frame_on_the_parent_bone(roll):
    # gg18 headset (kevin 2026-10-16, mode 3 / 75.5 deg / 0.2125): MH Wilds measures node 0's frame from the PARENT
    # joint (Spine_2; Blender-MHWilds lesson #59) and modes 3 and 4 squeeze the frame's Z (lesson #57), so the frame
    # is X = the arm, Z = her up (the tilt, squeezed), Y = Z x X (her front-back: the turn)
    prot = np.array([[math.cos(roll), -math.sin(roll), 0], [math.sin(roll), math.cos(roll), 0], [0, 0, 1]])
    up, front = np.array([0.0, 0.0, 1.0]), np.array([0.0, -1.0, 0.0])
    left = np.cross(up, front)
    q = K.squeezed_quat(prot, left, up)
    x, y, z = frame_axes(prot, q)
    assert x == pytest.approx(left, abs=1e-9)                    # the cone axis is the arm
    assert z == pytest.approx(up, abs=1e-9)                      # the squeezed axis is her up/down
    assert y == pytest.approx(-front, abs=1e-9)                  # the free one her front-back
    assert K.cone_axis(prot, q) == pytest.approx(left, abs=1e-9)


def test_squeezed_frame_squares_a_slanted_axis():
    d = np.array([0.3, -0.9, -0.2])
    d /= np.linalg.norm(d)
    q = K.squeezed_quat(np.eye(3), d, np.array([0.0, 0.0, 1.0]))
    x, y, z = frame_axes(np.eye(3), q)
    assert x == pytest.approx(d, abs=1e-9) and z @ d == pytest.approx(0.0, abs=1e-9) and z[2] > 0.95
    assert np.cross(x, y) == pytest.approx(z, abs=1e-9)


@pytest.mark.parametrize("mode, full, dist, want", [
    (1, 40.0, 0.0, (20.0, 20.0)),          # angleLimitRad is the FULL cone: the game allows half (lesson #57)
    (5, 40.0, 0.0, (20.0, 20.0)),          # elliptic runs the round cone
    (2, 40.0, 0.0, (20.0, 0.0)),           # hinge: Z locked
    (4, 20.0, 0.0, (10.0, 0.0)),           # gg16 / gg17 as built: Z locked
    (4, 70.0, 0.4512, (35.0, 15.01)),      # Physics_Sim/re/notes/angle_limits.md, measured in the game's solver
    (3, 70.0, 0.2195, (35.0, 14.99)),
    (3, 75.5, 0.2125, (37.75, 15.04)),     # kevin's pick
])
def test_walls_are_the_games(mode, full, dist, want):
    assert K.walls(mode, full, dist) == pytest.approx(want, abs=0.02)


@pytest.mark.parametrize("roll", [0.0, 1.1])
def test_resting_frame_puts_the_rest_on_the_lower_wall(roll):
    # gg20 headset: the arm (back of band -> cups, forward-down) rests ON the squeezed axis's lower wall, so gravity
    # holds it on her chest and it can only lift: X is the arm turned up by the wall angle, Z up square to X
    prot = np.array([[1, 0, 0], [0, math.cos(roll), -math.sin(roll)], [0, math.sin(roll), math.cos(roll)]])
    up = np.array([0.0, 0.0, 1.0])
    d = np.array([0.0, -0.2, -0.1])
    d /= np.linalg.norm(d)
    q = K.resting_quat(prot, d, up, 3, 14.0, 0.0433)
    x, y, z = frame_axes(prot, q)
    wall = K.walls(3, 14.0, 0.0433)[1]
    assert math.degrees(math.acos(float(x @ d))) == pytest.approx(wall, abs=1e-6)
    assert d @ z < 0 and d @ y == pytest.approx(0.0, abs=1e-9)      # below the axis, on the -Z side, not sideways
    assert x @ up > d @ up and z @ x == pytest.approx(0.0, abs=1e-9) and z @ up > 0
    assert np.cross(x, y) == pytest.approx(z, abs=1e-9)

