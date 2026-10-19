"""HeadlessSession: a private headless Blender serving the blender-mcp bridge on a free port.

    with HeadlessSession("5.2.2", work_dir) as s:
        s.open(checkpoint)                    # optional
        report = s.call("doctor", {})

It runs tools-5.2's harness/mcp_headless.py (the pinned blender-mcp add-on, its queue drained by
the main thread because its UI timer never fires in --background) in an isolated profile with the
pinned add-ons and the modpilot package linked in (compat.runtime.build_runtime(modpilot_src=)).
Never port 9876, where kevin's own Blender listens.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from modpilot_host import tools52
from modpilot_host.transport import BridgeTransport

MCP_MODULE = "blender_mcp_addon"


class HeadlessSession:
    def __init__(self, version: str, work: Path, timeout: float = 1800.0) -> None:
        self.version = version
        self.work = Path(work)
        self.timeout = timeout
        self.proc = None
        self.transport: BridgeTransport | None = None
        self._session = None

    def __enter__(self) -> HeadlessSession:
        compat = tools52.compat()
        from compat.l3 import wait_ready
        pins = compat.config.load_pins()
        self.work.mkdir(parents=True, exist_ok=True)
        spec, ready, self._stop = self.work / "spec.json", self.work / "ready.json", self.work / "stop"
        for f in (ready, self._stop):
            f.unlink(missing_ok=True)
        spec.write_text(json.dumps({"modules": [a.module for a in pins.addons], "mcp_module": MCP_MODULE}),
                        encoding="utf-8")
        self._session = compat.runtime.build_runtime(pins, modpilot_src=tools52.SRC)
        self.log = self.work / f"blender-{self.version}.log"
        self._log_handle = open(self.log, "w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(
            [str(pins.blenders[self.version]), "--background", "--factory-startup", "--python-exit-code", "1",
             "--python", str(tools52.root() / "harness" / "mcp_headless.py"), "--", str(spec), str(ready),
             str(self._stop)],
            env=compat.runtime.blender_env(self._session), stdout=self._log_handle, stderr=subprocess.STDOUT)
        try:
            port = wait_ready(ready, self.proc, self.log, timeout=300)
            self.transport = BridgeTransport(port=port, timeout=self.timeout).__enter__()
            self.execute("from modpilot.core import headless\nheadless.ensure_background_safe()\n")
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_) -> None:
        if self.transport is not None:
            self.transport.__exit__(None, None, None)
            self.transport = None
        if self.proc is not None:
            self._stop.write_text("", encoding="utf-8")
            try:
                self.proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            self.proc = None
            self._log_handle.close()
        if self._session is not None:
            tools52.compat().runtime.remove_session(self._session)
            self._session = None

    def execute(self, code: str) -> str:
        return self.transport.execute(code)

    def call(self, step: str, params: dict | None = None) -> dict:
        return self.transport.call(step, params)

    def open(self, blend: Path) -> None:
        """Open a .blend (a checkpoint) in place of the current scene."""
        self.execute(f"import bpy\nbpy.ops.wm.open_mainfile(filepath={str(Path(blend))!r}, load_ui=False)\n")
