#!/usr/bin/env python3
"""
Hermes Task Relay — 复杂任务接力管道

功能:
  多阶段任务接力：复杂任务分解→多Agent接力执行→结果综合
  支持 Hermes↔GA↔工具↔文件 之间的任务接力

预定义管道:
  system_health  系统健康全链路分析 (采集→分析→报告)
  investigate    智能调查 (推理→采集→分析→综合)
  code_review    代码审查 (读取→分析→建议)
  custom         自定义管道

使用示例:
  python3 scripts/hermes_relay.py run system_health
  python3 scripts/hermes_relay.py run investigate "分析内存使用率高的原因"
  python3 scripts/hermes_relay.py run code_review scripts/hermes_bridge.py
  python3 scripts/hermes_relay.py list
"""

import subprocess, sys, json, os, re, time, argparse, textwrap, signal, threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable

GA_HOME = Path(__file__).resolve().parent.parent
HERMES_CMD = "/home/admin/.local/bin/hermes"

# ======================== 接力管道框架 ========================

class RelayStage:
    """接力阶段基类"""
    def __init__(self, name: str, description: str = "", timeout: int = 240):
        self.name = name
        self.description = description
        self.timeout = timeout
    
    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """执行阶段，返回更新后的context"""
        raise NotImplementedError

class HermesChatStage(RelayStage):
    """Hermes聊天接力阶段（支持OpenLLM快速模式）"""
    def __init__(self, name: str, prompt_template: str, 
                 extract_key: Optional[str] = None, system_hint: str = "",
                 timeout: int = 240, model: str = "",
                 max_context_chars: int = 3000):
        super().__init__(name, f"Hermes分析: {prompt_template[:50]}...", timeout=timeout)
        self.prompt_template = prompt_template
        self.extract_key = extract_key
        self.system_hint = system_hint
        self.model = model  # 空=用Hermes CLI, 非空=用OpenLLM
        self.max_context_chars = max_context_chars  # 裁剪上下文大小
    
    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self._render_template(self.prompt_template, context)
        if self.system_hint:
            prompt = f"{self.system_hint}\n\n{prompt}"
        
        print(f"  🧠 {self.model or 'Hermes'}: {self.name} (timeout={self.timeout}s)")
        if self.model:
            # 使用OpenLLM快速模式
            result = _openllm_chat(prompt, model=self.model, timeout=self.timeout)
        else:
            # 使用Hermes CLI
            result = _hermes_chat(prompt, timeout=self.timeout)
        response = result.get("response", "")
        
        new_ctx = dict(context)
        new_ctx[self.name] = response
        if self.extract_key:
            new_ctx[self.extract_key] = response
        new_ctx["_last_response"] = response
        new_ctx["_last_stage"] = self.name
        new_ctx["_model_used"] = self.model or "hermes"
        return new_ctx
    
    def _render_template(self, template: str, ctx: Dict) -> str:
        """简单模板渲染 {key} 替换，自动裁剪上下文"""
        result = template
        for k, v in ctx.items():
            if isinstance(v, str):
                # 裁剪长上下文以减小prompt大小
                max_c = self.max_context_chars
                val = v[:max_c] if len(v) > max_c else v
                result = result.replace(f"{{{k}}}", val)
            elif isinstance(v, (dict, list)):
                val = json.dumps(v, ensure_ascii=False)[:self.max_context_chars]
                result = result.replace(f"{{{k}}}", val)
        return result

class SystemDataStage(RelayStage):
    """系统数据采集接力阶段"""
    def __init__(self, name: str = "system_data", 
                 data_types: List[str] = None):
        super().__init__(name, "采集系统数据")
        self.data_types = data_types or ["cpu", "memory", "disk", "process", "uptime"]
    
    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print(f"  📊 采集系统数据: {', '.join(self.data_types)}")
        data = _collect_system_data(self.data_types)
        new_ctx = dict(context)
        new_ctx["system_data"] = data
        new_ctx["_last_stage"] = self.name
        return new_ctx

