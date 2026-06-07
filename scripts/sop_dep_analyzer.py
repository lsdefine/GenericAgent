#!/usr/bin/env python3
"""
SOP依赖分析工具 v1.0
用途: 扫描memory/目录下所有SOP，分析跨文件引用，检测孤岛SOP
用法: python3 scripts/sop_dep_analyzer.py [--output FILE] [--threshold N]
"""

import os
import re
import sys
import json
from collections import defaultdict
from datetime import datetime

# 孤儿工具整合: 使用sop_recommender进行交叉推荐
try:
    from scripts.sop_recommender import SOP_KNOWLEDGE
    _has_recommender = True
except ImportError:
    _has_recommender = False

MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory")
# 引用模式: 匹配 sop文件名 或 _sop 或 .md/.py 文件引用
REF_PATTERNS = [
    re.compile(r'(\w+_sop)\b', re.I),
    re.compile(r'["\'](\w+_sop\.md)["\']'),
    re.compile(r'[`](\w+_sop)'),
    re.compile(r'see\s+(\w+_sop)', re.I),
]


def scan_sops(memory_dir: str) -> dict:
    """扫描memory/下的所有SOP文件"""
    sops = {}
    if not os.path.isdir(memory_dir):
        print(f"❌ 目录不存在: {memory_dir}")
        sys.exit(1)
    
    for fname in sorted(os.listdir(memory_dir)):
        fpath = os.path.join(memory_dir, fname)
        if not os.path.isfile(fpath):
            continue
        # 只处理 .md .txt .py
        if not any(fname.endswith(ext) for ext in ['.md', '.txt', '.py']):
            continue
        # 读取内容
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            sops[fname] = {
                'path': fpath,
                'size': len(content),
                'lines': content.count('\n') + 1,
                'content': content,
                'refs': [],  # 引用(出链)
                'refed_by': [],  # 被引用(入链)
            }
        except Exception as e:
            print(f"⚠  读取失败 {fname}: {e}")
    
    return sops


def extract_refs(sops: dict) -> dict:
    """提取所有SOP间的交叉引用"""
    # 所有已知SOP文件名（去扩展名）
    known_sop_names = set()
    for fname in sops:
        name_no_ext = os.path.splitext(fname)[0]
        known_sop_names.add(name_no_ext)
        known_sop_names.add(fname)
    
    for fname, info in sops.items():
        found = set()
        content = info['content']
        
        # 模式1: 直接匹配已知SOP名
        for sop_name in known_sop_names:
            if sop_name == os.path.splitext(fname)[0]:
                continue  # 不自引用
            if sop_name in content:
                found.add(sop_name)
        
        # 模式2: 正则匹配 _sop 模式
        for pattern in REF_PATTERNS:
            for m in pattern.finditer(content):
                ref = m.group(1).lower()
                # 清理后缀
                ref = ref.replace('.md', '').replace('.py', '').replace('.txt', '')
                if ref != os.path.splitext(fname)[0].lower() and '_sop' in ref:
                    found.add(ref)
        
        # 过滤：只保留在已知SOP列表中的
        valid_refs = set()
        for ref in found:
            for known in known_sop_names:
                if ref == known.lower() or ref == known or ref + '.md' == known or ref == os.path.splitext(known)[0].lower():
                    valid_refs.add(known)
                    break
        
        info['refs'] = sorted(valid_refs)
        for ref in valid_refs:
            if ref in sops and ref != fname:
                sops[ref]['refed_by'].append(fname)
    
    return sops


def analyze(sops: dict) -> dict:
    """分析依赖图"""
    # 统计引用关系
    all_files = list(sops.keys())
    orphaned = []
    hubs = []
    
    for fname, info in sops.items():
        in_degree = len(info['refed_by'])
        out_degree = len(info['refs'])
        
        # 孤岛: 没人引用 + 引用别人少(<=1)
        if in_degree == 0:
            orphaned.append(fname)
        
        # Hub: 被引用多的核心SOP
        if in_degree >= 3:
            hubs.append((fname, in_degree))
    
    return {
        'total': len(sops),
        'orphaned': sorted(orphaned),
        'hubs': sorted(hubs, key=lambda x: -x[1]),
        'all_files': all_files,
    }


