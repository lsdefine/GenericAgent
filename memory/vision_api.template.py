import base64, requests, sys, os
from io import BytesIO
from pathlib import Path

# ============ 用户配置区（从 template 拷贝后只需改这里）============
CLAUDE_CONFIG_KEY = 'claude_config141'   # mykey.py 中 Claude 配置的变量名
OPENAI_CONFIG_KEY = 'oai_config1'        # mykey.py 中 OpenAI 配置的变量名
MODELSCOPE_API_KEY = ''                  # 直接填你的 ModelScope token
DEFAULT_BACKEND = 'claude'               # 默认后端: 'claude' / 'openai' / 'modelscope'
# =================================================================

MODELSCOPE_API_BASE = 'https://api-inference.modelscope.cn'
MODELSCOPE_MODEL = 'Qwen/Qwen3-VL-235B-A22B-Instruct'

_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in [os.path.join(_DIR, '..'), os.path.join(_DIR, '../..')]:
    if _p not in sys.path: sys.path.insert(0, _p)

def ask_vision(image_input, prompt="详细描述这张图片的内容", timeout=60, max_pixels=1440000, backend=DEFAULT_BACKEND):
    try:
        b64 = _prepare_image(image_input, max_pixels)
    except Exception as e:
        return f"Error: 图片处理失败 - {type(e).__name__}: {e}"
    try:
        if backend == 'claude':
            return _call_claude(b64, prompt, timeout)
        elif backend == 'openai':
            mk = _load_config()
            cfg = getattr(mk, OPENAI_CONFIG_KEY)
            return _call_openai_compat(
                b64, prompt, timeout,
                apibase=cfg['apibase'], apikey=cfg['apikey'], model=cfg['model'], proxy=cfg.get('proxy')
            )
        elif backend == 'modelscope':
            return _call_openai_compat(
                b64, prompt, timeout,
                apibase=MODELSCOPE_API_BASE, apikey=MODELSCOPE_API_KEY, model=MODELSCOPE_MODEL, proxy=None
            )
        else: return f"Error: 未知backend '{backend}'，可选: claude, openai, modelscope"
    except requests.exceptions.Timeout:
        return f"Error: 请求超时 (>{timeout}s)"
    except requests.exceptions.RequestException as e:
        return f"Error: API请求失败 - {type(e).__name__}: {e}"
    except (KeyError, ValueError) as e:
        return f"Error: 响应解析失败 - {e}"

# ===================== 以下为内部实现 =====================

def _prepare_image(image_input, max_pixels=1440000):
    """加载+缩放+base64编码，返回b64字符串"""
    from PIL import Image
    if isinstance(image_input, Image.Image):
        img = image_input
    elif isinstance(image_input, (str, Path)):
        img = Image.open(image_input)
    else:
        raise TypeError(f"image_input 必须是文件路径或PIL Image，实际: {type(image_input).__name__}")
    w, h = img.size
    if w * h > max_pixels:
        scale = (max_pixels / (w * h)) ** 0.5
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        print(f"  📐 缩放: {w}×{h} → {new_w}×{new_h}")
    if img.mode in ('RGBA', 'LA', 'P'):
        rgb = Image.new('RGB', img.size, (255, 255, 255))
        rgb.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
        img = rgb
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=80, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    print(f"  📦 Base64: {len(buf.getvalue())/1024:.1f}KB")
    return b64

def _load_config():
    import mykey
    return mykey

def _call_claude(b64, prompt, timeout, max_tokens=1024):
    mk = _load_config()
    cfg = getattr(mk, CLAUDE_CONFIG_KEY)
    resp = requests.post(
        cfg['apibase'] + '/v1/messages',
        json={'model': cfg['model'], 'max_tokens': max_tokens, 'messages': [{
            'role': 'user',
            'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': b64}},
                {'type': 'text', 'text': prompt}
            ]
        }]},
        headers={'x-api-key': cfg['apikey'], 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
        timeout=timeout
    )
    resp.raise_for_status()
    return resp.json()['content'][0]['text']

def _call_openai_compat(b64, prompt, timeout, *, apibase, apikey, model, proxy=None):
    proxies = {'https': proxy, 'http': proxy} if proxy else None
    resp = requests.post(
        apibase.rstrip('/') + '/v1/chat/completions',
        json={'model': model, 'messages': [{
            'role': 'user',
            'content': [
                {'type': 'text', 'text': prompt},
                {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}'}}
            ]
        }]},
        headers={'Authorization': f"Bearer {apikey}", 'Content-Type': 'application/json'},
        proxies=proxies, timeout=timeout
    )
    resp.raise_for_status()
    return resp.json()['choices'][0]['message']['content']

if __name__ == '__main__':
    pass