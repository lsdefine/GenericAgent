#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GA搜索引擎自动验证器 (search_verification.py)
用途: 在每次部署/更新后运行，防止SOP与实际实现脱节

用法: python scripts/search_verification.py [--verbose] [--json] [--fail-on-warn]
"""

import os
import sys
import json
import argparse
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional
sys.stdout.reconfigure(encoding='utf-8')

# ============================================================
# 配置: 所有声称可用的搜索引擎
# ============================================================
SEARCH_TOOLS = {
    "baidu": {
        "description": "百度千帆中文搜索",
        "api_key_env": "BAIDU_API_KEY",
        "script_path": r"C:\Users\Administrator\.agents\skills\baidu-search\scripts\search.py",
        "skill_md_path": r"C:\Users\Administrator\.agents\skills\baidu-search\SKILL.md",
        "priority": "P0 - Chinese default",
        "call_format": "json",  # 需要JSON参数: '{"query": "...", "count": 3}'
    },
    "tavily": {
        "description": "Tavily英文/AI搜索",
        "api_key_env": "TAVILY_API_KEY",
        "script_path": r"C:\Users\Administrator\.agents\skills\tavily-search\scripts\search.py",
        "skill_md_path": r"C:\Users\Administrator\.agents\skills\tavily-search\SKILL.md",
        "priority": "P0 - English default",
        "call_format": "text_or_json",  # 纯文本查询或JSON: '{"query": "..."}'
    },
    "brave": {
        "description": "Brave全球Web搜索",
        "api_key_env": "BRAVE_SEARCH_API_KEY",
        "script_path": r"C:\Users\Administrator\.agents\skills\brave-search\scripts\search.py",
        "skill_md_path": r"C:\Users\Administrator\.agents\skills\brave-search\SKILL.md",
        "priority": "P1 - English fallback",
    },
    "serper": {
        "description": "Serper Google搜索结果",
        "api_key_env": "SERPER_API_KEY",
        "script_path": r"C:\Users\Administrator\.agents\skills\serper-search\scripts\search.py",
        "skill_md_path": r"C:\Users\Administrator\.agents\skills\serper-search\SKILL.md",
        "priority": "P1 - Google fallback",
    },
    "exa": {
        "description": "Exa语义搜索",
        "api_key_env": "EXA_API_KEY",
        "script_path": r"C:\Users\Administrator\.agents\skills\exa-search\scripts\search.py",
        "skill_md_path": r"C:\Users\Administrator\.agents\skills\exa-search\SKILL.md",
        "priority": "P2 - Semantic mining",
    },
    "jina": {
        "description": "Jina Reader全文提取",
        "api_key_env": "JINA_API_KEY",
        "script_path": r"C:\Users\Administrator\.agents\skills\jina-reader\scripts\reader.py",
        "skill_md_path": r"C:\Users\Administrator\.agents\skills\jina-reader\SKILL.md",
        "priority": "P2 - Full text extraction",
    },
}

# ============================================================
# 结果数据结构
# ============================================================
@dataclass
class ToolStatus:
    """单个搜索引擎的状态信息"""
    name: str
    description: str
    priority: str
    
    script_exists: bool = False
    api_key_configured: bool = False
    skill_md_exists: bool = False
    quick_test_passed: bool = False
    
    overall_status: str = ""  # "verified", "configured_only", "missing", "not_implemented"
    issues: List[str] = field(default_factory=list)
    
    def to_dict(self):
        return asdict(self)

def evaluate_status(tool: ToolStatus, tool_config: dict) -> str:
    """评估搜索引擎整体状态"""
    if tool.quick_test_passed:
        return "verified"
    
    has_anything = tool.script_exists or tool.api_key_configured or tool.skill_md_exists
    
    if has_anything:
        return "partially_configured"
    else:
        return "not_implemented"

def verify_tool(name: str, config: dict, verbose: bool = False) -> ToolStatus:
    """验证单个搜索引擎的所有组件"""
    result = ToolStatus(
        name=name,
        description=config["description"],
        priority=config["priority"],
    )
    
    # 1. 检查API Key
    api_key_env = config.get("api_key_env", "")
    api_key_value = os.environ.get(api_key_env, "")
    if api_key_value and len(api_key_value.strip()) > 5:
        result.api_key_configured = True
        if verbose:
            print(f"    [OK] API Key configured ({api_key_env})")
    else:
        result.issues.append(f"API Key missing: {api_key_env}")
        if verbose:
            print(f"    [MISSING] API Key: {api_key_env}")
    
    # 2. 检查脚本文件
    script_path = config.get("script_path", "")
    if script_path and os.path.isfile(script_path):
        result.script_exists = True
        file_size = os.path.getsize(script_path)
        if verbose:
            print(f"    [OK] Script exists: {script_path} ({file_size} bytes)")
    else:
        result.issues.append(f"Script not found: {script_path}")
        if verbose:
            print(f"    [MISSING] Script: {script_path}")
    
    # 3. 检查SKILL.md
    skill_md = config.get("skill_md_path", "")
    if skill_md and os.path.isfile(skill_md):
        result.skill_md_exists = True
        if verbose:
            print(f"    [OK] SKILL.md exists: {skill_md}")
    else:
        result.issues.append(f"SKILL.md not found: {skill_md}")
        if verbose:
            print(f"    [MISSING] SKILL.md: {skill_md}")
    
    # 4. 快速功能测试 (仅对Baidu和Tavily做真实测试)
    if name == "baidu" and result.api_key_configured and result.script_exists:
        try:
            import subprocess
            import json
            # Baidu需要JSON参数格式
            test_query = json.dumps({"query": "test", "count": 1}, ensure_ascii=False)
            proc = subprocess.run([
                sys.executable, script_path, test_query
            ], capture_output=True, text=True, timeout=15)
            result.quick_test_passed = proc.returncode == 0
            if verbose:
                print(f"    [{'OK' if result.quick_test_passed else 'FAIL'}] Quick test: {'passed' if result.quick_test_passed else 'failed'}")
            if not result.quick_test_passed and verbose:
                print(f"    [DEBUG] stdout: {proc.stdout[:200]}")
                print(f"    [DEBUG] stderr: {proc.stderr[:200]}")
        except Exception as e:
            if verbose:
                print(f"    [ERROR] Quick test failed: {e}")
    
    elif name == "tavily" and result.api_key_configured and result.script_exists:
        try:
            import subprocess
            # Tavily接受纯文本查询(第一个参数即query)
            proc = subprocess.run([
                sys.executable, script_path, "test query", "--results", "1"
            ], capture_output=True, text=True, timeout=15)
            result.quick_test_passed = proc.returncode == 0
            if verbose:
                print(f"    [{'OK' if result.quick_test_passed else 'FAIL'}] Quick test: {'passed' if result.quick_test_passed else 'failed'}")
            if not result.quick_test_passed and verbose:
                print(f"    [DEBUG] stdout: {proc.stdout[:200]}")
                print(f"    [DEBUG] stderr: {proc.stderr[:200]}")
        except Exception as e:
            if verbose:
                print(f"    [ERROR] Quick test failed: {e}")
    
    # 5. 整体状态评估
    result.overall_status = evaluate_status(result, config)
    
    return result

# ============================================================
# 主函数
# ============================================================
def run_verification(verbose: bool = False, json_output: bool = False, 
                     fail_on_warn: bool = False) -> Dict:
    """执行完整验证流程"""
    print("=" * 70)
    print("🔍 GA Search Tools Verification")
    print(f"📅 Date: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    results = {}
    status_counts = {
        "verified": 0,
        "partially_configured": 0,
        "not_implemented": 0,
    }
    
    for name, config in SEARCH_TOOLS.items():
        if verbose:
            print(f"\n[{name.upper()}] Testing...")
        
        result = verify_tool(name, config, verbose=verbose)
        results[name] = result
        
        status_counts[result.overall_status] = status_counts.get(result.overall_status, 0) + 1
        
        # 打印一行摘要
        emoji_map = {
            "verified": "✅",
            "partially_configured": "⚠️",
            "not_implemented": "❌",
        }
        emoji = emoji_map.get(result.overall_status, "?")
        print(f"{emoji:<5} {name:12s} | Status: {result.overall_status:25s} | Issues: {len(result.issues)}")
    
    # 汇总
    total = len(SEARCH_TOOLS)
    verified_count = status_counts["verified"]
    
    print("\n" + "=" * 70)
    print("📊 VERIFICATION SUMMARY")
    print("=" * 70)
    print(f"Total tools declared: {total}")
    print(f"Verified working:     {verified_count} ({verified_count/total*100:.1f}%)")
    print(f"Partially configured: {status_counts['partially_configured']}")
    print(f"Not implemented:      {status_counts['not_implemented']}")
    
    if verified_count < total * 0.5:
        print("\n⚠️  WARNING: Less than 50% of declared tools are verified!")
    
    # JSON输出
    if json_output:
        json_results = {k: v.to_dict() for k, v in results.items()}
        json_results["summary"] = {
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "total": total,
            "verified_count": verified_count,
            "status_counts": status_counts,
            "pass_rate": f"{verified_count/total*100:.1f}%",
        }
        print("\n--- JSON Output ---")
        print(json.dumps(json_results, indent=2, ensure_ascii=False))
    
    # 返回是否通过
    pass_threshold = 0.5 if not fail_on_warn else 1.0
    passed = verified_count >= total * pass_threshold
    
    if not passed:
        print(f"\n🚨 VERIFICATION FAILED: Pass rate {verified_count/total*100:.1f}% below threshold {pass_threshold*100:.0f}%")
    else:
        print(f"\n✅ VERIFICATION PASSED: Pass rate {verified_count/total*100:.1f}% meets threshold {pass_threshold*100:.0f}%")
    
    return {"passed": passed, "results": results, "summary": {
        "total": total,
        "verified_count": verified_count,
        "status_counts": status_counts,
        "pass_rate": f"{verified_count/total*100:.1f}%",
    }}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GA Search Tools Verification")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    parser.add_argument("--strict", action="store_true", help="Fail unless ALL tools work")
    args = parser.parse_args()
    
    result = run_verification(
        verbose=args.verbose,
        json_output=args.json,
        fail_on_warn=args.strict,
    )
    
    sys.exit(0 if result["passed"] else 1)
