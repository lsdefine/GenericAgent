#!/usr/bin/env python3
"""
procmem_scanner — Linux /proc 内存特征扫描工具

遵守 procmem_scanner_sop.md:
  - 支持 string / hex (CE风格, 含 ?? 通配符) 匹配
  - LLM 模式输出完整上下文 (前后32B hex+ASCII)
  - Python API: scan_memory(pid, pattern, mode='string', llm_mode=False)
  - CLI: python memory/procmem_scanner.py <PID> <pattern> [--mode hex|string] [--llm]

依赖: 无 (纯 Python 3, 仅使用标准库)
"""

import os
import sys
import json
import argparse
import struct
from pathlib import Path


# ── Hex 模式编译 ──────────────────────────────────────────────────

def _compile_hex(pattern_str: str):
    """
    将 CE 风格 hex (如 "48 8b ?? ?? 00") 编译为搜索模式。
    返回 (pattern_bytes, mask_bytes), 其中 mask 中 0 表示通配 (任意字节)。
    """
    # 移除空格, 分割
    tokens = pattern_str.strip().split()
    pattern = bytearray()
    mask = bytearray()
    for t in tokens:
        if t == '??' or t == '?':
            pattern.append(0)
            mask.append(0)  # wildcard
        else:
            pattern.append(int(t, 16))
            mask.append(1)  # fixed
    return bytes(pattern), bytes(mask)


def _match_at(data: bytes, pos: int, pattern: bytes, mask: bytes) -> bool:
    """检查 data[pos] 是否匹配 pattern (mask=0 表示任意字节)"""
    for i in range(len(pattern)):
        if mask[i]:
            if data[pos + i] != pattern[i]:
                return False
    return True


def _search_hex(data: bytes, pattern: bytes, mask: bytes) -> list:
    """在 data 中搜索 hex pattern, 返回偏移列表"""
    if not pattern:
        return []
    plen = len(pattern)
    results = []
    end = len(data) - plen + 1
    pos = 0
    while pos < end:
        if _match_at(data, pos, pattern, mask):
            results.append(pos)
            pos += 1  # 允许重叠匹配
        else:
            pos += 1
    return results


def _search_string(data: bytes, pattern_str: str) -> list:
    """在 data 中搜索字符串, 返回偏移列表"""
    pattern = pattern_str.encode('utf-8', errors='replace')
    if not pattern:
        return []
    results = []
    pos = 0
    while True:
        pos = data.find(pattern, pos)
        if pos == -1:
            break
        results.append(pos)
        pos += 1
    return results


# ── /proc 内存读取 ──────────────────────────────────────────────

def _get_memory_regions(pid: int) -> list:
    """
    解析 /proc/<pid>/maps, 返回可读内存区域列表。
    每项: (start_addr, end_addr, perms, pathname)
    """
    regions = []
    maps_path = f"/proc/{pid}/maps"
    try:
        with open(maps_path, 'r') as f:
            for line in f:
                parts = line.strip().split(None, 4)
                if len(parts) < 2:
                    continue
                addr_range = parts[0].split('-')
                if len(addr_range) != 2:
                    continue
                try:
                    start = int(addr_range[0], 16)
                    end = int(addr_range[1], 16)
                except ValueError:
                    continue
                perms = parts[1]
                pathname = parts[-1] if len(parts) > 4 else ''
                # 只扫描可读区域
                if 'r' in perms:
                    regions.append((start, end, perms, pathname))
    except FileNotFoundError:
        raise ValueError(f"PID {pid} 不存在")
    except PermissionError:
        raise PermissionError(f"无权限访问 PID {pid} 的 maps")
    return regions


def _read_process_mem(pid: int, start: int, size: int) -> bytes:
    """从 /proc/<pid>/mem 读取指定范围"""
    mem_path = f"/proc/{pid}/mem"
    try:
        with open(mem_path, 'rb') as f:
            f.seek(start)
            return f.read(size)
    except (OSError, PermissionError, IOError) as e:
        # 某些区域虽在 maps 中列出但实际不可读, 跳过
        return b''


def _format_hex_dump(data: bytes, max_bytes=32) -> str:
    """格式化 hex dump: hex + ASCII 预览"""
    hex_part = ' '.join(f'{b:02x}' for b in data[:max_bytes])
    ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[:max_bytes])
    return f"{hex_part}  |{ascii_part}|"


def _format_context(data: bytes, offset: int, context_bytes=32) -> dict:
    """提取匹配位置周围的上下文"""
    total = len(data)
    before_start = max(0, offset - context_bytes)
    after_end = min(total, offset + context_bytes)
    
    before = data[before_start:offset]
    after = data[offset:after_end]
    
    return {
        "before_hex": _format_hex_dump(before),
        "after_hex": _format_hex_dump(after),
        "before_offset": before_start,
        "after_offset": offset,
    }


# ── 主 API ────────────────────────────────────────────────────────

