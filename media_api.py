"""Small OpenAI-compatible vision/image adapter.

Credentials are loaded at call time. Values are never logged or returned.
"""
import base64
import importlib
import mimetypes
import os
from pathlib import Path


def _key_file():
    return Path(os.environ.get("GA_KEY_FILE", str(Path.home() / "key.txt")))


def _load_labeled_key(label):
    """Read ``label: value`` or an indented label followed by its value."""
    wanted = label.strip().lower()
    p = _key_file()
    if not p.is_file():
        return None
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    for i, raw in enumerate(lines):
        if ":" not in raw:
            continue
        name, value = raw.split(":", 1)
        if name.strip().lower() != wanted:
            continue
        if value.strip():
            return value.strip()
        # Support the user's grouped format: key name on one line,
        # secret on the following indented line. Do not expose either.
        for following in lines[i + 1:]:
            if not following.strip():
                continue
            if following[:1].isspace() and ":" not in following:
                return following.strip()
            break
    return None


def _ocr_config():
    """Use the explicitly selected cloud Luna config; never inherit another config."""
    try:
        cfg = getattr(importlib.import_module("mykey"), "native_oai_config_aihub3")
    except (ImportError, AttributeError) as e:
        raise RuntimeError("explicit OCR config native_oai_config_aihub3 is unavailable") from e
    if not isinstance(cfg, dict) or not cfg.get("apikey"):
        raise RuntimeError("explicit OCR Luna credential is not configured")
    return cfg


def _credential(kind):
    if kind == "image":
        return _load_labeled_key(os.environ.get("GA_IMAGE_KEY_LABEL", "image2")), None
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


def generate_image(prompt, size="1024x1024", quality="auto", timeout=180):
    import requests
    key, _ = _credential("image")
    if not key:
        raise RuntimeError("image2 credential is not configured")
    base = os.environ.get("GA_IMAGE_API_BASE", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("GA_IMAGE_MODEL", "image2")
    r = requests.post(base + "/images/generations", headers={"Authorization": "Bearer " + key,
        "Content-Type": "application/json"}, json={"model": model, "prompt": prompt, "size": size,
        "quality": quality, "n": 1}, timeout=timeout)
    r.raise_for_status()
    item = (r.json().get("data") or [{}])[0]
    if item.get("url"): return item["url"]
    if item.get("b64_json"):
        out = Path(os.environ.get("GA_IMAGE_OUTPUT_DIR", "./temp/generated_images")).resolve()
        out.mkdir(parents=True, exist_ok=True)
        target = out / "generated.png"
        target.write_bytes(base64.b64decode(item["b64_json"]))
        return str(target)
    raise RuntimeError("image API returned neither url nor b64_json")
