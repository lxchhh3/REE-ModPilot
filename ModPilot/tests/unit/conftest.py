"""Unit tests of the legacy agent loop stub tools by patching the legacy tool classes
(patch.object(SetupValidateScene, "run", ...)). Once a tool is ported (app.phases._bridge.PORTED)
the real catalog runs the new in-Blender step in its place and those patches no longer apply, yet
what those tests check, the loop's own mechanics, is the same either way. So unit tests see the
unwrapped legacy catalog; the adapter's own tests (marker `bridged_catalog`) see the real one.
Removed with the agent loop in M6."""
import pytest


@pytest.fixture(autouse=True)
def _legacy_tool_catalog(request, monkeypatch):
    if request.node.get_closest_marker("bridged_catalog"):
        return
    from app.agent import phase_loop
    monkeypatch.setattr(phase_loop, "build_full_tool_catalog", phase_loop.legacy_tool_catalog)
