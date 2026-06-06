#!/usr/bin/env python3
"""
sop_graph.py — SOP关系图谱生成器 (Graphviz集成)
依赖: graphviz (dot CLI)
用法:
  python scripts/sop_graph.py [--format png|svg|pdf|dot] [--output PATH]
"""

import os, re, sys, subprocess, argparse

def find_sops(memory_dir="memory"):
    """扫描memory目录，返回SOP文件列表"""
    sops = {}
    if not os.path.isdir(memory_dir):
        memory_dir = os.path.join(os.path.dirname(__file__), "..", memory_dir)
    if not os.path.isdir(memory_dir):
        memory_dir = os.path.join(os.path.dirname(__file__), "..", "..", memory_dir)
    
    for fname in os.listdir(memory_dir):
        if fname.endswith(".md") and not fname.startswith("L4_"):
            path = os.path.join(memory_dir, fname)
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            sops[fname.replace('.md','')] = content
    return sops, memory_dir

def extract_relations(sops):
    """提取SOP间的引用关系"""
    edges = []
    for name, content in sops.items():
        refs = set()
        for m in re.finditer(r'([a-z_]+_sop)\b', content):
            refs.add(m.group(1))
        for m in re.finditer(r'([a-z_]+_sop\.md)', content):
            refs.add(m.group(1).replace('.md',''))
        for ref in refs:
            if ref != name and ref in sops:
                edges.append((name, ref))
    return list(set(edges))

def generate_dot(sops, edges):
    """生成DOT图描述"""
    lines = ['digraph SOPs {']
    lines.append('  rankdir=LR;')
    lines.append('  node [shape=box, style=filled, fillcolor="#E8F0FE", fontname="sans", fontsize=10];')
    lines.append('  edge [color="#666666", arrowhead=open, penwidth=1.2];')
    lines.append('')
    
    for name in sorted(sops.keys()):
        label = name.replace('_sop','').replace('_',' ').title()
        lines.append(f'  "{name}" [label="{label}"];')
    
    lines.append('')
    for src, dst in edges:
        lines.append(f'  "{src}" -> "{dst}";')
    
    lines.append('}')
    return '\n'.join(lines)

def main():
    parser = argparse.ArgumentParser(description="SOP关系图谱生成器")
    parser.add_argument('--format', '-f', choices=['png','svg','pdf','dot'], default='png',
                       help="输出格式 (默认: png)")
    parser.add_argument('--output', '-o', default=None,
                       help="输出路径 (默认: temp/sop_graph/sop_relations.<format>)")
    args = parser.parse_args()
    
    sops, mem_dir = find_sops()
    edges = extract_relations(sops)
    dot_content = generate_dot(sops, edges)
    
    # 确保输出目录
    if args.output:
        out_path = args.output
    else:
        os.makedirs("temp/sop_graph", exist_ok=True)
        out_path = f"temp/sop_graph/sop_relations.{args.format}"
    
    # 先写DOT文件
    dot_path = out_path.rsplit('.', 1)[0] + '.dot'
    with open(dot_path, 'w') as f:
        f.write(dot_content)
    
    if args.format == 'dot':
        print(f"✅ DOT file: {dot_path}")
        print(f"   {len(sops)} SOPs, {len(edges)} relations")
        return
    
    # 渲染
    try:
        result = subprocess.run(['dot', f'-T{args.format}', dot_path, '-o', out_path],
                              capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            size = os.path.getsize(out_path)
            print(f"✅ {args.format.upper()} rendered: {out_path} ({size:,} bytes)")
            print(f"   {len(sops)} SOP nodes, {len(edges)} relations")
            print(f"   来源目录: {mem_dir}")
        else:
            print(f"❌ dot error: {result.stderr}")
            sys.exit(1)
    except FileNotFoundError:
        print("❌ graphviz (dot) not installed. Install: apt install graphviz")
        sys.exit(1)

if __name__ == "__main__":
    main()
