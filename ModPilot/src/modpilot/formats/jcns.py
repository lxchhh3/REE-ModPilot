"""A part's joint constraints (.jcns.102, via.motion.JointConstraints) written from scratch, in the layout of
Capcom's own ch03_032_0015_skirt.jcns: one kind-15 node whose stage 0 (the output evaluator) writes each output's
scalar into one component of a driven joint (Physics_Sim re/notes/jcns_format.md, jcns_runtime.md).

For Marette's skirt (kevin 2026-10-18, option B): the strand roots hang on a helper joint that `follow_rotation`
turns by a share of Spine_0's turn from bind; her skirt chain updates Last (UpdateTiming 4), after the parts'
constraints, so the chain reads what this file writes.

Only what the corpus uses is written: joint inputs with a two- or three-point range map, no value records, no
curves, one stage. Pure python.

Moved from Known_Good_mod_test/scripts/marette/rebuild/jcns_write.py unchanged (ModPilot restructure M3, 2026-10-20)."""
import struct
from dataclasses import dataclass, field

from modpilot.formats.editors import hash_name

VERSION, MAGIC, NODE = 102, b"jcns", 15
NODE_AT, NODE_SIZE, OUTPUT_SIZE, INPUT_SIZE, TARGET_SIZE = 0x50, 0xA0, 0x50, 0x48, 0x10
TRANSLATE, EULER_SET, SCALE, EULER_ROTATE = 0, 1, 2, 13                      # output kinds (+0x2f)
REST_RELATIVE, CLAMP_MIN, CLAMP_MAX, JOINT_TARGET, DEGREES = 0x01, 0x04, 0x08, 0x10, 0x20   # output flags
SUM, AVERAGE, PRODUCT, MIN, MAX = 0, 1, 2, 3, 4                              # combine ops (+0x48)
SOURCE_TRANSLATE, SOURCE_EULER, SOURCE_SCALE, SWING_TWIST = 0, 1, 2, 3        # input sources (+0x19)
INPUT_REST_RELATIVE, THREE_POINT = 0x01, 0x02                                # input flags (+0x18)
RANGE = 0                                                                    # input map mode (+0x1d)


@dataclass
class JointIn:
    """A driver joint's channel, mapped ins -> outs (two-point: ins[0] -> outs[0], ins[2] -> outs[2], clamped)."""
    joint: str
    axis: int
    ins: tuple
    outs: tuple
    source: int = SOURCE_EULER
    flags: int = INPUT_REST_RELATIVE
    euler_order: int = 0
    ease: int = 0
    ref: tuple = (0.0, 0.0, 0.0, 1.0)


@dataclass
class Write:
    """One scalar into one component of `target`; a lead with group_extra n writes itself and the next n."""
    target: str
    kind: int
    component: int
    inputs: list = field(default_factory=list)
    flags: int = REST_RELATIVE | JOINT_TARGET | DEGREES
    op: int = SUM
    euler_order: int = 0
    lod: int = 2
    group_extra: int = 0
    clamp: tuple = (0.0, 0.0)
    ref: tuple = (0.0, 0.0, 0.0, 1.0)


def follow_rotation(target, driver, share, limit_deg):
    """`target`'s local rotation = its bind turned by `share` x `driver`'s turn from bind, each euler axis
    (order 0), the driver's turn read up to +-limit_deg (beyond it the target holds share x limit)."""
    lim = float(limit_deg)
    return [Write(target, EULER_ROTATE, ax, [JointIn(driver, ax, (-lim, 0.0, lim), (-share * lim, 0.0, share * lim))],
                  group_extra=2 if ax == 0 else 0) for ax in range(3)]


def _align(n, a):
    return (n + a - 1) // a * a


def write(outputs):
    """The .jcns.102 bytes for `outputs` (in evaluation order)."""
    joints = []
    for o in outputs:
        for name in [o.target] + [i.joint for i in o.inputs]:
            if name not in joints:
                joints.append(name)
    index = {n: k for k, n in enumerate(joints)}
    hashes = [hash_name(n) for n in joints]
    targets = []                                          # [driven, its drivers], first appearance order
    for o in outputs:
        if o.flags & JOINT_TARGET:
            row = next((t for t in targets if t[0] == o.target), None)
            if row is None:
                row = [o.target]
                targets.append(row)
            row += [i.joint for i in o.inputs if i.joint not in row]
    # layout: header, kinds, items, node, outputs, inputs, names, target table, target hashes, stages, hash table
    at = NODE_AT + NODE_SIZE
    out_at = at
    at += OUTPUT_SIZE * len(outputs)
    in_at = []
    for o in outputs:
        in_at.append(at)
        at += INPUT_SIZE * len(o.inputs)
    name_at = {}
    for n in joints:
        name_at[n] = at
        at += 2 * (len(n) + 1)
    at = _align(at, 16)
    table_at = at
    at += TARGET_SIZE * len(targets)
    row_at = []
    for t in targets:
        row_at.append(at)
        at = _align(at + 4 * len(t), 8)
    at = _align(at, 16)
    stage_at = at
    at += 16
    hash_at = at
    at = _align(at + 4 * len(hashes), 16)
    d = bytearray(at)
    struct.pack_into("<I4sQQQQII", d, 0, VERSION, MAGIC, 0, 0x30, 0, 0x40, 1, 0)
    d[0x30] = NODE
    struct.pack_into("<Q", d, 0x40, NODE_AT)
    n = NODE_AT
    struct.pack_into("<QQQ", d, n, 0, out_at, stage_at)
    struct.pack_into("<QQQ", d, n + 0x60, stage_at, table_at, hash_at)
    struct.pack_into("<IHHH", d, n + 0x80, len(hashes), 0, len(outputs), len(targets))
    d[n + 0x9A] = 1
    for k, o in enumerate(outputs):
        p = out_at + OUTPUT_SIZE * k
        struct.pack_into("<QQQ", d, p, 0, in_at[k], name_at[o.target])
        struct.pack_into("<II", d, p + 0x20, index[o.target], hash_name(o.target))
        d[p + 0x2D], d[p + 0x2E], d[p + 0x2F] = len(o.inputs), o.flags, o.kind
        struct.pack_into("<4f2f", d, p + 0x30, *o.ref, *o.clamp)
        d[p + 0x48], d[p + 0x49], d[p + 0x4A], d[p + 0x4B], d[p + 0x4D] = o.op, o.component, o.euler_order, o.lod, o.group_extra
        for j, i in enumerate(o.inputs):
            q = in_at[k] + INPUT_SIZE * j
            struct.pack_into("<QQI", d, q, 0, name_at[i.joint], index[i.joint])
            d[q + 0x18], d[q + 0x19], d[q + 0x1A], d[q + 0x1B], d[q + 0x1C], d[q + 0x1D] = (
                i.flags, i.source, i.axis, i.euler_order, i.ease, RANGE)
            struct.pack_into("<3f3f4f", d, q + 0x20, *i.ins, *i.outs, *i.ref)
    for name, p in name_at.items():
        d[p:p + 2 * len(name)] = name.encode("utf-16le")
    for k, t in enumerate(targets):
        struct.pack_into("<QB", d, table_at + TARGET_SIZE * k, row_at[k], len(t) - 1)
        struct.pack_into(f"<{len(t)}I", d, row_at[k], *[hash_name(x) for x in t])
    struct.pack_into(f"<{len(hashes)}I", d, hash_at, *hashes)
    return bytes(d)
