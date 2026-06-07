#!/usr/bin/env python3
"""
dep_scanner.py — GA 代码依赖关系扫描器 🔎

扫描 GA 代码库, 提取 Python 文件间的 import 依赖关系。
支持: 全量扫描 / 增量扫描 / JSON 输出
"""

import os, sys, re, json, time
from pathlib import Path

GA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUDE_DIRS = {'.venv', '__pycache__', 'node_modules', '.git', '.idea', 'engine/metrics', 'temp', 'sche_tasks'}

def scan_python_files(root=None, fast=True):
    """返回 root 下所有 Python 文件列表"""
    root = root or GA_ROOT
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 跳过排除目录
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith('.')]
        for fn in filenames:
            if fn.endswith('.py'):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                files.append(rel)
    return sorted(files)

def parse_imports(filepath, root=None):
    """解析文件的 import 语句, 返回目标模块列表"""
    root = root or GA_ROOT
    imports = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except:
        return imports
    
    # 匹配 import X / from X import Y
    patterns = [
        r'^import\s+(\S+)',
        r'^from\s+(\S+)\s+import',
    ]
    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        for pat in patterns:
            m = re.match(pat, line)
            if m:
                mod = m.group(1).split('.')[0]  # 只取顶级模块名
                if mod not in ('os', 'sys', 're', 'json', 'time', 'math', 'random', 'pathlib',
                               'subprocess', 'shutil', 'glob', 'io', 'collections', 'typing',
                               'datetime', 'functools', 'itertools', 'abc', 'copy', 'enum',
                               'hashlib', 'textwrap', 'dataclasses', 'inspect', 'logging',
                               'asyncio', 'threading', 'multiprocessing', 'pickle', 'tempfile',
                               'atexit', 'signal', 'traceback', 'warnings', 'argparse',
                               'configparser', 'http', 'urllib', 'socket', 'ssl', 'email',
                               'base64', 'binascii', 'struct', 'csv', 'string', 'difflib',
                               'pprint', 'platform', 'stat', 'pdb', 'gc', 'ctypes',
                               # web
                               'flask', 'fastapi', 'bottle', 'aiohttp', 'django',
                               # 第三方常见
                               'requests', 'bs4', 'lxml', 'yaml', 'toml', 'markdown',
                               'pandas', 'numpy', 'PIL', 'cv2', 'selenium', 'playwright',
                               'psutil', 'redis', 'sqlalchemy', 'pymongo', 'httpx',
                               'pydantic', 'dotenv', 'rich', 'click', 'tqdm', 'schedule',
                               'dateutil', 'chardet', 'pil', 'PIL'):
                    # 尝试映射为相对路径
                    mod_path = mod.replace('.', '/') + '.py'
                    imports.append(mod_path)
    return imports

def build_graph(root=None, include_stdlib=False):
    """构建完整依赖图"""
    root = root or GA_ROOT
    py_files = scan_python_files(root)
    
    # 建立文件路径到模块名的映射
    file_set = set(py_files)
    
    nodes = []
    edges = []
    
    for rel_path in py_files:
        full_path = os.path.join(root, rel_path)
        imports = parse_imports(full_path, root)
        
        # 确定分组
        if rel_path.startswith('scripts/'):
            group = 'scripts'
        elif rel_path.startswith('engine/'):
            group = 'engine'
        elif rel_path.startswith('frontends/'):
            group = 'frontends'
        elif rel_path.startswith('ga_cli/'):
            group = 'ga_cli'
        elif rel_path.startswith('quality/'):
            group = 'quality'
        elif rel_path.startswith('memory/'):
            group = 'memory'
        else:
            group = 'root'
        
        nodes.append({
            'id': rel_path,
            'label': rel_path if len(rel_path) <= 40 else '...' + rel_path[-37:],
            'group': group
        })
        
        for imp in imports:
            # 匹配到已知文件
            if imp in file_set:
                edges.append({'from': rel_path, 'to': imp})
            # 尝试匹配 scripts/ 下的文件
            elif 'scripts/' + imp in file_set:
                edges.append({'from': rel_path, 'to': 'scripts/' + imp})
            # 去掉 .py 后缀匹配
            elif imp.endswith('.py') and imp[:-3] in file_set:
                edges.append({'from': rel_path, 'to': imp[:-3]})
    
    return {
        'nodes': nodes,
        'edges': edges,
        'stats': {
            'total_files': len(nodes),
            'total_edges': len(edges),
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
    }

def scan_incremental(root=None, cache_path=None):
    """增量扫描: 只返回变更的文件"""
    # TODO: implement file mtime tracking
    return build_graph(root)

if __name__ == '__main__':
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else 'full'
    if mode == 'full':
        graph = build_graph()
        print(json.dumps(graph, indent=2, ensure_ascii=False))
    elif mode == 'stats':
        graph = build_graph()
        s = graph['stats']
        print(f"📊 代码依赖图统计: {s['total_files']} 文件, {s['total_edges']} 依赖关系")
        print(f"   扫描时间: {s['timestamp']}")
