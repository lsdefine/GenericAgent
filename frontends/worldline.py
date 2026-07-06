"""GA 世界线(Rewind / checkpoint)统一后端 —— **UI 无关,单文件,tui/gui 共用**。

三块合一(本文件不含任何 Textual/前端交互逻辑,只产数据与做存储):
  1. **持久化**(`RewindStore`):content-addressable blob + checkpoint 树 + 全持久化。
     - 统一 **checkpoint 树**;**content-addressable blob**(内容 sha256 去重);
     - 只追 `file_write`/`file_patch`(路径由调用方在 `tool_before` 钩子喂入);
     - **global baseline**(每文件「首次改前」)解决「回退到该文件被追踪之前」。
  2. **视图模型 + 压缩**(`CheckpointTree`/`tree_from_store`/`CompressedTree`):把真实
     store 投影成只读树并强制折叠线性段,供任何前端渲染。
  3. **导航数学 + 恢复编排**(`next_same_depth`/`nearest_depth_node`/`restore_plan`):
     纯计算;`restore_plan` 算出回退后的 history/文件/prefill 并落地(改文件+移 HEAD+
     重写投影),前端只管把结果刷到自己的界面。

参考 Claude Code file-history 思路,按 GA 改造。纯 Python、可离线测试;线程安全交调用方
(agent 跑在子线程,约定仅 agent 空闲时 restore)。详见需求文档(ga_rewind_tui_requirements)。
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from rich.cells import cell_len, set_cell_size

# 该值为 None 表示「该版本文件不存在」（对应 CC 的 backupFileName: null）。
_ABSENT = None


class RewindStore:
    """一个 session 的 checkpoint 树 + blob 库。

    用法（典型时序）：
        store = RewindStore(root, cwd)
        # 改前（tool_before 钩子，file_write/file_patch 执行前）：
        store.track_pre_edit(abs_path)
        # ...工具实际写盘...
        # 段末（用户提问边界 / turn 收尾）：
        store.commit("修复 stdout", hist_len=42)
        # 浏览 / 恢复：
        store.apply_code(node_id)        # 把工作区还原到该节点
        store.rewind_head(node_id)       # 只移 HEAD（下次 commit 即从此分叉）
    """

    def __init__(self, root: str, cwd: str) -> None:
        self.root = os.path.abspath(root)
        self.cwd = os.path.realpath(cwd)   # realpath：与 key() 同基准，解析 junction/symlink
        self.objects_dir = os.path.join(self.root, "objects")
        self.tree_path = os.path.join(self.root, "tree.json")

        # id -> {parent, children[], title, created, kind, hist_len, files{rel: hash|None}}
        self.nodes: dict[str, dict] = {}
        self.head: str | None = None
        self.root_id: str | None = None
        self._seq = 0
        # 全局：每个被追踪文件的「首次改前」状态（hash 或 None=当时不存在）。
        self.baseline: dict[str, str | None] = {}
        self.tracked: set[str] = set()

        # 段内暂存：本段触碰过的相对路径（commit 时落定）。
        self._touched: set[str] = set()

        self.load()
        if self.nodes:
            self._ensure_origin()  # 迁移:旧树(无 origin)挂一个「会话起点」根

    # --------------------------------------------------------------- origin
    def _ensure_origin(self) -> None:
        """保证存在一个虚拟根「会话起点」(空状态):所有真实 checkpoint 都是它的
        后代。幂等。第一次 commit / 迁移旧树 / resume 时调用。

        - 它代表「第一轮对话之前」,使「回退到第一个会话之前」= 普通地 rewind 到它;
        - files={} + hist_len=0 → apply_code(origin) 经 baseline 回退 = 还原到空起点;
        - 它是唯一真根 → 不会出现 forest / head=None。"""
        if any(nd.get("kind") == "origin" for nd in self.nodes.values()):
            if self.head is None:
                self.head = self.root_id
            return
        oid = "origin"
        while oid in self.nodes:
            oid += "_"
        tops = self.top_level_nodes()
        self.nodes[oid] = {"parent": None, "children": list(tops),
                           "title": "会话起点", "created": time.time(),
                           "kind": "origin", "hist_len": 0, "files": {}}
        for t in tops:
            self.nodes[t]["parent"] = oid
        self.root_id = oid
        if self.head is None:
            self.head = oid

    # ------------------------------------------------------------------ paths
    def key(self, abs_path: str) -> str:
        """路径 → 规范 key：realpath 解析 junction/symlink，使同一物理文件只有一个身份
        （workspace 的 junction 相对路径与真实绝对路径不再分裂成两个 key，避免 apply_code
        对同一文件重复回写而损坏内容）；落在 cwd 下则存相对（参考 CC maybeShortenFilePath），
        否则存绝对。"""
        ap = os.path.realpath(abs_path)
        try:
            if os.path.commonpath([ap, self.cwd]) == self.cwd:
                return os.path.relpath(ap, self.cwd).replace(os.sep, "/")
        except ValueError:
            pass  # 跨盘符（Windows）等：commonpath 抛错 → 用绝对路径
        return ap.replace(os.sep, "/")

    def _abs(self, rel: str) -> str:
        if os.path.isabs(rel) or (len(rel) > 1 and rel[1] == ":"):
            return os.path.normpath(rel)
        return os.path.normpath(os.path.join(self.cwd, rel))

    # ------------------------------------------------------------------ blobs
    def _put_blob(self, data: bytes) -> str:
        h = hashlib.sha256(data).hexdigest()
        p = os.path.join(self.objects_dir, h[:2], h)
        if not os.path.exists(p):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "wb") as f:
                f.write(zlib.compress(data, 6))
            os.replace(tmp, p)
        return h

    def _get_blob(self, h: str) -> bytes:
        with open(os.path.join(self.objects_dir, h[:2], h), "rb") as f:
            return zlib.decompress(f.read())

    def _snapshot(self, abs_path: str) -> str | None:
        """当前内容 → blob hash；文件不存在 → None。"""
        try:
            with open(abs_path, "rb") as f:
                data = f.read()
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError, PermissionError):
            return _ABSENT
        return self._put_blob(data)

    # --------------------------------------------------------------- tracking
    def track_pre_edit(self, abs_path: str) -> None:
        """改前埋点：首次见到该文件时记下它的「改前」状态作 baseline。

        幂等——同一文件同段内多次调用只在首次抓 baseline（file_patch 连改不会
        覆盖原始版本，对应 CC trackEdit 的 v1 保护）。"""
        rel = self.key(abs_path)
        self._touched.add(rel)
        if rel not in self.baseline:
            self.baseline[rel] = self._snapshot(abs_path)  # 改前内容，可能是 None
            self.tracked.add(rel)

    def commit(self, title: str, hist_len: int | None = None, kind: str = "edit",
               history: list | None = None, hist_info: list | None = None,
               key_info: str | None = None) -> str:
        """段末落节点：继承 HEAD.files，把本段触碰文件的「改后」内容写进新节点。

        `history` 给定时(对话树化)：切 `history[parent.hist_len:当前]` 为本轮对话增量，
        存成 content-addressable conv blob，节点记其 hash + `hist_len=len(history)`。
        此刻索引可靠 → 增量精确，恢复时沿路径拼回即可，不再靠会漂的绝对下标。

        `hist_info`/`key_info` 给定时(工作记忆树化)：`hist_info` 是轮级摘要列表,与 conv
        同构切增量存 blob;`key_info` 是小便签(<200 token),直接内联进节点。rewind 时
        一并恢复 → 纪要与历史**硬同步**,杜绝旧 rewind「历史回退了、纪要没回」的串味。

        无触碰文件时也会落节点（纯对话推进也是 checkpoint）。返回新节点 id。"""
        self._ensure_origin()        # 第一次提交前先确保有「会话起点」根
        parent = self.head           # 至少是 origin,永不为 None
        files = dict(self.nodes[parent]["files"]) if parent is not None else {}
        for rel in self._touched:
            files[rel] = self._snapshot(self._abs(rel))  # 改后内容，删除则 None

        conv = None
        if history is not None:
            # 增量起点用【树重建的真实长度】而非 stored hist_len。原因:_rw_commit 喂的 history
            # 取自日志全量(见集成层),而 stored hist_len 可能是早先压缩态 commit 留下的脏值;
            # 删头后绝对下标会越界丢轮。以树实际已有长度为准:delta = 日志里树还没有的尾部 →
            # 既不丢轮,也能自愈此前因压缩漏掉的轮(日志只增不改,恒 ⊇ 树)。
            parent_len = len(self.rebuild_history(parent)) if parent is not None else 0
            delta = list(history[parent_len:])
            hist_len = len(history)
            conv = self._put_blob(
                json.dumps(delta, ensure_ascii=False, default=str).encode("utf-8"))

        # 工作记忆默认【从 history 派生】(与 reconcile 同口径 → 树的 WM 恒由日志重建、彼此
        # 对齐)。显式传入才尊重(测试/特殊调用)。关键:/continue 会把 handler.history_info
        # 清空,若仍取 live 纪要,长度与树派生的不一致 → 增量算空、续接后新轮纪要补不进树。
        # 从 history(集成层喂日志全量)派生则永远对齐,不受 live 纪要被重置影响。
        if history is not None and hist_info is None:
            hist_info = self._derive_hist_info(history)
        if history is not None and key_info is None:
            key_info = self._key_info_of(history)

        # 工作记忆增量(与 conv 同构):history_info 轮级摘要切本段增量存 blob;key_info
        # 覆盖式小便签直接内联。两者皆可选,老树/外部续接未传则为 None(恢复时跳过,不动现场)。
        hinfo = None
        hinfo_len = None
        if hist_info is not None:
            parent_hlen = len(self.rebuild_hist_info(parent)) if parent is not None else 0
            hdelta = list(hist_info[parent_hlen:])
            hinfo_len = len(hist_info)
            hinfo = self._put_blob(
                json.dumps(hdelta, ensure_ascii=False, default=str).encode("utf-8"))

        nid = self._new_id()
        self.nodes[nid] = {
            "parent": parent,
            "children": [],
            "title": title,
            "created": time.time(),
            "kind": kind,
            "hist_len": hist_len,
            "files": files,
            "conv": conv,
            "hinfo": hinfo,
            "hinfo_len": hinfo_len,
            "kinfo": key_info,
        }
        if parent is not None:
            self.nodes[parent]["children"].append(nid)
        elif self.root_id is None or self.root_id not in self.nodes:
            self.root_id = nid   # 只认第一个根;rewind-到-根之前再提交会产生第二个顶层节点(forest)
        self.head = nid
        self._touched.clear()
        self.save()
        return nid

    def commit_bridge(self, *, parent: str, conv_delta: list | None,
                      hinfo_delta: list | None, kinfo: str | None,
                      files_override: dict | None, title: str,
                      rw_tag: str) -> str:
        """落一个**桥接节点**(仅会话/仅代码回退用):承载「对话与代码来自不同节点」的
        交叉态,使该状态成为树里的一等节点(三种回退模式对它都可用)。

        与 `commit` 的区别:不走 `_touched`/继承派生,对话/WM 增量与文件均**显式给定**。
        - `conv_delta`/`hinfo_delta`:本节点自带的对话/纪要增量(list),存 blob(内容寻址,
          大多复用已有 blob);None 则不带(空会话桥接)。
        - `kinfo`:覆盖式便签,直接内联。
        - `files_override`:显式 files map;None → 继承 parent。
        - `rw_tag`:来源标注(`仅会话回退`/`仅代码回退`/`仅会话回退到聊天起点`),独立于 title。

        parent 必须是现存节点(由 restore_plan 保证)。返回新节点 id,HEAD 指向它。"""
        if parent not in self.nodes:
            parent = self.root_id if self.root_id in self.nodes else self.head
        files = (dict(files_override) if files_override is not None
                 else dict(self.nodes[parent]["files"]))
        conv = None
        if conv_delta:
            conv = self._put_blob(
                json.dumps(conv_delta, ensure_ascii=False, default=str).encode("utf-8"))
        hinfo = None
        hinfo_len = None
        if hinfo_delta:
            hinfo_len = len(self.rebuild_hist_info(parent)) + len(hinfo_delta)
            hinfo = self._put_blob(
                json.dumps(hinfo_delta, ensure_ascii=False, default=str).encode("utf-8"))
        nid = self._new_id()
        self.nodes[nid] = {
            "parent": parent,
            "children": [],
            "title": title,
            "created": time.time(),
            "kind": "edit",
            "hist_len": len(self.rebuild_history(parent)) + len(conv_delta or []),
            "files": files,
            "conv": conv,
            "hinfo": hinfo,
            "hinfo_len": hinfo_len,
            "kinfo": kinfo,
            "rw_tag": rw_tag,
        }
        self.nodes[parent]["children"].append(nid)
        self.head = nid
        self._touched.clear()
        self.save()
        return nid

    # ------------------------------------------------------------- navigation
    def rewind_head(self, node_id) -> None:
        """移动 HEAD(不动文件)。从非叶 HEAD 下次 commit 即 append 子节点 = fork。
        node_id=None 表示「回到根之前」(空起点),下次 commit 产生新的顶层节点。"""
        if node_id is not None and node_id not in self.nodes:
            raise KeyError(node_id)
        self.head = node_id
        self.save()

    def top_level_nodes(self) -> list[str]:
        """所有顶层节点(parent 为 None 或父已不存在)。通常一个 root,rewind-到-根
        之前再提交会出现多个(forest)。"""
        return [nid for nid, nd in self.nodes.items()
                if nd.get("parent") is None or nd.get("parent") not in self.nodes]

    def _target_state(self, node_id: str, rel: str):
        """文件 rel 在 node_id 时应有的状态：节点 files 里有就用它，否则回退到
        baseline（CC 的 first-version）。返回 (known: bool, hash_or_None)。"""
        files = self.nodes[node_id]["files"]
        if rel in files:
            return True, files[rel]
        if rel in self.baseline:
            return True, self.baseline[rel]
        return False, None

    def apply_code(self, node_id) -> list[tuple[str, str]]:
        """把工作区文件还原到 node_id 的状态。`node_id=None` → 还原到 baseline
        (任何 checkpoint 之前的原始状态,用于「回退到根之前」)。

        - **只动本 store 追踪过的路径**（self.tracked），绝不碰未记录文件。
        返回 [(rel, action)]，action ∈ {restored, deleted}。"""
        if node_id is not None and node_id not in self.nodes:
            raise KeyError(node_id)

        changed: list[tuple[str, str]] = []
        for rel in self.tracked:
            if node_id is None:
                known = rel in self.baseline
                target = self.baseline.get(rel)
            else:
                known, target = self._target_state(node_id, rel)
            if not known:
                continue
            ap = self._abs(rel)
            cur = self._snapshot(ap)
            if cur == target:
                continue
            if target is _ABSENT:
                try:
                    os.remove(ap)
                    changed.append((rel, "deleted"))
                except FileNotFoundError:
                    pass
            else:
                os.makedirs(os.path.dirname(ap) or ".", exist_ok=True)
                with open(ap, "wb") as f:
                    f.write(self._get_blob(target))
                changed.append((rel, "restored"))
        return changed

    def diff(self, node_id: str) -> list[dict]:
        """选中节点 vs 当前工作区，逐文件变更摘要（恢复到该节点会发生什么）。

        返回 [{rel, action, insertions, deletions}]，仅列出会变的文件。
        action: restore（覆盖）/ delete（删除）/ create（重建被删文件）。"""
        if node_id not in self.nodes:
            raise KeyError(node_id)
        out: list[dict] = []
        for rel in sorted(self.tracked):
            known, target = self._target_state(node_id, rel)
            if not known:
                continue
            cur = self._snapshot(self._abs(rel))
            if cur == target:
                continue
            old = self._text(cur)        # 当前工作区内容
            new = self._text(target)     # 该节点内容（恢复目标）
            ins = dele = 0
            for line in difflib.ndiff(old.splitlines(), new.splitlines()):
                if line.startswith("+ "):
                    ins += 1
                elif line.startswith("- "):
                    dele += 1
            if target is _ABSENT:
                action = "delete"
            elif cur is _ABSENT:
                action = "create"
            else:
                action = "restore"
            out.append({"rel": rel, "action": action, "insertions": ins, "deletions": dele})
        return out

    def node_diff(self, node_id) -> list[dict]:
        """选中节点 vs **父节点**的逐文件内容 diff(= 这次 checkpoint 改了什么)。
        返回 [{rel, old, new}](文本),仅含两者不同的文件;父缺失/文件不存在 → 空文本。
        供 UI 渲染逐行 diff(区别于 `diff()` 的"节点 vs 当前工作区"计数摘要)。"""
        if node_id not in self.nodes:
            return []
        nd = self.nodes[node_id]
        par = nd.get("parent")
        pf = self.nodes[par]["files"] if par in self.nodes else {}
        nf = nd.get("files") or {}
        out: list[dict] = []
        for rel in sorted(set(nf) | set(pf)):
            nh = nf.get(rel)
            # 「上一个状态」:父节点记录过就用它;父节点没有(本节点首次触碰该文件)→
            # 回退到 baseline(首次改前内容,CC first-version)。否则被 file_patch 修改的
            # 已有文件会因父节点无记录而被误显示成整文件新增,而非真正的逐行 diff。
            ph = pf[rel] if rel in pf else self.baseline.get(rel)
            if nh == ph:
                continue
            out.append({"rel": rel, "old": self._text(ph), "new": self._text(nh)})
        return out

    def node_line_delta(self, node_id) -> tuple[int, int]:
        """本节点相对父节点的 (新增行, 删除行) 合计，仅计 file_write/file_patch 追踪的
        文件。供 rewind/worldline 显示「代码变动行数」。"""
        ins = dele = 0
        for f in self.node_diff(node_id):
            for line in difflib.ndiff(f["old"].splitlines(), f["new"].splitlines()):
                if line.startswith("+ "):
                    ins += 1
                elif line.startswith("- "):
                    dele += 1
        return ins, dele

    def _text(self, h: str | None) -> str:
        if h is _ABSENT:
            return ""
        try:
            return self._get_blob(h).decode("utf-8", "replace")
        except Exception:
            return ""

    # --------------------------------------------------------- delete + gc
    def delete_subtree(self, node_id: str) -> list[str]:
        """删除节点及其整棵子树（不能删 HEAD 祖先路径上的节点 / root 由调用方把关）。
        返回被删的节点 id 列表。删后做一次 blob GC。"""
        if node_id not in self.nodes:
            raise KeyError(node_id)
        victims: list[str] = []

        def collect(nid: str) -> None:
            victims.append(nid)
            for c in list(self.nodes[nid]["children"]):
                collect(c)

        collect(node_id)
        parent = self.nodes[node_id]["parent"]
        if parent is not None:
            self.nodes[parent]["children"] = [
                c for c in self.nodes[parent]["children"] if c != node_id
            ]
        for nid in victims:
            self.nodes.pop(nid, None)
        if node_id == self.root_id:
            self.root_id = None
        if self.head in victims:
            self.head = parent  # HEAD 被删 → 退到父
        self._gc()
        self.save()
        return victims

    def _gc(self) -> int:
        """删除无人引用的 blob。返回删除数。"""
        referenced: set[str] = set()
        for node in self.nodes.values():
            for h in node["files"].values():
                if h is not _ABSENT:
                    referenced.add(h)
            ch = node.get("conv")          # 对话增量 blob 也是引用
            if ch:
                referenced.add(ch)
            hh = node.get("hinfo")         # 工作记忆纪要增量 blob 同样是引用
            if hh:
                referenced.add(hh)
        for h in self.baseline.values():
            if h is not _ABSENT:
                referenced.add(h)
        removed = 0
        if not os.path.isdir(self.objects_dir):
            return 0
        for sub in os.listdir(self.objects_dir):
            d = os.path.join(self.objects_dir, sub)
            if not os.path.isdir(d):
                continue
            for h in os.listdir(d):
                if h not in referenced:
                    try:
                        os.remove(os.path.join(d, h))
                        removed += 1
                    except OSError:
                        pass
        return removed

    # ------------------------------------------------------------ persistence
    def save(self) -> None:
        os.makedirs(self.root, exist_ok=True)
        payload = {
            "nodes": self.nodes,
            "head": self.head,
            "root": self.root_id,
            "seq": self._seq,
            "baseline": self.baseline,
            "tracked": sorted(self.tracked),
        }
        tmp = self.tree_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, default=str)
        # 崩溃兜底：替换前把上一份完好的 tree.json 留作 .bak（load 损坏时回退它）。
        if os.path.exists(self.tree_path):
            try:
                shutil.copyfile(self.tree_path, self.tree_path + ".bak")
            except OSError:
                pass
        os.replace(tmp, self.tree_path)

    def load(self) -> None:
        """加载树。主文件损坏/缺失 → 回退 .bak；都不行 → 留空 store（降级，不抛）。"""
        for path in (self.tree_path, self.tree_path + ".bak"):
            if not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                continue   # 损坏 → 尝试下一个候选
            self.nodes = d.get("nodes", {})
            self.head = d.get("head")
            self.root_id = d.get("root")
            self._seq = d.get("seq", 0)
            self.baseline = d.get("baseline", {})
            self.tracked = set(d.get("tracked", []))
            return

    def _new_id(self) -> str:
        self._seq += 1
        return f"v{self._seq}"

    # ---------------------------------------------------------- session key
    @staticmethod
    def key_for_log(log_path: str) -> str:
        """会话 key = log_path 的 basename 去扩展名,如 `model_responses_123456`。
        这是 GA 唯一稳定、/continue 据以识别会话的身份(task_dir 是 PID 级、重启即变,
        不能用)。"""
        return os.path.splitext(os.path.basename(log_path))[0]

    @classmethod
    def for_log(cls, temp_dir: str, log_path: str, cwd: str) -> "RewindStore":
        """按 GA 的 log_path 落到 `temp/.ga_rewind/<key>/`。"""
        root = os.path.join(temp_dir, ".ga_rewind", cls.key_for_log(log_path))
        return cls(root, cwd)

    def resume_from(self, old_root: str) -> bool:
        """/continue 续接:把旧会话的 rewind 目录接到本 store(贴近 CC 的
        copyFileHistoryForResume)。

        GA 每个新 agent 生成新 log_path → 新 key,旧会话的树/blob 默认看不到;
        这里在新 key 下重建:① 接管旧 tree.json(仅当本 store 尚为空);
        ② blob 内容寻址,直接 hardlink(同名即同内容,跳过;失败回退 copy)。
        返回是否接管成功。"""
        if not os.path.isdir(old_root) or os.path.abspath(old_root) == self.root:
            return False
        old_tree = os.path.join(old_root, "tree.json")
        if not self.nodes and os.path.exists(old_tree):
            try:
                with open(old_tree, encoding="utf-8") as f:
                    d = json.load(f)
                self.nodes = d.get("nodes", {})
                self.head = d.get("head")
                self.root_id = d.get("root")
                self._seq = d.get("seq", 0)
                self.baseline = d.get("baseline", {})
                self.tracked = set(d.get("tracked", []))
            except Exception:
                return False
        old_objects = os.path.join(old_root, "objects")
        if os.path.isdir(old_objects):
            for sub in os.listdir(old_objects):
                sd = os.path.join(old_objects, sub)
                if not os.path.isdir(sd):
                    continue
                dd = os.path.join(self.objects_dir, sub)
                os.makedirs(dd, exist_ok=True)
                for h in os.listdir(sd):
                    dst = os.path.join(dd, h)
                    if os.path.exists(dst):
                        continue  # 内容寻址:同名即同内容
                    src = os.path.join(sd, h)
                    try:
                        os.link(src, dst)          # hardlink 不占额外空间
                    except OSError:
                        try:
                            shutil.copyfile(src, dst)  # 跨盘/不支持 → 回退 copy
                        except OSError:
                            pass
        if self.nodes:
            self._ensure_origin()  # 旧树若无 origin,迁移补上
        self.save()
        return True

    # ------------------------------------------------------------------ views
    def linear_path(self) -> list[str]:
        """root → HEAD 的线性路径（节点 id），供 /rewind 时间线展示。"""
        return self.path_to(self.head)

    def path_to(self, node_id) -> list[str]:
        """root → node_id 的节点 id 列表（含两端）。node_id 缺失 → []。"""
        if node_id is None or node_id not in self.nodes:
            return []
        chain: list[str] = []
        cur: str | None = node_id
        while cur is not None and cur in self.nodes:
            chain.append(cur)
            cur = self.nodes[cur].get("parent")
        chain.reverse()
        return chain

    # ----------------------------------------------------------- conversation
    _PM_BLOCK_RE = re.compile(r"\s*-{3,}\s*\[PROJECT MODE:.*?(?:\n-{3,}\s*|$)", re.DOTALL)

    @classmethod
    def _strip_project_mode(cls, text: str) -> str:
        """剔除 project_mode 插件注入块(可出现在旧 WORKING MEMORY 文本中间)。"""
        return cls._PM_BLOCK_RE.sub("", text or "")

    def _node_conv(self, node_id) -> list:
        """单节点的对话增量（list）。无 conv / 读失败 → []（容错降级）。

        runtime history 尊重当时真实 prompt,包括 project_mode 的当轮注入;用户可见
        投影(标题/prefill/turn_sig/history_info)在各自入口清洗。"""
        h = self.nodes.get(node_id, {}).get("conv")
        if not h:
            return []
        try:
            data = json.loads(self._get_blob(h).decode("utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def rebuild_history(self, node_id) -> list:
        """沿 root→node_id 拼接各节点对话增量，整体重建 `backend.history`。

        这是「树=真相源」的恢复入口：选任意节点（含旁支）都能精确还原其对话，
        不依赖内存里那条线性 history。origin / 无 conv 的节点贡献空增量。"""
        hist: list = []
        for nid in self.path_to(node_id):
            hist.extend(self._node_conv(nid))
        return hist

    # ------------------------------------------------------ 工作记忆(随对话回退)
    def _node_hinfo(self, node_id) -> list:
        """单节点的 working-memory 纪要增量（list）。无 / 读失败 → []（容错降级）。"""
        h = self.nodes.get(node_id, {}).get("hinfo")
        if not h:
            return []
        try:
            data = json.loads(self._get_blob(h).decode("utf-8"))
            if not isinstance(data, list):
                return []
            return [self._strip_project_mode(str(x)) for x in data]
        except Exception:
            return []

    def rebuild_hist_info(self, node_id) -> list:
        """沿 root→node_id 拼接各节点纪要增量，重建 `handler.history_info`。
        与 `rebuild_history` 同构：纪要随对话一起精确回退，恢复后两者自洽。"""
        out: list = []
        for nid in self.path_to(node_id):
            out.extend(self._node_hinfo(nid))
        return out

    def key_info_at(self, node_id) -> str:
        """node_id 处生效的 key_info：沿 root→node 取最后一个非 None 的 `kinfo`
        （key_info 是覆盖式小便签，不像纪要那样累加）。无则空串。"""
        ki = ""
        for nid in self.path_to(node_id):
            v = self.nodes[nid].get("kinfo")
            if v is not None:
                ki = v
        return ki

    def path_has_wm(self, node_id) -> bool:
        """root→node 路径上是否记录过工作记忆（hinfo/kinfo）。老树（本特性之前）
        全为 None → False：恢复时据此跳过 WM 同步，不抹掉现场纪要（向后兼容）。"""
        for nid in self.path_to(node_id):
            nd = self.nodes.get(nid, {})
            if nd.get("hinfo") is not None or nd.get("kinfo") is not None:
                return True
        return False

    # ----------------------------------------------------- 对账(防外部改写灾难)
    @classmethod
    def _msg_user_text(cls, msg) -> str:
        """真实用户提问文本;非 user / 自动注入轮 → ""(不算提问边界)。"""
        if not isinstance(msg, dict) or msg.get("role") != "user":
            return ""
        c = msg.get("content")
        if isinstance(c, str):
            text = cls._strip_project_mode(c)
        elif isinstance(c, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                return ""
            text = cls._strip_project_mode(" ".join(
                b.get("text", "") for b in c
                if isinstance(b, dict) and b.get("type") == "text"))
        else:
            return ""
        text = (text or "").strip()
        inject_markers = ("### [WORKING MEMORY]", "[SYSTEM TIPS]", "[DANGER]",
                          "### [总结提炼经验]", "Continue from where you left off")
        if not text or text.startswith(inject_markers):
            return ""
        return text

    @classmethod
    def _turn_sig(cls, msgs) -> list:
        """一段消息的「对话身份」= 其中真实用户提问的文本序列(跳过 tool_result 轮,
        故不含注入的易变内容)。用于 reconcile 判两段是否同一对话。"""
        return [t for t in (cls._msg_user_text(m).strip() for m in msgs) if t]

    # ---------------------------------- 从日志/历史重建工作记忆(reconcile 吸收外部轮时补 WM)
    @staticmethod
    def _all_text(msg) -> str:
        """消息里所有 text block 的拼接(含 tool_result 轮注入的 WORKING MEMORY 文本)。"""
        if not isinstance(msg, dict):
            return ""
        c = msg.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return "\n".join(b.get("text", "") for b in c
                             if isinstance(b, dict) and b.get("type") == "text")
        return ""

    @classmethod
    def _summary_of(cls, msg) -> str:
        """从 assistant 消息提取 `<summary>`(GA 轮级纪要的来源);无则退化取首行。
        与 ga.turn_end_callback 的提取口径一致,使从日志重建的 history_info 贴近原值。"""
        text = re.sub(r'```.*?```|<thinking>.*?</thinking>', '',
                      cls._all_text(msg), flags=re.DOTALL)
        m = re.search(r'<summary>(.*?)</summary>', text, re.DOTALL)
        if m and m.group(1).strip():
            return m.group(1).strip()[:80]
        for line in text.splitlines():
            if line.strip():
                return line.strip()[:80]
        return "（无摘要）"

    @classmethod
    def _derive_hist_info(cls, history) -> list:
        """从对话历史重建 `handler.history_info`(轮级纪要):真实用户提问 → `[USER]: …`;
        每条 assistant(=一轮) → `[Agent] <summary>`。这正是 GA 原本构建 history_info 的
        方式,故 reconcile 从日志吸收外部/老会话轮次时可据此把工作记忆补回(否则续接后
        rewind 到这些轮,纪要会缺失 → 串味)。"""
        out: list = []
        for m in history:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            if role == "user":
                q = cls._msg_user_text(m).strip()   # tool_result 轮 → ""(非提问,不计)
                if q:
                    out.append(f"[USER]: {q}")
            elif role == "assistant":
                out.append(f"[Agent] {cls._summary_of(m)}")
        return out

    @classmethod
    def _key_info_of(cls, history) -> Optional[str]:
        """取历史里最后一个注入的 `<key_info>…</key_info>`(agent 便签);无则 None。"""
        ki = None
        for m in history:
            for mt in re.finditer(r'<key_info>(.*?)</key_info>', cls._all_text(m), re.DOTALL):
                ki = mt.group(1).strip()
        return ki

    def reconcile(self, history: list) -> int:
        """把 live history 里树尚未记录的尾部轮次吸收成节点,使树追平日志。

        ⚠️ **契约**:`history` 必须是**日志解析出的全量历史**(`_parse_native_history`),
        **禁止传压缩态的 `backend.history`**。对账是「日志 ↔ 树」两个全量真相源之间的事;
        喂压缩/删头后的内存会让全量的树去迁就残缺副本——前缀比对失败 → 误判分歧 → 弃树
        另起(详见下方安全闸)。调用方负责从日志取全量历史。

        用途:别的(不更新树的)UI 往同一日志追加后树会滞后;一旦在滞后状态 rewind,
        `rewrite_projection` 会拿陈旧树回写、**抹掉那些外部轮次**(灾难性丢失)。
        对账后树恒 ⊇ 日志,故 rewind 物理上不可能 clobber 未见过的轮次。

        **安全闸**:仅当树 HEAD 路径与 history 前缀是「同一段对话」才在其上 append;
        否则判为分歧(用户问了不同的问题),HEAD 退回 origin 另起一条顶层 trunk 容纳
        live history,旧树保留为旁支、绝不拿它回写日志。空树 = n=0 特例(吸收全部,
        即旧 _bootstrap_conv_tree)。幂等:无尾巴 → no-op,可任意重复调用。返回吸收条数。

        判「同一段对话」用**用户提问序列**(`_turn_sig`)而非逐条全等:消息里会被注入
        易变内容(如 `[WORKING MEMORY]`,只在 tool_result 轮),同一段对话在不同时刻
        捕获并不逐字节相等;逐条全等会把它误判成分歧、复制出一整条重复 trunk。提问
        文本在 tool_result 轮之外、稳定不变,是可靠的对话身份。"""
        history = list(history or [])
        self._ensure_origin()
        head = self.head if self.head in self.nodes else self.root_id
        known = self.rebuild_history(head)
        n = len(known)
        if self._turn_sig(history[:n]) != self._turn_sig(known):
            # 分歧(提问序列不同):不信任陈旧树。退回空起点,后续 append 只反映 live history。
            self.rewind_head(self.root_id)
            n = len(self.rebuild_history(self.root_id))   # origin 无 conv → 0
        if len(history) <= n:
            return 0
        # 按用户提问边界切尾巴 [n, len);逐段 commit(history=history[:段末]),
        # commit 内部 delta = history[parent.hist_len:段末]。清 _touched 保证纯 conv-only。
        starts = [i for i in range(n, len(history))
                  if self._msg_user_text(history[i]).strip()]
        if not starts or starts[0] > n:
            starts = [n] + starts
        self._touched.clear()
        absorbed = 0
        for p, s in enumerate(starts):
            end = starts[p + 1] if p + 1 < len(starts) else len(history)
            title = next((self._msg_user_text(history[i]).strip()
                          for i in range(s, end)
                          if self._msg_user_text(history[i]).strip()), "")
            title = (title or "（外部续接）").replace("\n", " ").strip()[:80]
            seg_hist = list(history[:end])
            # 吸收时一并从日志重建工作记忆 → 续接/外部轮也能随 rewind 同步纪要(修缺口B)。
            self.commit(title or "（外部续接）", kind="edit", history=seg_hist,
                        hist_info=self._derive_hist_info(seg_hist),
                        key_info=self._key_info_of(seg_hist))
            absorbed += end - s
        return absorbed

    def first_user_message(self, node_id) -> dict | None:
        """node_id 对话增量里的首条 `role==user` 消息（原始 dict）；无则 None。

        供 rewind 后精确 prefill（取「该提问本身」，不靠会漂的绝对下标）。文本提取
        交调用方（消息内容格式是 GA backend 私有的）。"""
        for msg in self._node_conv(node_id):
            if isinstance(msg, dict) and msg.get("role") == "user":
                return msg
        return None

    def first_question(self) -> Optional[str]:
        """当前 HEAD 路径上**第一条真实用户提问**的文本;空树 → None。沿路径读各节点
        conv（通常首个真实节点即命中,O(1) blob 读）。供集成层**廉价检测 backend.history
        是否被删头**:删头先 pop 掉首问,故 live 首问与此对不上 ⇒ 删过头(该回退到日志)。"""
        for nid in self.path_to(self.head):
            for msg in self._node_conv(nid):
                t = self._msg_user_text(msg).strip()
                if t:
                    return t
        return None


# ============================================================================
# 世界线视图模型 + 压缩 + 导航(从 rewind_tree_view.py 抽出的 UI 无关后端)
# ============================================================================
# 节点**语义**(字形 + 文字标签);**呈现色由前端决定**(颜色不属于后端)。
KIND_GLYPH = {"current": "◉", "rewind": "↩", "origin": "●"}  # ◉=当前所在;●=普通/根
KIND_LABEL = {"current": "当前位置", "rewind": "回退来源", "origin": "会话起点"}


def kind_glyph(kind: str) -> str:
    return KIND_GLYPH.get(kind, "●")


def kind_label(kind: str) -> str:
    return KIND_LABEL.get(kind, "")


def rel_time(ago_s) -> str:
    if ago_s is None:
        return ""
    if ago_s < 60:
        return "刚刚"
    m = ago_s // 60
    if m < 60:
        return f"{m} 分钟前"
    h = m // 60
    if h < 24:
        return f"{h} 小时前"
    return f"{h // 24} 天前"


def files_summary(files: List[str]) -> str:
    if not files:
        return "无变更"
    if len(files) <= 3:
        return "、".join(files)
    return "、".join(files[:3]) + f" (+{len(files) - 3})"


_TITLE_MAX_CELLS = 54   # 左树标题截断宽度，对应 worldline 左栏 60%（3:2 布局）


def ellipsize(s: str, max_cells: int = _TITLE_MAX_CELLS) -> str:
    """按显示宽度(中文算 2 格)截断,超长加 `…`。用于左树/右上的长提问标题。"""
    s = (s or "").replace("\n", " ").strip()
    if cell_len(s) <= max_cells:
        return s
    return set_cell_size(s, max(1, max_cells - 1)).rstrip() + "…"


# --------------------------------------------------------------- 数据模型
@dataclass
class CheckpointNode:
    id: str
    title: str
    parent_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    kind: str = "edit"
    files: List[str] = field(default_factory=list)
    ago: Optional[int] = 0
    rw_tag: Optional[str] = None  # 桥接来源标注(仅会话/仅代码回退);普通节点 None


class CheckpointTree:
    """只读视图树(供压缩/渲染);从 RewindStore 构造。"""

    def __init__(self) -> None:
        self.nodes: Dict[str, CheckpointNode] = {}
        self.root_id: Optional[str] = None


def _changed_files(store, node_id) -> List[str]:
    import os
    nd = store.nodes[node_id]
    par = nd.get("parent")
    pf = store.nodes[par]["files"] if par in store.nodes else {}
    out: List[str] = []
    for k, v in nd["files"].items():
        if pf.get(k) != v:
            b = os.path.basename(k)
            if b not in out:
                out.append(b)
    return out


def tree_from_store(store, now: float) -> CheckpointTree:
    """把 RewindStore 的真实树投影成只读 CheckpointTree;HEAD 标 current。"""
    t = CheckpointTree()
    for nid, nd in store.nodes.items():
        t.nodes[nid] = CheckpointNode(
            id=nid,
            title=store._strip_project_mode(nd.get("title") or "（空）").replace("\n", " ").strip() or "（空）",
            parent_id=nd.get("parent"),
            children=[c for c in nd.get("children", []) if c in store.nodes],
            kind="current" if nid == store.head else nd.get("kind", "edit"),
            files=_changed_files(store, nid),
            ago=int(max(0, now - nd.get("created", now))),
            rw_tag=nd.get("rw_tag"),
        )
    t.root_id = store.root_id
    return t


# --------------------------------------------- 压缩(强制折叠线性段,§4.2)
@dataclass
class DisplayNode:
    key: int
    kind: str  # 'real' | 'fold'
    depth: int = 0
    parent_key: Optional[int] = None
    children: List[int] = field(default_factory=list)
    node_id: Optional[str] = None
    seg: List[str] = field(default_factory=list)
    end_id: Optional[str] = None


class CompressedTree:
    def __init__(self, tree: CheckpointTree) -> None:
        self.tree = tree
        self.disp: Dict[int, DisplayNode] = {}
        self.roots: List[int] = []   # 顶层显示节点 keys(通常一个 = origin)
        self._k = 0
        # 顶层节点(origin「会话起点」)常驻独立显示作锚点;它下面的真实对话链
        # 照常折叠(§4.2)。origin 是「第一轮对话之前」的空状态,不是某轮对话,
        # 所以独立显示语义清晰、不会像"第一轮对话被强行拎出"那样让人困惑。
        for top in self._top_level():
            self._build_root_node(top)

    def _top_level(self) -> List[str]:
        return [nid for nid, n in self.tree.nodes.items()
                if n.parent_id is None or n.parent_id not in self.tree.nodes]

    def _new_key(self) -> int:
        k = self._k
        self._k += 1
        return k

    def _build_root_node(self, root_id: str) -> int:
        key = self._new_key()
        self.disp[key] = DisplayNode(key=key, kind="real", node_id=root_id, depth=0)
        self.roots.append(key)
        for child_id in self.tree.nodes[root_id].children:
            self._build_chain(child_id, 1, key)
        return key

    def _build_chain(self, start_id: str, depth: int, parent: Optional[int]) -> int:
        seg = [start_id]
        cur = start_id
        while len(self.tree.nodes[cur].children) == 1:
            cur = self.tree.nodes[cur].children[0]
            seg.append(cur)
        end = seg[-1]
        key = self._new_key()
        if len(seg) == 1:
            self.disp[key] = DisplayNode(key=key, kind="real", node_id=end,
                                         depth=depth, parent_key=parent)
        else:
            self.disp[key] = DisplayNode(key=key, kind="fold", depth=depth,
                                         parent_key=parent, seg=list(seg), end_id=end)
        if parent is None:
            self.roots.append(key)
        else:
            self.disp[parent].children.append(key)
        for child_id in self.tree.nodes[end].children:
            self._build_chain(child_id, depth + 1, key)
        return key

    def flatten(self) -> List[int]:
        order: List[int] = []

        def dfs(k: int) -> None:
            order.append(k)
            for c in self.disp[k].children:
                dfs(c)

        for r in self.roots:
            dfs(r)
        return order

    def end_node(self, key: int) -> CheckpointNode:
        d = self.disp[key]
        return self.tree.nodes[d.node_id if d.kind == "real" else d.end_id]

    def label(self, key: int) -> str:
        # 真实/折叠都只放末端标题(截断);折叠的 [N nodes] 标记放在 glyph 位(标题前)。
        d = self.disp[key]
        nid = d.node_id if d.kind == "real" else d.end_id
        return ellipsize(self.tree.nodes[nid].title)

    def glyph(self, key: int) -> str:
        # 折叠节点开头用 [N nodes] 替代原来的 … 省略号(→ "[3 nodes] 标题");
        # 真实节点仍用语义字形(● / ↩ / ◉)。
        d = self.disp[key]
        if d.kind == "fold":
            return f"[{len(d.seg)} nodes]"
        return kind_glyph(self.tree.nodes[d.node_id].kind)


# ----------------------------------------------------- 导航(纯计算)
def _order_depths(ct: CompressedTree) -> List[tuple[int, int]]:
    return [(k, ct.disp[k].depth) for k in ct.flatten()]


def next_same_depth(order, sel, direction):
    idx = next(i for i, (k, _) in enumerate(order) if k == sel)
    depth = order[idx][1]
    same = [i for i, (_, d) in enumerate(order) if d == depth]
    pos = same.index(idx)
    return order[same[(pos + direction) % len(same)]][0]


def nearest_depth_node(order, sel, delta):
    idx = next(i for i, (k, _) in enumerate(order) if k == sel)
    target = order[idx][1] + delta
    if target < 0:
        return sel
    cand = [i for i, (_, d) in enumerate(order) if d == target]
    if not cand:
        return sel
    if delta > 0:
        best = min(cand, key=lambda i: (abs(i - idx), 0 if i >= idx else 1, i))
    else:
        best = min(cand, key=lambda i: (abs(i - idx), 0 if i <= idx else 1, -i))
    return order[best][0]



# ============================================================================
# 恢复编排(UI 无关):算出回退后的对话/文件/prefill 并落地,前端只刷新自己的显示
# ============================================================================
def user_msg_text(entry) -> str:
    """从一条 user 消息里取出用户可见文本(content 为 str 或 text block 列表)。"""
    c = entry.get("content") if isinstance(entry, dict) else None
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [b.get("text", "") for b in c
                 if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return ""


def render_native_history(history, ts=None):
    """Inverse of `continue_cmd._parse_native_history`: render a `backend.history`
    (alternating user/assistant) back into the native `=== Prompt/Response ===`
    log text. Lives here (not continue_cmd) because the rewind tree is its only
    caller — it rewrites `model_responses_<key>.txt` as a linear projection of
    the current HEAD path so /continue + other UIs get a clean single-branch view
    (the TUI itself reads only the tree). Round-trip holds:
    `_parse_native_history(_pairs(render_native_history(h))) == h`.

    Byte-for-byte matches llmcore's `_write_llm_log` for the tool backend:
    Prompt = `json.dumps(merged, ensure_ascii=False, indent=2)`; Response =
    `str(content_blocks)` which for a list equals `repr(...)` (survives
    True/False/None that JSON would emit as true/false/null and break
    `ast.literal_eval`). Only complete (user, assistant) pairs are emitted."""
    ts = ts or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    out, i, n = [], 0, len(history)
    while i < n:
        u = history[i]
        if isinstance(u, dict) and u.get('role') == 'user' and i + 1 < n:
            a = history[i + 1]
            if isinstance(a, dict) and a.get('role') == 'assistant':
                out.append(f"=== Prompt === {ts}\n{json.dumps(u, ensure_ascii=False, indent=2)}\n\n")
                out.append(f"=== Response === {ts}\n{a.get('content')!r}\n\n")
                i += 2
                continue
        i += 1
    return "".join(out)


def rewrite_projection(store, target, log_path: str) -> bool:
    """把 `model_responses_<key>.txt` 重写成 root→target 的线性投影(native
    `=== Prompt/Response ===` 格式,`continue_cmd._parse_native_history` 可解析)。

    给其他 UI + /continue 的兼容视角;消除 rewind/fork 后多分支混排。故障静默。"""
    if store is None or not log_path:
        return False
    try:
        text = render_native_history(store.rebuild_history(target))
        # 回退到「会话起点」(origin)时 history 为空 → 日志被写空(0 字节)。这是【硬】回退:
        # 日志恒等于树 HEAD,无错位,reconcile 不会复制分支。空日志会被普通 UI 的
        # list_sessions(sz<32) 无害跳过;带 worldline 的 UI 靠 list_sessions(rewind_root=...)
        # 的树感知发现 + continue_inplace(allow_empty=True) 仍能找回并恢复(空对话 + 重连树)。
        tmp = log_path + ".tmp"
        with open(tmp, "w", encoding="utf-8", errors="replace") as f:
            f.write(text)
        os.replace(tmp, log_path)
        return True
    except Exception:
        return False


def restore_plan(store, node_id, mode: str = "both", to: str = "before",
                 log_path: str = "") -> Optional[dict]:
    """UI 无关的回退编排。`to`:
      - **before**(选中段内某节点):回到该提问**之前**(连该节点一起清除),prefill 其提问;
        target = parent(node) / origin。
      - **at**(末尾占位项):在该节点处**继续**(HEAD→node,不清除、无 prefill)。
    `mode`: both/conv/code。会就地:重建对话(返回 history,调用方自行赋给 backend)、
    `apply_code`(还原文件)、移 HEAD、重写投影日志。

    返回 None(无效) 或 dict:
      {history: list|None(对话变更时), hist_info: list|None, key_info: str|None,
       changed: [(rel,action)], prefill: str,
       at_origin: bool, target: str, title: str, to: str}
    `target` 字段:both = 落点节点;conv/code = 桥接节点 id(前端 cursor 标它)。
    —— 前端据此:赋 backend.history、同步 working memory、重建界面消息、prefill 输入框、刷新。

    conv/code 落一个**桥接节点**承载「对话/代码交叉态」(见 `commit_bridge`),使该状态成为
    一等节点;both 直接还原到 target,无桥接。"""
    if store is None or not node_id or node_id not in store.nodes:
        return None
    nd = store.nodes[node_id]
    prefill = ""
    if to == "at":
        target = node_id
        at_origin = nd.get("kind") == "origin"
    else:
        parent = nd.get("parent")
        parent = parent if parent in store.nodes else None
        target = parent if parent is not None else node_id
        at_origin = parent is None
        if not at_origin:
            um = store.first_user_message(node_id)
            # 剥离 project_mode 注入块:回填输入框的是用户原话,不能夹带注入内容。
            # 树里的 user 消息取自 native 日志(含注入),user_msg_text 逐字取文本不清洗,
            # 故在此统一 _strip_project_mode(幂等,无注入块则原样返回)。
            prefill = store._strip_project_mode((user_msg_text(um) if um else "") or nd.get("title", ""))

    old_head = store.head  # 回退前的 HEAD(代码/对话的「另一侧」来源)

    def _wm_at(node_id):
        """(hist_info, key_info) @ node;树无 WM 记录 → (None, None),调用方跳过不动现场。"""
        if store.path_has_wm(node_id):
            return store.rebuild_hist_info(node_id), store.key_info_at(node_id)
        return None, None

    def _prompt_of(node_id):
        um = store.first_user_message(node_id)
        # 同 prefill:桥接节点标题也要剥离 project_mode 注入,取用户原话。
        return store._strip_project_mode(
            (user_msg_text(um) if um else "") or store.nodes.get(node_id, {}).get("title", ""))

    # ---- both:直接还原到 target(对话+代码),无桥接
    if mode == "both":
        history = store.rebuild_history(target)
        hist_info, key_info = _wm_at(target)
        changed, code_error = _apply_code_safe(store, target)
        store.rewind_head(target)
        if log_path:
            rewrite_projection(store, target, log_path)
        return _res(history, hist_info, key_info, changed, prefill,
                    at_origin, target, store._strip_project_mode(nd.get("title", "")), to,
                    code_error=code_error)

    # ---- conv:对话退到 target、代码留 old_head。桥接挂 fork(=parent(target),或 target 若 origin)
    if mode == "conv":
        tp = store.nodes[target].get("parent")
        fork = tp if tp in store.nodes else target          # target=origin → fork=origin(空会话)
        at_start = (fork == target)                          # 空会话:对话退空,无 delta 可带
        conv_delta = None if at_start else store._node_conv(target)
        hinfo_delta = None if at_start else store._node_hinfo(target)
        bridge_files = dict(store.nodes[old_head]["files"]) if old_head in store.nodes else {}
        if at_start:
            b_title, rw_tag = prefill or "会话起点", "仅会话回退到聊天起点"
        else:
            b_title, rw_tag = _prompt_of(target), "仅会话回退"
        bridge_id = store.commit_bridge(
            parent=fork, conv_delta=conv_delta, hinfo_delta=hinfo_delta,
            kinfo=store.key_info_at(target), files_override=bridge_files,
            title=b_title, rw_tag=rw_tag)
        history = store.rebuild_history(target)
        hist_info, key_info = _wm_at(target)
        store.rewind_head(bridge_id)
        if log_path:
            rewrite_projection(store, target, log_path)
        return _res(history, hist_info, key_info, [], prefill,
                    at_origin, bridge_id, store._strip_project_mode(nd.get("title", "")), to)

    # ---- code:代码退到 target、对话留 old_head。桥接按会话拓扑挂在 old_head 的父节点,
    #      自带 old_head 这一轮对话/WM,文件显式覆盖为 target 的代码状态。
    if mode == "code":
        changed, code_error = _apply_code_safe(store, target)
        conv_parent = store.nodes.get(old_head, {}).get("parent")
        conv_parent = conv_parent if conv_parent in store.nodes else old_head
        conv_delta = list(store._node_conv(old_head) or [])
        hinfo_delta = list(store._node_hinfo(old_head) or []) or None
        bridge_files = dict(store.nodes[target]["files"])
        bridge_id = store.commit_bridge(
            parent=conv_parent, conv_delta=conv_delta, hinfo_delta=hinfo_delta,
            kinfo=store.key_info_at(old_head), files_override=bridge_files,
            title=_prompt_of(old_head), rw_tag="仅代码回退")
        store.rewind_head(bridge_id)
        # 对话没动 → history=None(前端不重赋 backend.history)、不重写投影日志、
        # 不 prefill(对话未回退,输入框不该被塞入选中节点的旧提问)。
        return _res(None, None, None, changed, "",
                    at_origin, bridge_id, store._strip_project_mode(nd.get("title", "")), to,
                    code_error=code_error)

    return None  # 未知 mode


def _apply_code_safe(store, target) -> "tuple[list, Optional[str]]":
    """还原工作区代码,失败不静默:返回 (changed, code_error)。code_error 非 None 时
    表示写盘中途出错(权限/磁盘…),工作区可能处于部分回退状态——交由前端提示用户,
    而非当作「无变更」悄悄放过(apply_code 直接写用户文件,失败半径不为零)。"""
    try:
        return store.apply_code(target), None
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"


def _res(history, hist_info, key_info, changed, prefill,
         at_origin, target, title, to, *, code_error=None) -> dict:
    """restore_plan 的返回 dict 构造器。code_error:代码回退失败信息(None=成功)。"""
    return {
        "history": history,
        "hist_info": hist_info,
        "key_info": key_info,
        "changed": changed,
        "prefill": prefill,
        "at_origin": at_origin,
        "target": target,
        "title": title,
        "to": to,
        "code_error": code_error,
    }
