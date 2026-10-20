"""Move a built MH Wilds armor mod onto another armor slot and its own texture folder, so it installs beside
the mod it was built from (kevin 2026-10-16: GG moved from pl024 to pl039 Lagiacrus with its own texture copies;
2026-10-18: Marette onto Zeronis's ch03_030_601). bpy-free: mesh / chain2 / clsp / fbxskel carry no slot or path
strings and are copied unchanged under their new names; the mdf2s are rewritten with RE Mesh Editor's bpy-free
reader/writer (byte-lossless round trip), only their texture paths changed; the BoneSystem json gets the new
mesh name and FbxPath. Only the textures an mdf2 names are shipped.

Moved from Known_Good_mod_test/scripts/gg/relocate_slot.py unchanged (its GG defaults stay there).
"""
from __future__ import annotations

import contextlib
import io
import re
import shutil
from pathlib import Path

from modpilot.formats import editors

CHAR = "natives/STM/Art/Model/Character/"
ENGINE = ("MasterMaterial/", "systems/", "RE_ENGINE_LIBRARY/")    # the game's own textures, never shipped
TEX_EXT = ".241106027"
SKEL_DIR = "natives/STM/BoneSystem/"
JSON_DIR = "reframework/data/BoneSystem/"


def slot_path(rel, src, dst):
    """<CHAR>ch03/024/001/<part>/ch03_024_001<part>.<ext> -> the same file on slot dst."""
    head = f"{CHAR}{src[0]}/{src[1]}/{src[2]}/"
    if not rel.startswith(head):
        raise ValueError(f"{rel} is not on slot {'_'.join(src)}")
    part, name = rel[len(head):].split("/")
    stem = f"{src[0]}_{src[1]}_{src[2]}{part}."
    if not name.startswith(stem):
        raise ValueError(f"{rel}: file is not named for slot {'_'.join(src)} part {part}")
    return f"{CHAR}{dst[0]}/{dst[1]}/{dst[2]}/{part}/{dst[0]}_{dst[1]}_{dst[2]}{part}.{name[len(stem):]}"


def texture_map(paths, tex_dir):
    """Every mod texture (not the game's, not already in tex_dir) -> tex_dir/<its file name>."""
    out, seen = {}, {}
    for p in sorted(set(paths)):
        if p.startswith(ENGINE):
            continue
        new = f"{tex_dir}/{p.rsplit('/', 1)[-1]}"
        if seen.setdefault(new, p) != p:
            raise ValueError(f"{p} and {seen[new]} would both become {new}")
        if new != p:
            out[p] = new
    return out


def set_fbx_path(data, name):
    """The BoneSystem json with only its FbxPath value changed (bytes, its own formatting and CRLFs)."""
    new, n = re.subn(rb'("FbxPath"\s*:\s*")[^"]*(")', lambda m: m.group(1) + name.encode() + m.group(2), data)
    if n != 1:
        raise ValueError(f"expected one FbxPath, found {n}")
    return new


def relocate(src, dst, src_slot, dst_slot, tex_dir, fbx_name):
    """Copy the mod at src onto slot dst_slot at dst (replaced if there), textures into tex_dir, the
    skeleton as fbx_name. Returns {moved: {old: new}, textures: {old: new}, unused_textures_dropped}."""
    src, dst = Path(src), Path(dst)
    if dst.exists():
        shutil.rmtree(dst)
    mdf = editors.module("mesh", "mdf.file_re_mdf")
    rels = sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file())
    with contextlib.redirect_stdout(io.StringIO()):
        mdfs = {r: mdf.readMDF(str(src / r)) for r in rels if r.endswith(".mdf2.45")}
    tmap = texture_map([t.texturePath for f in mdfs.values() for m in f.materialList for t in m.textureList],
                       tex_dir)
    named = {t.texturePath for f in mdfs.values() for m in f.materialList for t in m.textureList
             if not t.texturePath.startswith(ENGINE)}
    src_slot_id = "_".join(src_slot)
    report = {"moved": {}, "textures": {}, "unused_textures_dropped": []}

    def put(rel, data=None, from_rel=None):
        p = dst / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if data is None:
            shutil.copy2(src / from_rel, p)
        else:
            p.write_bytes(data)

    for r in rels:
        if r.endswith(".tex" + TEX_EXT):
            if r[len("natives/STM/"):-len(TEX_EXT)] not in named:
                report["unused_textures_dropped"].append(r)
            continue
        if r.startswith(CHAR):
            new = slot_path(r, src_slot, dst_slot)
            if r in mdfs:
                f = mdfs[r]
                for m in f.materialList:
                    for t in m.textureList:
                        t.texturePath = tmap.get(t.texturePath, t.texturePath)
                (dst / new).parent.mkdir(parents=True, exist_ok=True)
                with contextlib.redirect_stdout(io.StringIO()):
                    mdf.writeMDF(f, str(dst / new))
            else:
                put(new, from_rel=r)
        elif r.startswith(SKEL_DIR) and r.endswith(".fbxskel.7"):
            new = f"{SKEL_DIR}{fbx_name}.fbxskel.7"
            if (dst / new).exists():
                raise ValueError(f"more than one fbxskel in {src}")
            put(new, from_rel=r)
        elif r == f"{JSON_DIR}{src_slot_id}2.json":
            new = f"{JSON_DIR}{'_'.join(dst_slot)}2.json"
            put(new, set_fbx_path((src / r).read_bytes(), fbx_name))
        else:
            raise ValueError(f"don't know where {r} goes")
        report["moved"][r] = new
    for old in sorted(named):
        new = tmap.get(old, old)
        put(f"natives/STM/{new}{TEX_EXT}", from_rel=f"natives/STM/{old}{TEX_EXT}")
        report["textures"][old] = new
    return report
