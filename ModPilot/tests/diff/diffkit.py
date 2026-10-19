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


GOLDEN = Path(__file__).resolve().parents[1] / "golden"


def golden_params(log: str, index: int) -> tuple[str, dict]:
    """(tool, params) of call `index` in tests/golden/<log>.jsonl."""
    import json
    lines = [ln for ln in (GOLDEN / f"{log}.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    rec = json.loads(lines[index])
    return rec["tool"], rec["params"]


def checkpoint_before(version: str, step_index: int) -> Path | None:
    """claude_run1's scene before replay step `step_index` (None: the empty scene before step 0)."""
    if step_index == 0:
        return None
    found = [p for p in checkpoints(version) if p.name.startswith(f"{step_index - 1:02d}_")]
    assert found, f"no checkpoint {step_index - 1:02d}_* for {version}"
    return found[0]


def start(session, ck: Path | None) -> None:
    if ck is None:
        session.execute("import bpy\nbpy.ops.wm.read_homefile(use_empty=True)\n")
    else:
        session.open(ck)


# Scene properties only the new steps write (modpilot.core.config): not a difference in what a
# step does to the build.
NEW_ONLY_SCENE_KEYS = {"modpilot_config"}


def fingerprint(session) -> dict:
    sections = session.call("scene_fingerprint")["data"]["sections"]
    sections["scene"] = {k: v for k, v in sections["scene"].items() if k not in NEW_ONLY_SCENE_KEYS}
    return sections


def run_legacy(client, tool: str, params: dict):
    """The legacy tool's result: PhaseResult for a phase tool, parsed JSON for a query tool."""
    import json

    from app.agent.phase_loop import legacy_tool_catalog
    from app.blender.state import SceneCache
    from app.phases.query_tools import QueryTool
    t = legacy_tool_catalog()[tool]
    if isinstance(t, QueryTool):
        return json.loads(t.run(client, params))
    return t.run(client, SceneCache(client), params)


def differing_sections(a: dict, b: dict) -> dict:
    """{section: {key: (a, b)}} for the keys that differ, within each fingerprint section."""
    out = {}
    for name in sorted(set(a) | set(b)):
        sa, sb = a.get(name, {}), b.get(name, {})
        keys = sorted(set(sa) | set(sb))
        bad = {k: (sa.get(k), sb.get(k)) for k in keys if sa.get(k) != sb.get(k)}
        if bad:
            out[name] = bad
    return out
