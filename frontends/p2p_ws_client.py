"""Single-file Python P2P channel: WebRTC first, encrypted relay fallback."""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import math
import os
import re
import time
import urllib.error
import urllib.request
import zlib
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import websockets
try:
    from aiortc import (
        RTCConfiguration,
        RTCIceServer,
        RTCPeerConnection,
        RTCSessionDescription,
    )
except ImportError:  # 移动端(如Chaquopy)无aiortc轮子：自动降级为纯加密relay
    RTCConfiguration = RTCIceServer = RTCPeerConnection = RTCSessionDescription = None
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


# ---- merged from auth.py ----
# 仅用于过滤不知道本项目的扫描和噪声，不是安全秘密。
# 即使该值公开，握手访问安全仍由不可猜测、不得泄露的 UUID 保证。
DEFAULT_ACCESS_KEY = "ljq-p2p-ws-default-access-key-v1-7f3c9a2e"

def signed_url(url: str, action: str, target: str, key: str = DEFAULT_ACCESS_KEY) -> str:
    """为一次请求添加短时有效、不可重放的 HMAC 查询参数。"""
    ts = str(int(time.time()))
    nonce = os.urandom(16).hex()
    payload = f"{action}\n{target}\n{ts}\n{nonce}".encode()
    sig = hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(ts=ts, nonce=nonce, sig=sig)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

def code_url(signal_url: str, endpoint: str) -> str:
    """把 ws(s)://host/[prefix/]ws 转成 http(s)://host/[prefix/]code/...。"""
    parts = urlsplit(signal_url)
    scheme = {"ws": "http", "wss": "https"}.get(parts.scheme)
    if not scheme:
        raise ValueError("signal_url must use ws:// or wss://")
    parent = parts.path.rsplit("/", 1)[0]
    path = f"{parent}/{endpoint.lstrip('/')}"
    return urlunsplit((scheme, parts.netloc, path, "", ""))

# ---- merged from crypto.py ----
COMPRESS_MIN = 512

_FLAG_ZIP = 0x01

_FLAG_TEXT = 0x02

def _pub_raw(pk):
    """X25519 公钥原始 32 字节; 兼容 cryptography<40 (Android Chaquopy 无 public_bytes_raw)。"""
    try:
        return pk.public_bytes_raw()
    except AttributeError:
        from cryptography.hazmat.primitives import serialization as _ser
        return pk.public_bytes(_ser.Encoding.Raw, _ser.PublicFormat.Raw)

def keypair():
    """生成一次性 X25519 密钥对，返回 (私钥, 公钥字节)。"""
    sk = X25519PrivateKey.generate()
    return sk, _pub_raw(sk.public_key())

def session_key(sk, peer_pub: bytes) -> bytes:
    """ECDH + HKDF 派生 32 字节会话密钥。

    salt 取两个公钥排序后拼接，双方算出同一个值，且把密钥绑定到本次配对。
    """
    mine = _pub_raw(sk.public_key())
    salt = b"".join(sorted([mine, peer_pub]))
    shared = sk.exchange(X25519PublicKey.from_public_bytes(peer_pub))
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=salt, info=b"p2p-ws/v1"
    ).derive(shared)

def seal(key: bytes, data, compress: bool = True) -> bytes:
    """把 str/bytes 压缩并加密成一帧。"""
    flags = 0
    if isinstance(data, str):
        data = data.encode()
        flags |= _FLAG_TEXT
    if compress and len(data) >= COMPRESS_MIN:
        packed = zlib.compress(data, 6)
        if len(packed) < len(data):
            data, flags = packed, flags | _FLAG_ZIP
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, bytes([flags]) + data, None)

def open_(key: bytes, frame: bytes):
    """解密一帧，还原成原始 str 或 bytes；被篡改会抛异常。"""
    plain = AESGCM(key).decrypt(frame[:12], frame[12:], None)
    flags, data = plain[0], plain[1:]
    if flags & _FLAG_ZIP:
        data = zlib.decompress(data)
    return data.decode() if flags & _FLAG_TEXT else data

# ---- merged from signal.py ----
log = logging.getLogger("p2p_ws.signal")

