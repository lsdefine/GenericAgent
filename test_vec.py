"""临时验收:memory_vec 单例 + 写入 + 检索"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
t_import = time.time()
from memory_vec import brain
dt_import = time.time() - t_import
print(f"[IMPORT] {dt_import:.3f}s  (建 SQLite + meta 表,未加载模型 — R7 懒加载验证)")
print(f"[DB] {brain.db_path}")
print(f"[MODEL LOADED?] {brain._model is not None}  (应为 False)")

samples = [
    "教授叮嘱:每天早上 6 点起床读 30 分钟英文,坚持 90 天",
    "今天在 Python queue 模块上踩了坑,子线程不能直连 DB,必须走队列",
    "商业洞察:SaaS 定价要按客户价值分段,不是单纯成本加成",
]

print("\n[WRITE]")
t_add_all = time.time()
for i, s in enumerate(samples):
    t0 = time.time()
    rid = brain.add_memory(s)
    mark = " (首次触发模型加载)" if i == 0 else ""
    print(f"  add id={rid} {time.time()-t0:.3f}s{mark} :: {s}")
dt_add = time.time() - t_add_all
print(f"[WRITE TOTAL] {dt_add:.3f}s")
print(f"[MODEL LOADED?] {brain._model is not None}  (应为 True)")
print(f"[DIM] {brain._dim}  (应为 384)")

print("\n[SEARCH]")
q = "昨天老师给我布置了什么学习计划?"
t_s = time.time()
res = brain.search(q, k=3)
dt_s = time.time() - t_s
print(f'  query: "{q}"')
print(f"  {dt_s:.3f}s, {len(res)} hits")
for i, r in enumerate(res):
    print(f"    Top-{i+1}: {r}")

print("\n" + "=" * 60)
print(f"[SUMMARY] import={dt_import:.2f}s  write3={dt_add:.2f}s  search={dt_s*1000:.0f}ms")
print("=" * 60)