def generate_report(sops: dict, stats: dict) -> str:
    """生成可读报告"""
    lines = []
    lines.append("# SOP 依赖分析报告")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**SOP总数**: {stats['total']}")
    lines.append("")
    
    # 核心SOP (hubs)
    lines.append("---")
    lines.append("## 📌 核心SOP (被引用≥3次)")
    lines.append("")
    lines.append("| SOP | 被引用 | 引用其他 | 大小 |")
    lines.append("|-----|--------|---------|------|")
    for hub, degree in stats['hubs']:
        info = sops.get(hub, {})
        out_deg = len(info.get('refs', []))
        size_kb = info.get('size', 0) / 1024
        lines.append(f"| {hub} | {degree} | {out_deg} | {size_kb:.1f}KB |")
    lines.append("")
    
    # 孤岛SOP
    lines.append("---")
    lines.append("## 🏝️ 孤岛SOP (无入链引用)")
    lines.append("")
    if stats['orphaned']:
        for fname in stats['orphaned']:
            info = sops.get(fname, {})
            out_refs = info.get('refs', [])
            out_str = ', '.join(out_refs) if out_refs else '(无)'
            lines.append(f"- **{fname}** → 引用: {out_str}")
        lines.append("")
        lines.append(f"共 {len(stats['orphaned'])} 个孤岛SOP ({len(stats['orphaned'])/stats['total']*100:.1f}%)")
    else:
        lines.append("🎉 无孤岛SOP")
    lines.append("")
    
    # 完整依赖图
    lines.append("---")
    lines.append("## 🔗 完整引用关系")
    lines.append("")
    for fname in sorted(sops.keys()):
        info = sops[fname]
        refs = info.get('refs', [])
        refed = info.get('refed_by', [])
        if not refs and not refed:
            continue
        parts = []
        if refs:
            parts.append(f"→ 引用: {', '.join(refs)}")
        if refed:
            parts.append(f"← 被引用: {', '.join(refed)}")
        lines.append(f"- **{fname}**: {'; '.join(parts)}")
    
    return '\n'.join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='SOP依赖分析工具')
    parser.add_argument('--output', '-o', type=str, help='输出报告路径')
    parser.add_argument('--format', choices=['text', 'json'], default='text',
                        help='输出格式')
    args = parser.parse_args()
    
    print(f"🔍 扫描 {MEMORY_DIR}...")
    sops = scan_sops(MEMORY_DIR)
    print(f"📄 发现 {len(sops)} 个文件")
    
    sops = extract_refs(sops)
    stats = analyze(sops)
    
    print(f"\n📊 统计:")
    print(f"  核心SOP (被引用≥3): {len(stats['hubs'])}")
    print(f"  孤岛SOP (无入链): {len(stats['orphaned'])}")
    if stats['orphaned']:
        for f in stats['orphaned'][:10]:
            print(f"    🏝️ {f}")
        if len(stats['orphaned']) > 10:
            print(f"    ... 还有 {len(stats['orphaned'])-10} 个")
    
    report = generate_report(sops, stats)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"✅ 报告已保存: {args.output}")
    else:
        print("\n" + report)
    
    if args.format == 'json':
        json_output = {
            'timestamp': datetime.now().isoformat(),
            'total': stats['total'],
            'orphaned': stats['orphaned'],
            'hubs': [{'name': h, 'in_degree': d} for h, d in stats['hubs']],
        }
        if args.output:
            json_path = args.output.replace('.md', '.json')
            with open(json_path, 'w') as f:
                json.dump(json_output, f, indent=2, ensure_ascii=False)
            print(f"✅ JSON已保存: {json_path}")
        else:
            print(json.dumps(json_output, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
