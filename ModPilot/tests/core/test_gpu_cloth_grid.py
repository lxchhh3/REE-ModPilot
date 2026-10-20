"""gcj_grid: the particle grid over Marette's skirt for the game's GPU cloth. Pure numpy, no Blender.
Run with conda base's python: python -m pytest scripts/marette/gpuc/tests -q
(Moved with modpilot.geom.gpu_cloth_grid from Known_Good_mod_test/scripts/marette/gpuc/tests/test_gcj_grid.py.)"""
import math

import numpy as np
import pytest

from modpilot.geom import gpu_cloth_grid as G


def ring_points(radius, z_top, z_hem, n_ang=720, n_z=40, wobble=0.0):
    """A cylinder of points (N, 3) with its azimuths, 0 deg at -y (front), increasing to +x (her left)."""
    pts, az = [], []
    for a in np.linspace(0.0, 360.0, n_ang, endpoint=False):
        r = radius + wobble * math.sin(math.radians(3 * a))
        for z in np.linspace(z_top, z_hem, n_z):
            pts.append((r * math.sin(math.radians(a)), -r * math.cos(math.radians(a)), z))
            az.append(a)
    return np.array(pts), np.array(az)


# --- azimuth and columns -----------------------------------------------------------------------------

def test_azimuth_is_0_at_the_front_and_grows_towards_her_left():
    axis = np.array([0.0, 0.0])
    assert G.azimuth(np.array([[0.0, -1.0, 0.5]]), axis)[0] == pytest.approx(0.0)
    assert G.azimuth(np.array([[1.0, 0.0, 0.5]]), axis)[0] == pytest.approx(90.0)
    assert G.azimuth(np.array([[0.0, 1.0, 0.5]]), axis)[0] == pytest.approx(180.0)
    assert G.azimuth(np.array([[-1.0, 0.0, 0.5]]), axis)[0] == pytest.approx(270.0)


def test_angle_gap_is_the_shortest_way_round():
    assert G.angle_gap(np.array([350.0, 10.0, 180.0]), 5.0).tolist() == pytest.approx([15.0, 5.0, 175.0])


def test_column_angles_split_the_ring_evenly_from_the_front():
    assert G.column_angles(4).tolist() == [0.0, 90.0, 180.0, 270.0]


def test_pid_wraps_the_column_round_the_ring():
    assert G.pid(2, 3, 4) == 11 and G.pid(2, 4, 4) == 8 and G.pid(1, -1, 4) == 7


# --- per-column top edge and hem --------------------------------------------------------------------

def test_column_edges_take_each_sectors_top_and_hem_with_a_hem_margin():
    pts, az = ring_points(0.2, 1.1, 0.8)
    top, hem = G.column_edges(pts, az, nc=8, hem_margin=0.02)
    assert top.shape == (8,) and hem.shape == (8,)
    assert top.tolist() == pytest.approx([1.1] * 8)
    assert hem.tolist() == pytest.approx([0.82] * 8)


def test_column_edges_refuse_an_empty_sector():
    pts, az = ring_points(0.2, 1.1, 0.8)
    keep = az < 300.0                       # nothing in the last sixth of the ring
    with pytest.raises(ValueError):
        G.column_edges(pts[keep], az[keep], nc=12)


# --- the grid -----------------------------------------------------------------------------------------

def test_sector_grid_puts_each_particle_on_its_column_angle_and_row_height():
    pts, az = ring_points(0.2, 1.1, 0.8, wobble=0.01)
    nc, nr = 12, 4
    top, hem = G.column_edges(pts, az, nc, hem_margin=0.0)
    P = G.sector_grid(pts, az, nc, nr, top, hem, axis=(0.0, 0.0))
    assert P.shape == (nc * nr, 3)
    for r in range(nr):
        for k in range(nc):
            p = P[G.pid(r, k, nc)]
            a = 360.0 * k / nc
            assert G.azimuth(p[None], (0.0, 0.0))[0] == pytest.approx(a % 360.0, abs=1e-6)
            assert p[2] == pytest.approx(1.1 + (0.8 - 1.1) * r / (nr - 1))
            # on the (wobbling) shell, not at a fixed radius
            assert math.hypot(p[0], p[1]) == pytest.approx(0.2 + 0.01 * math.sin(math.radians(3 * a)), abs=2e-3)


