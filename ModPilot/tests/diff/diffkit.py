"""Differential tests (T2) of the restructure: the legacy tool and the new step, run on the same
scene, must agree before the tool's name joins app.phases._bridge.PORTED.

The scenes are claude_run1's legacy checkpoints (a .blend after every step of its replay, made by
tools-5.2 `python -m compat.legacy_baseline checkpoints`, ~650 MB per Blender version in
tools-5.2/runtime/cache, not in git).
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from app.blender.client import BlenderClient
from modpilot_host import tools52
from modpilot_host.session import HeadlessSession

VERSIONS = ("4.3.0", "5.2.2")


def checkpoint_dir(version: str) -> Path:
    return tools52.root() / "runtime" / "cache" / "legacy" / "claude_run1" / f"{version}-checkpoints"


def checkpoints(version: str) -> list[Path]:
    d = checkpoint_dir(version)
    found = sorted(d.glob("*.blend"))
    if not found:
        pytest.skip(f"no legacy checkpoints in {d} (tools-5.2: python -m compat.legacy_baseline checkpoints)")
    return found


@contextmanager
def session_and_client(version: str, work: Path):
    """A headless session plus a legacy BlenderClient on its bridge port (the legacy tools' client)."""
    with HeadlessSession(version, work) as s, BlenderClient(port=s.transport.port, timeout=1800) as client:
        yield s, client
