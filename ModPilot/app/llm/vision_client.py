"""
Vision model client (issue #22 Stage 0).

Wraps a vision-capable LLM provider behind the same provider trio used by the
text-only LLMClient (Anthropic / OpenAI-compatible / Ollama). The vision model
is configured independently via `settings.vision_model` / `vision_api_key` /
`vision_base_url` so users can keep an expensive reasoning model for the agent
loop while using a cheap VLM (Qwen-VL, DeepSeek-VL2, LLaVA, …) for image
classification.

Callers MUST gate any vision use with `vision_available()` first — when no
vision_model is configured, building a VisionClient raises.

Image preprocessing (`image_to_base64`) downsamples large textures to 256 px
on the long side by default and re-encodes as JPEG to keep wire payloads small.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from app.config import settings
from app.llm.client import BaseProvider, LLMResponse

# ── image preprocessing ────────────────────────────────────────────────────


def image_to_base64(
    source: bytes | str | Path,
    *,
    max_dim: int = 256,
    quality: int = 85,
) -> tuple[str, str]:
    """Downsample an image and return (base64 string, mime type).

    Args:
        source:   Raw image bytes, or a filesystem path (str / Path).
        max_dim:  Cap the long edge at this pixel count (preserves aspect).
        quality:  JPEG quality. 85 is a good balance for VLM input.

    Returns:
        (b64, "image/jpeg") — always JPEG so callers don't have to branch
        on format. Alpha channels are flattened against white.
    """
    raw = Path(source).read_bytes() if isinstance(source, (str, Path)) else source
    img = Image.open(io.BytesIO(raw))

    if img.mode in ("RGBA", "LA", "P"):
        # JPEG can't carry alpha; flatten to RGB.
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    width, height = img.size
    long_edge = max(width, height)
    if long_edge > max_dim:
        scale = max_dim / long_edge
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        img = img.resize(new_size, Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return b64, "image/jpeg"


# ── availability gate ──────────────────────────────────────────────────────

# Lazily snapshotted on first access — cheap (one bool of one string) but
# spec-mandated (issue #22 §"配置探测规则"). Call refresh_vision_cache() after
# any runtime mutation of settings.vision_model (POST /app/config) or in
# tests that swap the settings singleton.
_vision_available_cached: bool | None = None


def vision_available() -> bool:
    """Whether a vision model is configured. False → all vision phases skip.

    Result is cached after the first call to keep the hot path off the
    settings re-read. Use `refresh_vision_cache()` to force the next call
    to re-evaluate `settings.vision_model`.
    """
    global _vision_available_cached
    if _vision_available_cached is None:
        _vision_available_cached = bool(settings.vision_model)
    return _vision_available_cached


def refresh_vision_cache() -> None:
    """Invalidate the vision_available() cache.

    Called from POST /app/config after settings.vision_model is updated,
    and from any test that mutates the settings singleton mid-run.
    """
    global _vision_available_cached
    _vision_available_cached = None


# ── facade ─────────────────────────────────────────────────────────────────


class VisionClient:
    """Thin facade over a vision-capable BaseProvider.

    Instantiate via VisionClient.from_settings() in normal use, or pass a
    BaseProvider directly in tests.
    """

    def __init__(self, provider: BaseProvider) -> None:
        self._provider = provider

    @classmethod
    def from_settings(cls) -> VisionClient:
        """Build a VisionClient using `settings.vision_*`.

        Provider selection heuristic (same trio as LLMClient):
          - model starts with "claude" → AnthropicProvider
          - base_url contains "ollama"  → OllamaProvider
          - otherwise                   → OpenAIProvider (covers Qwen-VL,
            DeepSeek-VL2, OpenAI vision models, etc.)
        """
        if not settings.vision_model:
            raise ValueError(
                "vision_model is empty — gate calls with vision_available() first."
            )

        model = settings.vision_model
        base_url = settings.vision_base_url or ""
        api_key = settings.vision_api_key or ""

        if model.startswith("claude"):
            from app.llm.anthropic_provider import AnthropicProvider
            provider: BaseProvider = AnthropicProvider(
                api_key=api_key,
                model=model,
                base_url=base_url or None,
            )
        elif "ollama" in base_url.lower():
            from app.llm.ollama_provider import OllamaProvider
            provider = OllamaProvider(
                api_key=api_key,
                model=model,
                base_url=base_url or None,
            )
        else:
            from app.llm.openai_provider import OpenAIProvider
            provider = OpenAIProvider(
                api_key=api_key,
                model=model,
                base_url=base_url or None,
            )

        return cls(provider)

    @property
    def model(self) -> str:
        return self._provider.model_name()

    def classify_image(
        self,
        prompt: str,
        image_b64: str,
        mime_type: str,
        *,
        system: str = "",
        max_tokens: int = 256,
    ) -> str:
        """Send a single-image prompt and return the trimmed text reply.

        Use this for Layer 3 PBR channel classification: the prompt expects a
        single-word answer (base_color / normal / roughness / …) so we strip
        surrounding whitespace before returning.
        """
        resp: LLMResponse = self._provider.chat_with_image(
            prompt,
            image_b64,
            mime_type,
            system=system,
            max_tokens=max_tokens,
        )
        return (resp.content or "").strip()
