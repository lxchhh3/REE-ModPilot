"""jcns_write: a part's joint constraints (.jcns.102) written in the layout of Capcom's own files, read back and
evaluated by Physics_Sim's port of the game's loader and evaluator (physsim.setup.jcns, physsim.solver.constraints).
For Marette's skirt (kevin 2026-10-18, option B): a helper joint the strand roots hang on, turned by a share of
Spine_0's turn, between roots on Hip (share 0) and roots on Spine_0 (share 1).
Run with tools-5.2's venv: .venv/Scripts/python.exe -m pytest scripts/marette/rebuild/tests -q
(Moved with modpilot.formats.jcns from Known_Good_mod_test/scripts/marette/rebuild/tests/test_jcns_write.py.)"""
import math
import struct
import sys

import numpy as np
import pytest

from modpilot.formats import editors as _E
from modpilot.formats import jcns as J

ROOT = _E.tools52().parent / "Known_Good_mod_test"
sys.path.insert(0, str(ROOT.parent / "Physics_Sim"))
from physsim.setup import jcns  # noqa: E402
from physsim.setup.mesh import joint_hash  # noqa: E402
from physsim.solver import constraints  # noqa: E402
from physsim.solver.f32math import quat_mul  # noqa: E402
from physsim.solver.skeleton import BindPose, Skeleton  # noqa: E402

CAPCOM = ROOT.parent / "Physics_Sim/re/gamefiles/latest/natives/stm/art/model/character/ch03/032/001/5/ch03_032_0015_skirt.jcns.102"


def rot(axis, deg):
    q = np.zeros(4, np.float32)
    q[axis] = math.sin(math.radians(deg) / 2)
    q[3] = math.cos(math.radians(deg) / 2)
    return q


def same_rotation(a, b, tol=1e-5):
    return abs(abs(float(np.dot(a, b))) - 1.0) < tol


def evaluate(data, driver_local, bind):
    """Two joints, 0 the driver (Spine_0) and 1 the target (the helper), both with bind rotation `bind`: the
    target's local rotation after one pass of the file's constraints."""
    c = jcns.parse(data)
    names = ["Spine_0", "Skirt_Root_HJ_00"]
    hashes = [joint_hash(n) for n in names]
    bp = BindPose(hashes=hashes, parents=[-1, -1], rotations=np.array([bind, bind], np.float32),
                  positions=np.zeros((2, 3), np.float32))
    sk = Skeleton(positions=np.zeros((2, 4), np.float32), rotations=np.array([driver_local, bind], np.float32),
                  scales=np.ones((2, 4), np.float32), parents=np.array([-1, -1], np.int16), hashes=hashes)
    slots = [constraints.Joint(sk, bp, hashes.index(h)) for h in c.joint_hashes]
    constraints.evaluate(c, slots)
    return sk.rotations[1]


BIND = np.array([0.1, -0.2, 0.3, 0.927], np.float32) / np.linalg.norm([0.1, -0.2, 0.3, 0.927])


# --- the file ----------------------------------------------------------------------------------------

def test_follow_rotation_reads_back_as_one_group_of_three_euler_rotate_outputs():
    c = jcns.parse(J.write(J.follow_rotation("Skirt_Root_HJ_00", "Spine_0", share=0.5, limit_deg=40.0)))
    assert c.joint_hashes == [joint_hash("Skirt_Root_HJ_00"), joint_hash("Spine_0")]
    assert c.names == {joint_hash("Skirt_Root_HJ_00"): "Skirt_Root_HJ_00", joint_hash("Spine_0"): "Spine_0"}
    assert c.groups() == [[0, 1, 2]]
    for ax, o in enumerate(c.outputs):
        assert (o.target, o.hash, o.kind, o.component, o.op) == (0, joint_hash("Skirt_Root_HJ_00"), jcns.EULER_ROTATE, ax, jcns.SUM)
        assert o.flags == jcns.REST_RELATIVE | jcns.JOINT_TARGET | jcns.DEGREES       # 0x31, as Capcom's skirt
        (i,) = o.inputs
        assert (i.joint, i.source, i.axis, i.flags, i.map_mode) == (1, jcns.SOURCE_EULER, ax, jcns.INPUT_REST_RELATIVE, jcns.RANGE)
        assert i.ins == pytest.approx((-40.0, 0.0, 40.0)) and i.outs == pytest.approx((-20.0, 0.0, 20.0))


