import base64
import os
import sys
import threading
import urllib3
from io import BytesIO
from pathlib import Path

urllib3.disable_warnings()

DEFAULT_CONFIG_KEY = "native_oai_config"
DEFAULT_PROMPT = "Describe the image in detail."


def _self_dir():
    return os.path.dirname(os.path.abspath(__file__))


for _p in [_self_dir(), os.path.join(_self_dir(), "..")]:
    _ap = os.path.abspath(_p)
    if _ap not in sys.path:
        sys.path.insert(0, _ap)

from llmcore import _openai_stream, trim_messages_history  # noqa: E402


def _load_cfg(config_or_key=None):
    if isinstance(config_or_key, dict):
        return dict(config_or_key)
    key = config_or_key or DEFAULT_CONFIG_KEY
    import mykey
    return dict(getattr(mykey, key))


def _normalize_prompt(prompt):
    prompt = (prompt or "").strip()
    return prompt or DEFAULT_PROMPT


def _ensure_list(x):
    if x is None:
        return []
    return x if isinstance(x, (list, tuple)) else [x]


def _prepare_image_data_url(image_input, max_pixels=1440000, jpeg_quality=85):
    from PIL import Image

    if isinstance(image_input, Image.Image):
        img = image_input.copy()
    elif isinstance(image_input, (str, Path)):
        img = Image.open(image_input)
    else:
        raise TypeError(f"image_input 必须是文件路径、Path 或 PIL Image，实际: {type(image_input).__name__}")

    w, h = img.size
    if w * h > max_pixels:
        scale = (max_pixels / (w * h)) ** 0.5
        new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    if img.mode not in ("RGB", "L"):
        rgb = Image.new("RGB", img.size, (255, 255, 255))
        try:
            alpha = img.getchannel("A")
            rgb.paste(img, mask=alpha)
        except Exception:
            rgb.paste(img)
        img = rgb
    elif img.mode == "L":
        img = img.convert("RGB")

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


class VisionSession:
    def __init__(self, cfg):
        self.api_key = cfg["apikey"]
        self.api_base = cfg["apibase"].rstrip("/")
        self.model = cfg.get("model", "")
        self.name = cfg.get("name", f"vision:{self.model}")
        self.context_win = cfg.get("context_win", 24000)
        self.history = []
        self.lock = threading.Lock()
        self.system = ""
        proxy = cfg.get("proxy")
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        verify_ssl = cfg.get("verify_ssl", cfg.get("verify", True))
        self.verify_ssl = verify_ssl if isinstance(verify_ssl, bool) else str(verify_ssl).strip().lower() not in ("0", "false", "no", "off")
        self.max_retries = max(0, int(cfg.get("max_retries", 1)))
        self.stream = cfg.get("stream", True)
        default_ct, default_rt = (5, 60) if self.stream else (10, 120)
        self.connect_timeout = max(1, int(cfg.get("timeout", default_ct)))
        self.read_timeout = max(5, int(cfg.get("read_timeout", default_rt)))
        mode = str(cfg.get("api_mode", "chat_completions")).strip().lower().replace("-", "_")
        self.api_mode = "responses" if mode in ("responses", "response") else "chat_completions"
        self.temperature = cfg.get("temperature", 1)
        self.max_tokens = cfg.get("max_tokens", 2048)
        self.reasoning_effort = cfg.get("reasoning_effort")

    def set_system(self, text):
        self.system = text or ""

    def reset(self):
        with self.lock:
            self.history.clear()

    def raw_ask(self, messages):
        return (yield from _openai_stream(
            self.api_base,
            self.api_key,
            messages,
            self.model,
            self.api_mode,
            temperature=self.temperature,
            reasoning_effort=self.reasoning_effort,
            max_tokens=self.max_tokens,
            max_retries=self.max_retries,
            stream=self.stream,
            connect_timeout=self.connect_timeout,
            read_timeout=self.read_timeout,
            proxies=self.proxies,
            verify=self.verify_ssl,
        ))

    def ask(self, prompt=None, image_input=None, stream=False, detail="auto", max_pixels=1440000):
        def _ask_gen():
            with self.lock:
                content = [{"type": "text", "text": _normalize_prompt(prompt)}]
                for item in _ensure_list(image_input):
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": _prepare_image_data_url(item, max_pixels=max_pixels),
                            "detail": detail,
                        },
                    })
                self.history.append({"role": "user", "content": content})
                trim_messages_history(self.history, self.context_win)
                messages = list(self.history)
                if self.system:
                    messages = [{"role": "system", "content": self.system}] + messages

            content_blocks = None
            content_text = ""
            gen = self.raw_ask(messages)
            try:
                while True:
                    chunk = next(gen)
                    content_text += chunk
                    yield chunk
            except StopIteration as e:
                content_blocks = e.value or []

            if content_text and not content_text.startswith("Error:"):
                with self.lock:
                    self.history.append({"role": "assistant", "content": content_text})
            return content_blocks

        return _ask_gen() if stream else "".join(list(_ask_gen()))


def load_vision(config_or_key=None):
    return VisionSession(_load_cfg(config_or_key))


def ask_vision(image_input, prompt=DEFAULT_PROMPT, config_or_key=None, **kwargs):
    return load_vision(config_or_key).ask(prompt=prompt, image_input=image_input, **kwargs)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python visioncore.py <图片路径> [prompt] [config_key]")
        raise SystemExit(1)
    image_path = sys.argv[1]
    prompt = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PROMPT
    config_key = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_CONFIG_KEY
    print(ask_vision(image_path, prompt=prompt, config_or_key=config_key))