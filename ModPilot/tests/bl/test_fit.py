"""modpilot.bl.fit in real Blender (T1): the ICP similarity fit (mathutils KDTree + Umeyama) the GG,
Marette and OG builds map one model's frame onto another's with, and the UV-aware vertex match."""
import math

import numpy as np
import pytest
from mathutils.kdtree import KDTree

from modpilot.bl import fit as F
from modpilot.geom import similarity as S


def _figure(n=400, seed=3):
    """A tall, lopsided point cloud (an ICP needs no symmetry to lock on)."""
    rng = np.random.default_rng(seed)
    p = rng.normal(size=(n, 3)) * [0.2, 0.1, 0.8]
    p[:, 0] += np.where(p[:, 2] > 0, 0.15, 0.0)
    return p


def test_fit_recovers_a_similarity_turned_half_a_turn():
    src = _figure()
    r = S.rz(178)
    dst = (1.3 * (r @ src.T)).T + [0.5, -0.2, 1.0]
    f = F.fit(src, dst)
    assert f["start"] == 180
    assert f["s"] == pytest.approx(1.3, rel=1e-6) and np.allclose(f["R"], r, atol=1e-6)
    assert f["residual"]["max"] < 1e-6 and f["iterations"] >= 1


def test_match_prefers_the_twin_with_the_same_uv():
    pos = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    tree = KDTree(len(pos))
    for i, p in enumerate(pos):
        tree.insert(p, i)
    tree.balance()
    f = {"s": 1.0, "R": np.eye(3), "t": np.zeros(3)}
    uvs = {0: {(0.1, 0.1)}, 1: {(0.9, 0.9)}, 2: {(0.5, 0.5)}}
    assert F.match(tree, uvs, f, [0, 0, 0], (0.9, 0.9))[:2] == (1, "uv")
    i, how, _ = F.match(tree, uvs, f, [0, 0, 0], (0.3, 0.3))
    assert how == "pos" and i in (0, 1)
    idx, d = F.nearest_source(tree, f, [0.0, 0.0, 0.0])
    assert sorted(idx) == [0, 1] and d == pytest.approx(0.0)


def test_world_verts_and_uvs_read_a_mesh():
    import bpy
    me = bpy.data.meshes.new("Q")
    me.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    me.uv_layers.new(name="UVMap0")
    obj = bpy.data.objects.new("Q", me)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = (0, 0, 2)
    obj.rotation_euler = (0, 0, math.radians(90))
    bpy.context.view_layer.update()
    w = F.world_verts(obj)
    assert np.allclose(w[1], [0, 1, 2], atol=1e-6)
    assert set(F.uv_by_vertex(obj)) == {0, 1, 2, 3}
