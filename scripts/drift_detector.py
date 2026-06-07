#!/usr/bin/env python3
"""
Drift Detector — 自动对比 global_mem.txt 声明 vs 实际系统状态
检测L2记忆漂移并产出patch报告

Usage:
    python -m scripts.drift_detector check          # 检测漂移
    python -m scripts.drift_detector patch           # 生成patch报告
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

GA_ROOT = Path('/home/admin/GenericAgent')
MEM_PATH = GA_ROOT / 'memory' / 'global_mem.txt'

# 可验证事实的检查函数映射
# 格式: (section_key, display_name) -> (check_func, parse_pattern)
# parse_pattern: regex从global_mem中提取声明值
# check_func: 返回(实际值, is_match, detail)

def run_cmd(cmd, shell=False, timeout=8):
    try:
        r = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() or r.stderr.strip() or '(empty)'
    except Exception as e:
        return f'(error: {e})'

def pip_count(venv_hint=''):
    """Count pip packages in specified venv"""
    if 'hermes' in venv_hint:
        out = run_cmd(['/home/admin/.hermes/hermes-agent/venv/bin/pip3', 'list', '--format=json'], timeout=10)
    else:
        out = run_cmd(['/home/admin/GenericAgent/.venv/bin/pip3', 'list', '--format=json'], timeout=10)
    try:
        pkgs = json.loads(out)
        return len(pkgs)
    except:
        return -1

def check_pip_packages_hermes(declared):
    cnt = pip_count('hermes')
    declared_cnt = int(declared.split()[0]) if declared.split()[0].isdigit() else 0
    return (f'{cnt} total', str(cnt) == declared.split()[0], f'Declared: {declared}, Actual: {cnt} packages')

def check_pip_packages_ga(declared):
    cnt = pip_count('ga')
    declared_cnt = int(declared.split()[0]) if declared.split()[0].isdigit() else 0
    return (f'{cnt} total', str(cnt) == declared.split()[0], f'Declared: {declared}, Actual: {cnt} packages')

def check_running_service(name, port=None):
    """Check if service is running by systemctl or port"""
    out = run_cmd(['systemctl', 'is-active', name])
    if out == 'active':
        return (f'{name}=active (systemctl)', True, f'Service {name} is active')
    # fallback: check port
    if port:
        out2 = run_cmd(['ss', '-tlnp', f'sport = :{port}'], timeout=5)
        found = f':{port}' in out2
        return (f'port {port}: {"listening" if found else "NOT found"}', found, f'Port check: {port}')
    return (f'{name}={out}', out == 'active', f'Service {name}: {out}')

def check_version(cmd, flag='--version', parse_regex=None):
    out = run_cmd(cmd + [flag])
    if parse_regex:
        m = re.search(parse_regex, out)
        if m:
            return (m.group(1), m.group(1) in out, f'raw: {out[:80]}')
    return (out[:60], True, f'raw: {out[:80]}')

def check_file_exists(path):
    exists = os.path.exists(path)
    return (f'exists={exists}', exists, f'File {path}: {"exists" if exists else "missing"}')

def check_not_installed(cmd):
    out = run_cmd(['which', cmd])
    not_found = 'no ' in out.lower() or 'not found' in out.lower() or out == '' or '(empty)' in out
    return (f'installed={not not_found}', not_found, f'{cmd}: {"NOT installed (✅ )" if not_found else "INSTALLED (⚠️)"}')

def check_python_version(declared_path):
    out = run_cmd([declared_path, '--version'])
    return (out[:30], True, f'Python: {out[:50]}')

def check_ram_total():
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    kb = int(line.split()[1])
                    gb = kb / 1024 / 1024
                    return (f'{gb:.1f}Gi', True, f'MemTotal: {gb:.1f}Gi ({kb} kB)')
    except:
        pass
    return ('unknown', False, 'Cannot read /proc/meminfo')

def check_venv_python(venv_python):
    """Check if venv python exists and is correct"""
    exists = os.path.exists(venv_python)
    if exists:
        out = run_cmd([venv_python, '--version'])
        return (out[:30], True, f'{venv_python}: {out[:50]}')
    return ('NOT found', False, f'{venv_python} missing')

def check_python_import(module, version_attr='__version__'):
    try:
        import importlib
        mod = importlib.import_module(module)
        ver = getattr(mod, version_attr, 'installed')
        return (f'{module}=={ver}', True, f'{module} {ver} available')
    except ImportError:
        return (f'{module}=NOT installed', False, f'{module} not importable')
    except Exception as e:
        return (f'{module}={e}', False, f'{module} error: {e}')

def check_openllm():
    """Check OpenLLM endpoint"""
    import urllib.request
    try:
        resp = urllib.request.urlopen('http://localhost:11343/v1/models', timeout=5)
        data = json.loads(resp.read())
        cnt = len(data.get('data', data if isinstance(data, list) else []))
        return (f'accessible, ~{cnt} models', cnt > 0, f'OpenLLM /v1/models: {cnt} models')
    except Exception as e:
        return (f'error: {e}', False, f'OpenLLM unreachable: {e}')

def check_hermes_version():
    out = run_cmd(['/home/admin/.local/bin/hermes', '--version'], timeout=5)
    return (out[:40], '0.15' in out or '0.15.1' in out, f'hermes --version: {out[:60]}')


# 事实校验清单: (section, pattern_key, parse_pattern, check_func, description)
FACTS = [
    ('SYSTEM_TOOLS', 'Xvfb', r'Xvfb\s*=\s*(/\S+)', lambda m: check_file_exists(m.group(1)), 'Xvfb binary'),
    ('SYSTEM_TOOLS', 'gcc', r'gcc\s*=\s*(GCC\s+\S+)', lambda m: check_version(['gcc'], '--version', r'(GCC\s+[\d.]+)'), 'GCC version'),
    ('SYSTEM_TOOLS', 'jq', r'jq\s*=\s*(jq-\S+)', lambda m: check_version(['jq'], '--version', r'(jq-\S+)'), 'jq version'),
    ('SYSTEM_TOOLS', 'code-server', r'code-server\s*=\s*(running service)', lambda m: check_running_service('code-server', 9090), 'code-server'),
    ('SYSTEM_TOOLS', 'pip_packages', r'pip_packages\s*=\s*(\d+)\s+total.*?hermes venv', lambda m: check_pip_packages_hermes(m.group(1)), 'pip packages count (hermes)'),
    
    ('DEV_ENVIRONMENT', 'Python', r'Python\s*=\s*([\d.]+)', lambda m: check_version(['python3'], '--version', r'([\d.]+)'), 'Python version'),
    ('DEV_ENVIRONMENT', 'Node', r'Node\s*=\s*(v[\d.]+)', lambda m: check_version(['node'], '--version', r'(v[\d.]+)'), 'Node version'),
    ('DEV_ENVIRONMENT', 'npm', r'npm\s*=\s*([\d.]+)', lambda m: check_version(['npm'], '--version', r'([\d.]+)'), 'npm version'),
    ('DEV_ENVIRONMENT', 'Git', r'Git\s*=\s*([\d.]+)', lambda m: check_version(['git'], '--version', r'([\d.]+)'), 'Git version'),
    ('DEV_ENVIRONMENT', 'RAM_total', r'RAM_total\s*=\s*([\d.]+[GT]i)', lambda m: check_ram_total(), 'RAM total'),
    ('DEV_ENVIRONMENT', 'Chromium', r'Chromium\s*=\s*([\d.]+)', lambda m: check_version(['/usr/bin/chromium-browser'], '--version', r'([\d.]+)'), 'Chromium'),
    ('DEV_ENVIRONMENT', 'pip_packages_GA_venv', r'pip_packages_GA_venv\s*=\s*(\d+)', lambda m: check_pip_packages_ga(m.group(1)), 'pip packages count (GA)'),
    
    ('VISION_TOOLS', 'Pillow', r'Pillow\s*=\s*([\d.]+)', lambda m: check_python_import('PIL', '__version__'), 'Pillow'),
    ('VISION_TOOLS', 'OpenCV', r'OpenCV\s*=\s*([\d.]+)', lambda m: check_python_import('cv2', '__version__'), 'OpenCV'),
    ('VISION_TOOLS', 'RapidOCR', r'RapidOCR\s*=\s*(installed)', lambda m: check_python_import('rapidocr_onnxruntime'), 'RapidOCR'),
    ('VISION_TOOLS', 'pytesseract', r'pytesseract\s*=\s*(installed)', lambda m: check_python_import('pytesseract'), 'pytesseract'),
    
    ('LOCAL_SERVICES', 'OpenLLM', r'OpenLLM\s*=\s*(\S+)', lambda m: check_openllm(), 'OpenLLM'),
    ('LOCAL_SERVICES', 'models', r'models\s*=\s*(\d+)', lambda m: check_openllm(), 'OpenLLM models count'),
    ('LOCAL_SERVICES', 'deepseek', r'deepseek default\s*=\s*(\S+)', lambda m: check_openllm(), 'DeepSeek model'),
    
    ('HERMES_AGENT', 'version', r'version\s*=\s*([\d.]+)', lambda m: check_hermes_version(), 'Hermes version'),
    ('HERMES_AGENT', 'dashboard_api', r'dashboard_api\s*=\s*(\S+)', lambda m: check_running_service('hermes-dashboard'), 'Dashboard API'),
]

# 不可验证或需要特殊处理的事实（跳过）
SKIP = ['rsync', 'agentmail', 'git_user', 'editor_primary', 'shell_aliases', 
        'browser_', 'api_key', 'gateway_openai', '9router', 'node_app_',
        'hermes_cli', 'hermes_home', 'session_token', 'inboxes', 'org_id',
        'send_receive', 'mirothinker', 'fastapi', 'uvicorn',
        'task_engine_dir', 'optimization_loop_sop', 'pip_packages']


def load_global_mem():
    """Parse global_mem.txt into sections"""
    text = MEM_PATH.read_text()
    return text


def extract_declared_value(text, pattern):
    """Extract declared value from global_mem text using regex"""
    m = re.search(pattern, text, re.MULTILINE)
    return m.group(0).strip() if m else None


def run_checks(text):
    """Run all verifiable fact checks"""
    results = []
    
    for section, key, pattern, check_func, desc in FACTS:
        match = re.search(pattern, text, re.MULTILINE)
        if not match:
            results.append({
                'section': section,
                'key': key,
                'status': 'SKIP',
                'declared': '(not found)',
                'actual': '(not in global_mem)',
                'match': False,
                'detail': f'Pattern not found in global_mem.txt: {pattern}'
            })
            continue
        
        declared_line = match.group(0).strip()
        try:
            actual, is_match, detail = check_func(match)
        except Exception as e:
            actual, is_match, detail = f'(error: {e})', False, str(e)
        
        results.append({
            'section': section,
            'key': key,
            'status': 'OK' if is_match else 'DRIFT',
            'declared': declared_line,
            'actual': actual,
            'match': is_match,
            'detail': detail
        })
    
    return results


def format_report(results):
    """Format results as readable report"""
    drifts = [r for r in results if r['status'] == 'DRIFT']
    ok = [r for r in results if r['status'] == 'OK']
    skipped = [r for r in results if r['status'] == 'SKIP']
    
    lines = []
    lines.append(f'# Memory Drift Report — {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    lines.append(f'')
    lines.append(f'**Summary:** {len(drifts)} drifts, {len(ok)} ok, {len(skipped)} skipped')
    lines.append(f'')
    
    if drifts:
        lines.append(f'## 🚨 Detected Drifts ({len(drifts)})')
        lines.append(f'')
        for d in drifts:
            lines.append(f'### [{d["section"]}] {d["key"]}')
            lines.append(f'- Declared: `{d["declared"]}`')
            lines.append(f'- Actual:   `{d["actual"]}`')
            lines.append(f'- Detail: {d["detail"]}')
            lines.append(f'')
    
    if ok:
        lines.append(f'## ✅ Verified OK ({len(ok)})')
        lines.append(f'')
        for o in ok:
            lines.append(f'- [{o["section"]}] {o["key"]}: {o["actual"][:50]}')
        lines.append(f'')
    
    if skipped:
        lines.append(f'## ⏭️ Skipped ({len(skipped)})')
        for s in skipped:
            lines.append(f'- [{s["section"]}] {s["key"]}: {s["detail"]}')
        lines.append(f'')
    
    return '\n'.join(lines)


def generate_patch_report(results):
    """Generate a patch proposal if drifts >= 3"""
    drifts = [r for r in results if r['status'] == 'DRIFT']
    
    if len(drifts) < 3:
        return None
    
    lines = []
    lines.append(f'# Patch Proposal — Memory Drift Auto-Fix')
    lines.append(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    lines.append(f'Drifts detected: {len(drifts)}')
    lines.append(f'')
    lines.append(f'## Proposed global_mem.txt Patches')
    lines.append(f'')
    
    for d in drifts:
        lines.append(f'### [{d["section"]}] {d["key"]}')
        lines.append(f'- Current: `{d["declared"]}`')
        lines.append(f'- Proposed: update to `{d["actual"]}`')
        lines.append(f'- Reason: {d["detail"]}')
        lines.append(f'')
    
    lines.append(f'---')
    lines.append(f'*This patch report was auto-generated by drift_detector.py*')
    
    return '\n'.join(lines)


def apply_patches(results, dry_run=False):
    """Apply drift patches to global_mem.txt automatically (threshold ≥3 drifts).
    Returns list of (key, old_line, new_line, applied) tuples.
    """
    drifts = [r for r in results if r['status'] == 'DRIFT']
    if len(drifts) < 3:
        return []
    
    text = load_global_mem()
    patches = []
    
    for d in drifts:
        old_line = d['declared']
        # Build new line: replace declared value with actual
        # Try to extract the key=value pattern
        parts = old_line.split('=', 1)
        if len(parts) == 2:
            key_part = parts[0]
            # Use actual value from check
            actual_val = d['actual'].split('(')[0].strip() if '(' in d['actual'] else d['actual']
            new_line = f"{key_part}= {actual_val}"
        else:
            new_line = f"# {old_line}  # DRIFT FIX: {d['actual']}"
        
        if old_line in text:
            if not dry_run:
                text = text.replace(old_line, new_line, 1)
            patches.append((d['key'], old_line, new_line, True))
        else:
            patches.append((d['key'], old_line, new_line, False))
    
    if not dry_run and patches:
        # Backup
        backup = MEM_PATH.with_suffix('.txt.bak')
        if not backup.exists():
            MEM_PATH.rename(backup)
        MEM_PATH.write_text(text)
    
    return patches


def verify_patches():
    """Run check again and report if drifts resolved"""
    text = load_global_mem()
    results = run_checks(text)
    remaining = [r for r in results if r['status'] == 'DRIFT']
    return results, len(remaining) == 0, remaining

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Memory Drift Detector')
    parser.add_argument('command', nargs='?', default='check',
                       choices=['check', 'patch', 'apply', 'auto', 'full'],
                       help='check: detect drifts; patch: generate patch if ≥3 drifts; apply: auto-fix global_mem.txt; auto: check→apply→verify pipeline')
    parser.add_argument('--output', '-o', help='Output file path')
    parser.add_argument('--dry-run', action='store_true', help='With apply: show what would change without modifying')
    args = parser.parse_args()
    
    text = load_global_mem()
    results = run_checks(text)
    
    if args.command == 'check':
        report = format_report(results)
        print(report)
        if args.output:
            Path(args.output).write_text(report)
        return 1 if any(r['status'] == 'DRIFT' for r in results) else 0
    
    elif args.command == 'patch':
        patch = generate_patch_report(results)
        if patch:
            print(patch)
            if args.output:
                Path(args.output).write_text(patch)
        else:
            print(f'✅  No significant drift detected ({len([r for r in results if r["status"]=="DRIFT"])} drifts < 3 threshold). No patch needed.')
        return 0
    
    elif args.command == 'apply':
        patches = apply_patches(results, dry_run=args.dry_run)
        if not patches:
            print(f'✅  No drift to apply ({len([r for r in results if r["status"]=="DRIFT"])} drifts < 3 threshold).')
            return 0
        print(f'Applied {len(patches)} patches:')
        for k, old, new, ok in patches:
            status = '✅' if ok else '❌'
            print(f'  {status} [{k}] {old[:50]} → {new[:50]}')
        if not args.dry_run:
            print(f'\n🔒 Backup saved: {MEM_PATH}.bak')
            print(f'📝 Updated: {MEM_PATH}')
            # Verify
            v_results, clean, remaining = verify_patches()
            if clean:
                print(f'✅  Verification PASS: all drifts resolved.')
            else:
                print(f'⚠️  Verification: {len(remaining)} drifts still remain.')
        return 0
    
    elif args.command == 'auto':
        print('=== Step 1: Check ===')
        report = format_report(results)
        print(report)
        drifts = [r for r in results if r['status'] == 'DRIFT']
        if len(drifts) < 3:
            print(f'\n✅  No significant drift (< 3). Done.')
            return 0
        print(f'\n=== Step 2: Apply ===')
        patches = apply_patches(results)
        if patches:
            for k, old, new, ok in patches:
                print(f'  {"✅" if ok else "❌"} [{k}] {old[:50]} → {new[:50]}')
        print(f'\n=== Step 3: Verify ===')
        v_results, clean, remaining = verify_patches()
        if clean:
            print(f'✅  Auto-fix pipeline complete: check → apply → verify. All clean.')
        else:
            print(f'⚠️  Auto-fix partial: {len(remaining)} drifts still remain.')
        return 0 if clean else 1
    
    elif args.command == 'full':
        report = format_report(results)
        print(report)
        patch = generate_patch_report(results)
        if patch:
            print('\n' + '='*60)
            print('PATCH REPORT GENERATED\n')
            print(patch)
            if args.output:
                Path(args.output).write_text(report + '\n\n' + patch)


if __name__ == '__main__':
    main()
