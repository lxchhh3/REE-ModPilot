"""
Unit tests for `app/agent/history.py` — the off-prompt move log for long
modding sessions.

  MoveLog       — per-session JSON-lines write/read of every "move" (user msg
                  / agent msg / tool call / phase advance / widget confirm /
                  error choice / interrupt). Lives off-prompt at
                  `~/.modpilot/sessions/{sid}/moves.jsonl`. The LLM accesses
                  past moves via the `query_history` meta-tool whose schema
                  lives in the same module.

Run with: uv run pytest -m unit tests/unit/test_history.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.history import (
    QUERY_HISTORY_TOOL_NAME,
    QUERY_HISTORY_TOOL_SCHEMA,
    MoveLog,
)

# ── MoveLog ──────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Patch Path.home() to a tmp dir so MoveLog writes don't touch the real
    user filesystem. Mirror of test_app_config.py's home-stub pattern.

    Path.home is a classmethod — monkeypatch must use `classmethod(...)`,
    NOT `lambda self: tmp_path`, or the patch silently leaks (lesson logged).
    """
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


@pytest.mark.unit
class TestMoveLogPath:
    def test_path_resolves_under_dot_modpilot(self, fake_home):
        log = MoveLog("abc123")
        assert log.path == fake_home / ".modpilot" / "sessions" / "abc123" / "moves.jsonl"

    def test_session_id_with_special_chars_does_not_escape_dir(self, fake_home):
        # Defensive: even though session_ids are 12-char hex in practice,
        # a path-traversal attempt must not write outside the sessions root.
        with pytest.raises(ValueError):
            MoveLog("../escape")


@pytest.mark.unit
class TestMoveLogAppend:
    def test_first_append_creates_parent_dirs(self, fake_home):
        log = MoveLog("sess1")
        assert not log.path.exists()
        log.append({"kind": "user", "content": "hello"})
        assert log.path.is_file()
        assert log.path.parent.is_dir()

    def test_each_append_writes_one_jsonl_line(self, fake_home):
        log = MoveLog("sess1")
        log.append({"kind": "user", "content": "first"})
        log.append({"kind": "assistant", "content": "second"})
        lines = log.path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["content"] == "first"
        assert json.loads(lines[1])["content"] == "second"

    def test_append_injects_ts_and_turn_when_omitted(self, fake_home):
        log = MoveLog("sess1")
        log.append({"kind": "user", "content": "hi"})
        log.append({"kind": "assistant", "content": "yo"})
        moves = log.read()
        assert all("ts" in m for m in moves)
        assert moves[0]["turn"] == 1
        assert moves[1]["turn"] == 2

    def test_explicit_turn_is_preserved(self, fake_home):
        log = MoveLog("sess1")
        log.append({"kind": "user", "content": "hi", "turn": 7})
        assert log.read()[0]["turn"] == 7

    def test_unicode_content_round_trips(self, fake_home):
        """Chinese/Japanese mod names must survive jsonl round-trip without
        cp1252 mangling (lesson: Windows curl + UTF-8 logged in lesson.md)."""
        log = MoveLog("sess1")
        log.append({"kind": "user", "content": "导入模型 終末地"})
        assert log.read()[0]["content"] == "导入模型 終末地"


