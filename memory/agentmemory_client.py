"""
agentmemory REST API wrapper for GenericAgent
文档: https://github.com/rohitg00/agentmemory
服务: http://localhost:3111

官方API端点:
| 方法 | 端点 | 说明 |
|------|------|------|
| GET | /agentmemory/health | 健康检查 |
| GET | /agentmemory/profile?project=X | 项目概况 |
| GET | /agentmemory/memories?limit=N | 获取记忆列表 |
| GET | /agentmemory/sessions | 获取会话列表 |
| GET | /agentmemory/export | 导出所有数据 |
| GET | /agentmemory/audit | 审计跟踪 |
| POST | /agentmemory/observe | 创建观察记录 |
| POST | /agentmemory/remember | 创建记忆 |
| POST | /agentmemory/smart-search | 语义搜索 |
| POST | /agentmemory/forget | 删除记忆 (传memoryId) |
"""
import urllib.request
import json
from datetime import datetime

BASE_URL = "http://localhost:3111"
DEFAULT_SESSION = "20260515_104738_65cfa2"
PROJECT = "GenericAgent"
CWD = r"D:\Claws\GenericAgent"

def api_post(path, data):
    """POST请求"""
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=body,
        method='POST',
        headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())

def api_get(path):
    """GET请求"""
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

# ============ 核心功能 ============

def remember(content, session_id=None, project=PROJECT, cwd=CWD, category=None):
    """保存记忆到长期存储 (POST /remember)"""
    if session_id is None:
        session_id = DEFAULT_SESSION
    data = {
        "hookType": "manual",
        "sessionId": session_id,
        "project": project,
        "cwd": cwd,
        "timestamp": datetime.now().isoformat(),
        "content": content
    }
    if category:
        data["category"] = category
    result = api_post("/agentmemory/remember", data)
    return result.get('memory', result) if result.get('success') else result

def search(query, limit=10):
    """语义搜索记忆 (POST /smart-search)"""
    return api_post("/agentmemory/smart-search", {"query": query, "limit": limit})

def get_memories(limit=100):
    """获取所有记忆 (GET /memories)"""
    return api_get(f"/agentmemory/memories?limit={limit}")

def delete(memory_id):
    """删除指定记忆 (POST /forget)"""
    return api_post("/agentmemory/forget", {"memoryId": memory_id})

# ============ 辅助功能 ============

def health():
    """健康检查 (GET /health)"""
    return api_get("/agentmemory/health")

def get_sessions():
    """获取会话列表 (GET /sessions)"""
    return api_get("/agentmemory/sessions")

def observe(content, session_id=None, project=PROJECT, cwd=CWD):
    """创建观察记录 (POST /observe) - 与remember不同，返回observationId"""
    if session_id is None:
        session_id = DEFAULT_SESSION
    data = {
        "hookType": "manual",
        "sessionId": session_id,
        "project": project,
        "cwd": cwd,
        "timestamp": datetime.now().isoformat(),
        "content": content
    }
    return api_post("/agentmemory/observe", data)

if __name__ == "__main__":
    # 测试
    print("=== agentmemory 客户端测试 ===")
    
    # 健康检查
    h = health()
    print(f"服务状态: {h.get('status', 'unknown')}")
    
    # 写入测试
    result = remember(f"[自动测试 {datetime.now().strftime('%H:%M:%S')}]")
    print(f"写入结果: {result.get('id', result)}")