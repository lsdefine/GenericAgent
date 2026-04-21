"""
aduAgent 向量记忆大脑 - 极简实现
遵守 R7(懒加载+全局单例) / R8(dim死对齐+struct.pack) / MATCH两步查(规避 sqlite-vec 禁 JOIN)
"""
import os, sqlite3, struct, threading
import sqlite_vec


class VectorBrain:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path="memory/agent_vec.db"):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path="memory/agent_vec.db"):
        if self._initialized:
            return
        self.db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._model = None
        self._dim = None
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        # 维度无关的 meta 表先建;vec 虚拟表延后到拿到模型 dim 后再建
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS mem_meta(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()
        self._initialized = True

    def _get_model(self):
        """R7: 懒加载 + 单例。首次命中时按模型真实 dim 建 vec 表(R8 动态对齐)"""
        if self._model is None:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")  # 强制走本地缓存,避免在线校验阻塞
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("paraphrase-MiniLM-L6-v2")
            self._dim = self._model.get_sentence_embedding_dimension()
            # R8: vec 表维度 === 模型 dim,绝不猜测
            self.conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS mem_vec USING vec0("
                f"id INTEGER PRIMARY KEY, embedding float[{self._dim}])"
            )
            self.conn.commit()
        return self._model

    def add_memory(self, text: str) -> int:
        model = self._get_model()
        vec = model.encode(text)
        blob = struct.pack(f"{self._dim}f", *vec)  # R8: struct.pack,禁 json/pickle
        cur = self.conn.cursor()
        cur.execute("INSERT INTO mem_meta(content) VALUES (?)", (text,))
        rid = cur.lastrowid
        cur.execute("INSERT INTO mem_vec(id, embedding) VALUES (?, ?)", (rid, blob))
        self.conn.commit()
        return rid

    def search(self, query: str, k: int = 3) -> list:
        """两步查:MATCH 子句禁 JOIN,先拿 id+distance,再按 id 查 meta"""
        model = self._get_model()
        qvec = model.encode(query)
        qblob = struct.pack(f"{self._dim}f", *qvec)
        hits = self.conn.execute(
            "SELECT id, distance FROM mem_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (qblob, k)
        ).fetchall()
        if not hits:
            return []
        id_list = ",".join(str(h[0]) for h in hits)  # rowid 全是 int,无注入风险
        rows = self.conn.execute(
            f"SELECT id, content FROM mem_meta WHERE id IN ({id_list})"
        ).fetchall()
        cmap = {r[0]: r[1] for r in rows}
        return [cmap[h[0]] for h in hits if h[0] in cmap]


# 模块级单例(仅建 SQLite 连接 + meta 表,不触发模型加载)
brain = VectorBrain()