class FileReadStage(RelayStage):
    """文件读取接力阶段"""
    def __init__(self, name: str = "file_content", 
                 path_template: str = "", max_chars: int = 5000):
        super().__init__(name, f"读取文件")
        self.path_template = path_template
        self.max_chars = max_chars
    
    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        path_str = self.path_template
        for k, v in context.items():
            if isinstance(v, str):
                path_str = path_str.replace(f"{{{k}}}", v)
        
        target = GA_HOME / path_str
        print(f"  📖 读取文件: {target}")
        new_ctx = dict(context)
        
        if target.exists() and target.is_file():
            content = target.read_text(encoding="utf-8", errors="replace")
            if len(content) > self.max_chars:
                content = content[:self.max_chars] + f"\n\n... (截断, 原文件{len(content)}字符)"
            new_ctx[self.name] = content
            new_ctx["_last_stage"] = self.name
        else:
            new_ctx[self.name] = f"[文件不存在: {target}]"
            new_ctx["_last_stage"] = self.name
        return new_ctx

class ScriptExecStage(RelayStage):
    """脚本执行接力阶段"""
    def __init__(self, name: str, script_path: str, args: List[str] = None,
                 timeout: int = 30):
        super().__init__(name, f"执行脚本: {script_path}")
        self.script_path = script_path
        self.args = args or []
        self.timeout = timeout
    
    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        target = GA_HOME / self.script_path
        print(f"  ⚡ 执行脚本: {target}")
        new_ctx = dict(context)
        
        try:
            cmd = [sys.executable, str(target)] + self.args
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
            output = r.stdout[:3000] + (f"\n[STDERR]\n{r.stderr[:1000]}" if r.stderr else "")
            new_ctx[self.name] = output
            new_ctx["_last_stage"] = self.name
            new_ctx["_last_exit_code"] = r.returncode
        except Exception as e:
            new_ctx[self.name] = f"[执行失败: {e}]"
            new_ctx["_last_stage"] = self.name
        return new_ctx

class SynthesisStage(RelayStage):
    """综合输出接力阶段——用OpenLLM/Hermes综合所有阶段结果"""
    def __init__(self, name: str = "synthesis", 
                 instruction: str = "请综合以上所有信息，给出完整的分析报告。",
                 model: str = "", max_context_chars: int = 3000):
        super().__init__(name, "综合生成报告")
        self.instruction = instruction
        self.model = model
        self.max_context_chars = max_context_chars
    
    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print(f"  🔗 综合所有阶段结果 (model={self.model or 'Hermes'})...")
        
        # 收集所有阶段输出
        stages_summary = []
        for k, v in context.items():
            if k.startswith("_") or k == "system_data":
                continue
            if isinstance(v, str) and len(v) > 10:
                stages_summary.append(f"### {k}\n{v[:self.max_context_chars]}")
        
        # 添加系统数据（如有）
        if "system_data" in context and isinstance(context["system_data"], dict):
            stages_summary.append(f"### 系统数据\n{json.dumps(context['system_data'], indent=2, ensure_ascii=False)[:self.max_context_chars]}")
        
        all_info = "\n\n".join(stages_summary)
        
        prompt = f"""你是一个任务综合专家。以下是多阶段任务接力执行过程中收集的所有信息。

{self.instruction}

各阶段输出:
{all_info}

请提供:
1. **核心结论** — 对整个任务的综合判断
2. **关键发现** — 最重要的洞察点
3. **建议行动** — 具体可操作的下一步
4. **接力总结** — 各阶段接力效果评估

使用结构化格式输出，清晰易读。"""
        
        if self.model:
            result = _openllm_chat(prompt, model=self.model)
        else:
            result = _hermes_chat(prompt)
        synthesis = result.get("response", "")
        
        new_ctx = dict(context)
        new_ctx["synthesis"] = synthesis
        new_ctx["_last_stage"] = self.name
        return new_ctx

