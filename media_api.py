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


def _config_key():
    name = os.environ.get("GA_OCR_CONFIG", "native_oai_config_aihub1")
    try:
        cfg = getattr(importlib.import_module("mykey"), name)
    except (ImportError, AttributeError):
        return None
    return cfg if isinstance(cfg, dict) else None


def _credential(kind):
    if kind == "image":
        return _load_labeled_key(os.environ.get("GA_IMAGE_KEY_LABEL", "image2")), None
    cfg = _config_key() or {}
    return cfg.get("apikey"), cfg


def _read_image(path):
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(str(p))
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return mime, base64.b64encode(p.read_bytes()).decode("ascii")


def ocr(image_path, prompt="Extract all readable text exactly; preserve layout where possible.", timeout=120):
    import requests
    key, _ = _credential("ocr")
    if not key:
        raise RuntimeError("OCR credential is not configured")
    mime, data = _read_image(image_path)
    cfg = _config_key() or {}
    base = os.environ.get("GA_OCR_API_BASE", cfg.get("apibase", "https://api.openai.com/v1")).rstrip("/")
    model = os.environ.get("GA_OCR_MODEL", cfg.get("model", "gpt-5.6-sol"))
    r = requests.post(base + "/chat/completions", headers={"Authorization": "Bearer " + key,
        "Content-Type": "application/json"}, json={"model": model, "messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}
    ]}], "max_tokens": 4096}, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


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
