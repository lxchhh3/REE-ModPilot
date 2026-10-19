"""Smoke test of kevin's everyday Blender 5.2 (opt-in: `uv run pytest -m live`). Read-only: it runs
`doctor` and one failing `doctor` over both channels Claude Code uses to drive that Blender:

  9876  the community blender-mcp bridge (BridgeTransport), for long steps
  9877  Blender Lab MCP's add-on socket (LabTransport), 300 s limit

The modpilot package reaches that Blender through the junction
%APPDATA%/Blender Foundation/Blender/5.2/scripts/addons/modules/modpilot -> the fork's src/modpilot
(Blender-MHWilds lesson #98). A channel that isn't listening is skipped, not failed.
"""
import socket

import pytest

from modpilot.core.errors import StepError
from modpilot_host.transport import BridgeTransport, LabTransport

pytestmark = pytest.mark.live


def _listening(port):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


CHANNELS = {
    "bridge-9876": lambda: BridgeTransport(port=9876, timeout=120),
    "lab-9877": lambda: LabTransport(port=9877, timeout=120),
}
PORTS = {"bridge-9876": 9876, "lab-9877": 9877}


def _call(channel, step, params):
    t = CHANNELS[channel]()
    if isinstance(t, BridgeTransport):
        with t:
            return t.call(step, params)
    return t.call(step, params)


@pytest.mark.parametrize("channel", CHANNELS)
def test_doctor_answers_from_the_live_blender(channel):
    if not _listening(PORTS[channel]):
        pytest.skip(f"nothing listening on {PORTS[channel]}")
    r = _call(channel, "doctor", {"require": ["modder", "mhws", "re_chain", "re_clsp", "re_mesh"]})
    d = r["data"]
    assert r["ok"] and d["background"] is False and d["blender"].startswith("5.2")
    assert d["modpilot"]["path"].replace("\\", "/").endswith("ModPilot/src/modpilot")


@pytest.mark.parametrize("channel", CHANNELS)
def test_a_step_error_comes_back_from_the_live_blender(channel):
    if not _listening(PORTS[channel]):
        pytest.skip(f"nothing listening on {PORTS[channel]}")
    with pytest.raises(StepError) as e:
        _call(channel, "doctor", {"require": ["no_such_ns"]})
    assert e.value.category == "environment" and e.value.details["missing"] == ["no_such_ns"]