class VisionStage(RelayStage):
    """视觉捕获接力阶段 — 截图 + OCR，支持指定窗口"""
    def __init__(self, name: str = "vision_data",
                 window_title: str = "", save_screenshot: bool = False):
        super().__init__(name, f"视觉捕获: {window_title or '全屏'}")
        self.window_title = window_title
        self.save_screenshot = save_screenshot
    
    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print(f"  📷 视觉捕获: {self.window_title or '全屏'}")
        new_ctx = dict(context)
        
        scripts_dir = GA_HOME / "scripts"
        vision_script = scripts_dir / "vision_agent.py"
        
        if not vision_script.exists():
            new_ctx[self.name] = "[vision_agent.py 不存在]"
            new_ctx["_last_stage"] = self.name
            return new_ctx
        
        screenshot_path = "/tmp/vision_relay_capture.png"
        
        # Stage 1: Screenshot
        try:
            ss_args = [sys.executable, str(vision_script), "screenshot",
                       "--save", screenshot_path]
            if self.window_title:
                ss_args.extend(["--window", self.window_title])
            r1 = subprocess.run(ss_args, capture_output=True, text=True, timeout=30)
            if r1.returncode != 0:
                new_ctx[self.name] = f"[截图失败: {r1.stderr[:200]}]"
                new_ctx["_last_stage"] = self.name
                return new_ctx
        except Exception as e:
            new_ctx[self.name] = f"[截图异常: {e}]"
            new_ctx["_last_stage"] = self.name
            return new_ctx
        
        # Stage 2: OCR
        try:
            ocr_args = [sys.executable, str(vision_script), "ocr", "--json"]
            if self.window_title:
                ocr_args.extend(["--window", self.window_title])
            r2 = subprocess.run(ocr_args, capture_output=True, text=True, timeout=60)
            ocr_text = ""
            if r2.returncode == 0:
                # Extract text from OCR output
                lines = r2.stdout.split('\n')
                ocr_lines = []
                in_ocr = False
                for line in lines:
                    if line.startswith('OCR ('):
                        in_ocr = True
                        continue
                    if in_ocr:
                        if line.strip() and not line.startswith('{'):
                            ocr_lines.append(line)
                ocr_text = '\n'.join(ocr_lines).strip()
                # Try JSON parse for structured output
                if '{' in r2.stdout:
                    try:
                        import json as _json
                        json_start = r2.stdout.index('{')
                        json_data = _json.loads(r2.stdout[json_start:])
                        if isinstance(json_data, dict) and 'text' in json_data:
                            ocr_text = json_data['text']
                    except:
                        pass
        except Exception as e:
            ocr_text = f"[OCR异常: {e}]"
        
        result = {
            "screenshot_saved": screenshot_path if self.save_screenshot else None,
            "window": self.window_title or "全屏",
            "ocr_text": ocr_text[:5000] if ocr_text else "(无文字)",
        }
        new_ctx[self.name] = result
        new_ctx["_vision_ocr_text"] = result["ocr_text"]
        new_ctx["_last_stage"] = self.name
        return new_ctx


# ======================== 预定义管道 ========================