def test_sector_grid_spacing_report_gives_min_median_max_in_cm():
    pts, az = ring_points(0.2, 1.1, 0.8)
    top, hem = G.column_edges(pts, az, 12, hem_margin=0.0)
    P = G.sector_grid(pts, az, 12, 4, top, hem)
    rep = G.spacing(P, 12, 4)
    assert rep["around_cm"][1] == pytest.approx(2 * 0.2 * math.sin(math.pi / 12) * 100, abs=0.1)
    assert rep["down_cm"][1] == pytest.approx(10.0, abs=0.1)


# --- frames -------------------------------------------------------------------------------------------

def test_frames_point_the_normal_outward_and_y_up_the_cloth():
    pts, az = ring_points(0.2, 1.1, 0.8)
    top, hem = G.column_edges(pts, az, 12, hem_margin=0.0)
    P = G.sector_grid(pts, az, 12, 4, top, hem)
    F = G.frames(P, 12, 4, axis=(0.0, 0.0))
    assert F.shape == (48, 3, 3)
    for i in range(48):
        x, y, n = F[i]
        out = np.array([P[i][0], P[i][1], 0.0])
        assert n @ out > 0.99 * np.linalg.norm(out)          # outward normal
        assert y[2] > 0.99                                   # up the cloth
        assert np.allclose(np.cross(y, n), x) and abs(x @ y) < 1e-9 and abs(y @ n) < 1e-9


# --- bilinear weights ---------------------------------------------------------------------------------

def test_bilinear_on_a_particle_is_that_particle_alone():
    top, hem = np.full(4, 1.0), np.full(4, 0.0)
    w = G.bilinear(90.0, 0.5, 4, 3, top, hem)
    assert w == {G.pid(1, 1, 4): pytest.approx(1.0)}


def test_bilinear_between_two_columns_and_two_rows_sums_to_one_over_four_particles():
    top, hem = np.full(4, 1.0), np.full(4, 0.0)
    w = G.bilinear(45.0, 0.75, 4, 3, top, hem)
    assert set(w) == {G.pid(0, 0, 4), G.pid(0, 1, 4), G.pid(1, 0, 4), G.pid(1, 1, 4)}
    assert sum(w.values()) == pytest.approx(1.0)
    assert all(v == pytest.approx(0.25) for v in w.values())


def test_bilinear_wraps_the_seam_and_clamps_above_the_top_and_below_the_hem():
    top, hem = np.full(4, 1.0), np.full(4, 0.0)
    w = G.bilinear(315.0, 1.3, 4, 3, top, hem)           # between the last and the first column, above the top
    assert set(w) == {G.pid(0, 3, 4), G.pid(0, 0, 4)} and sum(w.values()) == pytest.approx(1.0)
    w = G.bilinear(0.0, -0.2, 4, 3, top, hem)            # under the hem: the last row
    assert w == {G.pid(2, 0, 4): pytest.approx(1.0)}


def test_bilinear_uses_the_edges_interpolated_between_its_two_columns():
    top, hem = np.array([1.0, 1.2, 1.0, 1.0]), np.array([0.0, 0.2, 0.0, 0.0])
    # halfway between columns 0 and 1 the top is 1.1 and the hem 0.1: z = 0.6 is row 1 of 3 exactly
    w = G.bilinear(45.0, 0.6, 4, 3, top, hem)
    assert set(w) == {G.pid(1, 0, 4), G.pid(1, 1, 4)} and sum(w.values()) == pytest.approx(1.0)


def test_ring_interp_walks_round_the_seam():
    v = np.array([0.0, 1.0, 2.0, 3.0])
    assert G.ring_interp(v, 0.5) == pytest.approx(0.5)
    assert G.ring_interp(v, 3.5) == pytest.approx(1.5)     # between v[3] and v[0]
