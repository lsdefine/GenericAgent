#!/usr/bin/env python3
"""
Hermes Bridge V2 — GA↔Hermes深度集成桥接

基于hermes_tool.py增强，新增：
  - HermesBridge类封装（OOP接口）
  - Chain-of-Thought推理（多步分解→中间结果→综合）
  - Session生命周期管理（创建/切换/归档/恢复）
  - 结构化查询（JSON schema驱动输出）
  - 工具代理模式（GA收集数据→Hermes分析→结构化结果）

验收标准: GA能通过hermes执行"分析当前系统状态并给出建议"的推理任务并获取结构化结果
"""

import subprocess, sys, json, os, re, time, argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Union

# ======================== 常量 ========================

HERMES_CMD = "/home/admin/.local/bin/hermes"
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TIMEOUT = 120
COT_TIMEOUT = 180

# ======================== 底层执行器 ========================

class HermesExecutor:
    """Hermes CLI底层封装，提供稳定子进程调用"""
    
    def __init__(self, cmd: str = HERMES_CMD, timeout: int = DEFAULT_TIMEOUT):
        self.cmd = cmd
        self.timeout = timeout
    
    def run(self, args: List[str], timeout: Optional[int] = None) -> Dict[str, Any]:
        """执行Hermes命令并返回结构化结果"""
        cmd = [self.cmd] + args
        t = timeout or self.timeout
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=t)
            return {
                "success": r.returncode == 0,
                "returncode": r.returncode,
                "stdout": r.stdout,
                "stderr": r.stderr,
                "command": " ".join(cmd)
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"TIMEOUT after {t}s", "command": " ".join(cmd)}
        except FileNotFoundError:
            return {"success": False, "error": f"hermes not found: {self.cmd}", "command": " ".join(cmd)}
        except Exception as e:
            return {"success": False, "error": str(e), "command": " ".join(cmd)}
    
    def chat(self, query: str, session_id: Optional[str] = None, 
             model: Optional[str] = None, quiet: bool = True) -> Dict[str, Any]:
        """发送聊天消息"""
        args = ["chat"]
        if session_id:
            args.extend(["-s", session_id])
        if model:
            args.extend(["-m", model])
        if quiet:
            args.append("-Q")
        args.extend(["-q", query])
        return self.run(args)
    
    def extract_response(self, raw_stdout: str) -> str:
        """从hermes输出中提取响应文本"""
        lines = raw_stdout.split('\n')
        result_lines = []
        in_response = False
        for line in lines:
            if '╰' in line and '─' in line:
                in_response = True
                continue
            if in_response:
                if line.startswith('Resume this session') or line.startswith('Session:'):
                    break
                result_lines.append(line)
        r = '\n'.join(result_lines).strip()
        if r:
            return r
        # Fallback
        non_empty = [l for l in lines if l.strip() and not l.startswith('╭') and not l.startswith('╰')]
        return '\n'.join(non_empty[-10:]) if non_empty else raw_stdout


# ======================== Session管理器 ========================

