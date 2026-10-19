"""material_setup / material_inspect find the emission socket by its Blender 4 name.

Blender 4.0 renamed the Principled BSDF 'Emission' socket to 'Emission Color' (Strength now
defaults to 0, which the Toolkit's generator reads as "not emissive"), so material_setup skipped
every emission texture as an unknown slot and material_inspect never saw one (claude_run1 wired
the eye glow by hand). Behaviour in Blender: tools-5.2 tests/test_l3_fixes.py.
"""

import ast
from unittest.mock import MagicMock

import pytest

from app.phases.material import SLOT_SOCKET_SRC, MaterialInspect, MaterialSetup

pytestmark = pytest.mark.unit


def _code(client):
    return client.execute_and_extract.call_args_list[0].args[0]


def test_slot_socket_source_is_valid_python():
    ast.parse(SLOT_SOCKET_SRC)
    assert '"Emission Color"' in SLOT_SOCKET_SRC


def test_setup_wires_slots_through_the_socket_lookup_and_turns_emission_on():
    client = MagicMock()
    client.execute_and_extract.return_value = ['WIRED:{"wired": [], "skipped": []}']
    MaterialSetup()._wire_all_materials(client, "Eye", "VRChat", {"EyeMat": {"Emission": "C:/e.png"}})
    code = _code(client)
    assert SLOT_SOCKET_SRC in code
    assert "target_inp = _slot_socket(pbs, slot)" in code
    assert "_emission_on(pbs)" in code


def test_inspect_reads_slots_through_the_socket_lookup():
    client = MagicMock()
    client.execute_and_extract.return_value = ['INSPECT:{"materials": [], "connections": {}}']
    MaterialInspect()._inspect_scene(client, "Eye")
    code = _code(client)
    assert SLOT_SOCKET_SRC in code
    assert "inp = _slot_socket(pbs, slot)" in code