PIPELINES = {
    "system_health": {
        "description": "系统健康全链路分析 — 采集→分析→报告",
        "stages": [
            SystemDataStage("system_data", ["cpu", "memory", "disk", "process", "uptime"]),
            HermesChatStage(
                "health_analysis",
                "分析以下系统数据，识别健康问题和风险：\n{system_data}",
                extract_key="health_report",
                system_hint="你是一个系统运维专家，请用中文回答。"
            ),
            SynthesisStage(
                "report",
                "基于系统数据和健康分析，生成系统健康报告，包括风险等级、问题清单和修复建议。"
            )
        ]
    },
    "investigate": {
        "description": "智能调查 — Hermes推理→采集→分析→综合",
        "stages": [
            HermesChatStage(
                "investigation_plan",
                "我需要调查以下问题：{task}\n\n请制定调查计划：需要采集哪些数据、检查哪些方面。列出3-5个具体步骤。",
                extract_key="plan",
                system_hint="你是一个调查专家，请用中文回答。"
            ),
            SystemDataStage("system_data", ["cpu", "memory", "disk", "process"]),
            HermesChatStage(
                "investigation_analysis",
                "调查任务: {task}\n\n调查计划: {plan}\n\n采集到的系统数据: {system_data}\n\n请根据以上信息进行分析，找出问题根因。",
                extract_key="analysis",
                system_hint="你是一个根因分析专家，请用中文回答。"
            ),
            SynthesisStage(
                "final_report",
                "基于调查计划、系统数据和根因分析，生成完整的调查报告，包括问题描述、根因、影响范围和修复方案。"
            )
        ]
    },
    "code_review": {
        "description": "代码审查 — 读取→分析→建议",
        "stages": [
            FileReadStage("source_code", "{file_path}", max_chars=8000),
            HermesChatStage(
                "code_review",
                "请审查以下代码：\n\n{source_code}\n\n从以下维度评审：\n1. 代码质量与可读性\n2. 潜在bug与安全问题\n3. 性能问题\n4. 架构设计\n5. 改进建议",
                extract_key="review",
                system_hint="你是一个资深代码评审专家，请用中文回答。"
            ),
            SynthesisStage(
                "review_report",
                "基于代码审查结果，生成可执行的改进计划，按优先级排序。"
            )
        ]
    },
    "tool_chain": {
        "description": "工具链接力 — Hermes推理→GA脚本执行→综合报告（analysis使用OpenLLM快速模型）",
        "stages": [
            HermesChatStage(
                "task_plan",
                "我需要执行以下任务：{task}\n\n请制定执行计划，列出需要调用哪些系统工具/脚本来完成此任务。",
                extract_key="plan",
                system_hint="你是一个自动化运维专家，请用中文回答。将计划输出为清晰的步骤列表。"
            ),
            SystemDataStage("system_data", ["cpu", "memory", "disk", "process", "uptime"]),
            ScriptExecStage("script_check", "scripts/hermes_tool.py", 
                           args=["status"], timeout=30),
            HermesChatStage(
                "analysis",
                "任务: {task}\n\n执行计划摘要: {plan}\n\n脚本输出: {script_check}\n\n请对以上信息进行简单分析，给出建议。回复控制在100字以内。",
                extract_key="analysis",
                system_hint="你是一个任务执行专家，请用中文回答。",
                model="deepseek/deepseek-v4-flash",  # 使用OpenLLM快模型
                timeout=120,
                max_context_chars=2000               # 控制上下文大小
            ),
            SynthesisStage(
                "final_report",
                "基于任务计划、系统数据、脚本输出和分析结果，生成完整的任务执行报告。"
            )
        ]
    },
    "visual_inspect": {
        "description": "视觉检查 — 截图→OCR→Hermes分析→报告",
        "stages": [
            VisionStage("vision_data", "{window_title}", save_screenshot=True),
            HermesChatStage(
                "vision_analysis",
                "以下是从目标窗口截取的视觉内容(OCR文字)：\n\n{_vision_ocr_text}\n\n请分析这些内容：\n1. 窗口中显示了什么信息？\n2. 有哪些关键文本/数据？\n3. 是否符合预期？\n4. 如果有异常，是什么？",
                extract_key="vision_report",
                system_hint="你是一个视觉分析专家，请用中文详细回答。"
            ),
            SynthesisStage(
                "vision_summary",
                "基于OCR提取的文字和视觉分析，生成视觉检查报告，总结窗口内容、关键信息和发现的异常。"
            )
        ]
    },
    "custom": {
        "description": "自定义管道 — 用参数定义阶段序列",
        "stages": []
    }
}


# ======================== 底层工具 ========================

def _hermes_chat(query: str, timeout: int = 240, stream: bool = False) -> Dict[str, Any]:
    """调用Hermes CLI聊天"""
    try:
        cmd = [HERMES_CMD, "chat", "-q", query]
        if not stream:
            cmd.append("-Q")  # quiet mode (no stream)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        response = _extract_response(r.stdout)
        return {"success": r.returncode == 0, "response": response, "raw": r.stdout}
    except subprocess.TimeoutExpired:
        return {"success": False, "response": "[TIMEOUT]", "error": f"超时{timeout}s"}
    except FileNotFoundError:
        return {"success": False, "response": "[Hermes CLI not found]", "error": "hermes not found"}
    except Exception as e:
        return {"success": False, "response": f"[Error: {e}]", "error": str(e)}


