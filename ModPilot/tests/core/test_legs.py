"""modpilot.geom.legs (moved with Known_Good_mod_test/scripts/gg/tests/test_gg_legs.py): the GG skirt carried by her legs as Dimi's in-game-verified BHS skirt is,
by where each vertex sits around her (kevin 2026-10-16: gg10B, thigh weights, worked where the collider flag did
nothing; "Dimi's front, by sector" -- it still clipped at the front at the peak of a movement with gg10B's
0 -> 53% curve, which was his side-front Skirt_3's, while his front is ~100% on the legs below the waist band;
scripts/gg/probe_front_weights.py)."""
import pytest

from modpilot.geom import legs as G

# sks4b BHS_A, mean legs share per cell (30-deg sectors from her front, 0.1 height bands, hip head 0 .. knee 1)
DIMI = {15: [0.0, 0.20, 0.60, 0.86, 0.98, 1.00, 1.00],
        45: [0.0, 0.31, 0.45, 0.87, 0.97, 1.00, 1.00],
        75: [0.0, 0.10, 0.31, 0.58, 0.63, 0.96, 0.96]}
H = [-0.15, -0.05, 0.05, 0.15, 0.25, 0.35, 0.45]


@pytest.mark.parametrize("ang", [15, 45, 75])
def test_share_is_dimis_cell_at_each_cell_centre(ang):
    for h, want in zip(H, DIMI[ang], strict=True):
        assert G.sector_share(ang, h) == pytest.approx(want, abs=1e-9)


@pytest.mark.parametrize("ang", [105, 135, 165, 180])
def test_side_to_back_is_left_to_the_chain(ang):
    for h in (-0.3, 0.0, 0.2, 0.5, 1.0):
        assert G.sector_share(ang, h) == 0.0


def test_nothing_on_the_legs_at_and_above_the_waist_band():
    for ang in range(0, 181, 5):
        assert G.sector_share(ang, -0.15) == 0.0 and G.sector_share(ang, -0.4) == 0.0


def test_front_is_on_the_legs_below_the_waist_band():
    assert G.sector_share(0, 0.25) == pytest.approx(0.98)
    assert G.sector_share(30, 0.35) == pytest.approx(1.0)
    assert G.sector_share(10, 0.9) == pytest.approx(1.0)


def test_share_is_bilinear_between_centres():
    # halfway between the 15 and 45 centres at h 0.05: (0.60 + 0.45) / 2; halfway in h at 15: (0.60 + 0.86) / 2
    assert G.sector_share(30, 0.05) == pytest.approx(0.525)
    assert G.sector_share(15, 0.10) == pytest.approx(0.73)
    # from the 75 centre to the 105 centre (the side, 0) it falls linearly
    assert G.sector_share(90, 0.25) == pytest.approx(0.63 / 2)


def test_share_is_continuous():
    for ang in range(0, 181, 3):
        prev = None
        for i in range(-40, 120):
            v = G.sector_share(ang, i / 100)
            assert 0.0 <= v <= 1.0
            if prev is not None:
                assert abs(v - prev) < 0.06
            prev = v


@pytest.mark.parametrize("d, front, want", [((0.0, -1.0), (0.0, -1.0), 0.0), ((1.0, 0.0), (0.0, -1.0), 90.0),
                                            ((-1.0, 0.0), (0.0, -1.0), 90.0), ((0.0, 1.0), (0.0, -1.0), 180.0),
                                            ((1.0, -1.0), (0.0, -1.0), 45.0), ((0.3, 0.0), (0.0, 2.0), 90.0)])
def test_angle_from_front(d, front, want):
    assert G.angle_from_front(d, front) == pytest.approx(want)


def test_height_from_hip_to_knee():
    assert G.height(1.02, 1.02, 0.553) == 0.0
    assert G.height(0.553, 1.02, 0.553) == pytest.approx(1.0)
    assert G.height(1.1, 1.02, 0.553) == pytest.approx(-0.08 / 0.467)


@pytest.mark.parametrize("x, want", [(0.0, 0.5), (0.09, 1.0), (0.2, 1.0), (-0.09, 0.0), (-0.3, 0.0), (0.045, 0.75)])
def test_left_share_by_x(x, want):
    # +x is her left in both the build's Blender space and the file: Dimi's Skirt_3_L sits at x > 0 on L_Thigh
    assert G.left_share(x, 0.09) == pytest.approx(want)


def test_blend_keeps_the_total_and_scales_the_rest():
    w = {"GG_Skirt.Root_F_L.003": 0.7, "Hip": 0.3}
    out = G.blend(w, f=0.4, left=0.75)
    assert sum(out.values()) == pytest.approx(1.0)
    assert out["GG_Skirt.Root_F_L.003"] == pytest.approx(0.42) and out["Hip"] == pytest.approx(0.18)
    assert out["L_Thigh"] == pytest.approx(0.3) and out["R_Thigh"] == pytest.approx(0.1)


def test_blend_adds_to_an_existing_thigh_weight_and_drops_zero_sides():
    out = G.blend({"S": 0.8, "L_Thigh": 0.2}, f=0.5, left=1.0)
    assert out == pytest.approx({"S": 0.4, "L_Thigh": 0.6})
    assert "R_Thigh" not in out


def test_blend_with_all_on_the_legs_drops_the_strand():
    out = G.blend({"S": 0.9, "Hip": 0.1}, f=1.0, left=0.5)
    assert out == pytest.approx({"L_Thigh": 0.5, "R_Thigh": 0.5})


def test_blend_with_no_share_changes_nothing():
    w = {"S": 0.6, "Hip": 0.4}
    assert G.blend(w, f=0.0, left=0.5) == w
