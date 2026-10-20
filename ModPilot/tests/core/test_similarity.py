"""modpilot.geom.similarity: the one Umeyama fit (scale, rotation, translation) the build scripts
shared three copies of (og_sks/og_lib.py, marette/fit.py, marette/rebuild/tests/mrcheck.py)."""
import math

import numpy as np
import pytest

from modpilot.geom import similarity as S


def _cloud(n=200, seed=1):
    return np.random.default_rng(seed).normal(size=(n, 3))


def _known(s=1.7, deg=35.0, t=(0.3, -1.2, 2.0)):
    a = math.radians(deg)
    r = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]]) @ S.rz(20)
    return s, r, np.array(t)


def test_umeyama_recovers_a_known_similarity():
    src = _cloud()
    s, r, t = _known()
    dst = (s * (r @ src.T)).T + t
    s2, r2, t2 = S.umeyama(src, dst)
    assert s2 == pytest.approx(s) and np.allclose(r2, r) and np.allclose(t2, t)


def test_umeyama_never_returns_a_reflection():
    src = _cloud()
    dst = src * np.array([1, 1, -1])            # a mirror: the best proper rotation is not it
    _, r, _ = S.umeyama(src, dst)
    assert np.linalg.det(r) == pytest.approx(1.0)


def test_the_three_old_copies_agree_with_it():
    src, (s, r, t) = _cloud(), _known()
    dst = (s * (r @ src.T)).T + t + _cloud(seed=2) * 1e-3
    # marette/fit.py and mrcheck.py computed the variance as (a**2).sum(1).mean() and a.var(0).sum()
    a = src - src.mean(0)
    for var in ((a ** 2).sum(1).mean(), a.var(0).sum()):
        assert var == pytest.approx((a ** 2).sum() / len(src), rel=1e-12)
    s2, r2, t2 = S.umeyama(src, dst)
    assert s2 == pytest.approx(s, rel=1e-3) and np.allclose(r2, r, atol=1e-3) and np.allclose(t2, t, atol=1e-3)


def test_points_and_deltas_map_both_ways():
    s, r, t = _known()
    f = {"s": s, "R": r, "t": t}
    p = np.array([0.1, 0.2, 0.3])
    assert np.allclose(S.from_frame(f, S.to_frame(f, p)), p)
    assert np.allclose(S.delta_to_frame(f, p), s * (r @ p))


def test_rz_turns_about_z():
    assert np.allclose(S.rz(90) @ [1, 0, 0], [0, 1, 0])


def test_matrix_json_is_plain_json():
    import json
    s, r, t = _known()
    f = {"s": s, "R": r, "t": t, "residual": {"p50": 0.0}, "start": 0, "iterations": 3}
    assert json.loads(json.dumps(S.matrix_json(f)))["R"] == r.tolist()
