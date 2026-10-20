"""chain2 files through RE Chain Editor's own reader/writer (file_re_chain2), bpy-free. Moved from
Known_Good_mod_test/scripts/og_collar/collar_lib.py unchanged: a verified build's chain2 round-trips
byte for byte, and records compare with their file offsets zeroed (they move when groups are added)."""
from __future__ import annotations

import io
from pathlib import Path

from modpilot.formats import editors

VERSION = 14          # MH Wilds' chain2 (.chain2.14): the version its records are written with


def editor():
    return editors.module("chain", "file_re_chain2")


def load(path):
    return load_bytes(Path(path).read_bytes())


def load_bytes(data):
    cf = editor().Chain2File()
    cf.read(io.BytesIO(data))
    return cf


def to_bytes(cf):
    buf = io.BytesIO()
    cf.write(buf)
    return buf.getvalue()


def copy(obj):
    """A record's shallow copy (its lists copied, not shared)."""
    new = obj.__class__()
    new.__dict__.update({k: (list(v) if isinstance(v, list) else v) for k, v in vars(obj).items()})
    return new


def struct_bytes(obj, *args):
    buf = io.BytesIO()
    obj.write(buf, *args)
    return buf.getvalue()


def no_offsets(obj, fields):
    c = copy(obj)
    for f in fields:
        setattr(c, f, 0)
    return c


def group_bytes(g):
    """A group's record and its nodes as written, file offsets zeroed."""
    rec = struct_bytes(no_offsets(g, ("nodeOffset", "subGroupDataOffset")), VERSION)
    return rec, [struct_bytes(no_offsets(n, ("jiggleDataOffset",)), VERSION) for n in g.nodeList]


def link_bytes(link):
    rec = struct_bytes(no_offsets(link, ("nodeOffset",)), VERSION)
    return rec, [struct_bytes(n) for n in link.nodeColLinkList]
