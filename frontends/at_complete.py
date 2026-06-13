"""@ file completion — shared UI-less logic for tui_v2 / tui_v3.

File index (os.scandir, cached per root) + fuzzy match + @token detection +
insert text. No UI deps; each front-end renders candidates its own way and
calls candidates_for(query, root). Index root is the front-end's choice
(session workspace, else CWD). Submit-time is intentionally absent —
completion-only sends @path as plain text (auto-read variant lives in
temp/plan_v2_at_mention/autoread_version.py).
"""

import os
import re
import threading

# ---------------------------------------------------------------- index

_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".next", ".idea", ".vscode", "target", ".cache", ".eggs",
}
_IGNORE_EXT = {".pyc", ".pyo", ".so", ".o", ".class", ".lock", ".dll", ".exe"}
_MAX_FILES = 50_000          # 超大目录宁缺毋卡：到上限就停


def scan_files(root: str, max_files: int = _MAX_FILES) -> list[str]:
    """Collect relative file paths under root, '/'-normalized.

    os.scandir over os.walk: one syscall yields is_dir without an extra
    stat per entry. Dotted dirs are skipped wholesale (.git, .venv...).
    """
    out: list[str] = []
    stack = [root]
    while stack and len(out) < max_files:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name not in _IGNORE_DIRS and not e.name.startswith("."):
                                stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            if os.path.splitext(e.name)[1].lower() not in _IGNORE_EXT:
                                rel = os.path.relpath(e.path, root).replace("\\", "/")
                                out.append(rel)
                                if len(out) >= max_files:
                                    return out
                    except OSError:
                        continue
        except OSError:
            continue
    return out


class FileIndexCache:
    """Per-root background file index. warm() is idempotent-cheap: a
    rebuild is only started when none is in flight."""

    def __init__(self, root: str):
        self.root = root
        self._files: list[str] = []
        self._lock = threading.Lock()
        self._building = False
        self.ready = threading.Event()

    def warm(self) -> None:
        with self._lock:
            if self._building:
                return
            self._building = True

        def _build():
            try:
                files = scan_files(self.root)
                with self._lock:
                    self._files = files
                self.ready.set()
            finally:
                with self._lock:
                    self._building = False

        threading.Thread(target=_build, name="ga-at-index", daemon=True).start()

    def snapshot(self) -> list[str]:
        with self._lock:
            return self._files


_indexes: dict[str, FileIndexCache] = {}
_indexes_lk = threading.Lock()


def get_index(root: str) -> FileIndexCache:
    key = os.path.normcase(os.path.realpath(root or os.getcwd()))
    with _indexes_lk:
        idx = _indexes.get(key)
        if idx is None:
            idx = _indexes[key] = FileIndexCache(root)
    return idx


# ---------------------------------------------------------------- fuzzy

def _subseq_score(q: str, path: str):
    """Subsequence match score (higher = better), None when q doesn't
    fully appear in order. Contiguous runs dominate (fzf-style): scattered
    one-char hits across a long path must not beat a tight cluster.
    Word-boundary hits and basename substring add on top; ties broken by
    caller on shorter path."""
    if not q:
        return 0
    score, qi, prev_hit = 0, 0, -2
    for pi, ch in enumerate(path):
        if qi < len(q) and ch == q[qi]:
            score += 1
            if pi == prev_hit + 1:
                score += 2          # contiguous run: the dominant signal
            if pi == 0 or path[pi - 1] in "/\\_-. ":
                score += 3
            prev_hit = pi
            qi += 1
    if qi < len(q):
        return None
    base = path.rsplit("/", 1)[-1]
    if q in base:
        score += 8
    elif q in path:
        score += 4
    return score


def fuzzy_rank(query: str, files: list[str], limit: int = 10) -> list[str]:
    q = query.lower()
    if not q:
        # bare `@`: surface shallow paths first for discoverability
        return sorted(files, key=lambda f: (f.count("/"), f))[:limit]
    scored = []
    for f in files:
        s = _subseq_score(q, f.lower())
        if s is not None:
            scored.append((s, f))
    scored.sort(key=lambda x: (-x[0], len(x[1]), x[1]))
    return [f for _, f in scored[:limit]]


# ------------------------------------------------------- edit-time token

# `(?:^|\s)@` 前置：@ 前必须是行首或空白 → 邮箱/代码里的 a@b 不触发。
# 字符集含路径分隔符与 ~ :，\w 在 unicode 下覆盖中文文件名。
_AT_TOKEN_RE = re.compile(r"(?:^|\s)(@[\w\-./\\~:]*)$", re.UNICODE)


def find_at_token(line_before_cursor: str):
    """Return (query, at_pos) when the cursor sits in an @token being
    typed on this line, else None. at_pos is the index of '@'."""
    m = _AT_TOKEN_RE.search(line_before_cursor)
    if not m:
        return None
    tok = m.group(1)
    return tok[1:], m.start(1)


def format_pick(path: str) -> str:
    """`@path` insert text; dirs get no trailing space (keep completing next
    level), files get one (close token). Spaces → quoted."""
    trailing = '' if path.endswith(('/', '\\')) else ' '
    return f'@"{path}"{trailing}' if ' ' in path else f'@{path}{trailing}'


# --- path-like completion: an explicit-path @token (~/ / ./ ../ or C:\) goes
# to live directory completion instead of index fuzzy — this is how absolute
# paths outside the index root get completed level by level (claude-code parity).

def is_path_like(token: str) -> bool:
    if token in ('~', '.', '..'):
        return True
    if token.startswith(('~/', '~\\', './', '.\\', '../', '..\\', '/', '\\')):
        return True
    return len(token) >= 3 and token[0].isalpha() and token[1] == ':' and token[2] in '/\\'


def path_completions(token: str, root: str, limit: int = 15) -> list[str]:
    """readdir the real dir of a path-like token, prefix-match, dirs first.
    `~` expanded, relative → root, absolute as-is; candidates keep the token's
    spelling, dirs carry a trailing '/'."""
    sep = max(token.rfind('/'), token.rfind('\\'))
    if sep >= 0:
        dir_part, prefix = token[:sep + 1], token[sep + 1:]
    elif token in ('~', '.', '..'):
        dir_part, prefix = token.rstrip('/\\') + '/', ''
    else:
        return []
    exp = os.path.expanduser(dir_part)
    real_dir = exp if os.path.isabs(exp) else os.path.join(root, exp)
    try:
        with os.scandir(real_dir) as it:
            entries = list(it)
    except OSError:
        return []
    pl = prefix.lower()
    rows = []
    for e in entries:
        nm = e.name
        if pl and not nm.lower().startswith(pl):
            continue
        if nm.startswith('.') and not prefix.startswith('.'):   # 隐藏项需显式 . 才出
            continue
        try:
            is_dir = e.is_dir()
        except OSError:
            is_dir = False
        rows.append((not is_dir, nm.lower(), dir_part + nm + ('/' if is_dir else '')))
    rows.sort(key=lambda r: (r[0], r[1]))                       # 目录优先 + 字母序
    return [d for _, _, d in rows[:limit]]


def candidates_for(query: str, root: str, limit: int = 15) -> list[str]:
    """@token candidates: path-like → directory completion, else index fuzzy.
    Single dispatch point shared by both front-ends."""
    if is_path_like(query):
        return path_completions(query, root, limit)
    files = get_index(root).snapshot()
    return fuzzy_rank(query, files, limit) if files else []
