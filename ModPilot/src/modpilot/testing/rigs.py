"""A small avatar with physics chains, carried through the pipeline steps: the graft scenario of
tools-5.2's tests/test_l3_fixes.py (Ribbon on the chest, a two-bone Tail, an unweighted Helper)
plus an Ear chain. Used by the physics and collider T1 tests."""
import bpy

import modpilot
from modpilot.testing import scenes

TYPES = {"Ribbon": "accessory_ribbon", "Tail": "fur_tail"}


def call(step, params=None):
    return modpilot.call(step, params, quiet=True)


def grafted(ear=True):
    """The graft scenario (plus an Ear chain), through import, join and transplant."""
    call("setup_import_mhwilds")
    bones = [("Hips", None, (0, 0, 0.9), (0, 0, 1.0)), ("Spine", "Hips", (0, 0, 1.0), (0, 0, 1.1)),
             ("Chest", "Spine", (0, 0, 1.1), (0, 0, 1.25)), ("Neck", "Chest", (0, 0, 1.4), (0, 0, 1.5)),
             ("Head", "Neck", (0, 0, 1.5), (0, 0, 1.7)),
             ("Ribbon", "Chest", (0.05, 0.08, 1.2), (0.05, 0.12, 1.08)),
             ("Tail", "Hips", (0, 0.1, 0.92), (0, 0.2, 0.85)), ("Tail.001", "Tail", (0, 0.2, 0.85), (0, 0.3, 0.8)),
             ("Helper", "Hips", (0.1, 0, 0.95), (0.1, 0, 1.0))]
    if ear:
        bones.append(("Ear", "Head", (0.04, 0, 1.65), (0.06, 0, 1.75)))
    arm = scenes.make_armature("Armature", bones)
    quads = [[(-0.1, 0, 0.9), (0.1, 0, 0.9), (0.1, 0, 1.1), (-0.1, 0, 1.1)],
             [(0.04, 0.08, 1.08), (0.06, 0.08, 1.08), (0.06, 0.12, 1.2), (0.04, 0.12, 1.2)],
             [(-0.01, 0.1, 0.8), (0.01, 0.1, 0.8), (0.01, 0.3, 0.92), (-0.01, 0.3, 0.92)]]
    weights = {"Hips": [(i, 1.0) for i in range(4)], "Ribbon": [(i, 1.0) for i in range(4, 8)],
               "Tail": [(8, 1.0), (9, 1.0)], "Tail.001": [(10, 1.0), (11, 1.0)]}
    if ear:
        quads.append([(0.04, -0.01, 1.65), (0.06, -0.01, 1.65), (0.06, 0.01, 1.75), (0.04, 0.01, 1.75)])
        weights["Ear"] = [(i, 1.0) for i in range(12, 16)]
    body = scenes.make_quads("Body", quads, "BodyMat")
    scenes.skin(body, arm, weights)
    call("vertex_groups", {"x_preset": "VRChat", "y_preset": "mhws", "mesh_objects": ["Body"]})
    return arm


def transplant():
    return call("physics_transplant", {"source_armature": "Armature", "x_preset": "VRChat", "y_preset": "mhws"})


def chains(params):
    call("physics_classification")
    call("physics_chains", {"prepare_only": True})
    return call("physics_chains", params)


def groups():
    out = {}
    for o in bpy.data.objects:
        if o.get("TYPE") != "RE_CHAIN_CHAINGROUP":
            continue
        node = next((c for c in o.children if c.get("TYPE") == "RE_CHAIN_NODE"), None)
        head = node.constraints["BoneName"].subtarget if node else ""
        out[head] = o
    return out
