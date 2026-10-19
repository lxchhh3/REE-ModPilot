"""Making mesh parts join-safe (ModPilot lesson #48; Blender-MHWilds lessons #11 / #42 / #73).

Blender's join keeps ONE value per shape key (the active object's) and merges UV / colour layers by
NAME, while the exporter ships each vertex's BASIS position (keys are muted before export) and writes
UV layers by INDEX. Unprepared, the BHS shoes lost High heeled = 1 (soles 4.3 cm into the floor) and
the GG garments' 'UVマップ' went to a third layer the exporter never writes (every UV at (0, 0),
colour zero-filled: the clothes did not draw).
  1. each part's current shape-key mix becomes its basis; every key block moves by the same offset,
     so each key still adds what it added, and every value goes to 0
  2. each part's UV layers take the active part's names by position (missing ones are added,
     zero-filled), so each part exports the UVs it would have exported alone
  3. a colour layer some part lacks is added to it white (MultiBlend cloth reads vertex colour, and
     black cut the clothes away in game)
"""
from __future__ import annotations


def bake_mix_keep_keys(obj) -> dict | None:
    keys = obj.data.shape_keys
    if keys is None or not keys.use_relative:
        return None
    live = {kb.name: round(kb.value, 6) for kb in keys.key_blocks[1:] if kb.value != 0.0 and not kb.mute}
    if not live:
        return None
    n = len(obj.data.vertices)
    ref_co, mix_co = [0.0] * (3 * n), [0.0] * (3 * n)
    keys.reference_key.data.foreach_get("co", ref_co)
    tmp = obj.shape_key_add(name="__modpilot_mix", from_mix=True)
    tmp.data.foreach_get("co", mix_co)
    obj.shape_key_remove(tmp)
    shift = [m - r for m, r in zip(mix_co, ref_co, strict=True)]
    co = [0.0] * (3 * n)
    for kb in keys.key_blocks:
        kb.data.foreach_get("co", co)
        kb.data.foreach_set("co", [c + s for c, s in zip(co, shift, strict=True)])
    for kb in keys.key_blocks[1:]:
        kb.value = 0.0
    obj.data.vertices.foreach_set("co", mix_co)
    obj.data.update()
    return live


def match_uv_layers(obj, names: list[str]) -> tuple[dict, list]:
    uv = obj.data.uv_layers
    old = [u.name for u in uv]
    k = min(len(old), len(names))
    renamed = {old[i]: names[i] for i in range(k) if old[i] != names[i]}
    if renamed:
        for i in range(k):  # through temporary names: a part's 'UVMap' may have to become 'UV 맵' first
            uv[i].name = f"__modpilot_uv{i}"
        for i in range(k):
            uv[i].name = names[i]
    added = []
    for name in names[k:]:
        layer = uv.new(name=name)
        layer.data.foreach_set("uv", [0.0] * (2 * len(layer.data)))
        added.append(name)
    return renamed, added


def prepare_for_join(objs) -> dict:
    """`objs[0]` is the part the join keeps (the active one)."""
    report = {"baked_keys": {}, "uv_renamed": {}, "uv_added": {}, "colour_added": {}}
    for obj in objs:
        live = bake_mix_keep_keys(obj)
        if live:
            report["baked_keys"][obj.name] = live
    names = [u.name for u in objs[0].data.uv_layers]
    for obj in objs[1:]:
        renamed, added = match_uv_layers(obj, names)
        if renamed:
            report["uv_renamed"][obj.name] = renamed
        if added:
            report["uv_added"][obj.name] = added
    colours: dict = {}
    for obj in objs:
        for ca in obj.data.color_attributes:
            colours.setdefault(ca.name, (ca.domain, ca.data_type))
    for obj in objs:
        for name, (domain, data_type) in colours.items():
            if name in obj.data.color_attributes:
                continue
            ca = obj.data.color_attributes.new(name=name, type=data_type, domain=domain)
            ca.data.foreach_set("color", [1.0] * (4 * len(ca.data)))
            report["colour_added"].setdefault(obj.name, []).append(name)
    return report
