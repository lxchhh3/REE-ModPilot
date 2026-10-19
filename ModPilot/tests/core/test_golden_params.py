"""Every params dict the three builds that passed in game sent to ModPilot (tests/golden/*.jsonl)
parses under the new step's strict params, once that step exists. Tools not ported yet are
expected failures; the list shrinks as M2 lands each port."""
import json
from pathlib import Path

import pytest

import modpilot.steps  # noqa: F401  (registers the steps; they import Blender only inside functions)
from modpilot.core.params import parse
from modpilot.core.step import REGISTRY

pytestmark = pytest.mark.unit

GOLDEN = Path(__file__).resolve().parents[1] / "golden"


def _records():
    out = []
    for log in sorted(GOLDEN.glob("*.jsonl")):
        for i, line in enumerate(log.read_text(encoding="utf-8").splitlines()):
            if line.strip():
                rec = json.loads(line)
                out.append(pytest.param(rec["tool"], rec["params"], id=f"{log.stem}-{i:02d}-{rec['tool']}"))
    return out


@pytest.mark.parametrize("tool,params", _records())
def test_the_new_step_accepts_what_the_landed_builds_sent(tool, params):
    if tool not in REGISTRY.names():
        pytest.xfail(f"{tool} is not ported yet")
    parse(REGISTRY.get(tool).params_cls, params)


def test_the_golden_logs_are_all_there():
    assert {p.stem for p in GOLDEN.glob("*.jsonl")} == {"claude_run1", "gg_mp4", "marette"}
    assert len(_records()) == 20 + 16 + 19