class Signal:
    def __init__(
        self, url: str, room: str, retries: int = 6,
        access_key: str = DEFAULT_ACCESS_KEY,
    ):
        separator = "&" if "?" in url else "?"
        self.url = f"{url}{separator}room={room}"
        self.room = room
        self.access_key = access_key
        self.retries = retries  # 单次断线的最大重连尝试次数
        self.on_data = None  # 回调：dict -> None
        self._ws = None
        self._queues: dict[str, asyncio.Queue] = {}
        self._ready = asyncio.Event()
        self._closing = False
        self._task = None

    # ---------- 生命周期 ----------

    def _signed_url(self):
        return signed_url(self.url, "ws", self.room, self.access_key)

    async def start(self):
        self._ws = await websockets.connect(self._signed_url(), max_size=1 << 21)
        self._ready.set()
        self._task = asyncio.create_task(self._loop())
        return self

    async def close(self):
        self._closing = True
        if self._task:
            self._task.cancel()
        if self._ws:
            await self._ws.close()

    @property
    def alive(self) -> bool:
        return self._ready.is_set() and not self._closing

    # ---------- 收发 ----------

    def queue(self, type_: str) -> asyncio.Queue:
        return self._queues.setdefault(type_, asyncio.Queue())

    async def expect(self, type_: str, timeout: float = 15):
        return await asyncio.wait_for(self.queue(type_).get(), timeout)

    async def send(self, obj: dict, timeout: float = 15):
        """等连接就绪后发送；重连期间会阻塞而不是直接失败。"""
        await asyncio.wait_for(self._ready.wait(), timeout)
        await self._ws.send(json.dumps(obj))

    async def _loop(self):
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("type") == "data" and self.on_data:
                    self.on_data(msg)
                else:
                    self.queue(msg.get("type", "")).put_nowait(msg)
        except Exception as exc:
            log.debug("signal read stopped: %r", exc)
        if not self._closing:
            # 房间配对、ECDH 密钥与 relay 序号都属于本次 socket 会话；
            # 信令原地重连会留下僵尸 P2PSocket，必须由上层完整重握手。
            self._ready.clear()
            self.queue("closed").put_nowait({"type": "closed"})

# ---- merged from socket.py ----
log = logging.getLogger("p2p_ws")

_CHUNK = 48 * 1024
# WebRTC DataChannel 单条消息有实现上限（aiortc 上超过 64KiB 会静默截断），
# 所以直连消息统一先整包压缩再分片，接收端重组后还原。
_DIRECT_CHUNK = 16 * 1024
_DIRECT_MAGIC = b"P2P1"
_DIRECT_HEAD = len(_DIRECT_MAGIC) + 1 + 6 + 2 + 2

def _pack_direct(data):
    """把一条消息封装成若干可安全通过 DataChannel 的帧。"""
    raw = data.encode() if isinstance(data, str) else data
    flags = _FLAG_TEXT if isinstance(data, str) else 0
    # 保留小消息的旧版 wire format；魔数开头的 bytes 必须封装以免误判。
    if len(raw) <= _DIRECT_CHUNK and not (
            isinstance(data, bytes) and data.startswith(_DIRECT_MAGIC)):
        yield data
        return
    if len(raw) >= COMPRESS_MIN:
        packed = zlib.compress(raw, 6)
        if len(packed) < len(raw):
            raw, flags = packed, flags | _FLAG_ZIP
    ident = os.urandom(6)
    total = max(1, math.ceil(len(raw) / _DIRECT_CHUNK))
    if total > 0xFFFF:
        raise ValueError("message too large for direct mode")
    for n in range(total):
        head = (
            _DIRECT_MAGIC + bytes([flags]) + ident
            + total.to_bytes(2, "big") + n.to_bytes(2, "big")
        )
        yield head + raw[n * _DIRECT_CHUNK : (n + 1) * _DIRECT_CHUNK]

