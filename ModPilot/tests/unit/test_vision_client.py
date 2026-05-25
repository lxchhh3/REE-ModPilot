"""
Unit tests for app/llm/vision_client.py (issue #22 Stage 0).

Covers:
  - image_to_base64(): downsamples large images, encodes as base64 JPEG, returns
    (b64, mime). Round-trip decode keeps the resized dimensions.
  - VisionClient.is_available() reads settings.vision_model; empty → False.
  - VisionClient.from_settings() builds the right provider trio
    (openai_compatible default for Qwen-VL / DeepSeek-VL; anthropic when model
    starts with "claude-"; ollama when base_url contains "ollama").
  - classify_image() routes to the underlying provider's chat_with_image() and
    returns the text content (no tool-calls expected for single-classification).

No real provider HTTP calls are made — providers are stubbed.

Run with: uv run pytest -m unit tests/unit/test_vision_client.py -v
"""

from __future__ import annotations

import base64
import io
from unittest.mock import patch

import pytest
from PIL import Image

from app.llm.client import BaseProvider, LLMResponse
from app.llm.vision_client import (
    VisionClient,
    image_to_base64,
    refresh_vision_cache,
    vision_available,
)

# ── image_to_base64 ────────────────────────────────────────────────────────


def _make_test_image(width: int, height: int, color=(255, 0, 0)) -> bytes:
    """Build a solid-color PNG in memory."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.unit
def test_image_to_base64_returns_b64_and_mime():
    raw = _make_test_image(64, 64)
    b64, mime = image_to_base64(raw)
    assert isinstance(b64, str)
    assert mime == "image/jpeg"
    # Decodes to a valid JPEG.
    decoded = base64.b64decode(b64)
    decoded_img = Image.open(io.BytesIO(decoded))
    assert decoded_img.format == "JPEG"


@pytest.mark.unit
def test_image_to_base64_downsamples_above_max_dim():
    """A 2048x1024 input should be capped at max_dim=256 on the long side
    while preserving aspect ratio (256x128)."""
    raw = _make_test_image(2048, 1024)
    b64, _ = image_to_base64(raw, max_dim=256)
    decoded = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert decoded.size == (256, 128)


@pytest.mark.unit
def test_image_to_base64_leaves_small_image_alone():
    """Images already smaller than max_dim must keep their original size."""
    raw = _make_test_image(100, 50)
    b64, _ = image_to_base64(raw, max_dim=256)
    decoded = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert decoded.size == (100, 50)


@pytest.mark.unit
def test_image_to_base64_accepts_pathlike(tmp_path):
    """Filesystem paths are accepted alongside raw bytes."""
    raw = _make_test_image(32, 32)
    p = tmp_path / "swatch.png"
    p.write_bytes(raw)
    b64, mime = image_to_base64(p)
    assert mime == "image/jpeg"
    assert len(b64) > 0


@pytest.mark.unit
def test_image_to_base64_converts_rgba_to_rgb():
    """RGBA inputs must be flattened to RGB before JPEG-encoding (JPEG can't
    carry alpha — without conversion Pillow raises OSError)."""
    img = Image.new("RGBA", (40, 40), (0, 255, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64, mime = image_to_base64(buf.getvalue())
    assert mime == "image/jpeg"
    decoded = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert decoded.mode == "RGB"


# ── vision_available gate ──────────────────────────────────────────────────


@pytest.mark.unit
def test_vision_available_false_when_model_empty():
    refresh_vision_cache()
    with patch("app.llm.vision_client.settings") as mock_settings:
        mock_settings.vision_model = ""
        assert vision_available() is False
    refresh_vision_cache()


@pytest.mark.unit
def test_vision_available_true_when_model_set():
    refresh_vision_cache()
    with patch("app.llm.vision_client.settings") as mock_settings:
        mock_settings.vision_model = "qwen-vl-max"
        assert vision_available() is True
    refresh_vision_cache()


@pytest.mark.unit
def test_vision_available_caches_until_refresh():
    """First call snapshots settings.vision_model; subsequent calls hit the
    cache. After refresh_vision_cache() the next read goes through to
    settings again."""
    refresh_vision_cache()
    with patch("app.llm.vision_client.settings") as mock_settings:
        mock_settings.vision_model = "qwen-vl-max"
        assert vision_available() is True
        # Flip settings without refreshing — cache returns the stale True.
        mock_settings.vision_model = ""
        assert vision_available() is True
        # Refresh and re-read — now the empty value is observed.
        refresh_vision_cache()
        assert vision_available() is False
    refresh_vision_cache()


# ── VisionClient.from_settings provider routing ────────────────────────────


@pytest.mark.unit
def test_from_settings_picks_openai_compatible_for_qwen_vl():
    """Default route: any non-claude model with a base_url → OpenAI-compatible."""
    with patch("app.llm.vision_client.settings") as mock_settings:
        mock_settings.vision_model = "qwen-vl-max"
        mock_settings.vision_api_key = "sk-v"
        mock_settings.vision_base_url = (
            "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        with patch("app.llm.openai_provider.OpenAI"):
            client = VisionClient.from_settings()
            from app.llm.openai_provider import OpenAIProvider
            assert isinstance(client._provider, OpenAIProvider)


@pytest.mark.unit
def test_from_settings_picks_anthropic_for_claude_model():
    with patch("app.llm.vision_client.settings") as mock_settings:
        mock_settings.vision_model = "claude-haiku-4-5"
        mock_settings.vision_api_key = "sk-ant"
        mock_settings.vision_base_url = ""
        with patch("app.llm.anthropic_provider.anthropic.Anthropic"):
            client = VisionClient.from_settings()
            from app.llm.anthropic_provider import AnthropicProvider
            assert isinstance(client._provider, AnthropicProvider)


@pytest.mark.unit
def test_from_settings_picks_ollama_when_base_url_says_so():
    with patch("app.llm.vision_client.settings") as mock_settings:
        mock_settings.vision_model = "llava:13b"
        mock_settings.vision_api_key = "sk-ollama"
        mock_settings.vision_base_url = "https://ollama.com"
        client = VisionClient.from_settings()
        from app.llm.ollama_provider import OllamaProvider
        assert isinstance(client._provider, OllamaProvider)


@pytest.mark.unit
def test_from_settings_raises_when_model_blank():
    """Building a VisionClient with no model configured is a programming
    error — callers must check vision_available() first."""
    with patch("app.llm.vision_client.settings") as mock_settings:
        mock_settings.vision_model = ""
        with pytest.raises(ValueError, match="vision_model"):
            VisionClient.from_settings()


# ── classify_image facade ──────────────────────────────────────────────────


class _StubVisionProvider(BaseProvider):
    """Captures chat_with_image() calls so tests can inspect routing."""

    def __init__(self, reply: str = "base_color") -> None:
        self._model = "stub-vl"
        self.calls: list[dict] = []
        self._reply = reply

    def model_name(self) -> str:
        return self._model

    def chat(self, messages, *, system="", tools=None, max_tokens=4096):
        # Unused for vision tests but required by BaseProvider.
        return LLMResponse(content="", tool_calls=[], stop_reason="end_turn", raw=None)

    def chat_with_image(
        self,
        prompt: str,
        image_b64: str,
        mime_type: str,
        *,
        system: str = "",
        max_tokens: int = 256,
    ) -> LLMResponse:
        self.calls.append({
            "prompt": prompt,
            "image_b64": image_b64,
            "mime_type": mime_type,
            "system": system,
            "max_tokens": max_tokens,
        })
        return LLMResponse(
            content=self._reply, tool_calls=[], stop_reason="end_turn", raw=None
        )


@pytest.mark.unit
def test_classify_image_returns_provider_text():
    provider = _StubVisionProvider(reply="normal")
    client = VisionClient(provider)
    result = client.classify_image(
        prompt="What PBR channel is this?",
        image_b64="ZmFrZQ==",
        mime_type="image/jpeg",
    )
    assert result == "normal"
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["prompt"] == "What PBR channel is this?"
    assert call["image_b64"] == "ZmFrZQ=="
    assert call["mime_type"] == "image/jpeg"


@pytest.mark.unit
def test_classify_image_strips_whitespace():
    """Vision models often emit trailing newlines / leading spaces around the
    one-word answer. The facade normalises so callers don't have to."""
    provider = _StubVisionProvider(reply="  roughness\n")
    client = VisionClient(provider)
    assert client.classify_image(
        prompt="?", image_b64="ZmFrZQ==", mime_type="image/jpeg"
    ) == "roughness"


@pytest.mark.unit
def test_vision_client_model_property():
    client = VisionClient(_StubVisionProvider())
    assert client.model == "stub-vl"


@pytest.mark.unit
def test_classify_image_propagates_system_and_max_tokens():
    provider = _StubVisionProvider()
    client = VisionClient(provider)
    client.classify_image(
        prompt="?",
        image_b64="ZmFrZQ==",
        mime_type="image/jpeg",
        system="be terse",
        max_tokens=42,
    )
    call = provider.calls[0]
    assert call["system"] == "be terse"
    assert call["max_tokens"] == 42