def scan_memory(pid: int, pattern: str, mode: str = 'string',
                llm_mode: bool = False,
                max_regions: int = 50,
                max_total_mb: int = 256) -> dict:
    """
    在目标进程内存中搜索指定特征。

    参数:
        pid: 目标进程 PID
        pattern: 搜索模式 (字符串 or CE风格 hex, 如 "48 8b ?? ?? 00")
        mode: 'string' | 'hex' | 'auto' (auto: 若包含空格和hex字符则自动选hex)
        llm_mode: 若 True, 返回包含上下文的详细结果
        max_regions: 最多扫描的内存区域数 (默认 50, 防扫描过大进程)
        max_total_mb: 最多读取的总 MB 数 (默认 256, 防内存爆炸)

    返回:
        {
            "pid": int,
            "pattern": str,
            "mode": str,
            "matches": int,
            "results": [...],
            "error": str | None
        }
    """
    # 自动检测模式
    if mode == 'auto':
        if ' ' in pattern.strip() and all(
            c in '0123456789abcdefABCDEF? \t' for c in pattern.strip()
        ):
            mode = 'hex'
        else:
            mode = 'string'

    result = {
        "pid": pid,
        "pattern": pattern,
        "mode": mode,
        "matches": 0,
        "results": [],
        "error": None,
    }

    try:
        # 编译 pattern
        if mode == 'hex':
            pattern_bytes, mask = _compile_hex(pattern)
            search_fn = lambda data: _search_hex(data, pattern_bytes, mask)
        else:
            pattern_bytes = pattern.encode('utf-8', errors='replace')
            mask = None
            search_fn = lambda data: _search_string(data, pattern)

        if not pattern_bytes:
            result["error"] = "空 pattern"
            return result

        # 获取内存区域
        regions = _get_memory_regions(pid)
        if not regions:
            result["error"] = f"PID {pid} 无可用可读内存区域"
            return result

        total_match_count = 0
        total_bytes_read = 0
        max_total_bytes = max_total_mb * 1024 * 1024
        region_count = 0

        for start, end, perms, pathname in regions:
            if region_count >= max_regions:
                result["truncated_reason"] = f"max_regions({max_regions})"
                break
            region_count += 1

            size = end - start
            if size <= 0:
                continue

            # 跳过过大的区域以控制耗时
            if size > 10 * 1024 * 1024:  # 10MB per region max
                continue

            # 累计读入上限
            if total_bytes_read + size > max_total_bytes:
                size = max_total_bytes - total_bytes_read
                if size <= 0:
                    result["truncated_reason"] = f"max_total_mb({max_total_mb})"
                    break

            data = _read_process_mem(pid, start, size)
            if not data:
                continue

            total_bytes_read += len(data)

            offsets = search_fn(data)
            if not offsets:
                continue

            for offset in offsets:
                entry = {
                    "address": hex(start + offset),
                    "region": perms,
                    "pathname": pathname,
                    "offset_in_region": offset,
                }
                if llm_mode:
                    entry["context"] = _format_context(data, offset)
                result["results"].append(entry)
                total_match_count += 1

        result["matches"] = total_match_count

    except ValueError as e:
        result["error"] = str(e)
    except PermissionError as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = f"未知错误: {e}"

    return result


# ── CLI ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="procmem_scanner — Linux 进程内存特征扫描",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s 1234 "secret_key" --mode string
  %(prog)s 1234 "48 8b ?? ?? 00" --mode hex --llm
  %(prog)s 1234 "hello" --llm
        """,
    )
    parser.add_argument("pid", type=int, help="目标进程 PID")
    parser.add_argument("pattern", type=str, help="搜索模式 (string 或 CE风格 hex)")
    parser.add_argument("--mode", choices=['string', 'hex', 'auto'], default='auto',
                        help="匹配模式 (默认: auto 自动检测)")
    parser.add_argument("--llm", action="store_true",
                        help="LLM 增强模式, 输出包含上下文的 JSON")
    parser.add_argument("--max-rows", type=int, default=50,
                        help="LLM 模式下最多输出行数 (默认 50, -1 表示全部)")

    args = parser.parse_args()

    res = scan_memory(args.pid, args.pattern, mode=args.mode, llm_mode=args.llm)

    if args.llm:
        # 截断结果行数
        if args.max_rows != -1 and len(res["results"]) > args.max_rows:
            res["results"] = res["results"][:args.max_rows]
            res["truncated"] = True
            res["total_matches"] = res.pop("matches")
            res["matches"] = len(res["results"])
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        if res["error"]:
            print(f"❌ 错误: {res['error']}", file=sys.stderr)
            sys.exit(1)
        print(f"PID {res['pid']}: 搜索 '{res['pattern']}' ({res['mode']}) → {res['matches']} 处匹配")
        for r in res["results"][:20]:
            ctx = r.get("context", {})
            if ctx:
                print(f"  {r['address']} [{r['region']}] {r['pathname']}")
                print(f"    before: {ctx['before_hex']}")
                print(f"    after:  {ctx['after_hex']}")
            else:
                print(f"  {r['address']} [{r['region']}] {r['pathname']}")
        if res["matches"] > 20:
            print(f"  ... 还有 {res['matches'] - 20} 处结果 (使用 --llm 查看更多)")


if __name__ == '__main__':
    main()
