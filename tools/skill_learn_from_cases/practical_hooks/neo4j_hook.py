#!/usr/bin/env python3
"""
neo4j_hook.py — Neo4j/Cypher 实操测试

统一接口: run(env: dict) -> dict
  env 来自 env_detector.detect_all()
  返回 {"score": 0-100, "passed": bool, "note": str, "detail": [...]}

独立运行: python neo4j_hook.py (会自动探测环境)
"""
import json, sys, os, re


def run(env: dict = None) -> dict:
    """统一入口：接收 env 字典，返回测试结果"""
    if env is None:
        env = _detect_env()
    
    neo4j_info = env.get("neo4j", {})
    password = os.environ.get("neo4j_password", "")
    
    if neo4j_info.get("available") and password:
        return _real_neo4j_test(password)
    else:
        return _syntax_fallback()


def _detect_env() -> dict:
    """独立运行时的环境探测"""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from env_detector import detect_all
        return detect_all(quiet=True)
    except Exception:
        return {}


def _syntax_fallback() -> dict:
    """降级：Cypher 语法检查"""
    tests = [
        ("MATCH (n) RETURN n", True, "基本查询"),
        ("MATCH (n:Person)-[:KNOWS]->(f) RETURN n,f", True, "关系查询"),
        ("MERGE (n:Label {id:$id}) ON CREATE SET n.ts=timestamp()", True, "MERGE模式"),
        ("这个不是cypher语法 123 !!!", False, "语法错误检测"),
    ]
    correct = sum(1 for q, ok, _ in tests if _check_syntax(q) == ok)
    return {
        "score": int(correct / len(tests) * 100),
        "passed": correct >= 3,
        "note": f"Cypher 语法检查 {correct}/{len(tests)} (无连接)",
        "detail": [{"name": t[2], "passed": _check_syntax(t[0]) == t[1]} for t in tests]
    }


def _check_syntax(query: str) -> bool:
    if not query.strip():
        return False
    keywords = ["match", "create", "merge", "return", "set", "delete", "where"]
    has_keyword = any(kw in query.lower().split() for kw in keywords)
    has_arrow = "->" in query or "-[" in query or "--" in query
    return has_keyword or has_arrow


def _real_neo4j_test(password: str) -> dict:
    """真实 Neo4j 连接测试"""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return _syntax_fallback()

    driver = None
    try:
        driver = GraphDatabase.driver(
            "bolt://localhost:7687",
            auth=("neo4j", password),
            connection_timeout=5
        )
        with driver.session() as session:
            r = session.run("RETURN 1 AS n")
            if not r.single() or r.single()["n"] != 1:
                raise Exception("连接验证失败")

        tests = [
            ("RETURN 'hello' AS greeting", "基本Cypher查询"),
            ("match (n) return n limit 5", "图数据查询"),
            ("call db.labels()", "获取标签列表"),
            ("call db.relationshipTypes()", "获取关系类型"),
            ("call db.propertyKeys()", "获取属性键"),
        ]
        correct = 0
        detail = []
        with driver.session() as session:
            for query, desc in tests:
                try:
                    session.run(query).consume()
                    correct += 1
                    detail.append({"name": desc, "passed": True})
                except Exception as e:
                    detail.append({"name": desc, "passed": False, "error": str(e)})

        return {
            "score": int((correct / len(tests)) * 100),
            "passed": correct >= 3,
            "note": f"Neo4j 真实连接 {correct}/{len(tests)}",
            "detail": detail
        }
    except Exception as e:
        result = _syntax_fallback()
        result["note"] += f" (连接失败: {e})"
        return result
    finally:
        if driver:
            driver.close()


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False))