class SessionManager:
    """Hermes session生命周期管理"""
    
    def __init__(self, executor: HermesExecutor):
        self.executor = executor
        self._sessions_cache = []
    
    def list(self, refresh: bool = False) -> List[Dict[str, str]]:
        """列出所有session"""
        if self._sessions_cache and not refresh:
            return self._sessions_cache
        
        result = self.executor.run(["sessions", "list"])
        sessions = []
        if result["success"]:
            lines = result["stdout"].strip().split('\n')
            header_passed = False
            for line in lines:
                if '─' * 10 in line:
                    header_passed = True
                    continue
                if header_passed and line.strip():
                    parts = line.rsplit(None, 2)
                    if len(parts) >= 3:
                        preview = parts[0]
                        last_active = parts[-3] if len(parts) >= 3 else ""
                        source = parts[-2] if len(parts) >= 2 else ""
                        sid = parts[-1]
                        sessions.append({
                            "id": sid,
                            "preview": preview[:60],
                            "last_active": last_active,
                            "source": source
                        })
        self._sessions_cache = sessions
        return sessions
    
    def get_latest(self, source: Optional[str] = None) -> Optional[str]:
        """获取最新session ID"""
        sessions = self.list(refresh=True)
        if source:
            sessions = [s for s in sessions if s.get("source") == source]
        return sessions[0]["id"] if sessions else None
    
    def create(self, label: Optional[str] = None) -> Optional[str]:
        """创建新session并返回ID"""
        if label:
            result = self.executor.run(["chat", "-q", label, "-Q"])
        else:
            result = self.executor.run(["chat", "-q", "init", "-Q"])
        
        if result["success"]:
            # After first chat, a session is created - get it
            sessions = self.list(refresh=True)
            return sessions[0]["id"] if sessions else None
        return None
    
    def archive(self, session_id: str) -> bool:
        """归档session"""
        result = self.executor.run(["sessions", "archive", session_id])
        if result["success"]:
            self._sessions_cache = []
        return result["success"]
    
    def delete(self, session_id: str) -> bool:
        """删除session"""
        result = self.executor.run(["sessions", "rm", session_id])
        if result["success"]:
            self._sessions_cache = []
        return result["success"]


# ======================== CoT推理引擎 ========================

class CoTEngine:
    """Chain-of-Thought推理引擎
    
    将复杂任务分解为多步推理链，每步执行→记录→综合
    """
    
    def __init__(self, executor: HermesExecutor):
        self.executor = executor
        self.steps: List[Dict] = []
    
    def reason(self, task: str, context: Optional[Dict] = None,
               max_steps: int = 5) -> Dict[str, Any]:
        """执行Chain-of-Thought推理"""
        self.steps = []
        start_time = time.time()
        
        # Step 1: 任务分解
        decomposition = self._decompose(task, context)
        self.steps.append({
            "step": "decomposition",
            "input": task,
            "output": decomposition,
            "status": "success"
        })
        
        if not decomposition.get("sub_tasks"):
            return {
                "success": False,
                "error": "Task decomposition failed",
                "steps": self.steps,
                "duration": time.time() - start_time
            }
        
        # Step 2~N: 执行子任务
        sub_results = []
        for i, sub in enumerate(decomposition.get("sub_tasks", [])[:max_steps]):
            step_prompt = f"[Step {i+1}/{len(decomposition['sub_tasks'])}] {sub}"
            
            if context:
                ctx_str = json.dumps(context, ensure_ascii=False)
                step_prompt = f"{step_prompt}\n\nContext: {ctx_str[:2000]}"
            
            result = self.executor.chat(step_prompt)
            response = self.executor.extract_response(result.get("stdout", ""))
            
            step_result = {
                "step": i + 1,
                "sub_task": sub,
                "response": response[:1000],
                "status": "success" if result.get("success") else "failed"
            }
            sub_results.append(step_result)
            self.steps.append(step_result)
        
        # Step N+1: 综合结果
        synthesis_prompt = self._build_synthesis_prompt(task, sub_results)
        synthesis_result = self.executor.chat(synthesis_prompt)
        synthesis = self.executor.extract_response(synthesis_result.get("stdout", ""))
        
        self.steps.append({
            "step": "synthesis",
            "input": task,
            "output": synthesis,
            "status": "success"
        })
        
        return {
            "success": True,
            "task": task,
            "decomposition": decomposition,
            "sub_results": sub_results,
            "synthesis": synthesis,
            "steps": self.steps,
            "duration": time.time() - start_time,
            "num_steps": len(sub_results) + 2
        }
    
    def _decompose(self, task: str, context: Optional[Dict] = None) -> Dict:
        """将任务分解为子任务列表"""
        prompt = f"""你是一个任务分解专家。请将以下任务分解为2-5个可执行的子任务。

任务: {task}

请以JSON格式输出：
{{
    "task": "{task}",
    "sub_tasks": ["子任务1", "子任务2", ...],
    "reasoning": "分解理由"
}}

只输出JSON，不要其他内容。"""
        
        if context:
            prompt += f"\n\n上下文: {json.dumps(context, ensure_ascii=False)[:1000]}"
        
        result = self.executor.chat(prompt)
        response = self.executor.extract_response(result.get("stdout", ""))
        
        # 尝试解析JSON
        try:
            # Find JSON block
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        
        # Fallback: 简单解析
        lines = [l.strip() for l in response.split('\n') if l.strip()]
        sub_tasks = [l for l in lines if l.startswith('-') or l[0].isdigit()]
        return {
            "task": task,
            "sub_tasks": sub_tasks[:5] if sub_tasks else [task],
            "reasoning": "fallback parse"
        }
    
    def _build_synthesis_prompt(self, task: str, sub_results: List[Dict]) -> str:
        """构建综合提示"""
        results_text = ""
        for sr in sub_results:
            results_text += f"\n### {sr.get('sub_task', 'Step')}\n{sr.get('response', 'N/A')[:500]}\n"
        
        return f"""请综合以下子任务结果，回答原始问题。

原始任务: {task}

子任务结果:
{results_text}

请提供：
1. **核心结论** — 直接回答原始任务
2. **关键发现** — 重要洞察
3. **建议行动** — 具体可操作的下一步

使用结构化格式输出。"""


