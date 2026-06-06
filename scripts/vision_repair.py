#!/usr/bin/env python3
"""
Vision Repair — AI-enhanced诊断与修复模块

集成 vision_api(截图+OCR) + openllm(本地LLM分析) 到 auto_repair 流程。
当 auto_repair 检测到系统异常时，调用本模块进行 AI 辅助分析并建议修复方案。

Usage:
    python3 -m scripts.vision_repair diagnose          # AI增强诊断
    python3 -m scripts.vision_repair screenshot        # 截图并分析
    python3 -m scripts.vision_repair analyze <input>   # 分析诊断数据
"""

import json, os, sys, requests, traceback
from datetime import datetime
from pathlib import Path

# ============ 配置 ============
OPENLLM_BASE = "http://localhost:11343"
OPENLLM_MODEL = "deepseek/deepseek-v4-flash"  # 快速模型
OPENLLM_MODEL_DEEP = "deepseek/deepseek-v4-pro"  # 深度分析用
AI_TIMEOUT = 30
REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'temp', 'vision_reports')

# ============ openllm AI 接口 ============

def _call_llm(prompt: str, model: str = None, max_tokens: int = 512) -> str:
    """调用本地 openllm 进行 AI 分析"""
    if model is None:
        model = OPENLLM_MODEL
    try:
        resp = requests.post(
            f"{OPENLLM_BASE}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.1
            },
            timeout=AI_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0]["message"]["content"].strip()
        return f"Error: 无返回内容 - {json.dumps(data)[:200]}"
    except requests.exceptions.Timeout:
        return f"Error: openllm 超时 (>={AI_TIMEOUT}s)"
    except requests.exceptions.ConnectionError:
        return f"Error: openllm 连接失败 ({OPENLLM_BASE})"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


def _build_diagnosis_prompt(data: dict) -> str:
    """构建诊断提示词"""
    lines = [
        "你是一个服务器运维专家。分析以下系统诊断数据，输出JSON格式的诊断报告。",
        "",
        "## 系统诊断数据",
        f"- 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    # 扁平化数据
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"\n### {key}")
            for k, v in value.items():
                lines.append(f"- {k}: {v}")
        elif isinstance(value, list):
            lines.append(f"\n### {key} ({len(value)} 项)")
            for i, item in enumerate(value[:10]):  # 最多10项
                if isinstance(item, dict):
                    item_str = " | ".join(f"{k}={v}" for k, v in list(item.items())[:5])
                    lines.append(f"  [{i}] {item_str}")
                else:
                    lines.append(f"  [{i}] {item}")
        else:
            lines.append(f"- {key}: {value}")
    
    lines.extend([
        "",
        "## 输出格式（严格JSON）",
        """{
  "issues": ["问题1", "问题2"],
  "severity": "critical|warning|info",
  "suggested_actions": [
    {"action": "具体操作命令", "description": "修复说明", "priority": 1}
  ],
  "root_cause_analysis": "根因分析",
  "health_score": 0-100
}""",
        "",
        "请分析上述数据，输出JSON诊断报告。"
    ])
    return "\n".join(lines)


def ai_analyze(diagnostic_data: dict, deep: bool = False) -> dict:
    """
    使用 AI 分析诊断数据，返回结构化报告
    
    Args:
        diagnostic_data: auto_repair 生成的诊断数据
        deep: 是否使用深度模型（更慢但更准确）
    
    Returns:
        dict: 包含 issues, severity, suggested_actions, root_cause_analysis, health_score 的字典
    """
    prompt = _build_diagnosis_prompt(diagnostic_data)
    model = OPENLLM_MODEL_DEEP if deep else OPENLLM_MODEL
    
    result = _call_llm(prompt, model=model, max_tokens=1024)
    
    # 尝试解析 JSON
    try:
        # 查找第一个 { 到最后一个 }
        start = result.find('{')
        end = result.rfind('}')
        if start >= 0 and end > start:
            json_str = result[start:end+1]
            report = json.loads(json_str)
            return report
    except (json.JSONDecodeError, ValueError) as e:
        pass
    
    # 解析失败，返回原始结果
    return {
        "issues": ["AI分析解析失败"],
        "severity": "info",
        "suggested_actions": [],
        "root_cause_analysis": result[:500],
        "health_score": 50,
        "_raw": result[:1000]
    }


# ============ 截图接口 ============

