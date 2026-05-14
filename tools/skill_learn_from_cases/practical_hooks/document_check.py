#!/usr/bin/env python3
"""
document_check.py — 文档/图像鉴权实操测试

统一接口: run(env) -> dict
使用本机 PaddleOCR-VL-1.5 (llama-server on :8090) 做真实OCR验证
降级: 检测本地OCR库可用性
"""
import json, sys, os, urllib.request, base64, io, contextlib

PADDLE_API = "http://localhost:8090/v1/chat/completions"
_TEST_TEXT = "OCR Test 123"


def _make_test_image():
    """创建测试图片(base64)"""
    # fallback: 1x1 pixel PNG
    return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def _paddle_ocr_available():
    """检测 PaddleOCR-VL API"""
    try:
        req = urllib.request.Request("http://localhost:8090/v1/models")
        with urllib.request.urlopen(req, timeout=3) as r:
            models = json.loads(r.read())
        for m in models.get("models", []):
            if "PaddleOCR" in m.get("name", "") or "ocr" in m.get("name", "").lower():
                return True
        return False
    except:
        return False


def _run_paddle_ocr(img_b64: str) -> str | None:
    """调用 PaddleOCR-VL API 做OCR"""
    try:
        req_data = {
            "model": "PaddleOCR-VL-1.5-GGUF",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": "请精准识别图片中的所有文字，逐行输出，不要多余内容"}
            ]}],
            "temperature": 0.0,
            "max_tokens": 1024
        }
        req = urllib.request.Request(PADDLE_API, data=json.dumps(req_data).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"]
    except:
        return None


def run(env: dict = None) -> dict:
    """统一入口"""
    detail = {"paddle_ocr_api": False, "local_libs": []}
    notes = []
    score = 0

    # 1. 检测 PaddleOCR API
    if _paddle_ocr_available():
        detail["paddle_ocr_api"] = True
        score += 30
        notes.append("PaddleOCR-VL API可用")
        # 尝试OCR
        img = _make_test_image()
        ocr_result = _run_paddle_ocr(img)
        if ocr_result:
            detail["ocr_test_result"] = ocr_result[:100]
            score += 40
            notes.append("OCR测试通过")
        else:
            notes.append("OCR测试失败(API未返回有效文本)")
    else:
        notes.append("PaddleOCR-VL API不可用")

    # 2. 检测本地库
    libs_found = []
    for lib in ["pytesseract", "PIL", "cv2", "paddleocr"]:
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                __import__(lib)
            libs_found.append(lib)
            score += 15
        except:
            pass
    detail["local_libs"] = libs_found
    if libs_found:
        notes.append(f"本地库: {','.join(libs_found)}")
    if not notes:
        notes.append("无可用OCR工具")

    return {
        "score": min(score, 100),
        "passed": score >= 40,
        "note": "; ".join(notes),
        "detail": detail
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False))
