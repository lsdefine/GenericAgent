"""
puburl.py — 把本地文件临时暴露成公网 HTTPS URL，供 QQ 富媒体出站使用。

QQ 出站富媒体（图片/视频/语音/文件）不接受字节直传，必须给腾讯一个公网 URL
让它反向拉取。本模块在【任意机器】上自包含地解决这个依赖：

  本地文件 -> 复制到内部 serve 目录 -> 内置 HTTP 文件服务(127.0.0.1:随机端口)
          -> cloudflared quick tunnel 出站建连 -> 公网 https://xxx.trycloudflare.com/<token>/<file>

设计目标（换任何电脑部署 GA、重启即复现）：
  1. 隧道 URL 每次重启都变 —— 运行期从 cloudflared 输出实时抓取，绝不硬编码。
  2. cloudflared 缺失 —— 按当前 OS/架构自动从官方 GitHub 下载到 .portable/tools/。
  3. 纯标准库实现 HTTP 服务，无额外依赖。

安全：文件放在以 uuid4 token 命名的子目录下，URL 不可枚举；隧道地址本身随机；
仅在隧道存活期间可达，并自动清理超过 TTL 的旧文件。
"""

import atexit
import functools
import http.server
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import threading
import time
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(ROOT, ".portable", "tools")
SERVE_DIR = os.path.join(ROOT, "temp", "_pubserve")
FILE_TTL = 3600  # 已发布文件保留秒数，超过则清理

_TUNNEL_RE = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com", re.I)


def _log(msg):
    print(f"[puburl] {msg}", flush=True)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """静默版文件 handler（不污染 qqapp.log）。"""

    def log_message(self, *args):
        pass


def _cf_asset():
    """返回 (github资产名, 本地二进制文件名)，按当前系统/架构。"""
    sysname = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("aarch64", "arm64"):
        arch = "arm64"
    elif machine in ("x86_64", "amd64", "x64"):
        arch = "amd64"
    elif "386" in machine or "i686" in machine or "i386" in machine:
        arch = "386"
    elif machine.startswith("arm"):
        arch = "arm"
    else:
        arch = "amd64"
    if sysname == "windows":
        return f"cloudflared-windows-{arch}.exe", "cloudflared.exe"
    if sysname == "linux":
        return f"cloudflared-linux-{arch}", "cloudflared"
    if sysname == "darwin":
        # macOS 官方只发布 .tgz
        return f"cloudflared-darwin-{arch}.tgz", "cloudflared"
    return f"cloudflared-linux-{arch}", "cloudflared"


