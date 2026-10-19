"""modpilot_host.transport: the host end of the community blender-mcp bridge (port 9876 in kevin's
Blender, a free port in headless sessions). It sends the one-line call and returns the report
from the step's MODPILOT_REPORT line; a failed step comes back as the same StepError. On error
the bridge wraps the exception text in a JSON message {"exception_type", "message", "traceback"}
(tools-5.2 upstream/blender-mcp addon.py execute_code), so the StepError sits one level down."""
import json
import socket
import threading

import pytest

from modpilot.core.errors import StepError
from modpilot_host.transport import BridgeError, BridgeTransport, call_code

pytestmark = pytest.mark.unit


class FakeBridge:
    """A one-connection server that answers each request with the next canned response."""

    def __init__(self, responses, chunk=None):
        self.responses = list(responses)
        self.requests = []
        self.chunk = chunk
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self.sock.accept()
        with conn:
            for resp in self.responses:
                buf = b""
                while True:
                    buf += conn.recv(65536)
                    try:
                        self.requests.append(json.loads(buf.decode("utf-8")))
                        break
                    except ValueError:
                        continue
                data = json.dumps(resp).encode("utf-8")
                step = self.chunk or len(data)
                for i in range(0, len(data), step):
                    conn.sendall(data[i:i + step])


REPORT = {"ok": True, "step": "doctor", "data": {"blender": "5.2.2"}}


def _ok(stdout):
    return {"status": "success", "result": {"executed": True, "result": stdout}}


def test_the_call_line_is_one_import_and_one_call():
    code = call_code("vertex_groups", {"x_preset": "VRChat", "mesh_objects": ["Body", "UVマップ"]})
    assert code.splitlines()[0] == "import modpilot"
    assert "modpilot.call('vertex_groups', " in code
    ns = {}
    exec(code.replace("import modpilot\n", ""), {"modpilot": type("M", (), {"call": staticmethod(
        lambda n, p: ns.update(name=n, params=p))})})
    assert ns == {"name": "vertex_groups", "params": {"x_preset": "VRChat", "mesh_objects": ["Body", "UVマップ"]}}


def test_a_report_comes_back_from_the_last_report_line():
    stdout = "some add-on chatter\nMODPILOT_REPORT=" + json.dumps(REPORT) + "\n"
    fake = FakeBridge([_ok(stdout)], chunk=7)          # and it arrives in small pieces
    with BridgeTransport(port=fake.port) as t:
        assert t.call("doctor", {}) == REPORT
    assert fake.requests[0]["type"] == "execute_code"


def test_a_step_error_comes_back_as_the_same_step_error():
    err = StepError("precondition", "no armature 'X'", step="vertex_groups", details={"name": "X"})
    message = json.dumps({"exception_type": "StepError", "message": str(err), "traceback": "Traceback ..."})
    fake = FakeBridge([{"status": "error", "message": message}])
    with BridgeTransport(port=fake.port) as t, pytest.raises(StepError) as e:
        t.call("vertex_groups", {})
    assert e.value.to_dict() == err.to_dict()


def test_any_other_bridge_error_is_a_bridge_error_with_its_text():
    message = json.dumps({"exception_type": "ModuleNotFoundError", "message": "No module named 'modpilot'",
                          "traceback": "..."})
    fake = FakeBridge([{"status": "error", "message": message}])
    with BridgeTransport(port=fake.port) as t, pytest.raises(BridgeError) as e:
        t.call("doctor", {})
    assert "No module named 'modpilot'" in str(e.value)


def test_a_reply_without_a_report_line_is_a_bridge_error():
    fake = FakeBridge([_ok("nothing here\n")])
    with BridgeTransport(port=fake.port) as t, pytest.raises(BridgeError):
        t.call("doctor", {})


def test_execute_returns_plain_stdout():
    fake = FakeBridge([_ok("hello\n")])
    with BridgeTransport(port=fake.port) as t:
        assert t.execute("print('hello')") == "hello\n"
