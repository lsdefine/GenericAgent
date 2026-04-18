from __future__ import annotations

import base64
import copy
import io
import math
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from PIL import Image

import llmcore
from llmcore import ClaudeSession, LLMSession, NativeClaudeSession, NativeOAISession

DEFAULT_PROMPT = "详细描述这张图片的内容"
DEFAULT_MAX_PIXELS = 1_440_000
DEFAULT_TIMEOUT = 60
DEFAULT_CFG_NAMES = (
    "claude_config141",
    "native_claude_config2",
    "native_claude_config84",
    "native_claude_config5535",
)


def _normalize_prompt(prompt: str | None) -> str:
    if prompt is None:
        return DEFAULT_PROMPT
    prompt = str(prompt).strip()
    return prompt or DEFAULT_PROMPT


def _load_image(image_input: Any) -> Image.Image:
    if isinstance(image_input, Image.Image):
        return image_input.copy()
    if isinstance(image_input, (str, Path)):
        p = Path(image_input)
        if not p.exists():
            raise FileNotFoundError(f"image not found: {p}")
        with Image.open(p) as img:
            return img.copy()
    raise TypeError("image_input must be str, Path, or PIL.Image.Image")


def _resize_image(img: Image.Image, max_pixels: int = DEFAULT_MAX_PIXELS) -> Image.Image:
    max_pixels = int(max_pixels or DEFAULT_MAX_PIXELS)
    if max_pixels <= 0:
        raise ValueError("max_pixels must be > 0")
    w, h = img.size
    if w <= 0 or h <= 0:
        raise ValueError(f"invalid image size: {img.size}")
    pixels = w * h
    if pixels <= max_pixels:
        return img
    scale = math.sqrt(max_pixels / float(pixels))
    nw = max(1, int(w * scale))
    nh = max(1, int(h * scale))
    return img.resize((nw, nh), Image.LANCZOS)


def _normalize_mode_for_png(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "RGB"):
        return img
    if img.mode in ("LA",):
        return img.convert("RGBA")
    if img.mode == "P":
        return img.convert("RGBA" if "transparency" in img.info else "RGB")
    return img.convert("RGB")


def _encode_png_bytes(image_input: Any, max_pixels: int = DEFAULT_MAX_PIXELS) -> tuple[bytes, str, tuple[int, int]]:
    img = _normalize_mode_for_png(_resize_image(_load_image(image_input), max_pixels=max_pixels))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), "image/png", img.size


def image_to_data_url(image_input: Any, max_pixels: int = DEFAULT_MAX_PIXELS) -> str:
    data, media_type, _ = _encode_png_bytes(image_input, max_pixels=max_pixels)
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def _build_user_message(image_input: Any, prompt: str | None = None, max_pixels: int = DEFAULT_MAX_PIXELS) -> dict:
    data, media_type, _ = _encode_png_bytes(image_input, max_pixels=max_pixels)
    return {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(data).decode("ascii"),
                },
            },
            {"type": "text", "text": _normalize_prompt(prompt)},
        ],
    }



def _unwrap_session(session: Any):
    return getattr(session, "backend", session)


def _resolve_cfg(cfg: dict | None = None, cfg_name: str | None = None) -> tuple[dict, str]:
    if cfg is not None:
        if not isinstance(cfg, dict):
            raise TypeError("cfg must be a dict when provided")
        return copy.deepcopy(cfg), (cfg_name or cfg.get("name") or "")
    mykeys = getattr(llmcore, "mykeys")
    if cfg_name:
        hit = mykeys.get(cfg_name)
        if not isinstance(hit, dict):
            raise KeyError(f"config not found or not a dict: {cfg_name}")
        return copy.deepcopy(hit), cfg_name
    for name in DEFAULT_CFG_NAMES:
        hit = mykeys.get(name)
        if isinstance(hit, dict):
            return copy.deepcopy(hit), name
    raise KeyError(f"no usable vision config found in {DEFAULT_CFG_NAMES}")


