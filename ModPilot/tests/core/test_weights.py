"""modpilot.geom.weights (moved with Known_Good_mod_test/scripts/gg/tests/test_gg_tail.py's generic tests; the
tail-island and UV tests stay there): GG's shirt flaps and tag ride its skirt (kevin 2026-10-16), and the
hem fade keeps thigh weight below the hip joint only (gg14)."""
import pytest

from modpilot.geom import weights as T


def _gg_skirt(bone):
    return bone.startswith("GG_Skirt")


T.ride_gg = lambda own, under, cap=T.MAX_WEIGHTS: T.ride(own, under, _gg_skirt, cap)


# ---------------------------------------------------------------- the skirt surface right under a vertex


def test_barycentric_inside_the_triangle_is_its_own_point():
    a, b, c = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    u, v, w = T.closest_barycentric((0.2, 0.3, 0.05), a, b, c)   # 5 cm off the face, above (0.2, 0.3)
    assert (u, v, w) == pytest.approx((0.5, 0.2, 0.3))


@pytest.mark.parametrize("p,want", [((-1.0, -1.0, 0.0), (1, 0, 0)), ((2.0, -0.5, 0.3), (0, 1, 0)),
                                    ((0.5, -1.0, 0.0), (0.5, 0.5, 0)), ((1.0, 1.0, 0.0), (0, 0.5, 0.5))])
def test_barycentric_outside_clamps_to_the_nearest_edge_or_corner(p, want):
    assert T.closest_barycentric(p, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)) == pytest.approx(want)


def test_nearest_on_triangles_picks_the_closest_face():
    pts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0)]
    tris = [(0, 1, 2), (3, 4, 5)]
    k, bary, dist = T.nearest_on_triangles((0.2, 0.2, 0.9), pts, tris)
    assert k == 1 and bary == pytest.approx((0.6, 0.2, 0.2)) and dist == pytest.approx(0.1)


def test_mix_is_the_weighted_sum_of_the_corners_weights():
    got = T.mix([{"A": 1.0}, {"A": 0.5, "B": 0.5}, {"C": 1.0}], (0.5, 0.25, 0.25))
    assert got == pytest.approx({"A": 0.625, "B": 0.125, "C": 0.25})


# ---------------------------------------------------------------- the ride


def test_ride_replaces_the_skirt_share_by_the_skirt_under_it_and_keeps_the_rest():
    own = {"Hip": 0.3, "GG_Skirt.Root_F_L.002": 0.7}
    under = {"GG_Skirt.Root_F_L.003": 0.2, "L_Thigh": 0.6, "Hip": 0.2}
    assert T.ride_gg(own, under) == pytest.approx({"Hip": 0.3 + 0.7 * 0.2, "GG_Skirt.Root_F_L.003": 0.14, "L_Thigh": 0.42})


def test_ride_normalises_both_sides():
    assert T.ride_gg({"Hip": 1.0, "GG_Skirt.Root_M.002": 3.0}, {"R_Thigh": 2.0, "GG_Skirt.Root_M.003": 2.0}) == \
        pytest.approx({"Hip": 0.25, "R_Thigh": 0.375, "GG_Skirt.Root_M.003": 0.375})


def test_ride_leaves_a_vertex_without_skirt_weight_alone():
    own = {"Hip": 0.6, "Spine_0": 0.4}
    assert T.ride_gg(own, {"L_Thigh": 1.0}) == pytest.approx(own)


def test_a_flap_tip_all_on_the_skirt_moves_exactly_as_the_skirt_under_it():
    under = {"GG_Skirt.Root_F_L.003": 0.1, "GG_Skirt.Root_F_L.002": 0.05, "L_Thigh": 0.7, "R_Thigh": 0.15}
    assert T.ride_gg({"GG_Skirt.Root_F_L.002": 1.0}, under) == pytest.approx(under)


def test_ride_keeps_at_most_six_weights_the_largest_renormalised():
    # MH Wilds stores 6 weights per vertex; a 7th switches the WHOLE mesh to the extended weight buffer
    own = {"Hip": 0.30, "Spine_0": 0.02, "GG_Skirt.Root_M.002": 0.68}
    under = {"a": 0.30, "b": 0.25, "c": 0.20, "d": 0.15, "e": 0.06, "f": 0.04}
    got = T.ride_gg(own, under)
    assert len(got) == 6 and sum(got.values()) == pytest.approx(1.0)
    assert "Spine_0" not in got and "f" not in got          # the two smallest (0.02, 0.0272) go
    keep = {"Hip": 0.30, "a": 0.204, "b": 0.17, "c": 0.136, "d": 0.102, "e": 0.0408}
    tot = sum(keep.values())
    assert got == pytest.approx({k: v / tot for k, v in keep.items()})


# ---------------------------------------------------------------- the hem fade (gg14, kevin's option A)
# thigh weight above her hip joint turns a vertex BACK into her belly when the leg swings forward: the uniform's
# flaps and tag got it from the skirt under them and went up to 25 mm into her at a 90 deg lift (probe_cover_pose)


@pytest.mark.parametrize("below,want", [(-0.02, 0.0), (0.0, 0.0), (0.015, 0.5), (0.03, 1.0), (0.2, 1.0)])
def test_hem_keep_is_0_at_and_above_the_hip_joint_and_1_from_3_cm_below(below, want):
    assert T.hem_keep(below) == pytest.approx(want)


def test_fade_keeps_everything_at_keep_1():
    w = {"Hip_HJ_00": 0.3, "L_Thigh": 0.5, "GG_Skirt.Root_M.002": 0.2}
    assert T.fade_thighs(w, 1.0) == pytest.approx(w)


def test_fade_at_0_drops_the_thighs_and_refills_the_rest():
    assert T.fade_thighs({"Hip_HJ_00": 0.3, "L_Thigh": 0.4, "R_Thigh": 0.1, "GG_Skirt.Root_M.002": 0.2}, 0.0) == \
        pytest.approx({"Hip_HJ_00": 0.6, "GG_Skirt.Root_M.002": 0.4})


def test_fade_halfway_scales_the_thighs_then_normalises():
    got = T.fade_thighs({"Hip_HJ_00": 0.5, "L_Thigh": 0.5}, 0.5)
    assert got == pytest.approx({"Hip_HJ_00": 0.5 / 0.75, "L_Thigh": 0.25 / 0.75})


@pytest.mark.parametrize("keep,want", [(0.0, {"Hip_HJ_00": 1.0}), (0.5, {"L_Thigh": 0.5, "Hip_HJ_00": 0.5})])
def test_a_thigh_only_vertex_hands_what_it_loses_to_the_hip_helper_joint(keep, want):
    assert T.fade_thighs({"L_Thigh": 1.0}, keep) == pytest.approx(want)


def test_fade_leaves_a_vertex_without_thigh_weight_alone():
    w = {"Spine_2_HJ_00": 0.7, "breast_L": 0.3}
    assert T.fade_thighs(w, 0.0) == pytest.approx(w)


