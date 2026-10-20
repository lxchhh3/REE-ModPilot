"""MH Wilds .mdf2 materials through RE Mesh Editor's own bpy-free reader/writer (a byte-lossless round trip),
and a material block copied over named materials. Moved from Known_Good_mod_test/scripts/marette/materials.py
(its read / write, and on_bhs_block with the template file an argument)."""
from __future__ import annotations

import copy
import io
from contextlib import redirect_stdout

from modpilot.formats import editors


def editor():
    return editors.module("mesh", "mdf.file_re_mdf")


def read(path):
    with redirect_stdout(io.StringIO()):
        return editor().readMDF(str(path))


def write(f, path):
    with redirect_stdout(io.StringIO()):
        editor().writeMDF(f, str(path))


def on_block(src_path, out_path, own, block_mdf, template):
    """The mdf2 at src_path with each material named in `own` replaced by a copy of material `template` of the
    mdf2 at block_mdf (renamed, its texture bindings own[name] = {texture type: path} laid over the
    template's), written to out_path. Returns {material: bindings}. Refuses a name not in the file or a
    texture type the template lacks."""
    f = read(src_path)
    block = next(m for m in read(block_mdf).materialList if m.materialName == template)
    done = {}
    for i, m in enumerate(f.materialList):
        if m.materialName not in own:
            continue
        new = copy.deepcopy(block)
        new.materialName = m.materialName
        types = {t.textureType for t in new.textureList}
        for t in new.textureList:
            if t.textureType in own[m.materialName]:
                t.texturePath = own[m.materialName][t.textureType]
        missing = set(own[m.materialName]) - types
        assert not missing, (m.materialName, missing)
        f.materialList[i] = new
        done[m.materialName] = own[m.materialName]
    assert set(done) == set(own), set(own) - set(done)
    write(f, out_path)
    return done
