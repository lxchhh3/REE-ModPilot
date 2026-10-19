"""The host end of the community blender-mcp bridge (port 9876 in kevin's Blender, a free port in
headless sessions): raw JSON over TCP, {"type": "execute_code", "params": {"code": ...}} in,
{"status": "success", "result": {"result": <stdout>}} or {"status": "error", "message": ...} out.

`call(step, params)` sends the one-line call and returns the report from the step's
MODPILOT_REPORT line; a failed step is raised as the same StepError (the bridge wraps the
exception text in a JSON message, so it is unwrapped first). Anything else wrong with the round
trip is a BridgeError.
"""
from __future__ import annotations

import contextlib
import json
import socket

from modpilot.core.errors import StepError
from modpilot.core.report import PREFIX as REPORT_PREFIX


class BridgeError(RuntimeError):
    pass


def call_code(step: str, params: dict | None) -> str:
    """The line every channel sends (Blender Lab MCP, the 9876 bridge, headless sessions)."""
    return f"import modpilot\nmodpilot.call({step!r}, {params or {}!r})\n"


def unwrap_bridge_error(message: str) -> tuple[StepError | None, str]:
    """The StepError inside a bridge error message (the bridge wraps the exception text in JSON
    {"exception_type", "message", "traceback"}), and the inner text either way."""
    inner = str(message)
    with contextlib.suppress(ValueError, AttributeError):
        inner = json.loads(inner).get("message", inner)
    return StepError.from_text(inner) or StepError.from_text(str(message)), inner


def report_from_stdout(step: str, stdout: str) -> dict:
    lines = [ln for ln in stdout.splitlines() if ln.startswith(REPORT_PREFIX)]
    if not lines:
        raise BridgeError(f"{step}: no {REPORT_PREFIX} line in Blender's output: {stdout[-2000:]!r}")
    return json.loads(lines[-1][len(REPORT_PREFIX):])


class BridgeTransport:
    def __init__(self, host: str = "127.0.0.1", port: int = 9876, timeout: float = 1800.0) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self._sock: socket.socket | None = None

    def __enter__(self) -> BridgeTransport:
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.settimeout(self.timeout)
        return self

    def __exit__(self, *_) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def _request(self, payload: dict) -> dict:
        if self._sock is None:
            raise BridgeError("not connected (use `with BridgeTransport(...) as t:`)")
        self._sock.sendall(json.dumps(payload).encode("utf-8"))
        buf = b""
        while True:
            chunk = self._sock.recv(1 << 16)
            if not chunk:
                raise BridgeError("the bridge closed the connection before a complete reply")
            buf += chunk
            try:
                return json.loads(buf.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue

    def execute(self, code: str) -> str:
        """Run `code` in Blender; its stdout. A failure raises StepError (if the code raised one)
        or BridgeError."""
        reply = self._request({"type": "execute_code", "params": {"code": code}})
        if reply.get("status") == "success":
            return (reply.get("result") or {}).get("result", "")
        err, inner = unwrap_bridge_error(str(reply.get("message", "")))
        if err is not None:
            raise err
        raise BridgeError(inner[:4000])

    def call(self, step: str, params: dict | None = None) -> dict:
        return report_from_stdout(step, self.execute(call_code(step, params)))


def lab_call_code(step: str, params: dict | None) -> str:
    """The call over Blender Lab MCP: its add-on returns whatever the code assigns to `result`."""
    return f"import modpilot\nresult = modpilot.call({step!r}, {params or {}!r})\n"


class LabTransport:
    """The host end of Blender Lab MCP's add-on socket (port 9877 in kevin's Blender): one request
    per connection, {"type": "execute", "code", "strict_json"} + NUL in, a JSON reply + NUL out
    (upstream blender_mcp mcp/blmcp/tools_helpers/connection.py). Its own MCP server gives up
    after 300 s, so long steps go over the 9876 bridge (BridgeTransport) instead."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9877, timeout: float = 300.0) -> None:
        self.host, self.port, self.timeout = host, port, timeout

    def _request(self, code: str) -> dict:
        payload = json.dumps({"type": "execute", "code": code, "strict_json": True}).encode("utf-8") + b"\0"
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.sendall(payload)
            buf = bytearray()
            while b"\0" not in buf:
                chunk = sock.recv(1 << 16)
                if not chunk:
                    break
                buf.extend(chunk)
        if b"\0" not in buf:
            raise BridgeError("Blender Lab MCP closed the connection before a complete reply")
        return json.loads(bytes(buf).split(b"\0", 1)[0].decode("utf-8"))

    def execute(self, code: str) -> dict:
        reply = self._request(code)
        if reply.get("status") == "ok":
            return reply
        message = str(reply.get("message", ""))
        err = StepError.from_text(message) or StepError.from_text(str(reply.get("stdout", "")))
        if err is not None:
            raise err
        raise BridgeError(message[-4000:])

    def call(self, step: str, params: dict | None = None) -> dict:
        return self.execute(lab_call_code(step, params))["result"]
