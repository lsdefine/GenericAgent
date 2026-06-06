import base64, requests, sys, os, json
from io import BytesIO
from pathlib import Path

# ============ 用户配置区（从 template 拷贝后只需改这里）============
# 默认后端: 'claude' / 'openai' / 'modelscope'
DEFAULT_BACKEND = 'claude'
# ======================== 密钥存储方式 ===========================
# 方式A（推荐）：使用 keychain 安全存储（XOR加密，~/.ga_keychain.enc）
#   用 keychain_tool.py set CLAUDE_CONFIG '{...}' 设置JSON配置
#   或 keys.set("CLAUDE_CONFIG", json.dumps({...}))
# 方式B（兼容旧版）：使用 mykey.py 模块属性
# =================================================================

# ---- keychain 集成 ----
_KEYCHAIN_ENABLED = True
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    from memory.keychain import keys
    _keychain_available = True
except Exception:
    _keychain_available = False

def _get_config_from_keychain(name):
    """从 keychain 获取配置（期望存储为 JSON 字符串）"""
    if not _keychain_available:
        return None
    try:
        raw = getattr(keys, name, None)
        if raw is None:
            return None
        val = raw.use()
        if val.startswith('{') or val.startswith('['):
            return json.loads(val)
        return {'apikey': val}  # 纯文本密钥，包装为 dict
    except (KeyError, AttributeError, json.JSONDecodeError):
        return None

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
            return _call_openai_compat(
                b64, prompt, timeout,
                **_get_config('OPENAI_CONFIG')
            )
        elif backend == 'modelscope':
            cfg = _get_config('MODELSCOPE_CONFIG') or {}
            return _call_openai_compat(
                b64, prompt, timeout,
                apibase=cfg.get('apibase', MODELSCOPE_API_BASE),
                apikey=cfg.get('apikey', _get_config('MODELSCOPE_API_KEY') or ''),
                model=cfg.get('model', MODELSCOPE_MODEL),
                proxy=None
            )
        elif backend == 'mock':
            return _call_mock(b64, prompt)
        else: return f"Error: 未知backend '{backend}'，可选: claude, openai, modelscope, mock"
    except requests.exceptions.Timeout:
        return f"Error: 请求超时 (>{timeout}s)"
    except requests.exceptions.RequestException as e:
        return f"Error: API请求失败 - {type(e).__name__}: {e}"
    except (KeyError, ValueError) as e:
        return f"Error: 响应解析失败 - {e}"

# ===================== 密钥获取逻辑 =====================

def _get_config(name):
    """优先 keychain → 旧版 mykey.py 属性 → 环境变量/辅助密钥 fallback"""
    # 1. keychain
    if _keychain_available:
        cfg = _get_config_from_keychain(name)
        if cfg is not None:
            return cfg
    # 2. 旧版 mykey.py
    try:
        import mykey
        val = getattr(mykey, name, None)
        if val is not None:
            return val
    except (ImportError, AttributeError):
        pass
    # 3. 环境变量 fallback: AUXILIARY_VISION_API_KEY
    if name == 'OPENAI_CONFIG':
        env_key = os.environ.get('AUXILIARY_VISION_API_KEY') or os.environ.get('OPENAI_API_KEY')
        if env_key:
            # 尝试从 keychain 获取辅助密钥（如已存储）
            if _keychain_available:
                aux = _get_config_from_keychain('AUXILIARY_VISION_API_KEY')
                if aux and isinstance(aux, dict) and aux.get('apikey'):
                    return aux
            # 从环境变量构造默认配置
            return {
                'apibase': os.environ.get('OPENAI_API_BASE', 'https://apihub.agnes-ai.com'),
                'apikey': env_key,
                'model': os.environ.get('OPENAI_VISION_MODEL', 'agnes-1.5-flash'),
            }
    return None