def _openllm_chat(query: str, model: str = "deepseek/deepseek-v4-flash",
                  timeout: int = 120) -> Dict[str, Any]:
    """使用OpenLLM本地API替代Hermes CLI，快10-50x
    
    依赖: OpenLLM服务运行在 http://127.0.0.1:11343
    """
    import urllib.request, urllib.error
    url = "http://127.0.0.1:11343/v1/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": query}],
        "max_tokens": 1024,
        "temperature": 0.3,
    }).encode("utf-8")
    
    try:
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read().decode("utf-8"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"success": True, "response": content, "model": model}
    except urllib.error.HTTPError as e:
        return {"success": False, "response": f"[OpenLLM HTTP {e.code}]", "error": str(e)}
    except urllib.error.URLError as e:
        return {"success": False, "response": f"[OpenLLM不可用: {e.reason}]", "error": str(e)}
    except Exception as e:
        return {"success": False, "response": f"[OpenLLM Error: {e}]", "error": str(e)}

def _extract_response(raw: str) -> str:
    """从hermes输出中提取响应文本"""
    lines = raw.split('\n')
    result = []
    in_response = False
    for line in lines:
        if '╰' in line and '─' in line:
            in_response = True
            continue
        if in_response:
            if line.startswith('Resume this session') or line.startswith('Session:'):
                break
            result.append(line)
    r = '\n'.join(result).strip()
    if r:
        return r
    non_empty = [l for l in lines if l.strip() and not l.startswith('╭') and not l.startswith('╰')]
    return '\n'.join(non_empty[-10:]) if non_empty else raw

def _collect_system_data(data_types: List[str]) -> Dict[str, Any]:
    """采集指定系统数据"""
    data = {}
    
    if "cpu" in data_types:
        try:
            with open('/proc/loadavg') as f:
                parts = f.read().strip().split()
                data["cpu"] = {
                    "load_1m": float(parts[0]), "load_5m": float(parts[1]),
                    "load_15m": float(parts[2]),
                    "process_running": parts[3].split('/')[0],
                    "process_total": parts[3].split('/')[1]
                }
        except: data["cpu"] = "unavailable"
    
    if "memory" in data_types:
        try:
            with open('/proc/meminfo') as f:
                mem = {}
                for line in f:
                    if 'MemTotal' in line: mem["total_kb"] = int(line.split()[1])
                    elif 'MemAvailable' in line: mem["available_kb"] = int(line.split()[1])
                if "total_kb" in mem and "available_kb" in mem:
                    total_mb = mem["total_kb"] / 1024
                    avail_mb = mem["available_kb"] / 1024
                    data["memory"] = {
                        "total_mb": round(total_mb, 1), 
                        "available_mb": round(avail_mb, 1),
                        "used_mb": round(total_mb - avail_mb, 1),
                        "usage_pct": round((total_mb - avail_mb) / total_mb * 100, 1)
                    }
        except: data["memory"] = "unavailable"
    
    if "disk" in data_types:
        try:
            import shutil
            total, used, free = shutil.disk_usage("/")
            data["disk"] = {
                "total_gb": round(total / (1024**3), 1),
                "used_gb": round(used / (1024**3), 1),
                "free_gb": round(free / (1024**3), 1),
                "usage_pct": round(used / total * 100, 1)
            }
        except: data["disk"] = "unavailable"
    
    if "process" in data_types:
        try:
            proc_count = len([d for d in Path('/proc').iterdir() if d.name.isdigit()])
            data["process_count"] = proc_count
        except: data["process_count"] = "unavailable"
    
    if "uptime" in data_types:
        try:
            with open('/proc/uptime') as f:
                uptime_seconds = float(f.read().split()[0])
                data["uptime_hours"] = round(uptime_seconds / 3600, 1)
        except: data["uptime_hours"] = "unavailable"
    
    data["timestamp"] = datetime.now().isoformat()
    return data


