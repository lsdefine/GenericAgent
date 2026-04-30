"""
代理处理通用模块 - 支持所有 Case 的代理环境初始化
基于 practiceCases.md 的"代理处理通用模块设计"部分
"""

import os
import subprocess
import time

PROXY_HOST = "127.0.0.1:6789"
# 完整的内网地址排除列表
NO_PROXY = "localhost,127.*,10.*,172.16.*,172.17.*,172.18.*,172.19.*,172.20.*,172.21.*,172.22.*,172.23.*,172.24.*,172.25.*,172.26.*,172.27.*,172.28.*,172.29.*,172.30.*,172.31.*,192.168.*"

def is_process_running(process_name):
    """检查进程是否存在"""
    import subprocess
    try:
        result = subprocess.run(
            ["tasklist"], 
            capture_output=True, 
            text=True, 
            shell=True
        )
        return process_name in result.stdout
    except Exception:
        return False

def ensure_proxy():
    """
    检测并启动 okz.exe，设置代理环境变量。
    返回 True 表示代理就绪，False 表示无法启动代理。
    """
    if not is_process_running("okz.exe"):
        try:
            subprocess.Popen("okz.exe", shell=True)
            time.sleep(3)
        except Exception as e:
            print(f"启动代理失败: {e}")
            return False
    
    # 设置环境变量
    os.environ['HTTP_PROXY'] = f'http://{PROXY_HOST}'
    os.environ['HTTPS_PROXY'] = f'http://{PROXY_HOST}'
    os.environ['NO_PROXY'] = NO_PROXY
    
    # 快速连通性测试
    if not test_proxy():
        print("代理连通性测试失败")
        return False
    return True

def test_proxy():
    """测试代理连通性"""
    import urllib.request
    try:
        req = urllib.request.Request('https://www.google.com')
        req.set_proxy(PROXY_HOST, 'https')
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception as e:
        print(f"代理测试异常: {e}")
        return False

def get_proxy_dict():
    """获取 requests 库所需的代理字典格式"""
    return {
        "http": f"http://{PROXY_HOST}",
        "https": f"http://{PROXY_HOST}"
    }

def is_internal_ip(ip):
    """判断 IP 是否为内网地址"""
    import re
    patterns = [
        r"^127\.",           # 127.0.0.0/8
        r"^10\.",            # 10.0.0.0/8
        r"^172\.(1[6-9]|2\d|3[01])\.",  # 172.16.0.0/12
        r"^192\.168\.",     # 192.168.0.0/16
    ]
    return any(re.match(p, ip) for p in patterns)

# === 目录白名单安全模块 (CONSTITUTION R6, 2026-04-30) ===
import os

def get_allowed_prefixes():
    """获取目录白名单（GA受控目录树，不含cwd/根目录以防路径穿越）"""
    return [
        "E:/AI/GenericAgent/memory",
        "E:/AI/GenericAgent/temp",
        "E:/AI/GenericAgent/scripts",
        "E:/AI/GenericAgent/logs",
    ]

def is_path_safe(target_path: str) -> bool:
    """
    检查目标路径是否在白名单目录树内
    来源: global_mem.txt CONSTITUTION R6
    用法: file_write前必须调用此函数校验
    """
    if not target_path:
        return False
    # 【修复RT-1 V1漏洞】先用realpath+normpath完全展开路径，消除所有../、./、符号链接等相对成分
    try:
        abs_path = os.path.realpath(os.path.normpath(str(target_path)))
    except (OSError, ValueError):
        abs_path = os.path.abspath(str(target_path))
    # Windows路径统一为正斜杠
    abs_path = abs_path.replace("\\", "/")
    prefixes = [p.replace("\\", "/") for p in get_allowed_prefixes()]
    # 检查是否在任一白名单前缀下
    for prefix in prefixes:
        if abs_path.startswith(prefix + "/") or abs_path == prefix:
            return True
    return False

def safe_file_read(path: str, encoding: str = "utf-8") -> str:
    """安全的文件读取（带路径校验）"""
    if not is_path_safe(path):
        raise PermissionError(f"[R6拒绝] 路径不在白名单内: {path}")
    with open(path, "r", encoding=encoding) as f:
        return f.read()

def safe_file_write(path: str, content: str, encoding: str = "utf-8") -> None:
    """安全的文件写入（带路径校验）"""
    if not is_path_safe(path):
        raise PermissionError(f"[R6拒绝] 路径不在白名单内: {path}")
    with open(path, "w", encoding=encoding) as f:
        f.write(content)

def assert_path_safe(path: str) -> None:
    """断言路径安全，不安全则抛出异常（供assert使用）"""
    if not is_path_safe(path):
        raise PermissionError(f"[R6断言失败] 路径不在白名单内: {path}")