def _guess_session_cls(cfg: dict, cfg_name: str = ""):
    explicit = str(cfg.get("session_class") or cfg.get("session_type") or "").strip().lower()
    if explicit in {"nativeclaudesession", "native_claude", "native_claude_session"}:
        return NativeClaudeSession
    if explicit in {"nativeoaisession", "native_oai", "native_openai", "native_oai_session"}:
        return NativeOAISession
    if explicit in {"claudesession", "claude", "anthropic"}:
        return ClaudeSession
    if explicit in {"llmsession", "openai", "oai"}:
        return LLMSession

    hint = " | ".join(
        str(x) for x in [cfg_name, cfg.get("name"), cfg.get("model"), cfg.get("apibase")] if x
    ).lower()
    if "native" in hint and "claude" in hint:
        return NativeClaudeSession
    if "native" in hint and any(k in hint for k in ("oai", "openai", "gpt")):
        return NativeOAISession
    if any(k in hint for k in ("claude", "anthropic")):
        return ClaudeSession
    return LLMSession


@contextmanager
def _temporary_session_overrides(session: Any, timeout: int = DEFAULT_TIMEOUT, max_retries: int = 0):
    timeout = max(1, int(timeout or DEFAULT_TIMEOUT))
    max_retries = max(0, int(max_retries or 0))
    restore = {}
    for name, value in {
        "connect_timeout": min(10, timeout),
        "read_timeout": max(5, timeout),
        "max_retries": max_retries,
    }.items():
        if hasattr(session, name):
            restore[name] = getattr(session, name)
            setattr(session, name, value)
    try:
        yield session
    finally:
        for name, value in restore.items():
            setattr(session, name, value)


def _prepare_messages_for_raw_ask(session: Any, user_msg: dict) -> list[dict]:
    if hasattr(session, "make_messages"):
        return session.make_messages([user_msg])
    return [user_msg]


def _join_text_blocks(blocks: list[dict]) -> str:
    texts = [str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(t for t in texts if t).strip()


def _drain_generator(gen) -> tuple[str, Any]:
    streamed = []
    try:
        while True:
            chunk = next(gen)
            if isinstance(chunk, str):
                streamed.append(chunk)
    except StopIteration as e:
        return "".join(streamed).strip(), e.value


def _extract_text(result: Any, streamed_text: str = "") -> str:
    if isinstance(result, list):
        text = _join_text_blocks(result)
        return text or streamed_text.strip()
    if hasattr(result, "content"):
        return str(getattr(result, "content", "") or streamed_text).strip()
    if isinstance(result, str):
        return result.strip()
    return streamed_text.strip()


def _call_backend(session: Any, user_msg: dict) -> str:
    if hasattr(session, "raw_ask"):
        messages = _prepare_messages_for_raw_ask(session, user_msg)
        streamed_text, result = _drain_generator(session.raw_ask(messages))
        return _extract_text(result, streamed_text)
    if hasattr(session, "ask"):
        streamed_text, result = _drain_generator(session.ask(user_msg))
        return _extract_text(result, streamed_text)
    raise TypeError(f"unsupported session object: {type(session).__name__}")


def ask_vision(
    image_input,
    prompt: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    *,
    session=None,
    cfg: dict | None = None,
    cfg_name: str | None = None,
    max_retries: int = 0,
) -> str:
    try:
        backend = _unwrap_session(session) if session is not None else None
        created_backend = False
        if backend is None:
            cfg2, resolved_name = _resolve_cfg(cfg=cfg, cfg_name=cfg_name)
            cfg2["timeout"] = min(10, max(1, int(timeout or DEFAULT_TIMEOUT)))
            cfg2["read_timeout"] = max(5, int(timeout or DEFAULT_TIMEOUT))
            cfg2["max_retries"] = max(0, int(max_retries or 0))
            backend = _guess_session_cls(cfg2, resolved_name)(cfg2)
            created_backend = True

        user_msg = _build_user_message(image_input, prompt=prompt, max_pixels=max_pixels)
        with _temporary_session_overrides(backend, timeout=timeout, max_retries=max_retries):
            text = _call_backend(backend, user_msg)
        text = (text or "").strip()
        if text:
            return text
        return "Error: empty response"
    except Exception as e:
        return f"Error: {e}"


__all__ = [
    "ask_vision",
    "image_to_data_url",
    "_build_user_message",
    "_encode_png_bytes",
]
