"""Workspace 命令的共享逻辑(tuiapp_v2 / tui_v3 复用)。

设计要点(详见对话设计稿):
  * **兼容旧入口** `plugins/project_mode.py` 与 `memory/project_mode_sop.md` 的 pid 锚。
    前端在
    `<repo>/temp/projects/<name>` 建一个指向用户真实绝对路径的目录联接(junction),
    并可按需写激活锚 `<repo>/temp/.active_project.<pid>`。project_mode 插件
    照常每轮注入 L1,并把 project_memory.md / 产物经 junction 写进真实仓库根
    (与 Claude Code 在仓库根放 CLAUDE.md 同理,已接受)。
  * **路径基准必须与插件一致**:插件的 `_TEMP` 是基于其 `__file__` 的 `<repo>/temp`
    绝对路径(非 cwd)。本模块也从自身 `__file__` 推 `<repo>/temp`(frontends/ 的上一级
    即 repo 根),两边独立计算但结果一致,互不 import。
  * **pid 语义**:插件读 `os.getpid()`(GA 进程)。前端就跑在 GA 进程里,写锚同样用
    `os.getpid()`(不是 SOP 里 code_run 子进程用的 getppid)。
  * **命名** `name = f"{basename}-{hash8}"`,hash8 = blake2b(规范化绝对路径)[:8]。
    同一 workspace 恒定同名(幂等复用);hash 后缀又让 junction 名不与其它 UI 人工命名的
    普通项目目录相撞。
  * **junction 安全**:检测用 reparse 属性(`os.path.islink` 对 junction 返回 False!);
    删除用 `os.rmdir`,**绝不 rmtree**(会击穿删真实文件)。cleanup 只动确认是 junction
    且悬空/未注册的条目,真实目录(其它 UI 的普通项目)一律不碰。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from typing import Optional


# --------------------------------------------------------------------------- #
# 路径基准(与 plugins/project_mode.py 的 _TEMP 保持一致)
# --------------------------------------------------------------------------- #
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _temp_root() -> str:
    return os.path.join(_REPO_ROOT, "temp")


def _projects_root() -> str:
    return os.path.join(_temp_root(), "projects")


def _anchor_path() -> str:
    """激活锚,pid 键控,与插件 `_ANCHOR` 同。"""
    return os.path.join(_temp_root(), f".active_project.{os.getpid()}")


def _registry_path() -> str:
    return os.path.join(_temp_root(), "workspaces.json")


_REGISTRY_VERSION = 1


# --------------------------------------------------------------------------- #
# 命名
# --------------------------------------------------------------------------- #
def _norm_abspath(p: str) -> str:
    """规范化绝对路径用于 hash:abspath + normcase(Windows 大小写不敏感 ->
    同一目录恒定同名)。不走 realpath,避免解析 junction/symlink 带来的意外。"""
    return os.path.normcase(os.path.abspath(p))


def _ws_name(abs_path: str) -> str:
    base = os.path.basename(abs_path.rstrip("/\\")) or "ws"
    digest = hashlib.blake2b(_norm_abspath(abs_path).encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"


def _link_path(name: str) -> str:
    return os.path.join(_projects_root(), name)


# --------------------------------------------------------------------------- #
# junction / symlink 跨平台封装(reparse 安全)
# --------------------------------------------------------------------------- #
def make_dir_link(target_abs: str, link_path: str) -> bool:
    """建目录联接。Windows 用 `mklink /J`(免管理员);POSIX 用 symlink。
    成功返回 True;失败打印到 stderr 并返回 False。"""
    target_abs = os.path.abspath(target_abs)
    parent = os.path.dirname(link_path)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as e:
        sys.stderr.write(f"[workspace] mkdir {parent} failed: {e}\n")
        return False
    if os.name == "nt":
        # mklink 是 cmd 内建,必须经 cmd 调用。列表传参由 subprocess 负责加引号,
        # 兼容含空格/中文的路径。
        try:
            r = subprocess.run(
                ["cmd", "/c", "mklink", "/J", link_path, target_abs],
                capture_output=True, text=True,
            )
        except OSError as e:
            sys.stderr.write(f"[workspace] mklink invoke failed: {e}\n")
            return False
        if r.returncode != 0 or not os.path.exists(link_path):
            sys.stderr.write(f"[workspace] mklink /J failed: "
                             f"{(r.stderr or r.stdout or '').strip()}\n")
            return False
        return True
    # POSIX
    try:
        os.symlink(target_abs, link_path, target_is_directory=True)
        return True
    except OSError as e:
        sys.stderr.write(f"[workspace] symlink failed: {e}\n")
        return False


def is_dir_link(path: str) -> bool:
    """是否目录联接/符号链接。**不能只用 os.path.islink**——它对 Windows junction
    返回 False。改看 reparse point 属性 + reparse tag。"""
    try:
        if os.path.islink(path):  # POSIX symlink、Windows 符号链接
            return True
    except OSError:
        return False
    if os.name != "nt":
        return False
    try:
        st = os.lstat(path)
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if not (attrs & reparse):
        return False
    # 进一步认 tag:挂载点(junction)或符号链接
    tag = getattr(st, "st_reparse_tag", 0)
    mount = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
    syml = getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C)
    if tag:
        return tag in (mount, syml)
    return True  # 有 reparse 属性但拿不到 tag,保守视作链接(我们只在此目录建链)


def link_target(path: str) -> Optional[str]:
    """读链接目标;清洗 Windows 的 \\??\\ / \\\\?\\ 前缀。失败返回 None。"""
    try:
        t = os.readlink(path)
    except OSError:
        return None
    for pre in ("\\??\\", "\\\\?\\"):
        if t.startswith(pre):
            t = t[len(pre):]
            break
    return t


def remove_dir_link(path: str) -> bool:
    """只摘掉链接本身,绝不递归删目标。Windows junction / 符号链接目录用 os.rmdir,
    POSIX symlink 用 os.unlink。**调用前务必 is_dir_link 确认。**"""
    try:
        if os.name == "nt":
            os.rmdir(path)
        else:
            os.unlink(path)
        return True
    except OSError as e:
        sys.stderr.write(f"[workspace] remove link {path} failed: {e}\n")
        return False


# --------------------------------------------------------------------------- #
# 注册表 temp/workspaces.json(本功能私有;v2/v3 可能并发 -> 原子写)
# --------------------------------------------------------------------------- #
def registry_load() -> dict:
    try:
        with open(_registry_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("version") == _REGISTRY_VERSION:
            items = data.get("items")
            if isinstance(items, dict):
                return items
    except (OSError, ValueError):
        pass
    return {}


def _registry_save(items: dict) -> None:
    path = _registry_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": _REGISTRY_VERSION, "items": items},
                      fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError as e:
        sys.stderr.write(f"[workspace] registry save failed: {e}\n")


# --------------------------------------------------------------------------- #
# 会话→工作区映射 temp/session_workspaces.json — 让 /continue 即时恢复，不必先
# 聊一轮在日志留 PROJECT MODE 块。key=会话日志名, value=workspace 真实路径,
# ""=已 off（区别于缺 key=无记录→回退扫日志）。手动操作触发、极低频，照搬注册
# 表原子写、不加锁。
# --------------------------------------------------------------------------- #
def _session_map_path() -> str:
    return os.path.join(_temp_root(), "session_workspaces.json")


def _session_map_load() -> dict:
    try:
        with open(_session_map_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("version") == _REGISTRY_VERSION:
            items = data.get("items")
            if isinstance(items, dict):
                return items
    except (OSError, ValueError):
        pass
    return {}


def _session_map_save(items: dict) -> None:
    path = _session_map_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": _REGISTRY_VERSION, "items": items},
                      fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError as e:
        sys.stderr.write(f"[workspace] session map save failed: {e}\n")


def session_ws_set(log_path: str, target: str) -> None:
    """记录会话绑定的 workspace 路径；target="" 表示该会话已 off。"""
    key = os.path.basename(log_path or "")
    if not key:
        return
    items = _session_map_load()
    items[key] = target or ""
    _session_map_save(items)


def session_ws_get(log_path: str):
    """路径=绑定 / ""=已 off / None=无记录（调用方回退扫日志）。"""
    key = os.path.basename(log_path or "")
    return _session_map_load().get(key) if key else None


def session_map_prune() -> None:
    """删掉日志文件已不存在的孤儿条目（启动时调一次）。"""
    items = _session_map_load()
    logdir = os.path.join(_temp_root(), "model_responses")
    alive = {k: v for k, v in items.items() if os.path.isfile(os.path.join(logdir, k))}
    if len(alive) != len(items):
        _session_map_save(alive)


def registry_upsert(name: str, abs_path: str) -> None:
    items = registry_load()
    items[name] = {"path": os.path.abspath(abs_path), "last_used": int(time.time())}
    _registry_save(items)


def registry_remove(name: str) -> None:
    items = registry_load()
    if items.pop(name, None) is not None:
        _registry_save(items)


def _mem_lines(link: str) -> int:
    """project_memory.md 行数(经 junction 读真实文件);读不到返回 0。"""
    mp = os.path.join(link, "project_memory.md")
    try:
        with open(mp, encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def registry_list() -> list[dict]:
    """供 picker 候选列表:[{name, path, last_used, mem_lines, dangling}],按最近使用倒序。"""
    out = []
    for name, ent in registry_load().items():
        path = (ent or {}).get("path") or ""
        out.append({
            "name": name,
            "path": path,
            "last_used": int((ent or {}).get("last_used") or 0),
            "mem_lines": _mem_lines(_link_path(name)) if path else 0,
            "dangling": not (path and os.path.isdir(path)),
        })
    out.sort(key=lambda x: x["last_used"], reverse=True)
    return out


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
def validate_path(abs_path: str) -> tuple[bool, str]:
    if not abs_path or not abs_path.strip():
        return False, "路径为空"
    p = abs_path.strip().strip('"').strip("'")
    if not os.path.isabs(p):
        return False, "需要绝对路径"
    if os.name == "nt" and p.startswith("\\\\"):
        return False, "不支持网络路径(UNC):junction 无法指向网络位置"
    if not os.path.exists(p):
        return False, f"路径不存在: {p}"
    if not os.path.isdir(p):
        return False, "不是目录"
    if _norm_abspath(p).startswith(_norm_abspath(_temp_root())):
        return False, "该路径已在 temp 内,无需 workspace"
    return True, ""


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def prepare(abs_path: str) -> dict:
    """准备 workspace,但不写进程级激活锚。返回:
       {ok, name, link, target, mem_text, warning, error}。
    流程:校验 -> name -> 幂等建链 -> 确保 project_memory.md 存在 -> 注册 -> 回读记忆。
    TUI 多会话隔离使用本函数,避免多个 session 争用同一个 pid 锚。"""
    p = abs_path.strip().strip('"').strip("'") if abs_path else ""
    ok, msg = validate_path(p)
    if not ok:
        return {"ok": False, "error": msg}
    target = os.path.abspath(p)
    name = _ws_name(target)
    link = _link_path(name)
    warning = ""

    # 幂等建链
    if os.path.lexists(link):
        if is_dir_link(link):
            cur = link_target(link)
            if cur and _norm_abspath(cur) == _norm_abspath(target):
                pass  # 已指向同一目标 -> 复用
            else:
                remove_dir_link(link)
                if not make_dir_link(target, link):
                    return {"ok": False, "error": "重建 junction 失败(见 stderr)"}
        else:
            # 极罕见:同名真实目录占位(其它 UI 的普通项目)。绝不覆盖。
            return {"ok": False,
                    "error": f"{link} 已是真实目录(可能是其它项目),拒绝覆盖"}
    else:
        if not make_dir_link(target, link):
            return {"ok": False, "error": "创建 junction 失败(见 stderr)"}

    # 确保 project_memory.md 存在(经 junction 落到真实仓库根)
    mem_path = os.path.join(link, "project_memory.md")
    if not os.path.isfile(mem_path):
        try:
            open(mem_path, "a", encoding="utf-8").close()
        except OSError as e:
            warning = f"无法创建 project_memory.md: {e}"

    mem_text = ""
    try:
        with open(mem_path, encoding="utf-8", errors="replace") as fh:
            mem_text = fh.read()
    except OSError:
        pass

    registry_upsert(name, target)

    return {"ok": True, "name": name, "link": link, "target": target,
            "mem_text": mem_text, "warning": warning, "error": ""}


def activate(abs_path: str) -> dict:
    """设定并激活进程级 workspace。保留给旧 SOP / 非多会话 UI 使用。"""
    r = prepare(abs_path)
    if not r.get("ok"):
        return r
    try:
        with open(_anchor_path(), "w", encoding="utf-8") as fh:
            fh.write(r["name"])
    except OSError as e:
        r = dict(r)
        r.update({"ok": False, "error": f"写激活锚失败: {e}"})
    return r


def deactivate() -> bool:
    """仅删激活锚;junction 与文件保留。返回是否原本处于激活态。"""
    anchor = _anchor_path()
    if os.path.isfile(anchor):
        try:
            os.remove(anchor)
            return True
        except OSError as e:
            sys.stderr.write(f"[workspace] deactivate failed: {e}\n")
    return False


def current() -> Optional[dict]:
    """当前激活的 workspace:{name, path};未激活返回 None。"""
    anchor = _anchor_path()
    try:
        name = open(anchor, encoding="utf-8").read().strip()
    except OSError:
        return None
    if not name:
        return None
    ent = registry_load().get(name) or {}
    return {"name": name, "path": ent.get("path") or ""}


def is_dangling(name: str) -> bool:
    """junction 指向的真实目标是否已失效(被删/盘断开)。"""
    link = _link_path(name)
    if not is_dir_link(link):
        return True
    t = link_target(link)
    return not (t and os.path.isdir(t))


def remove(name: str) -> None:
    """显式注销:删 junction(不动真实文件)+ 删注册表条目。若正激活该项目则一并删锚。"""
    link = _link_path(name)
    if is_dir_link(link):
        remove_dir_link(link)
    registry_remove(name)
    cur = current()
    if cur and cur["name"] == name:
        deactivate()


# project_mode 插件注入的标记:`[PROJECT MODE: <name>]`(见 _build_injection)。
# 它随用户消息写进 model_responses 日志,故可据此判断被 /continue 的会话当时
# 在哪个 workspace。
_PM_RE = re.compile(r"\[PROJECT MODE:\s*([^\]\n]+?)\s*\]")


def workspace_from_log(log_path: str) -> Optional[dict]:
    """扫一份 model_responses 日志,返回它最后激活的 workspace {name, path};
    仅当该 name 是**已注册的 workspace**(在 workspaces.json 里)才返回——
    普通 SOP 项目(无 hash、不在注册表)一律忽略。"""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None
    names = _PM_RE.findall(content)
    if not names:
        return None
    name = names[-1].strip()        # 最后一次激活胜出
    ent = registry_load().get(name)
    if not ent or not ent.get("path"):
        return None
    return {"name": name, "path": ent["path"]}


def cleanup() -> None:
    """v2/v3 启动时调一次:清理 temp/projects/ 下**悬空或未注册**的 junction。
    安全纪律:只处理 is_dir_link 确认的链接;真实目录(其它 UI 的普通项目)一律跳过。"""
    proot = _projects_root()
    if not os.path.isdir(proot):
        return
    registered = set(registry_load().keys())
    try:
        entries = os.listdir(proot)
    except OSError:
        return
    for nm in entries:
        link = os.path.join(proot, nm)
        if not is_dir_link(link):
            continue  # 真实目录 -> 不碰
        t = link_target(link)
        dangling = not (t and os.path.isdir(t))
        if dangling or nm not in registered:
            remove_dir_link(link)
