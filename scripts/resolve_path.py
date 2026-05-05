# -*- coding: utf-8 -*-
"""
路径解析与安全写入工具
AGENT_ROOT = E:\AI\GenericAgent
MEMORY_DIR = E:\AI\GenericAgent\memory
TEMP_DIR   = E:\AI\GenericAgent\temp
SCRIPTS_DIR= E:\AI\GenericAgent\scripts
LOGS_DIR   = E:\AI\GenericAgent\logs
"""
import os, shutil, datetime

AGENT_ROOT = r"E:\AI\GenericAgent"
MEMORY_DIR = r"E:\AI\GenericAgent\memory"
TEMP_DIR   = r"E:\AI\GenericAgent\temp"
SCRIPTS_DIR= r"E:\AI\GenericAgent\scripts"
LOGS_DIR   = r"E:\AI\GenericAgent\logs"

ALLOWED_WRITE_PREFIXES = [AGENT_ROOT]

def resolve_path(path, base=None):
    if os.path.isabs(path):
        full = os.path.abspath(path)
    else:
        b = base or AGENT_ROOT
        full = os.path.abspath(os.path.join(b, path))
    return os.path.realpath(full)

def assert_allowed(path):
    rp = resolve_path(path)
    if not any(rp.startswith(p) for p in ALLOWED_WRITE_PREFIXES):
        raise PermissionError(f"路径 {rp} 不在白名单内，禁止写入")
    return rp

def backup_if_exists(abs_path):
    if os.path.isfile(abs_path):
        ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        bak = abs_path + f'.bak_{ts}'
        shutil.copy2(abs_path, bak)
        return bak
    return None

def write_with_backup(content, path, encoding='utf-8'):
    rp = assert_allowed(path)
    bk = backup_if_exists(rp)
    with open(rp, 'w', encoding=encoding) as f:
        f.write(content)
    with open(rp, 'r', encoding=encoding) as f:
        verify = f.read()
    if verify != content:
        raise IOError(f"写入验证失败: {rp}")
    return {'written': rp, 'backup': bk}

def is_memory_path(path):
    return resolve_path(path).startswith(MEMORY_DIR)

def is_temp_path(path):
    return resolve_path(path).startswith(TEMP_DIR)

def safe_relative(path, base=None):
    """Return path relative to AGENT_ROOT, or original if not possible."""
    rp = resolve_path(path)
    try:
        return os.path.relpath(rp, AGENT_ROOT)
    except ValueError:
        return path