class P2PSocket:
    """一条按 UUID 配对、用法近似 WebSocket 的异步消息通道。

    用法::

        ws = await P2PSocket.connect("ws://host:8765/ws", "same-uuid")
        await ws.send("hello")
        print(await ws.recv())
        await ws.close()

    ``mode`` 为 ``"direct"`` 或 ``"relay"``；send/recv 的消息边界和
    str/bytes 类型都会保留。
    """

    def __init__(
        self, signal_url, room, *, direct_timeout=15, peer_timeout=120, retries=6,
        stun=True, access_key=DEFAULT_ACCESS_KEY,
    ):
        self.signal = Signal(signal_url, room, retries, access_key)
        self.direct_timeout = direct_timeout
        # 等对端进房的时长；须 >= 配对码有效期(120s)，否则码没过期本端已离房
        self.peer_timeout = peer_timeout
        self.stun = stun
        self.mode = "connecting"
        self.closed = False
        self._key = None
        self._pc = None
        self._dc = None
        self._inbox = asyncio.Queue()
        self._parts = {}
        self._send_lock = asyncio.Lock()
        self._relay_ready = asyncio.Event()
        self._direct_open = asyncio.Event()
        self._peer_watch = None
        self._direct_task = None
        self._upgrade_prepare = asyncio.Event()
        self._upgrade_ack = asyncio.Event()
        self._upgrade_commit = asyncio.Event()
        self._direct_pending = []

    @classmethod
    async def connect(
        cls, signal_url: str, room: str, *, direct_timeout=15, peer_timeout=120,
        retries=6, stun=True, access_key=DEFAULT_ACCESS_KEY,
    ):
        """连接同一 UUID 的另一个客户端，直连失败自动回退中继。"""
        self = cls(
            signal_url, room, direct_timeout=direct_timeout,
            peer_timeout=peer_timeout, retries=retries, stun=stun,
            access_key=access_key,
        )
        try:
            await self._connect()
        except BaseException:
            # 失败必须关闭信令连接，否则泄漏的连接会留在房间里
            # 与本端下一次重连"自配对"，把双人房占满导致真对端永远进不来。
            await self.close()
            raise
        return self

    async def _connect(self):
        await self.signal.start()
        peer = await self.signal.expect("peer", self.peer_timeout)

        # 一次性 ECDH：即使走中继，服务器也拿不到会话密钥。
        private, public = keypair()
        await self.signal.send(
            {"type": "key", "key": base64.b64encode(public).decode()}
        )
        key_msg = await self.signal.expect("key")
        self._key = session_key(private, base64.b64decode(key_msg["key"]))
        self.signal.on_data = self._on_relay_data
        self._relay_ready.set()
        self.mode = "relay"
        # 对端离开房间后本连接已无意义；若不关闭，本端会一直占着房间等待，
        # 新 peer 加入时无人重做 key 握手，对方只能 15s 超时退出（死循环）。
        self._peer_watch = asyncio.create_task(self._on_peer_left())
        if RTCPeerConnection is not None and self.direct_timeout > 0:
            self._direct_task = asyncio.create_task(
                self._upgrade_direct(bool(peer["initiator"])))
        return self

    async def _upgrade_direct(self, initiator):
        """Relay 已可用时后台打洞，以三步屏障保序切到 DataChannel。"""
        try:
            await asyncio.wait_for(self._make_direct(initiator), self.direct_timeout)
            await asyncio.wait_for(self._direct_open.wait(), self.direct_timeout)
            if initiator:
                async with self._send_lock:
                    await self._send_control(b"prepare")
                    await asyncio.wait_for(self._upgrade_ack.wait(), self.direct_timeout)
                    await self._send_control(b"commit")
                    self._commit_direct()
            else:
                await asyncio.wait_for(self._upgrade_prepare.wait(), self.direct_timeout)
                async with self._send_lock:
                    await self._send_control(b"ack")
                    await asyncio.wait_for(self._upgrade_commit.wait(), self.direct_timeout)
                    self._commit_direct()
            log.info("encrypted relay upgraded to direct DataChannel")
        except Exception as exc:
            log.info("background direct upgrade unavailable, keeping relay: %r", exc)
            await self._drop_direct()

    def _commit_direct(self):
        self.mode = "direct"
        for item in self._direct_pending:
            self._inbox.put_nowait(item)
        self._direct_pending.clear()

    async def _on_peer_left(self):
        """对端离开或本端信令断开时，关闭连接让上层完整重握手。"""
        waits = [asyncio.create_task(self.signal.queue(kind).get())
                 for kind in ("peer_left", "closed")]
        try:
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            return
        finally:
            for task in waits:
                task.cancel()
        if not self.closed:
            log.info("P2P peer/signaling left; closing socket for a fresh handshake")
            await self.close()

    # ---------- WebSocket 风格接口 ----------

    async def send(self, data):
        """发送一条 str 或 bytes 消息；并发 send 会按调用顺序串行化。"""
        if self.closed:
            raise ConnectionError("socket is closed")
        if not isinstance(data, (str, bytes)):
            raise TypeError("data must be str or bytes")
        async with self._send_lock:
            if self.mode == "direct" and self._dc and self._dc.readyState == "open":
                for frame in _pack_direct(data):
                    self._dc.send(frame)
                    # 避免一次灌满发送缓冲导致底层丢帧。
                    while self._dc.bufferedAmount > 4 * 1024 * 1024:
                        await asyncio.sleep(0.01)
                return
            # 直连在运行中失效时，无需重新创建对象，立即降级。
            self.mode = "relay"
            await self._send_relay(data)

    async def recv(self):
        """等待并返回下一条完整消息，保持原始 str/bytes 类型。"""
        item = await self._inbox.get()
        if isinstance(item, _Closed):
            raise ConnectionError(item.reason)
        return item

    async def close(self):
        if self.closed:
            return
        self.closed = True
        if self._peer_watch is not None and self._peer_watch is not asyncio.current_task():
            self._peer_watch.cancel()
        if self._direct_task is not None and self._direct_task is not asyncio.current_task():
            self._direct_task.cancel()
        await self._drop_direct()
        await self.signal.close()
        self._inbox.put_nowait(_Closed("socket is closed"))
        self.mode = "closed"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    # ---------- WebRTC 直连 ----------

    async def _make_direct(self, initiator: bool):
        if RTCPeerConnection is None:
            raise RuntimeError("aiortc not installed; direct mode unavailable")
        if self.stun:
            if isinstance(self.stun, str):
                stun_url = self.stun
            else:
                parts = urlsplit(self.signal.url)
                host = parts.hostname
                if not host:
                    raise ValueError("signal URL has no host for STUN")
                if ":" in host:  # IPv6 URI 必须保留方括号
                    host = f"[{host}]"
                port = parts.port or (443 if parts.scheme == "wss" else 80)
                stun_url = f"stun:{host}:{port}"
            ice = [RTCIceServer(stun_url)]
        else:
            ice = []
        pc = self._pc = RTCPeerConnection(RTCConfiguration(iceServers=ice))

        @pc.on("connectionstatechange")
        async def state_changed():
            if pc.connectionState in ("failed", "closed", "disconnected"):
                self._direct_open.clear()
                if not self.closed and self.mode == "direct":
                    log.info("direct channel lost; switched to encrypted relay")
                    self.mode = "relay"

        if initiator:
            self._bind_datachannel(pc.createDataChannel("p2p-ws"))
            await pc.setLocalDescription(await pc.createOffer())
            await self.signal.send(
                {
                    "type": "sdp",
                    "sdp_type": pc.localDescription.type,
                    "sdp": pc.localDescription.sdp,
                }
            )
            answer = await self.signal.expect("sdp", self.direct_timeout)
            await pc.setRemoteDescription(
                RTCSessionDescription(answer["sdp"], answer["sdp_type"])
            )
        else:
            channel_seen = asyncio.Event()

            @pc.on("datachannel")
            def datachannel(channel):
                self._bind_datachannel(channel)
                channel_seen.set()

            offer = await self.signal.expect("sdp", self.direct_timeout)
            await pc.setRemoteDescription(
                RTCSessionDescription(offer["sdp"], offer["sdp_type"])
            )
            await pc.setLocalDescription(await pc.createAnswer())
            await self.signal.send(
                {
                    "type": "sdp",
                    "sdp_type": pc.localDescription.type,
                    "sdp": pc.localDescription.sdp,
                }
            )
            await asyncio.wait_for(channel_seen.wait(), self.direct_timeout)

    def _bind_datachannel(self, dc):
        self._dc = dc

        # 应答方拿到的通道可能已经是 open，此时不会再触发 open 事件
        if dc.readyState == "open":
            self._direct_open.set()

        @dc.on("open")
        def opened():
            self._direct_open.set()

        @dc.on("message")
        def message(data):
            self._recv_direct(data)

        @dc.on("close")
        def closed():
            self._direct_open.clear()
            if not self.closed and self.mode == "direct":
                self.mode = "relay"

    def _recv_direct(self, data):
        """重组直连分片；未封装的小消息按原样交付。"""
        if not isinstance(data, bytes) or not data.startswith(_DIRECT_MAGIC):
            self._inbox.put_nowait(data)
            return
        flags = data[4]
        key = ("direct", data[5:11])
        total = int.from_bytes(data[11:13], "big")
        index = int.from_bytes(data[13:15], "big")
        entry = self._parts.setdefault(
            key, {"flags": flags, "total": total, "chunks": {}}
        )
        entry["chunks"][index] = data[_DIRECT_HEAD:]
        if len(entry["chunks"]) < entry["total"]:
            return
        del self._parts[key]
        try:
            raw = b"".join(entry["chunks"][i] for i in range(entry["total"]))
            if entry["flags"] & _FLAG_ZIP:
                raw = zlib.decompress(raw)
            item = raw.decode() if entry["flags"] & _FLAG_TEXT else raw
            if self.mode == "direct":
                self._inbox.put_nowait(item)
            else:
                self._direct_pending.append(item)
        except Exception as exc:
            log.warning("discarded invalid direct frame: %r", exc)

    async def _drop_direct(self):
        pc, self._pc, self._dc = self._pc, None, None
        self._direct_open.clear()
        if pc:
            with suppress(Exception):
                await pc.close()

    # ---------- 加密中继 ----------

    async def _send_control(self, command):
        await self._send_relay(command, control=True)

    async def _send_relay(self, data, control=False):
        await self._relay_ready.wait()
        raw = data.encode() if isinstance(data, str) else data
        kind = 2 if control else int(isinstance(data, str))
        total = max(1, math.ceil(len(raw) / _CHUNK))
        msg_id = os.urandom(8).hex()
        for n in range(total):
            chunk = bytes([kind]) + raw[n * _CHUNK : (n + 1) * _CHUNK]
            cipher = seal(self._key, chunk)
            await self.signal.send(
                {
                    "type": "data",
                    "id": msg_id,
                    "n": n,
                    "total": total,
                    "blob": base64.b64encode(cipher).decode(),
                }
            )

    def _on_relay_data(self, msg):
        try:
            chunk = open_(self._key, base64.b64decode(msg["blob"]))
            if not isinstance(chunk, bytes) or not chunk:
                raise ValueError("invalid encrypted chunk")
            ident = msg["id"]
            entry = self._parts.setdefault(
                ident, {"kind": chunk[0], "total": int(msg["total"]), "chunks": {}}
            )
            entry["chunks"][int(msg["n"])] = chunk[1:]
            if len(entry["chunks"]) == entry["total"]:
                raw = b"".join(entry["chunks"][i] for i in range(entry["total"]))
                del self._parts[ident]
                if entry["kind"] == 2:
                    if raw == b"prepare":
                        self._upgrade_prepare.set()
                    elif raw == b"ack":
                        self._upgrade_ack.set()
                    elif raw == b"commit":
                        self._upgrade_commit.set()
                else:
                    self._inbox.put_nowait(raw.decode() if entry["kind"] else raw)
        except Exception as exc:
            # 篡改、错误密钥或畸形分片不会进入应用层。
            log.warning("discarded invalid relay frame: %r", exc)