@pytest.mark.unit
class TestMoveLogRead:
    def _seed(self, log: MoveLog) -> None:
        log.append({"kind": "user", "phase": "setup_validate", "content": "go"})
        log.append({"kind": "tool", "phase": "setup_validate", "name": "scene_info"})
        log.append({"kind": "phase_advance", "phase": "setup_validate", "to_phase": "phase_1"})
        log.append({"kind": "tool", "phase": "phase_1", "name": "pose_correction"})
        log.append({"kind": "tool", "phase": "phase_1", "name": "scene_info"})
        log.append({"kind": "assistant", "phase": "phase_1", "content": "phase 1 done"})

    def test_read_no_filter_returns_all(self, fake_home):
        log = MoveLog("sess1")
        self._seed(log)
        assert len(log.read()) == 6

    def test_read_missing_file_returns_empty(self, fake_home):
        # Cold start — no session dir created yet. Don't crash.
        log = MoveLog("brand_new")
        assert log.read() == []

    def test_filter_by_phase(self, fake_home):
        log = MoveLog("sess1")
        self._seed(log)
        phase_1_moves = log.read(phase="phase_1")
        assert len(phase_1_moves) == 3
        assert all(m["phase"] == "phase_1" for m in phase_1_moves)

    def test_filter_by_kind(self, fake_home):
        log = MoveLog("sess1")
        self._seed(log)
        tool_moves = log.read(kind="tool")
        assert len(tool_moves) == 3
        assert all(m["kind"] == "tool" for m in tool_moves)

    def test_filter_by_name(self, fake_home):
        log = MoveLog("sess1")
        self._seed(log)
        named = log.read(name="scene_info")
        assert len(named) == 2

    def test_last_n_trims_from_end(self, fake_home):
        log = MoveLog("sess1")
        self._seed(log)
        recent = log.read(last_n=2)
        assert len(recent) == 2
        # last two seeded moves are the phase_1 scene_info call + assistant msg
        assert recent[-1]["kind"] == "assistant"

    def test_combined_filters_are_ANDed(self, fake_home):
        log = MoveLog("sess1")
        self._seed(log)
        result = log.read(phase="phase_1", kind="tool")
        assert len(result) == 2
        assert all(m["phase"] == "phase_1" and m["kind"] == "tool" for m in result)

    def test_last_n_applied_after_filters(self, fake_home):
        log = MoveLog("sess1")
        self._seed(log)
        result = log.read(phase="phase_1", last_n=1)
        assert len(result) == 1
        assert result[0]["kind"] == "assistant"

    def test_malformed_line_in_middle_is_skipped(self, fake_home):
        log = MoveLog("sess1")
        log.append({"kind": "user", "content": "ok"})
        # Manually corrupt: append a bad line, then another good one.
        with log.path.open("a", encoding="utf-8") as f:
            f.write("not valid json\n")
        log.append({"kind": "user", "content": "still ok"})
        moves = log.read()
        # Bad line dropped silently; surrounding moves preserved.
        assert len(moves) == 2
        assert moves[0]["content"] == "ok"
        assert moves[1]["content"] == "still ok"


# ── system prompt injection ──────────────────────────────────────────────────


@pytest.mark.unit
class TestContextManagementProtocolInjection:
    """The system prompt must teach the LLM that older detail is off-prompt
    but recoverable via `query_history`. Without this section the LLM has no
    reason to reach for the tool and will keep asking the user for things
    it has already been told."""

    def test_protocol_section_present(self):
        from app.agent.prompts import build_system_prompt
        sysp = build_system_prompt()
        assert "Context Management Protocol" in sysp

    def test_protocol_names_the_query_history_tool(self):
        from app.agent.prompts import build_system_prompt
        from app.agent.history import QUERY_HISTORY_TOOL_NAME
        sysp = build_system_prompt()
        assert QUERY_HISTORY_TOOL_NAME in sysp


@pytest.mark.unit
class TestQueryHistoryToolSchema:
    def test_name_matches_constant(self):
        assert QUERY_HISTORY_TOOL_SCHEMA["name"] == QUERY_HISTORY_TOOL_NAME

    def test_has_description_mentioning_compaction(self):
        # The LLM should learn from the schema description that detail older
        # than the most recent phase has been compacted away and is
        # retrievable here.
        desc = QUERY_HISTORY_TOOL_SCHEMA["description"].lower()
        assert "compact" in desc or "history" in desc

    def test_all_filter_params_are_optional(self):
        schema = QUERY_HISTORY_TOOL_SCHEMA["input_schema"]
        # No required params — calling with empty input returns recent history.
        assert schema.get("required", []) == []

    def test_accepts_phase_kind_name_last_n(self):
        props = QUERY_HISTORY_TOOL_SCHEMA["input_schema"]["properties"]
        for key in ("phase", "kind", "name", "last_n"):
            assert key in props, f"missing schema property: {key}"