# ======================== 结构化查询 ========================

class StructuredQuery:
    """结构化查询——让Hermes按schema输出"""
    
    @staticmethod
    def ask(executor: HermesExecutor, query: str, 
            output_schema: Optional[Dict] = None,
            system_context: Optional[str] = None) -> Dict[str, Any]:
        """执行结构化查询，返回JSON格式结果"""
        
        schema_instruction = ""
        if output_schema:
            schema_instruction = f"""
请严格按照以下JSON Schema输出：
```json
{json.dumps(output_schema, indent=2, ensure_ascii=False)}
```

只输出JSON，不要其他内容。确保JSON有效。"""
        
        system_part = f"\n上下文信息:\n{system_context[:2000]}\n" if system_context else ""
        
        full_prompt = f"""{system_part}

请回答以下问题:
{query}
{schema_instruction}"""
        
        result = executor.chat(full_prompt)
        # 使用原始stdout（_extract_json已具备健壮的JSON提取能力，不依赖╰─标记）
        response = result.get("stdout", "")
        
        # Try parse JSON (robust version)
        parsed = None
        try:
            parsed = StructuredQuery._extract_json(response)
        except:
            pass
        
        return {
            "success": result.get("success", False),
            "query": query,
            "raw_response": response,
            "parsed": parsed,
            "has_structured_output": parsed is not None
        }
    
    @staticmethod
    def _extract_json(text: str) -> Optional[Dict]:
        """健壮地从文本中提取JSON，处理markdown代码块、非法转义、尾部多余内容"""
        if not text:
            return None
        
        # Step 1: 尝试直接解析（如果整个响应就是JSON）
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # Step 2: 去掉markdown代码块标记
        cleaned = re.sub(r'```(?:json)?\s*', '', text).strip()
        
        # Step 3: 找到第一个 { 和匹配的 }
        start = cleaned.find('{')
        if start == -1:
            return None
        
        # 用栈匹配大括号，找到真正的JSON结尾
        depth = 0
        end = -1
        in_string = False
        escape = False
        for i in range(start, len(cleaned)):
            ch = cleaned[i]
            if escape:
                escape = False
                continue
            if ch == '\\' and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        
        if end == -1:
            return None
        
        json_str = cleaned[start:end+1]
        
        # Step 4: 修复常见非法JSON转义
        # JSON标准中 \' 是非法转义，替换为 '
        json_str = json_str.replace("\\'", "'")
        # 修复未转义的控制字符
        json_str = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', json_str)
        
        # Step 5: 尝试解析
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return None