class _Closed:
    def __init__(self, reason):
        self.reason = reason

# ---- merged from invite.py ----
_CODE = re.compile(r"^[0-9]{9}$")

async def _post_json(url: str, timeout: float = 15):
    def request():
        req = urllib.request.Request(url, data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)

    try:
        return await asyncio.to_thread(request)
    except urllib.error.HTTPError as exc:
        reason = exc.read().decode(errors="replace").strip()
        raise ConnectionError(f"short-code server rejected request: {exc.code} {reason}") from exc

# ---- optional HTTP-over-P2P tunnel ----
_HTTP_REQ, _HTTP_RES = "p2p-http.req", "p2p-http.res"
_HTTP_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "content-length", "host",
}


def _http_modules():
    """The base P2P channel stays dependency-light; HTTP support is optional."""
    try:
        import aiohttp
        from aiohttp import web
        from multidict import CIMultiDict
    except ImportError as exc:
        raise RuntimeError(
            'HTTP tunnelling requires aiohttp: pip install "p2p-ws[http]"'
        ) from exc
    return aiohttp, web, CIMultiDict


def _safe_headers(items, drop=()):
    blocked = _HTTP_HOP | {str(name).lower() for name in drop}
    return [(str(k), str(v)) for k, v in items if str(k).lower() not in blocked]