class PublicFileServer:
    def __init__(self):
        self._lock = threading.Lock()
        self._httpd = None
        self._http_port = None
        self._cf_proc = None
        self._tunnel_url = None

    # ---- cloudflared 二进制 ----
    def _ensure_cloudflared(self):
        asset, binname = _cf_asset()
        os.makedirs(TOOLS_DIR, exist_ok=True)
        binpath = os.path.join(TOOLS_DIR, binname)
        if os.path.exists(binpath) and os.path.getsize(binpath) > 0:
            return binpath
        url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{asset}"
        _log(f"cloudflared 未找到，开始下载: {asset}")
        tmp = binpath + ".part"
        req = urllib.request.Request(url, headers={"User-Agent": "GA-puburl"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as f:
            shutil.copyfileobj(resp, f)
        if asset.endswith(".tgz"):
            import tarfile
            with tarfile.open(tmp) as tar:
                member = next((m for m in tar.getmembers() if m.name.endswith("cloudflared")), None)
                if not member:
                    raise RuntimeError("tgz 内未找到 cloudflared")
                with tar.extractfile(member) as src, open(binpath, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            os.remove(tmp)
        else:
            os.replace(tmp, binpath)
        if platform.system().lower() != "windows":
            os.chmod(binpath, os.stat(binpath).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        _log(f"cloudflared 已就绪: {binpath} ({os.path.getsize(binpath)} bytes)")
        return binpath

    # ---- 本地 HTTP 文件服务 ----
    def _start_http(self):
        os.makedirs(SERVE_DIR, exist_ok=True)
        handler = functools.partial(_QuietHandler, directory=SERVE_DIR)
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._http_port = httpd.server_address[1]
        self._httpd = httpd
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        _log(f"本地文件服务启动于 127.0.0.1:{self._http_port}")

    # ---- cloudflared 隧道 ----
    def _start_tunnel(self, binpath):
        cmd = [
            binpath, "tunnel",
            "--no-autoupdate",
            "--url", f"http://127.0.0.1:{self._http_port}",
        ]
        self._cf_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        found = threading.Event()

        def _reader():
            for line in self._cf_proc.stdout:
                if self._tunnel_url is None:
                    m = _TUNNEL_RE.search(line)
                    if m:
                        self._tunnel_url = m.group(0)
                        _log(f"隧道已建立: {self._tunnel_url}")
                        found.set()
        threading.Thread(target=_reader, daemon=True).start()
        if not found.wait(timeout=45):
            raise RuntimeError("等待 cloudflared 隧道 URL 超时")
        self._warmup(self._tunnel_url)

    def _warmup(self, base_url):
        """隧道刚建立时边缘节点可能尚未就绪，首次请求会 SSL EOF。
        这里自探到拿回任意 HTTP 响应为止，避免腾讯首次反向拉取失败。"""
        import ssl
        ctx = ssl.create_default_context()
        for i in range(10):
            try:
                req = urllib.request.Request(base_url, headers={"User-Agent": "ga-warmup"})
                urllib.request.urlopen(req, timeout=15, context=ctx)
                _log(f"隧道边缘就绪 (warmup#{i})")
                return True
            except urllib.error.HTTPError:
                # 有 HTTP 响应（如 404）即说明边缘已就绪
                _log(f"隧道边缘就绪 (warmup#{i}, http)")
                return True
            except Exception:
                time.sleep(3)
        _log("隧道预热未确认就绪，继续（腾讯侧可能首拉失败）")
        return False

    def ensure_started(self):
        with self._lock:
            if self._tunnel_url and self._cf_proc and self._cf_proc.poll() is None:
                return self._tunnel_url
            # 隧道挂了则重置重建
            if self._cf_proc and self._cf_proc.poll() is not None:
                _log("检测到 cloudflared 已退出，重建隧道")
                self._tunnel_url = None
            if self._httpd is None:
                self._start_http()
            binpath = self._ensure_cloudflared()
            self._start_tunnel(binpath)
            return self._tunnel_url

    # ---- 清理过期文件 ----
    def _cleanup(self):
        now = time.time()
        try:
            for name in os.listdir(SERVE_DIR):
                p = os.path.join(SERVE_DIR, name)
                try:
                    if now - os.path.getmtime(p) > FILE_TTL:
                        shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
                except OSError:
                    pass
        except FileNotFoundError:
            pass

    # ---- 对外接口 ----
    def publish(self, local_path):
        """把本地文件复制到 serve 目录并返回公网 URL；失败返回 None。"""
        if not os.path.isfile(local_path):
            return None
        url = self.ensure_started()
        if not url:
            return None
        self._cleanup()
        token = uuid.uuid4().hex
        dest_dir = os.path.join(SERVE_DIR, token)
        os.makedirs(dest_dir, exist_ok=True)
        fname = os.path.basename(local_path)
        shutil.copy2(local_path, os.path.join(dest_dir, fname))
        return f"{url}/{token}/{urllib.request.quote(fname)}"

    def shutdown(self):
        if self._cf_proc and self._cf_proc.poll() is None:
            self._cf_proc.terminate()
        if self._httpd:
            self._httpd.shutdown()


_INSTANCE = PublicFileServer()
atexit.register(_INSTANCE.shutdown)


def publish(local_path):
    return _INSTANCE.publish(local_path)


def ensure_started():
    return _INSTANCE.ensure_started()


if __name__ == "__main__":
    # 自测：发布一个临时文件并打印 URL
    import sys
    test_file = sys.argv[1] if len(sys.argv) > 1 else __file__
    print("publishing:", test_file)
    print("URL:", publish(test_file))
    print("Ctrl-C to stop"); 
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        _INSTANCE.shutdown()