# ======================== 接力执行器 ========================

class RelayPipeline:
    """接力管道执行器"""
    
    def __init__(self, name: str, stages: List[RelayStage], description: str = "",
                 checkpoint_dir: str = "/tmp/hermes_relay_checkpoints"):
        self.name = name
        self.stages = stages
        self.description = description
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    
    def _checkpoint_path(self, run_id: str) -> Path:
        return self.checkpoint_dir / f"{self.name}_{run_id}.json"
    
    def save_checkpoint(self, run_id: str, ctx: dict, stage_idx: int):
        """保存检查点"""
        cp = {
            "run_id": run_id,
            "pipeline": self.name,
            "timestamp": datetime.now().isoformat(),
            "completed_stage": stage_idx,
            "context": {k: v for k, v in ctx.items() if not k.startswith("_") or k in ("_pipeline", "_start_time")}
        }
        cp_path = self._checkpoint_path(run_id)
        cp_path.write_text(json.dumps(cp, indent=2, ensure_ascii=False))
        return cp_path
    
    def load_checkpoint(self, run_id: str) -> Optional[dict]:
        """加载检查点"""
        cp_path = self._checkpoint_path(run_id)
        if cp_path.exists():
            return json.loads(cp_path.read_text())
        return None
    
    def list_checkpoints(self) -> List[dict]:
        """列出所有检查点"""
        cps = []
        for f in sorted(self.checkpoint_dir.glob(f"{self.name}_*.json")):
            try:
                data = json.loads(f.read_text())
                cps.append({
                    "run_id": data.get("run_id", f.stem),
                    "timestamp": data.get("timestamp", ""),
                    "completed_stage": data.get("completed_stage", -1),
                    "pipeline": data.get("pipeline", ""),
                    "file": f.name
                })
            except:
                pass
        return cps
    
    def run(self, initial_context: Dict[str, Any] = None, 
            total_timeout: int = 0,
            progress_callback: Optional[Callable] = None,
            run_id: str = None) -> Dict[str, Any]:
        """执行接力管道
        
        Args:
            initial_context: 初始上下文
            total_timeout: 总超时(秒)，0=不限
            progress_callback: 进度回调 fn(stage_name, stage_idx, total, status, elapsed, detail)
            run_id: 运行ID，用于检查点
        """
        ctx = initial_context or {}
        ctx["_pipeline"] = self.name
        ctx["_start_time"] = datetime.now().isoformat()
        run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        
        print(f"\n{'='*60}")
        print(f"🚀 接力管道: {self.name}")
        print(f"📋 {self.description}")
        if total_timeout > 0:
            print(f"⏱ 总超时: {total_timeout}s")
        print(f"🆔 Run ID: {run_id}")
        print(f"{'='*60}\n")
        
        # 总超时控制
        timeout_exceeded = threading.Event()
        def _timeout_watchdog():
            if total_timeout > 0:
                if not timeout_exceeded.wait(total_timeout):
                    timeout_exceeded.set()
                    print(f"\n   ❌ 总超时 {total_timeout}s 到达!")
        
        if total_timeout > 0:
            watchdog = threading.Thread(target=_timeout_watchdog, daemon=True)
            watchdog.start()
        
        pipeline_start = time.time()
        stage_results = []
        
        for i, stage in enumerate(self.stages):
            # 检查总超时
            if timeout_exceeded.is_set():
                print(f"\n[{i+1}/{len(self.stages)}] {stage.name} — ⏭ 跳过(总超时)")
                stage_results.append({
                    "stage": stage.name,
                    "status": "skipped",
                    "duration_s": 0,
                    "error": "pipeline timeout exceeded"
                })
                continue
            
            print(f"\n[{i+1}/{len(self.stages)}] {stage.name}")
            print(f"    {stage.description}")
            
            t0 = time.time()
            try:
                ctx = stage.execute(ctx)
                elapsed = time.time() - t0
                status = "✅" if ctx.get("_last_error") is None else "❌"
                print(f"   {status} 完成 ({elapsed:.1f}s)")
                
                stage_results.append({
                    "stage": stage.name,
                    "status": "success" if ctx.get("_last_error") is None else "error",
                    "duration_s": round(elapsed, 2),
                    "output_preview": str(ctx.get(stage.name, ""))[:200]
                })
                
                # 进度回调
                if progress_callback:
                    try:
                        progress_callback(stage.name, i, len(self.stages), 
                                        stage_results[-1]["status"], elapsed, None)
                    except Exception:
                        pass
                
                # 每个阶段完成后保存检查点
                self.save_checkpoint(run_id, ctx, i)
                
            except Exception as e:
                elapsed = time.time() - t0
                print(f"   ❌ 失败 ({elapsed:.1f}s): {e}")
                ctx["_last_error"] = str(e)
                stage_results.append({
                    "stage": stage.name,
                    "status": "error",
                    "duration_s": round(elapsed, 2),
                    "error": str(e)
                })
                
                if progress_callback:
                    try:
                        progress_callback(stage.name, i, len(self.stages), "error", elapsed, str(e))
                    except Exception:
                        pass
                break
        
        ctx["_stage_results"] = stage_results
        ctx["_end_time"] = datetime.now().isoformat()
        ctx["_run_id"] = run_id
        
        total_elapsed = time.time() - pipeline_start
        success_count = sum(1 for s in stage_results if s["status"] == "success")
        
        print(f"\n{'='*60}")
        print(f"🏁 接力完成: {self.name}")
        print(f"   阶段: {success_count}/{len(self.stages)} 成功 ({total_elapsed:.1f}s)")
        if total_timeout > 0:
            timeout_exceeded.clear()
        print(f"{'='*60}\n")
        
        return ctx
    
    @classmethod
    def from_config(cls, name: str, custom_stages: List[RelayStage] = None) -> Optional["RelayPipeline"]:
        """从预定义配置创建管道"""
        if name == "custom" and custom_stages:
            return cls("custom", custom_stages, "自定义接力管道")
        if name not in PIPELINES:
            return None
        config = PIPELINES[name]
        return cls(name, config["stages"], config["description"])


