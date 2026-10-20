"""Read assets out of a .unitypackage (kevin 2026-10-15: the GG build takes its textures and lilToon
materials from GG/GG_Maya.unitypackage, where the BHS build had them unpacked in Input/).

A .unitypackage is a gzipped tar of <guid>/pathname (the asset's project path, first line), <guid>/asset
(the bytes; absent for a folder) and <guid>/asset.meta. Prefabs name their materials, and materials their
textures, by guid, so a colourway is resolved the way Unity resolves it (prefab -> .mat -> texture), never
by guessing from file names. Pure python: runs in tools-5.2's venv and in Blender.

The package is untrusted data: nothing in it is executed, and a pathname that would land outside the
output folder is refused.

Moved from Known_Good_mod_test/scripts/gg/upk.py unchanged (ModPilot restructure M3, 2026-10-20)."""
import hashlib
import re
import tarfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

_GUID_REF = re.compile(r"\{fileID: (-?\d+)(?:, guid: ([0-9a-f]{32}))?")
_TEX_SLOT = re.compile(r"^\s*- (\w+):\s*\n\s*m_Texture: \{fileID: (-?\d+)(?:, guid: ([0-9a-f]{32}))?", re.M)
_COLOR = re.compile(r"^\s*- (\w+): \{r: ([-\d.eE]+), g: ([-\d.eE]+), b: ([-\d.eE]+), a: ([-\d.eE]+)\}", re.M)


@dataclass
class Index:
    path_of: dict = field(default_factory=dict)    # guid -> pathname
    guid_of: dict = field(default_factory=dict)    # pathname -> guid
    has_asset: set = field(default_factory=set)    # guids that carry an asset (folders do not)


def read_index(upk):
    """Every entry's pathname and whether it has an asset (one pass over the tar headers)."""
    idx = Index()
    with tarfile.open(upk, "r:gz") as t:
        for m in t:
            parts = m.name.split("/")
            if len(parts) != 2:
                continue
            guid, leaf = parts
            if leaf == "pathname":
                p = t.extractfile(m).read().decode("utf-8").splitlines()[0].strip()
                idx.path_of[guid] = p
                idx.guid_of[p] = guid
            elif leaf == "asset":
                idx.has_asset.add(guid)
    return idx


def _read_assets(upk, guids):
    """{guid: bytes} for the given guids' assets."""
    want, out = set(guids), {}
    with tarfile.open(upk, "r:gz") as t:
        for m in t:
            parts = m.name.split("/")
            if len(parts) == 2 and parts[1] == "asset" and parts[0] in want:
                out[parts[0]] = t.extractfile(m).read()
    return out


def read_text(upk, guid):
    return _read_assets(upk, [guid])[guid].decode("utf-8", "replace")


def prefab_materials(text, idx):
    """The .mat pathnames a prefab references, in order of first appearance (slot order)."""
    out = []
    for _, guid in _GUID_REF.findall(text):
        p = idx.path_of.get(guid)
        if p and p.endswith(".mat") and p not in out:
            out.append(p)
    return out


def material_textures(text, idx):
    """{texture slot: pathname} for every slot that points at a texture inside the package."""
    out = {}
    for slot, file_id, guid in _TEX_SLOT.findall(text):
        if file_id != "0" and guid in idx.path_of:
            out[slot] = idx.path_of[guid]
    return out


def material_colors(text):
    """{colour property: (r, g, b, a)} of a material."""
    return {k: tuple(float(c) for c in rgba) for k, *rgba in _COLOR.findall(text)}


def prefab_closure(upk, prefabs):
    """The prefabs, the materials they use and those materials' textures (a set of pathnames)."""
    idx = read_index(upk)
    guids = [idx.guid_of[p] for p in prefabs]          # KeyError on an unknown prefab
    texts = _read_assets(upk, guids)
    out = set(prefabs)
    mats = []
    for g in guids:
        for m in prefab_materials(texts[g].decode("utf-8", "replace"), idx):
            if m not in mats:
                mats.append(m)
    mat_texts = _read_assets(upk, [idx.guid_of[m] for m in mats])
    for m in mats:
        out.add(m)
        out.update(material_textures(mat_texts[idx.guid_of[m]].decode("utf-8", "replace"), idx).values())
    return out


def _safe_target(out_dir, pathname):
    rel = PurePosixPath(pathname)
    if rel.is_absolute() or ".." in rel.parts or ":" in pathname:
        raise ValueError(f"refusing pathname outside the output folder: {pathname!r}")
    return Path(out_dir) / Path(*rel.parts)


def extract(upk, pathnames, out_dir):
    """Write each pathname's asset under out_dir/<pathname>; returns {pathname: {guid, bytes, sha256, file}}."""
    idx = read_index(upk)
    targets = {}
    for p in pathnames:
        guid = idx.guid_of[p]                            # KeyError: not in the package
        if guid not in idx.has_asset:
            raise KeyError(f"{p} has no asset (a folder?)")
        targets[p] = (guid, _safe_target(out_dir, p))
    data = _read_assets(upk, [g for g, _ in targets.values()])
    man = {}
    for p, (guid, dst) in targets.items():
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data[guid])
        man[p] = {"guid": guid, "bytes": len(data[guid]), "sha256": hashlib.sha256(data[guid]).hexdigest(),
                  "file": dst.as_posix()}
    return man