def _decode_body(value, limit):
    try:
        body = base64.b64decode(value or "", validate=True)
    except Exception as exc:
        raise ValueError("invalid base64 HTTP body") from exc
    if len(body) > limit:
        raise ValueError("HTTP body exceeds configured limit")
    return body


def _claim_receiver(socket, owner):
    """A tunnel owns recv(); two consumers would silently steal each other's frames."""
    current = getattr(socket, "_http_tunnel_owner", None)
    if current is not None and current is not owner:
        raise RuntimeError("this P2PSocket already has an HTTP tunnel consumer")
    socket._http_tunnel_owner = owner


def _release_receiver(socket, owner):
    if getattr(socket, "_http_tunnel_owner", None) is owner:
        delattr(socket, "_http_tunnel_owner")


class HTTPExporter:
    """Expose one fixed HTTP origin to the peer over a P2PSocket.

    The peer supplies only a relative target. Redirects are not followed, so
    this cannot be turned into a general SSRF proxy. This object exclusively
    consumes ``socket.recv()`` until closed.
    """

    def __init__(
        self, socket, upstream, *, allow=("/",),
        methods=("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"),
        query=None, headers=None, drop_request_headers=(), timeout=30,
        max_body=8 * 1024 * 1024, max_concurrency=16,
    ):
        parts = urlsplit(str(upstream))
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("upstream must be an absolute http(s) URL")
        if parts.query or parts.fragment:
            raise ValueError("upstream must not contain query or fragment")
        self.socket, self.upstream = socket, str(upstream).rstrip("/")
        self.allow = tuple(str(path) for path in allow)
        if not self.allow or any(not path.startswith("/") for path in self.allow):
            raise ValueError("allow must contain absolute path prefixes")
        self.methods = {str(method).upper() for method in methods}
        self.query = [(str(k), str(v)) for k, v in (query or {}).items()]
        self.headers = [(str(k), str(v)) for k, v in (headers or {}).items()]
        self.drop_request_headers = tuple(drop_request_headers)
        self.timeout, self.max_body = float(timeout), int(max_body)
        self._slots = asyncio.Semaphore(int(max_concurrency))
        self._session = self._receiver = None
        self._requests, self._closed = set(), asyncio.Event()

    async def start(self):
        if self._receiver:
            return self
        aiohttp, _, _ = _http_modules()
        _claim_receiver(self.socket, self)
        try:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
            self._receiver = asyncio.create_task(self._receive())
        except Exception:
            _release_receiver(self.socket, self)
            raise
        return self

    async def _receive(self):
        try:
            while True:
                raw = await self.socket.recv()
                try:
                    message = json.loads(raw) if isinstance(raw, str) else None
                except (TypeError, json.JSONDecodeError):
                    message = None
                if not isinstance(message, dict) or message.get("type") != _HTTP_REQ:
                    log.warning("HTTPExporter ignored a non-HTTP message")
                    continue
                task = asyncio.create_task(self._forward(message))
                self._requests.add(task)
                task.add_done_callback(self._requests.discard)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.debug("HTTP exporter stopped: %r", exc)
        finally:
            self._closed.set()

    async def _forward(self, message):
        request_id = str(message.get("id", ""))
        status, response_headers, body = 502, [], b"upstream request failed"
        try:
            if not request_id:
                raise ValueError("missing request id")
            method = str(message.get("method", "")).upper()
            if method not in self.methods:
                status, body = 405, b"method not allowed"
            else:
                target = str(message.get("target", ""))
                parts = urlsplit(target)
                segments = parts.path.replace("\\", "/").split("/")
                if (parts.scheme or parts.netloc or parts.fragment
                        or not parts.path.startswith("/") or ".." in segments):
                    status, body = 400, b"invalid relative HTTP target"
                elif not any(parts.path.startswith(prefix) for prefix in self.allow):
                    status, body = 403, b"path not allowed"
                else:
                    request_body = _decode_body(message.get("body", ""), self.max_body)
                    query = parse_qsl(parts.query, keep_blank_values=True) + self.query
                    url = self.upstream + parts.path
                    if query:
                        url += "?" + urlencode(query)
                    incoming = message.get("headers") or []
                    if not isinstance(incoming, list):
                        raise ValueError("headers must be a list")
                    request_headers = _safe_headers(incoming, self.drop_request_headers)
                    request_headers.extend(self.headers)
                    async with self._slots:
                        async with self._session.request(
                            method, url, headers=request_headers, data=request_body,
                            allow_redirects=False,
                        ) as response:
                            if (response.content_length is not None
                                    and response.content_length > self.max_body):
                                raise ValueError("HTTP response exceeds configured limit")
                            # StreamReader.read(n) means "at most n", not
                            # "read until EOF"; a single call often returns
                            # only aiohttp's current 64KiB buffer.
                            chunks, size = [], 0
                            async for chunk in response.content.iter_chunked(64 * 1024):
                                size += len(chunk)
                                if size > self.max_body:
                                    raise ValueError("HTTP response exceeds configured limit")
                                chunks.append(chunk)
                            body = b"".join(chunks)
                            status = response.status
                            response_headers = _safe_headers(response.headers.items())
        except ValueError as exc:
            status, response_headers, body = 400, [], str(exc).encode()
        except Exception as exc:
            log.debug("HTTP upstream request failed: %r", exc)
        response = {
            "v": 1, "type": _HTTP_RES, "id": request_id,
            "status": status, "headers": response_headers,
            "body": base64.b64encode(body).decode("ascii"),
        }
        with suppress(Exception):
            await self.socket.send(json.dumps(response, separators=(",", ":")))

    async def close(self):
        if self._receiver:
            self._receiver.cancel()
            with suppress(asyncio.CancelledError):
                await self._receiver
            self._receiver = None
        for task in tuple(self._requests):
            task.cancel()
        if self._requests:
            await asyncio.gather(*self._requests, return_exceptions=True)
        self._requests.clear()
        if self._session:
            await self._session.close()
            self._session = None
        _release_receiver(self.socket, self)
        self._closed.set()

    async def wait_closed(self):
        await self._closed.wait()

    async def serve_forever(self):
        await self.start()
        await self.wait_closed()

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *_):
        await self.close()