def capture_screen(region: tuple = None, output_path: str = None) -> str:
    """
    截图并保存
    
    Args:
        region: (left, top, width, height), 默认全屏
        output_path: 保存路径，默认自动生成
    
    Returns:
        str: 图片保存路径
    """
    try:
        from PIL import Image
        import mss
        
        if output_path is None:
            os.makedirs(REPORT_DIR, exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = os.path.join(REPORT_DIR, f"screenshot_{ts}.png")
        
        with mss.mss() as sct:
            if region:
                mon = {"left": region[0], "top": region[1], "width": region[2], "height": region[3]}
                img = sct.grab(mon)
            else:
                img = sct.grab(sct.monitors[1])  # 主显示器全屏
            
            pil_img = Image.frombytes("RGB", img.size, img.rgb)
            pil_img.save(output_path)
            return output_path
    except ImportError as e:
        return f"Error: 截图库未安装 - {e}"
    except Exception as e:
        return f"Error: 截图失败 - {type(e).__name__}: {e}"


def vision_analyze(image_path: str, prompt: str = "分析这张截图中的系统状态") -> str:
    """
    使用 vision_api 分析截图
    
    Args:
        image_path: 截图路径
        prompt: 分析提示词
    
    Returns:
        str: 分析结果
    """
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from scripts.vision_api import ask_vision
        
        from PIL import Image
        img = Image.open(image_path)
        
        # 先尝试 mock 模式（无需 API 密钥）
        result = ask_vision(img, prompt, backend='mock')
        
        # 如果 mock 模式提示需要配置，尝试用 openllm 分析
        if "配置API密钥" in result:
            # 转换为文本描述，用 openllm 分析
            desc = f"系统截图 ({image_path})，mock分析: {result[:200]}"
            analysis = _call_llm(f"分析以下系统截图描述，判断是否存在异常:\n{desc}\n\n输出JSON: {{\"status\": \"normal|abnormal\", \"findings\": [], \"confidence\": 0-1}}")
            return analysis
        
        return result
    except Exception as e:
        return f"Error: vision分析失败 - {type(e).__name__}: {e}"


# ============ 集成 API ============

def vision_diagnose(diagnostic_data: dict = None, screenshot: bool = False) -> dict:
    """
    AI增强诊断：结合系统数据和截图分析
    
    Args:
        diagnostic_data: 诊断数据（如为 None 则自动收集）
        screenshot: 是否同时截图分析
    
    Returns:
        dict: 综合诊断报告
    """
    report = {
        "timestamp": datetime.now().isoformat(),
        "ai_analysis": {},
        "screenshot_analysis": None,
        "combined_assessment": None
    }
    
    # 1. 如果没有数据，尝试从 auto_repair 收集
    if diagnostic_data is None:
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
            from scripts.auto_repair import diagnose
            diagnostic_data = diagnose()
        except Exception as e:
            diagnostic_data = {"error": f"auto_repair调用失败: {e}"}
    
    # 2. AI 分析诊断数据
    report["ai_analysis"] = ai_analyze(diagnostic_data)
    
    # 3. 截图分析
    if screenshot:
        img_path = capture_screen()
        if not img_path.startswith("Error"):
            report["screenshot_analysis"] = {
                "image": img_path,
                "analysis": vision_analyze(img_path)
            }
    
    # 4. 综合评估
    health_score = report["ai_analysis"].get("health_score", 50)
    severity = report["ai_analysis"].get("severity", "info")
    issues = report["ai_analysis"].get("issues", [])
    
    if not issues:
        report["combined_assessment"] = "✅ 系统正常运行，未发现问题。"
    elif severity == "critical":
        report["combined_assessment"] = f"🔴 严重问题 ({len(issues)}项): 需要立即处理"
    elif severity == "warning":
        report["combined_assessment"] = f"🟡 警告 ({len(issues)}项): 建议关注"
    else:
        report["combined_assessment"] = f"ℹ️ 提示 ({len(issues)}项): 常规维护"
    
    report["health_score"] = health_score
    report["severity"] = severity
    report["issues_count"] = len(issues)
    
    return report


# ============ auto_repair 集成接口 ============

def auto_repair_vision_step(diagnostic_data: dict) -> dict:
    """
    供 auto_repair.py 调用的 vision 分析步骤
    
    auto_repair 可以在 diagnose 后调用此函数获得 AI 增强建议，
    然后用建议指导 repair 策略。
    
    Args:
        diagnostic_data: diagnose() 的返回值
    
    Returns:
        dict: 包含建议操作的字典
    """
    analysis = ai_analyze(diagnostic_data)
    
    result = {
        "vision_enabled": True,
        "ai_suggestions": analysis.get("suggested_actions", []),
        "root_cause": analysis.get("root_cause_analysis", ""),
        "health_score": analysis.get("health_score", 50),
        "severity": analysis.get("severity", "info"),
    }
    
    return result


# ============ CLI ============

def cmd_diagnose():
    """执行 AI 增强诊断"""
    print(f"🔍 AI 增强诊断 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print("=" * 55)
    
    report = vision_diagnose(screenshot=False)
    
    print(f"\n健康评分: {report.get('health_score', '?')}/100")
    print(f"严重程度: {report.get('severity', '?')}")
    print(f"问题数: {report.get('issues_count', 0)}")
    print(f"\n综合评估: {report.get('combined_assessment', '?')}")
    
    ai = report.get("ai_analysis", {})
    issues = ai.get("issues", [])
    if issues:
        print(f"\n📋 发现问题:")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
    
    actions = ai.get("suggested_actions", [])
    if actions:
        print(f"\n🔧 建议操作:")
        for i, act in enumerate(actions, 1):
            if isinstance(act, dict):
                print(f"  {i}. [{act.get('priority', '?')}] {act.get('description', act.get('action', '?'))}")
            else:
                print(f"  {i}. {act}")
    
    # 保存报告
    os.makedirs(REPORT_DIR, exist_ok=True)
    report_path = os.path.join(REPORT_DIR, f"diagnose_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n📝 报告已保存: {report_path}")
    
    return report


def cmd_screenshot():
    """截图并分析"""
    print(f"📸 截图分析 ({datetime.now().strftime('%Y%m%d_%H%M%S')})")
    print("=" * 55)
    
    img_path = capture_screen()
    if img_path.startswith("Error"):
        print(f"❌ {img_path}")
        return
    
    print(f"✅ 截图保存: {img_path}")
    print(f"   ({os.path.getsize(img_path)} bytes)")
    
    print("\n🔍 分析中...")
    analysis = vision_analyze(img_path)
    print(f"\n📋 分析结果:\n{analysis}")


def cmd_analyze(input_path: str):
    """分析诊断数据文件"""
    try:
        with open(input_path) as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ 读取失败: {e}")
        return
    
    report = ai_analyze(data)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    cmd = sys.argv[1]
    if cmd == "diagnose":
        cmd_diagnose()
    elif cmd == "screenshot":
        cmd_screenshot()
    elif cmd == "analyze" and len(sys.argv) > 2:
        cmd_analyze(sys.argv[2])
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