def test_the_file_keeps_capcoms_layout_and_constants():
    """Header, the single kind-15 item at 0x50, the stage list [0] (also behind node +0x10), LOD 2 as
    ch03_032_0015_skirt.jcns."""
    data = J.write(J.follow_rotation("Skirt_Root_HJ_00", "Spine_0", share=0.5, limit_deg=40.0))
    ref = CAPCOM.read_bytes()
    for d in (data, ref):
        assert struct.unpack_from("<I4sQQQQII", d, 0)[:2] == (102, b"jcns")
        kinds, items, count = struct.unpack_from("<Q", d, 0x10)[0], struct.unpack_from("<Q", d, 0x20)[0], struct.unpack_from("<I", d, 0x28)[0]
        node = struct.unpack_from("<Q", d, items)[0]
        assert (count, d[kinds], node) == (1, 15, 0x50)
        stages = struct.unpack_from("<Q", d, node + 0x60)[0]
        assert struct.unpack_from("<Q", d, node + 0x10)[0] == stages and struct.unpack_from("<I", d, stages)[0] == 0
        assert d[node + 0x9A] == 1 and not any(d[node + 0x9B:node + 0xA0])
    assert {o.lod for o in jcns.parse(data).outputs} == {o.lod for o in jcns.parse(ref).outputs} == {2}


def test_the_output_target_table_follows_the_corpus_rule():
    """One entry per driven joint, in first-appearance order: [driven, its distinct drivers in input order]."""
    outs = J.follow_rotation("A_HJ", "Spine_0", share=0.5, limit_deg=40.0) + J.follow_rotation("B_HJ", "Spine_1", share=1.0, limit_deg=30.0)
    data = J.write(outs)
    node = 0x50
    table, n = struct.unpack_from("<Q", data, node + 0x68)[0], struct.unpack_from("<H", data, node + 0x88)[0]
    got = []
    for k in range(n):
        p, cnt = struct.unpack_from("<Q", data, table + 16 * k)[0], data[table + 16 * k + 8]
        got.append(list(struct.unpack_from(f"<{cnt + 1}I", data, p)))
    assert got == [[joint_hash("A_HJ"), joint_hash("Spine_0")], [joint_hash("B_HJ"), joint_hash("Spine_1")]]


# --- what the game computes from it -------------------------------------------------------------------

def test_share_one_copies_the_drivers_turn_from_bind():
    data = J.write(J.follow_rotation("Skirt_Root_HJ_00", "Spine_0", share=1.0, limit_deg=90.0))
    turn = quat_mul(quat_mul(rot(0, 20.0), rot(1, -12.0)), rot(2, 7.0))
    local = quat_mul(turn, BIND)                          # bind (x) turn, as the evaluator composes it
    assert same_rotation(evaluate(data, local, BIND), local)


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_share_half_turns_the_target_half_as_far(axis):
    data = J.write(J.follow_rotation("Skirt_Root_HJ_00", "Spine_0", share=0.5, limit_deg=40.0))
    got = evaluate(data, quat_mul(rot(axis, 30.0), BIND), BIND)
    assert same_rotation(got, quat_mul(rot(axis, 15.0), BIND))


def test_a_turn_past_the_limit_is_clamped():
    data = J.write(J.follow_rotation("Skirt_Root_HJ_00", "Spine_0", share=0.5, limit_deg=40.0))
    got = evaluate(data, quat_mul(rot(0, 70.0), BIND), BIND)
    assert same_rotation(got, quat_mul(rot(0, 20.0), BIND))


def test_share_zero_holds_the_target_at_bind():
    data = J.write(J.follow_rotation("Skirt_Root_HJ_00", "Spine_0", share=0.0, limit_deg=40.0))
    assert same_rotation(evaluate(data, quat_mul(rot(0, 30.0), BIND), BIND), BIND)