class HTTPLocalProxy:
    """Expose the peer's exported HTTP origin as a local aiohttp server."""

    def __init__(
        self, socket, listen=("127.0.0.1", 0), *, cors="loopback",
        timeout=30, max_body=8 * 1024 * 1024, allow_public=False,
    ):
        host, port = listen
        host = str(host)
        if not allow_public and host not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("HTTPLocalProxy is loopback-only by default")
        self.socket, self.listen = socket, (host, int(port))
        self.cors, self.timeout, self.max_body = cors, float(timeout), int(max_body)
        self.allow_public = bool(allow_public)
        self._app = self._runner = self._site = self._receiver = None
        self._pending, self._closed = {}, asyncio.Event()
        self._counter = 0

    async def start(self):
        if self._runner:
            return self
        _, web, _ = _http_modules()
        _claim_receiver(self.socket, self)
        try:
            self._app = web.Application(client_max_size=self.max_body)
            self._app.router.add_route("*", "/{tail:.*}", self._handle)
            self._runner = web.AppRunner(self._app, access_log=None)
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, *self.listen)
            await self._site.start()
            sockets = getattr(self._site, "_server", None).sockets or ()
            if sockets:
                address = sockets[0].getsockname()
                self.url = f"http://{address[0] if ':' not in str(address[0]) else '[' + address[0] + ']'}:{address[1]}"
                self.listen = (address[0], address[1])
            self._receiver = asyncio.create_task(self._receive())
        except Exception:
            _release_receiver(self.socket, self)
            if self._runner:
                await self._runner.cleanup()
                self._runner = self._site = None
            raise
        return self

    def _cors_headers(self, request):
        if self.cors is False or self.cors is None:
            return {}
        origin = request.headers.get("Origin")
        if self.cors == "*":
            return {"Access-Control-Allow-Origin": "*"}
        if self.cors == "loopback":
            allowed = not origin or origin.startswith(("http://127.0.0.1:", "http://localhost:", "http://[::1]:"))
            return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"} if allowed and origin else {}
        if isinstance(self.cors, str):
            return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"} if origin == self.cors else {}
        allowed = origin in self.cors if origin else False
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"} if allowed else {}

    async def _handle(self, request):
        _, web, _ = _http_modules()
        cors_headers = self._cors_headers(request)
        if request.method == "OPTIONS":
            headers = {**cors_headers,
                       "Access-Control-Allow-Methods": "GET,HEAD,POST,PUT,PATCH,DELETE,OPTIONS",
                       "Access-Control-Allow-Headers": request.headers.get("Access-Control-Request-Headers", "Content-Type")}
            return web.Response(status=204, headers=headers)
        if request.headers.get("Content-Length"):
            try:
                if int(request.headers["Content-Length"]) > self.max_body:
                    return web.Response(status=413, text="request body too large", headers=cors_headers)
            except ValueError:
                return web.Response(status=400, text="invalid content length", headers=cors_headers)
        try:
            body = await request.read()
        except Exception as exc:
            return web.Response(status=400, text=str(exc), headers=cors_headers)
        if len(body) > self.max_body:
            return web.Response(status=413, text="request body too large", headers=cors_headers)
        self._counter += 1
        request_id = f"{id(self):x}-{self._counter:x}"
        message = {
            "v": 1, "type": _HTTP_REQ, "id": request_id,
            "method": request.method, "target": request.raw_path,
            "headers": _safe_headers(request.headers.items()),
            "body": base64.b64encode(body).decode("ascii"),
        }
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self.socket.send(json.dumps(message, separators=(",", ":")))
            response = await asyncio.wait_for(future, self.timeout)
        except asyncio.TimeoutError:
            return web.Response(status=504, text="P2P HTTP request timed out", headers=cors_headers)
        except (ConnectionError, asyncio.CancelledError):
            return web.Response(status=502, text="P2P connection closed", headers=cors_headers)
        finally:
            self._pending.pop(request_id, None)
        if not isinstance(response, dict):
            return web.Response(status=502, text="invalid P2P HTTP response", headers=cors_headers)
        try:
            status = int(response["status"])
            response_body = _decode_body(response.get("body", ""), self.max_body)
            headers = dict(_safe_headers(response.get("headers") or []))
        except (KeyError, TypeError, ValueError) as exc:
            return web.Response(status=502, text=f"invalid P2P HTTP response: {exc}", headers=cors_headers)
        headers.update(cors_headers)
        return web.Response(status=status, body=response_body, headers=headers)

    async def _receive(self):
        try:
            while True:
                raw = await self.socket.recv()
                try:
                    message = json.loads(raw) if isinstance(raw, str) else None
                except (TypeError, json.JSONDecodeError):
                    message = None
                if isinstance(message, dict) and message.get("type") == _HTTP_RES:
                    request_id = str(message.get("id", ""))
                    future = self._pending.get(request_id)
                    if future is not None and not future.done():
                        future.set_result(message)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.debug("HTTP local proxy stopped: %r", exc)
        finally:
            for future in tuple(self._pending.values()):
                if not future.done():
                    future.set_exception(ConnectionError("P2P connection closed"))
            self._closed.set()

    async def close(self):
        if self._receiver:
            self._receiver.cancel()
            with suppress(asyncio.CancelledError):
                await self._receiver
            self._receiver = None
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(ConnectionError("HTTP proxy closed"))
        self._pending.clear()
        if self._runner:
            await self._runner.cleanup()
            self._runner = self._site = self._app = None
        _release_receiver(self.socket, self)
        self._closed.set()

    async def wait_closed(self):
        await self._closed.wait()

    async def serve_forever(self):
        await self.start()
        await self.wait_closed()

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *_):
        await self.close()


