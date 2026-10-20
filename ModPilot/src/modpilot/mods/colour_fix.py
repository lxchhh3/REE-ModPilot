"""The colour-layer fix (Blender-MHWilds lesson #80) for any mod built from Dimi's cloth block: every material
that doubles its base colour gets ColorLayer_MaskMap -> the alpha-0 null, nothing else changes. Kept in game on
the BHS OG (bhs_colour2) and GG (gg22), kevin 2026-10-18. Moved from Known_Good_mod_test/scripts/bhs_shader/
colour_fix.py; its command line stays there.

A material is doubled when it is on the DetailColLayer_MultiBlend shader, both colour-layer masks are the
alpha-255 systems/rendering/NullBlack.tex, layer A's colour has alpha > 0, overlay mode is on and the detail-mask
blend is 1 (then layer A's weight is 1 and overlay with white = base x2)."""
from __future__ import annotations

from pathlib import Path

from modpilot.formats import mdf as materials

SHADER = "DetailColLayer_MultiBlend.mmtr"
OLD, NEW = "systems/rendering/NullBlack.tex", "MasterMaterial/Textures/NullBlack_Alpha_MSK4.tex"


def doubled(m):
    """Layer A fully on (both masks the alpha-255 null, detail blend 1), A colour with alpha > 0, overlay mode."""
    t = {x.textureType: x.texturePath for x in m.textureList}
    p = {x.propName: list(x.propValue) for x in m.propertyList}
    return (m.mmtrPath.endswith(SHADER) and t.get("ColorLayer_MaskMap") == OLD
            and t.get("ColorLayer_DetailMaskMap") == OLD and p.get("ColorLayer_DetailMask_Blend") == [1.0]
            and p.get("ColorLayer_A", [0.0])[-1] > 0 and p.get("UseOverRay_ColorLayer") == [1.0])


def fix_mdf(src, dst):
    """Write the fixed file to dst and return the fixed material names; [] (and nothing written) if none is doubled."""
    f = materials.read(src)
    names = []
    for m in f.materialList:
        if doubled(m):
            hit = [t for t in m.textureList if t.textureType == "ColorLayer_MaskMap"]
            assert len(hit) == 1, m.materialName
            hit[0].texturePath = NEW
            names.append(m.materialName)
    if names:
        materials.write(f, dst)
    return names


def fix_tree(mod_dir):
    """Fix every mdf2 under mod_dir in place. Returns {relative path: fixed material names}."""
    root = Path(mod_dir)
    report = {}
    for p in sorted(root.rglob("*.mdf2.*")):
        fixed = fix_mdf(p, p)
        if fixed:
            report[p.relative_to(root).as_posix()] = fixed
    return report
