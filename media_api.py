"""Small OpenAI-compatible vision/image adapter.

Credentials are loaded from explicit dictionaries in ``mykey.py`` at call time.
Values are never logged or returned.
"""
import base64
import importlib
import mimetypes
import os
from pathlib import Path


def _ocr_config():
    """Use the explicitly selected cloud Luna config; never inherit another config."""
    try:
        cfg = getattr(importlib.import_module("mykey"), "native_oai_config_aihub3")
    except (ImportError, AttributeError) as e:
        raise RuntimeError("explicit OCR config native_oai_config_aihub3 is unavailable") from e
    if not isinstance(cfg, dict) or not cfg.get("apikey"):
        raise RuntimeError("explicit OCR Luna credential is not configured")
    return cfg


def _image_config():
    """Use the explicit image2 config from mykey.py."""
    try:
        cfg = getattr(importlib.import_module("mykey"), "native_oai_config_image2")
    except (ImportError, AttributeError) as e:
        raise RuntimeError("explicit image config native_oai_config_image2 is unavailable") from e
    if not isinstance(cfg, dict) or not cfg.get("apikey"):
        raise RuntimeError("explicit image2 credential is not configured")
    return cfg


def _credential(kind):
    if kind == "image":
        cfg = _image_config()
        return cfg["apikey"], cfg
    cfg = _ocr_config()
    return cfg["apikey"], cfg


def _read_image(path):
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(str(p))
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return mime, base64.b64encode(p.read_bytes()).decode("ascii")


def _response_text(payload):
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                return text
    raise RuntimeError("OCR response contained no output text")


def ocr(image_path, prompt="Extract all readable text exactly; preserve layout where possible.", timeout=120):
    import requests
    key, cfg = _credential("ocr")
    mime, data = _read_image(image_path)
    base = cfg["apibase"].rstrip("/")
    model = cfg["model"]
    payload = {"model": model, "input": [{"role": "user", "content": [
        {"type": "input_text", "text": prompt},
        {"type": "input_image", "image_url": f"data:{mime};base64,{data}"}
    ]}]}
    r = requests.post(base + "/responses", headers={"Authorization": "Bearer " + key,
        "Content-Type": "application/json"}, json=payload, timeout=timeout)
    r.raise_for_status()
    return _response_text(r.json())


def generate_image(prompt, size="1K", quality="auto", timeout=180, output_dir=None):
    import requests
    from uuid import uuid4
    key, cfg = _credential("image")
    if not key:
        raise RuntimeError("image2 credential is not configured")
    base = cfg["apibase"].rstrip("/")
    model = cfg["model"]
    payload = {"model": model, "prompt": prompt, "size": size,
               "quality": quality, "n": 1}
    # The upstream exposes no parameter schema; pass through values it accepts.
    r = requests.post(base + "/images/generations", headers={"Authorization": "Bearer " + key,
        "Content-Type": "application/json"}, json=payload, timeout=timeout)
    r.raise_for_status()
    item = (r.json().get("data") or [{}])[0]
    if item.get("url"):
        image_url = item["url"]
        download = requests.get(image_url, timeout=timeout)
        download.raise_for_status()
        content_type = download.headers.get("content-type", "image/png").split(";", 1)[0]
        suffix = {"image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(content_type, ".png")
        out = Path(output_dir).expanduser().resolve() / "image" if output_dir else Path.cwd() / "image"
        out.mkdir(parents=True, exist_ok=True)
        target = out / f"generated_{uuid4().hex[:12]}{suffix}"
        target.write_bytes(download.content)
        return str(target)
    if item.get("b64_json"):
        out = Path(output_dir).expanduser().resolve() / "image" if output_dir else Path.cwd() / "image"
        out.mkdir(parents=True, exist_ok=True)
        target = out / f"generated_{uuid4().hex[:12]}.png"
        target.write_bytes(base64.b64decode(item["b64_json"]))
        return str(target)
    raise RuntimeError("image API returned neither url nor b64_json")