def _call_mock(b64, prompt):
    """Mock后端: 从图片元数据和OCR提取描述(无需API密钥)"""
    from PIL import Image, ImageStat
    from io import BytesIO
    import base64
    import math
    img_data = base64.b64decode(b64)
    img = Image.open(BytesIO(img_data))
    w, h = img.size
    lines = [f"📷 截图分析 [{w}×{h}]"]
    
    # 颜色模式
    lines.append(f"  颜色模式: {img.mode}")
    
    # 基本图像统计
    if img.mode in ('RGB', 'RGBA'):
        if img.mode == 'RGBA':
            img_rgb = img.convert('RGB')
        else:
            img_rgb = img
        stat = ImageStat.Stat(img_rgb)
        avg_r, avg_g, avg_b = [int(v) for v in stat.mean[:3]]
        brightness = (avg_r + avg_g + avg_b) / 3
        if brightness > 200:
            brightness_desc = "明亮"
        elif brightness > 128:
            brightness_desc = "适中"
        elif brightness > 64:
            brightness_desc = "偏暗"
        else:
            brightness_desc = "昏暗"
        lines.append(f"  亮度: {brightness_desc} (avg={int(brightness)})")
        
        # 颜色丰富度
        std_r, std_g, std_b = [int(v) for v in stat.stddev[:3]] if stat.stddev[:3][0] else (0,0,0)
        color_richness = (std_r + std_g + std_b) / 3
        if color_richness > 60:
            rich_desc = "色彩丰富"
        elif color_richness > 30:
            rich_desc = "色彩适中"
        else:
            rich_desc = "色彩单一"
        lines.append(f"  色彩: {rich_desc}")
        
        # 判断主色调
        if avg_r > avg_g + 30 and avg_r > avg_b + 30:
            tone = "偏红色调"
        elif avg_g > avg_r + 30 and avg_g > avg_b + 30:
            tone = "偏绿色调"
        elif avg_b > avg_r + 30 and avg_b > avg_g + 30:
            tone = "偏蓝色调"
        elif avg_r > 200 and avg_g > 200 and avg_b > 200:
            tone = "浅色/白色调"
        elif avg_r < 60 and avg_g < 60 and avg_b < 60:
            tone = "深色/黑色调"
        else:
            tone = "中性色调"
        lines.append(f"  主色调: {tone} (RGB={avg_r},{avg_g},{avg_b})")
    
    # 判断大致内容类型
    file_kb = len(b64) * 3 // 4 // 1024
    # 简单启发式: 低KB高分辨率=文字为主, 高KB=复杂图像
    bytes_per_pixel = file_kb * 1024 / (w * h) if w * h > 0 else 0
    if bytes_per_pixel < 0.1:
        content_type = "文字密集型(文档/代码/阅读)"
    elif bytes_per_pixel < 0.3:
        content_type = "混合型(图文混排/界面)"
    else:
        content_type = "图像密集型(照片/绘图)"
    lines.append(f"  内容类型: {content_type}")
    lines.append(f"  文件大小: {file_kb}KB")
    
    # 尝试用tesseract OCR提取文字(如果可用)
    text_found = ""
    try:
        import pytesseract
        ocr_text = pytesseract.image_to_string(img, lang='chi_sim+eng').strip()
        if ocr_text:
            lines.append(f"  识别文字: {ocr_text[:300]}")
    except Exception:
        pass
    
    # 根据prompt添加指引
    lines.append("")
    lines.append("💡 提示: 配置API密钥后可用真正AI视觉描述。")
    lines.append("   设置: memory/keychain.py 中配置 CLAUDE_CONFIG / OPENAI_CONFIG / MODELSCOPE_CONFIG")
    
    return "\n".join(lines)

def _call_claude(b64, prompt, timeout, max_tokens=1024):
    cfg = _get_config('CLAUDE_CONFIG')
    if not cfg:
        return "Error: 未找到 Claude 配置（请在 keychain 中设置 CLAUDE_CONFIG）"
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

# ===================== 内部工具函数 =====================

def _prepare_image(image_input, max_pixels=1440000):
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

if __name__ == '__main__':
    pass