# ======================== CLI ========================

def main():
    parser = argparse.ArgumentParser(
        description="Hermes Task Relay — 复杂任务接力管道",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            使用示例:
              python3 scripts/hermes_relay.py list
              python3 scripts/hermes_relay.py run system_health
              python3 scripts/hermes_relay.py run investigate "分析内存使用率高的原因"
              python3 scripts/hermes_relay.py run code_review scripts/hermes_bridge.py
        """)
    )
    
    subparsers = parser.add_subparsers(dest="command", help="子命令")
    
    # list
    subparsers.add_parser("list", help="列出可用管道")
    
    # run
    run_p = subparsers.add_parser("run", help="运行接力管道")
    run_p.add_argument("pipeline", choices=list(PIPELINES.keys()) + ["custom"],
                       help="管道名称")
    run_p.add_argument("args", nargs="*", help="管道参数（如调查任务、文件路径等）")
    run_p.add_argument("--json", action="store_true", help="JSON输出")
    run_p.add_argument("--resume", metavar="RUN_ID", help="从指定RUN_ID的检查点恢复")
    run_p.add_argument("--checkpoint-dir", default="/tmp/hermes_relay_checkpoints",
                       help="检查点目录")
    run_p.add_argument("--progress-stream", action="store_true",
                       help="输出JSONL格式进度行到stderr")
    run_p.add_argument("--timeout", type=int, default=300,
                       help="管道总超时(秒)，默认300s")
    run_p.add_argument("--model", default="",
                       help="使用OpenLLM指定模型(如 deepseek/deepseek-v4-flash)，空=使用Hermes CLI")
    run_p.add_argument("--list-checkpoints", action="store_true",
                       help="列出此管道的检查点")
    
    args = parser.parse_args()
    
    if args.command == "list":
        print("📋 可用接力管道:\n")
        for name, cfg in PIPELINES.items():
            stages_desc = " → ".join(s.name for s in cfg["stages"])
            print(f"  {name:<20} {cfg['description']}")
            print(f"  {'':20} 阶段: {stages_desc}")
            print()
    
    elif args.command == "run":
        pipeline = RelayPipeline.from_config(args.pipeline)
        if not pipeline:
            print(f"❌ 未知管道: {args.pipeline}")
            return
        
        # 设置检查点目录
        pipeline.checkpoint_dir = Path(args.checkpoint_dir)
        pipeline.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        # 使用OpenLLM快速模型（覆盖所有支持model参数的阶段）
        if args.model:
            for stage in pipeline.stages:
                if hasattr(stage, 'model') and not stage.model:
                    stage.model = args.model
                    if hasattr(stage, 'timeout'):
                        stage.timeout = min(stage.timeout, 120)  # 快模型缩短超时
        
        # 列出检查点
        if args.list_checkpoints:
            cps = pipeline.list_checkpoints()
            if not cps:
                print(f"📭 无检查点 (pipeline={args.pipeline}, dir={pipeline.checkpoint_dir})")
            else:
                print(f"📋 检查点列表 (pipeline={args.pipeline}):\n")
                for cp in cps:
                    print(f"  🆔 {cp['run_id']}")
                    print(f"     📅 {cp['timestamp']}")
                    print(f"     ✅ 完成阶段 #{cp['completed_stage']+1}")
                    print()
            return
        
        # 进度回调
        progress_cb = None
        if args.progress_stream:
            def _progress(stage_name, idx, total, status, elapsed, error):
                import sys
                obj = {
                    "event": "stage_progress",
                    "pipeline": args.pipeline,
                    "stage": stage_name,
                    "stage_idx": idx,
                    "total_stages": total,
                    "status": status,
                    "elapsed_s": round(elapsed, 2),
                    "error": error
                }
                print(json.dumps(obj), file=sys.stderr, flush=True)
            progress_cb = _progress
        
        # 恢复检查点
        ctx = {}
        resume_from = -1
        if args.resume:
            cp_data = pipeline.load_checkpoint(args.resume)
            if cp_data:
                ctx = cp_data.get("context", {})
                resume_from = cp_data.get("completed_stage", -1) + 1
                print(f"♻️ 恢复管道 {args.pipeline} 从阶段 #{resume_from+1}")
                # 只运行未完成的阶段
                pipeline.stages = pipeline.stages[resume_from:]
            else:
                print(f"⚠️ 检查点 {args.resume} 未找到，从头开始")
        
        if args.pipeline == "investigate" and args.args:
            ctx["task"] = " ".join(args.args)
        elif args.pipeline == "code_review" and args.args:
            ctx["file_path"] = args.args[0]
        elif args.pipeline == "tool_chain" and args.args:
            ctx["task"] = " ".join(args.args)
        
        result = pipeline.run(ctx, total_timeout=args.timeout,
                             progress_callback=progress_cb,
                             run_id=args.resume or None)
        
        if args.json:
            # 清理context（移除大文本字段用于JSON输出）
            clean = {k: v for k, v in result.items() 
                    if not isinstance(v, str) or len(v) < 2000}
            clean["_pipeline_summary"] = {
                "pipeline": result.get("_pipeline"),
                "stages": len(result.get("_stage_results", [])),
                "duration_s": sum(s.get("duration_s", 0) for s in result.get("_stage_results", [])),
                "has_synthesis": "synthesis" in result
            }
            print(json.dumps(clean, indent=2, ensure_ascii=False))
        else:
            # 显示综合结果
            if result.get("synthesis"):
                print("\n" + "="*60)
                print("📊 综合报告")
                print("="*60)
                print(result["synthesis"])
            
            # 显示各阶段摘要
            print(f"\n{'='*60}")
            print("📋 各阶段接力摘要")
            print("="*60)
            for sr in result.get("_stage_results", []):
                icon = "✅" if sr["status"] == "success" else "❌"
                print(f"  {icon} {sr['stage']} ({sr['duration_s']:.1f}s)")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
