#!/usr/bin/env python3
"""SQL 实操测试 — SQLite 查询验证"""
import json, sqlite3, os, sys


def run_sql_tests():
    """创建测试表，执行查询，验证结果"""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    
    # 建表
    cur.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT,
            age INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        INSERT INTO users VALUES (1, 'Alice', 'alice@test.com', 28, '2025-01-15');
        INSERT INTO users VALUES (2, 'Bob', 'bob@test.com', 35, '2025-02-20');
        INSERT INTO users VALUES (3, 'Charlie', 'charlie@test.com', 42, '2025-03-10');
        INSERT INTO orders VALUES (1, 1, 150.00, 'completed', '2025-02-01');
        INSERT INTO orders VALUES (2, 1, 89.99, 'completed', '2025-02-15');
        INSERT INTO orders VALUES (3, 2, 250.00, 'pending', '2025-03-01');
        INSERT INTO orders VALUES (4, 2, 39.99, 'shipped', '2025-03-05');
        INSERT INTO orders VALUES (5, 3, 520.00, 'completed', '2025-03-20');
        INSERT INTO orders VALUES (6, 1, 75.00, 'cancelled', '2025-04-01');
    """)
    
    # 测试1: JOIN查询
    cur.execute("""
        SELECT u.name, COUNT(o.id) as order_count, SUM(o.amount) as total_spent
        FROM users u
        LEFT JOIN orders o ON u.id = o.user_id AND o.status = 'completed'
        GROUP BY u.id
        ORDER BY total_spent DESC
    """)
    rows = cur.fetchall()
    assert len(rows) == 3, f"JOIN测试: 期望3行, 实际{len(rows)}"
    assert rows[0][0] == 'Charlie', f"JOIN测试: Charlie应排第一"
    
    # 测试2: 子查询
    cur.execute("""
        SELECT name, age
        FROM users
        WHERE age >= (SELECT AVG(age) FROM users)
    """)
    rows = cur.fetchall()
    assert len(rows) == 2, f"子查询测试: 期望2行(>=平均年龄), 实际{len(rows)}"
    
    # 测试3: 聚合 + HAVING
    cur.execute("""
        SELECT u.name, SUM(o.amount) as total
        FROM users u
        JOIN orders o ON u.id = o.user_id
        GROUP BY u.id
        HAVING total > 200
        ORDER BY total DESC
    """)
    rows = cur.fetchall()
    assert len(rows) == 3, f"聚合测试: 期望3行(每人总额均>200), 实际{len(rows)}"
    assert rows[0][0] == 'Charlie', f"聚合测试: Charlie应排第一"
    
    conn.close()
    return True


def main():
    result = {"score": 0, "passed": False, "note": ""}
    try:
        run_sql_tests()
        result["score"] = 100
        result["passed"] = True
        result["note"] = "SQL 实操测试通过！JOIN/子查询/聚合 全部正确"
    except AssertionError as e:
        result["score"] = 50
        result["note"] = f"SQL 查询结果不符预期: {e}"
    except Exception as e:
        result["score"] = 30
        result["note"] = f"SQL 测试异常: {e}"
    
    print(json.dumps(result))
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