async def export_http(socket, upstream, **kwargs):
    """Create and start an :class:`HTTPExporter`."""
    return await HTTPExporter(socket, upstream, **kwargs).start()


async def mount_http(socket, listen=("127.0.0.1", 0), **kwargs):
    """Create and start an :class:`HTTPLocalProxy`."""
    return await HTTPLocalProxy(socket, listen, **kwargs).start()


ROOMS_FILE = Path.home() / ".p2p_ws" / "rooms.json"


def _load_rooms(path=ROOMS_FILE):
    path = Path(path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"cannot read saved rooms: {path}: {exc}") from exc


def save_room(signal_url: str, room: str, *, name: str = "default", path=ROOMS_FILE):
    """原子保存配对 UUID；访问密钥不会写入磁盘。"""
    if not name or not isinstance(name, str):
        raise ValueError("name must be a non-empty string")
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    rooms = _load_rooms(path)
    rooms[name] = {
        "signal_url": signal_url,
        "room": room,
        "saved_at": int(time.time()),
    }
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(rooms, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if os.name != "nt":
        temporary.chmod(0o600)
    os.replace(temporary, path)
    return room


def load_room(name: str = "default", *, path=ROOMS_FILE):
    """读取命名配对，返回包含 signal_url/room/saved_at 的字典。"""
    try:
        return _load_rooms(path)[name].copy()
    except KeyError as exc:
        raise KeyError(f"saved room not found: {name}") from exc


async def connect_saved(
    name: str = "default", *, access_key: str = DEFAULT_ACCESS_KEY,
    path=ROOMS_FILE, **kwargs
):
    """使用本机保存的 UUID 长期重连；另一端应使用相同的命名配对。"""
    saved = load_room(name, path=path)
    return await P2PSocket.connect(
        saved["signal_url"], saved["room"], access_key=access_key, **kwargs
    )


@dataclass
class Invite:
    """短码创建结果；显示 ``code``，本端调用 ``connect()`` 等待对方。"""

    code: str
    room: str
    expires_at: int
    signal_url: str
    access_key: str
    name: str = "default"
    rooms_file: object = ROOMS_FILE

    async def connect(self, **kwargs):
        return await P2PSocket.connect(
            self.signal_url, self.room, access_key=self.access_key, **kwargs
        )

async def create_code(
    signal_url: str, *, access_key: str = DEFAULT_ACCESS_KEY,
    name: str = "default", rooms_file=ROOMS_FILE,
) -> Invite:
    """创建两分钟短码并保存 UUID，短码过期后仍可用 connect_saved 重连。"""
    url = signed_url(code_url(signal_url, "code/new"), "code:new", "", access_key)
    data = await _post_json(url)
    save_room(signal_url, data["room"], name=name, path=rooms_file)
    return Invite(
        code=data["code"], room=data["room"], expires_at=data["expires_at"],
        signal_url=signal_url, access_key=access_key, name=name, rooms_file=rooms_file,
    )

async def connect_code(
    signal_url: str, code: str, *, access_key: str = DEFAULT_ACCESS_KEY,
    name: str = "default", rooms_file=ROOMS_FILE, **kwargs
):
    """兑换一次性短码、保存所得 UUID 并立即连接创建者。"""
    if not _CODE.fullmatch(str(code)):
        raise ValueError("code must be exactly 9 digits")
    code = str(code)
    url = signed_url(code_url(signal_url, "code/use") + f"?code={code}",
                     "code:use", code, access_key)
    data = await _post_json(url)
    save_room(signal_url, data["room"], name=name, path=rooms_file)
    return await P2PSocket.connect(
        signal_url, data["room"], access_key=access_key, **kwargs
    )


connect = P2PSocket.connect

__all__ = [
    "DEFAULT_ACCESS_KEY", "ROOMS_FILE", "Invite", "P2PSocket", "Signal",
    "HTTPExporter", "HTTPLocalProxy", "export_http", "mount_http",
    "connect", "connect_code", "connect_saved", "create_code", "load_room",
    "save_room", "signed_url",
]