# ======================== 工具代理模式 ========================

class ToolProxy:
    """工具代理——让Hermes通过GA间接执行系统操作
    
    工作流:
    1. GA收集系统数据（通过本地工具）
    2. 将数据作为context传给Hermes
    3. Hermes分析并返回结构化洞察
    """
    
    def __init__(self, executor: HermesExecutor):
        self.executor = executor
    
    def analyze_with_context(self, task: str, 
                             collected_data: Dict[str, Any]) -> Dict[str, Any]:
        """使用收集的数据让Hermes分析并返回结构化结果"""
        
        context_str = json.dumps(collected_data, indent=2, ensure_ascii=False)
        
        schema = {
            "type": "object",
            "properties": {
                "analysis": {"type": "string", "description": "核心分析"},
                "findings": {"type": "array", "items": {"type": "string"}},
                "recommendations": {"type": "array", "items": {"type": "string"}},
                "risk_level": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1}
            },
            "required": ["analysis", "findings", "recommendations", "risk_level", "confidence"]
        }
        
        return StructuredQuery.ask(
            self.executor,
            query=task,
            output_schema=schema,
            system_context=f"以下是通过系统工具收集的当前状态数据:\n\n{context_str[:3000]}"
        )


# ======================== 主桥接类 ========================

class HermesBridge:
    """Hermes Bridge V2 — 统一入口"""
    
    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.executor = HermesExecutor(timeout=timeout)
        self.sessions = SessionManager(self.executor)
        self.cot = CoTEngine(self.executor)
        self.proxy = ToolProxy(self.executor)
    
    def chat(self, query: str, session_id: Optional[str] = None,
             model: Optional[str] = None, json_output: bool = False) -> Dict[str, Any]:
        """基础聊天接口"""
        result = self.executor.chat(query, session_id, model)
        response = self.executor.extract_response(result.get("stdout", ""))
        
        output = {
            "success": result.get("success", False),
            "response": response,
            "session_id": session_id,
            "raw": result.get("stdout", "")[-500:] if not json_output else result.get("stdout", "")
        }
        return output
    
    def reason(self, task: str, context: Optional[Dict] = None,
               max_steps: int = 5) -> Dict[str, Any]:
        """Chain-of-Thought推理"""
        return self.cot.reason(task, context, max_steps)
    
    def structured_query(self, query: str, schema: Dict,
                         context: Optional[str] = None) -> Dict[str, Any]:
        """结构化查询"""
        return StructuredQuery.ask(self.executor, query, schema, context)
    
    def analyze_system(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """系统状态分析——验收标准场景"""
        return self.proxy.analyze_with_context(
            "分析当前系统状态，识别问题并提供改进建议",
            data
        )
    
    def status(self) -> Dict[str, Any]:
        """Hermes状态"""
        result = self.executor.run(["status"])
        return {
            "success": result["success"],
            "info": result.get("stdout", "").strip() or result.get("stderr", "").strip()
        }
    
    def get_info(self) -> Dict[str, Any]:
        """获取Hermes版本和配置信息"""
        result = self.executor.run(["--version"])
        return {
            "version": result.get("stdout", "").strip(),
            "available": result["success"]
        }


# ======================== 系统数据采集 ========================

def collect_system_data() -> Dict[str, Any]:
    """采集系统状态数据供Hermes分析"""
    import shutil
    
    data = {}
    
    # CPU
    try:
        with open('/proc/loadavg') as f:
            parts = f.read().strip().split()
            data["cpu"] = {
                "load_1m": float(parts[0]),
                "load_5m": float(parts[1]),
                "load_15m": float(parts[2]),
                "process_running": parts[3].split('/')[0],
                "process_total": parts[3].split('/')[1]
            }
    except:
        data["cpu"] = "unavailable"
    
    # Memory
    try:
        with open('/proc/meminfo') as f:
            mem = {}
            for line in f:
                if 'MemTotal' in line:
                    mem["total_kb"] = int(line.split()[1])
                elif 'MemAvailable' in line:
                    mem["available_kb"] = int(line.split()[1])
                elif 'MemFree' in line:
                    mem["free_kb"] = int(line.split()[1])
            if "total_kb" in mem and "available_kb" in mem:
                total_mb = mem["total_kb"] / 1024
                avail_mb = mem["available_kb"] / 1024
                used_mb = total_mb - avail_mb
                mem["total_mb"] = round(total_mb, 1)
                mem["available_mb"] = round(avail_mb, 1)
                mem["used_mb"] = round(used_mb, 1)
                mem["usage_pct"] = round(used_mb / total_mb * 100, 1)
            data["memory"] = mem
    except:
        data["memory"] = "unavailable"
    
    # Disk
    try:
        total, used, free = shutil.disk_usage("/")
        data["disk"] = {
            "total_gb": round(total / (1024**3), 1),
            "used_gb": round(used / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1),
            "usage_pct": round(used / total * 100, 1)
        }
    except:
        data["disk"] = "unavailable"
    
    # Temp directory size
    try:
        temp_dir = BASE_DIR / "temp"
        total_size = sum(f.stat().st_size for f in temp_dir.rglob('*') if f.is_file())
        data["temp_size_mb"] = round(total_size / (1024**2), 1)
    except:
        data["temp_size_mb"] = "unavailable"
    
    # Process count
    try:
        proc_count = len([d for d in Path('/proc').iterdir() if d.name.isdigit()])
        data["process_count"] = proc_count
    except:
        data["process_count"] = "unavailable"
    
    # Uptime
    try:
        with open('/proc/uptime') as f:
            uptime_seconds = float(f.read().split()[0])
            data["uptime_hours"] = round(uptime_seconds / 3600, 1)
    except:
        data["uptime_hours"] = "unavailable"
    
    data["timestamp"] = datetime.now().isoformat()
    data["hostname"] = os.uname().nodename
    
    return data


# ======================== CLI ========================

def main():
    parser = argparse.ArgumentParser(
        description="Hermes Bridge V2 — GA↔Hermes深度集成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python3 scripts/hermes_bridge.py chat "Hello"
  python3 scripts/hermes_bridge.py reason "分析系统瓶颈" 
  python3 scripts/hermes_bridge.py analyze    # 验收标准场景
  python3 scripts/hermes_bridge.py status
  python3 scripts/hermes_bridge.py sessions list
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="子命令")
    
    # chat
    chat_p = subparsers.add_parser("chat", help="基础聊天")
    chat_p.add_argument("query", help="问题")
    chat_p.add_argument("-s", "--session", help="Session ID")
    chat_p.add_argument("-m", "--model", help="模型")
    chat_p.add_argument("--json", action="store_true", help="JSON输出")
    
    # reason (CoT)
    reason_p = subparsers.add_parser("reason", help="Chain-of-Thought推理")
    reason_p.add_argument("task", help="复杂任务描述")
    reason_p.add_argument("--max-steps", type=int, default=5, help="最大子步骤数")
    
    # analyze (验收标准场景)
    analyze_p = subparsers.add_parser("analyze", help="分析系统状态并给出建议（验收标准）")
    analyze_p.add_argument("--json", action="store_true", help="JSON输出")
    
    # query
    query_p = subparsers.add_parser("query", help="结构化查询")
    query_p.add_argument("query", help="查询内容")
    
    # sessions
    sessions_p = subparsers.add_parser("sessions", help="Session管理")
    sessions_p.add_argument("action", choices=["list", "latest", "archive", "delete"], nargs="?",
                           default="list")
    sessions_p.add_argument("--id", help="Session ID")
    sessions_p.add_argument("--source", help="筛选来源 (cli/cron)")
    
    # status
    subparsers.add_parser("status", help="Hermes状态")
    
    # info
    subparsers.add_parser("info", help="Hermes版本信息")
    
    args = parser.parse_args()
    
    bridge = HermesBridge()
    
    if args.command == "chat":
        result = bridge.chat(args.query, args.session, args.model, args.json)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(result["response"])
    
    elif args.command == "reason":
        print(f"🧠 CoT推理: {args.task}")
        print(f"   最大步骤: {args.max_steps}")
        print()
        result = bridge.reason(args.task, max_steps=args.max_steps)
        
        if result.get("success"):
            print(f"✅ 推理完成 ({result.get('num_steps', 0)}步, {result.get('duration', 0):.1f}s)")
            print()
            
            # 显示分解
            decomp = result.get("decomposition", {})
            if decomp.get("sub_tasks"):
                print("📋 任务分解:")
                for i, st in enumerate(decomp["sub_tasks"]):
                    print(f"  {i+1}. {st}")
                print()
            
            # 显示综合结果
            synthesis = result.get("synthesis", "")
            if synthesis:
                print("📊 综合分析:")
                print(synthesis)
                print()
        else:
            print(f"❌ 推理失败: {result.get('error', 'unknown')}")
    
    elif args.command == "analyze":
        print("🔍 采集系统数据...")
        data = collect_system_data()
        
        print(f"   CPU负载: {data.get('cpu', {}).get('load_1m', '?')}/1m")
        print(f"   内存使用: {data.get('memory', {}).get('usage_pct', '?')}%")
        print(f"   磁盘使用: {data.get('disk', {}).get('usage_pct', '?')}%")
        print(f"   运行进程: {data.get('process_count', '?')}")
        print()
        
        print("🧠 请求Hermes分析...")
        result = bridge.analyze_system(data)
        
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"✅ 分析完成")
            if result.get("parsed"):
                p = result["parsed"]
                print(f"\n📊 风险等级: {p.get('risk_level', 'N/A')} | 置信度: {p.get('confidence', 'N/A')}")
                print(f"\n📝 分析: {p.get('analysis', 'N/A')[:500]}")
                print(f"\n🔍 发现:")
                for f in p.get("findings", []):
                    print(f"  • {f}")
                print(f"\n💡 建议:")
                for r in p.get("recommendations", []):
                    print(f"  • {r}")
            else:
                print(f"\n原始响应:\n{result.get('raw_response', 'N/A')[:1000]}")
    
    elif args.command == "query":
        schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "confidence": {"type": "number"},
                "sources": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["answer", "confidence"]
        }
        result = StructuredQuery.ask(bridge.executor, args.query, schema)
        if result.get("parsed"):
            print(json.dumps(result["parsed"], indent=2, ensure_ascii=False))
        else:
            print(result.get("raw_response", "No response"))
    
    elif args.command == "sessions":
        if args.action == "list":
            sessions = bridge.sessions.list(refresh=True)
            if sessions:
                print(f"{'Session ID':<30} {'Preview':<40} {'Last Active':<20} {'Source':<10}")
                print("-" * 100)
                for s in sessions:
                    print(f"{s.get('id', '?'):<30} {s.get('preview', '?'):<40} {s.get('last_active', '?'):<20} {s.get('source', '?'):<10}")
            else:
                print("无活动session")
        elif args.action == "latest":
            sid = bridge.sessions.get_latest(args.source)
            print(sid or "无活动session")
        elif args.action == "archive":
            if args.id:
                ok = bridge.sessions.archive(args.id)
                print(f"✅ 已归档 {args.id}" if ok else f"❌ 归档失败")
            else:
                print("请指定 --id")
        elif args.action == "delete":
            if args.id:
                ok = bridge.sessions.delete(args.id)
                print(f"✅ 已删除 {args.id}" if ok else f"❌ 删除失败")
            else:
                print("请指定 --id")
    
    elif args.command == "status":
        result = bridge.status()
        print(result.get("info", "Hermes状态不可用"))
    
    elif args.command == "info":
        result = bridge.get_info()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