def classify_content_type(raw_content: str) -> str:
    """
    内容类型识别 - 基于内容特征自动判断数据类型
    迁移自: Case5 文件类型检测逻辑（路径检测 → 内容检测）
    
    用法: 在处理外部来源数据时，先调用此函数判断类型，再选择提取策略
    返回: "text/html" | "application/json" | "text/plain" | "unknown"
    """
    if not raw_content:
        return "unknown"
    
    stripped = raw_content.strip()
    
    # JSON检测: 以 { 或 [ 开头
    if stripped.startswith('{') or stripped.startswith('['):
        # 验证是否为有效JSON
        import json
        try:
            json.loads(stripped)
            return "application/json"
        except (json.JSONDecodeError, ValueError):
            pass
    
    # 优先检测内嵌JSON（HTML中的<pre><code>包裹的JSON）
    try:
        import re
        # 宽松匹配: <pre>标签内的JSON内容
        json_match = re.search(r'<pre[^>]*>([\s\S]*?)</pre>', stripped)
        if json_match:
            potential = json_match.group(1).strip()
            # 去掉HTML标签后再试
            clean = re.sub(r'<[^>]+>', '', potential).strip()
            if clean.startswith('{') or clean.startswith('['):
                json.loads(clean)
                return "application/json"
        # 备选: 直接搜索JSON对象模式
        if re.search(r'\{\s*"[^"]+"\s*:', stripped):
            json.loads(re.search(r'\{[\s\S]*\}', stripped).group())
            return "application/json"
    except:
        pass
    
    # HTML检测: 以 <html/<!doctype/<!DOCTYPE 开头，或包含HTML标签
    lower = stripped[:500].lower()  # 只检查前500字符
    if (lower.startswith('<!doctype') or 
        lower.startswith('<html') or
        '<html' in lower or 
        '<head' in lower or
        '<body' in lower or
        '<div' in lower):
        return "text/html"
    
    # 纯文本: 无特殊标记
    return "text/plain"


def extract_by_content_type(raw_content: str, content_type: str = None) -> dict:
    """
    根据内容类型自动提取关键信息
    content_type为None时自动检测
    """
    if content_type is None:
        content_type = classify_content_type(raw_content)
    
    result = {
        "type": content_type,
        "raw_length": len(raw_content),
        "extracted": {}
    }
    
    if content_type == "application/json":
        import json
        result["extracted"] = json.loads(raw_content)
        result["keys"] = list(result["extracted"].keys()) if isinstance(result["extracted"], dict) else "array"
    
    elif content_type == "text/html":
        # 提取body文本（复用MiniCase-E的fallback策略）
        result["extracted"] = {
            "title": "",
            "body_text": raw_content[:500]
        }
    
    else:  # text/plain
        result["extracted"] = {"text": raw_content[:500]}
    
    return result


# === 单元测试 ===
if __name__ == "__main__":
    print("=== CONSTITUTION R6 目录白名单测试 ===")
    # 白名单内路径
    safe_tests = [
        os.getcwd(),
        os.path.join(os.getcwd(), "test.txt"),
        "E:/AI/GenericAgent/memory/test.txt",
    ]
    # 白名单外路径
    unsafe_tests = [
        "C:/Windows/System32/test.txt",
        "C:/Program Files/test.txt",
    ]
    print(f"白名单前缀: {get_allowed_prefixes()}")
    print("\n--- 安全路径 ---")
    for p in safe_tests:
        print(f"  {p}: {'✅' if is_path_safe(p) else '❌'}")
    print("\n--- 危险路径 ---")
    for p in unsafe_tests:
        print(f"  {p}: {'✅拒绝' if not is_path_safe(p) else '❌应拒绝'}")
    print("\n=== R6模块加载成功 ===")


# === RT5: 审计日志防篡改模块 ===
def compute_file_hash(file_path: str) -> str:
    """计算文件的SHA256哈希"""
    import hashlib
    with open(file_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def store_integrity_hash(file_path: str, hash_dir: str = None) -> str:
    """存储文件哈希到独立位置，返回哈希文件路径"""
    import os
    if hash_dir is None:
        hash_dir = os.path.dirname(file_path)
    hash_file = os.path.join(hash_dir, ".integrity_" + os.path.basename(file_path) + ".sha256")
    sha256 = compute_file_hash(file_path)
    with open(hash_file, "w") as f:
        f.write(f"{os.path.basename(file_path)}|{sha256}")
    return hash_file

def verify_file_integrity(file_path: str, hash_dir: str = None) -> tuple:
    """验证文件完整性，返回(is_valid, current_hash, stored_hash)"""
    import os
    if hash_dir is None:
        hash_dir = os.path.dirname(file_path)
    hash_file = os.path.join(hash_dir, ".integrity_" + os.path.basename(file_path) + ".sha256")
    if not os.path.exists(hash_file):
        return False, None, None
    with open(hash_file, "r") as f:
        stored = f.read().strip().split("|")[1]
    current = compute_file_hash(file_path)
    return current == stored, current, stored

def audit_integrity_check() -> dict:
    """检查所有受保护审计文件的完整性"""
    import os
    ga_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    audit_dir = os.path.join(ga_root, "memory", "audit")
    protected = [
        "capability_profile_v2.md",
        "rt_regression_full.md",
        "rt_regression_fix.md",
    ]
    results = {}
    for fname in protected:
        fpath = os.path.join(audit_dir, fname)
        if os.path.exists(fpath):
            ok, curr, stored = verify_file_integrity(fpath, audit_dir)
            results[fname] = {"valid": ok, "current": (curr[:16] + "...") if curr else None, "stored": (stored[:16] + "...") if stored else None}
    return results
