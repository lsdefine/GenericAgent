"""
SuperGrok Local Proxy - CLI
本地 OpenAI 兼容代理，通过 xAI OAuth (PKCE) 登录 SuperGrok，自动管理 token 并转发请求。

用法：
  python assets/supergrok_proxy.py login
  python assets/supergrok_proxy.py serve --port 15433
  python assets/supergrok_proxy.py models
  python assets/supergrok_proxy.py test --model grok-4.3

GenericAgent/mykey 配置示例：
  native_oai_config_supergrok_proxy = {
      'name': 'supergrok',
      'apikey': 'dummy',
      'apibase': 'http://127.0.0.1:15433/v1',
      'model': 'grok-4.3',
      'max_retries': 3,
      'read_timeout': 600,
      'stream': False,
  }
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs

import requests

XAI_CLIENT_ID = 'b1a00492-073a-47ea-816f-4c329264a828'
XAI_AUTHORIZE_URL = 'https://auth.x.ai/oauth2/authorize'
XAI_TOKEN_URL = 'https://auth.x.ai/oauth2/token'
XAI_SCOPE = 'openid profile email offline_access grok-cli:access api:access'
XAI_CALLBACK_PORT = 56121
XAI_CALLBACK_URI = f'http://127.0.0.1:{XAI_CALLBACK_PORT}/callback'
XAI_API_BASE = 'https://api.x.ai/v1'
DEFAULT_STORE = os.path.join(os.path.expanduser('~'), '.genericagent', 'xai_oauth.json')
DEFAULT_PROXY_PORT = 15433
REFRESH_MARGIN = 120


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def make_proxies(proxy: str | None):
    if not proxy:
        return None
    return {'http': proxy, 'https': proxy}


class TokenManager:
    def __init__(self, store_path=DEFAULT_STORE, proxy='http://127.0.0.1:2082'):
        self.store_path = os.path.expanduser(store_path)
        self.proxy = proxy or None
        self.proxies = make_proxies(self.proxy)
        self.lock = threading.Lock()
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0.0
        self.load()

    def load(self):
        try:
            with open(self.store_path, encoding='utf-8') as f:
                data = json.load(f)
            self.access_token = data.get('access_token')
            self.refresh_token = data.get('refresh_token')
            self.expires_at = float(data.get('expires_at') or 0)
            if self.access_token:
                remain = int(self.expires_at - time.time())
                log(f"Token loaded: ***{self.access_token[-6:]} expires_in={remain}s")
        except FileNotFoundError:
            log(f"No saved token: {self.store_path}")
        except Exception as e:
            log(f"Failed to load token: {e}")

    def save(self, data):
        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
        with open(self.store_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(self.store_path, 0o600)
        except OSError:
            pass
        log(f"Token saved: {self.store_path}")

    def login(self, open_browser=True, timeout=300):
        verifier = b64url(secrets.token_bytes(32))
        challenge = b64url(hashlib.sha256(verifier.encode()).digest())
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        params = {
            'client_id': XAI_CLIENT_ID,
            'redirect_uri': XAI_CALLBACK_URI,
            'response_type': 'code',
            'scope': XAI_SCOPE,
            'state': state,
            'nonce': nonce,
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
            'plan': 'generic',
            'referrer': 'generic-agent',
        }
        auth_url = f'{XAI_AUTHORIZE_URL}?{urlencode(params)}'
        result = {}

        class CallbackHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def do_GET(self):
                qs = parse_qs(urlparse(self.path).query)
                result.update({k: v[0] for k, v in qs.items() if v})
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write('SuperGrok login complete. You can close this tab.'.encode('utf-8'))

        httpd = HTTPServer(('127.0.0.1', XAI_CALLBACK_PORT), CallbackHandler)
        httpd.timeout = 1
        log(f"Callback listening: {XAI_CALLBACK_URI}")
        log("Open this URL to login xAI/SuperGrok:")
        print(auth_url, flush=True)
        if open_browser:
            try:
                webbrowser.open(auth_url)
            except Exception as e:
                log(f"Browser open failed: {e}")

        deadline = time.time() + timeout
        while not result.get('code') and time.time() < deadline:
            httpd.handle_request()
        httpd.server_close()

        if not result.get('code'):
            raise RuntimeError(f'OAuth timeout after {timeout}s')
        if result.get('state') and result['state'] != state:
            raise RuntimeError('OAuth state mismatch')

        log("Exchanging authorization code for token...")
        resp = requests.post(XAI_TOKEN_URL, data={
            'grant_type': 'authorization_code',
            'client_id': XAI_CLIENT_ID,
            'code': result['code'],
            'redirect_uri': XAI_CALLBACK_URI,
            'code_verifier': verifier,
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
        }, proxies=self.proxies, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        data['expires_at'] = time.time() + int(data.get('expires_in', 3600))
        self.access_token = data.get('access_token')
        self.refresh_token = data.get('refresh_token')
        self.expires_at = data['expires_at']
        self.save(data)
        log("Login OK")
        return self.access_token

    def get_token(self):
        with self.lock:
            if self.access_token and time.time() < self.expires_at - REFRESH_MARGIN:
                return self.access_token
            return self.refresh()

    def refresh(self):
        if not self.refresh_token:
            raise RuntimeError('No refresh_token. Run login first.')
        log("Refreshing token...")
        resp = requests.post(XAI_TOKEN_URL, data={
            'grant_type': 'refresh_token',
            'client_id': XAI_CLIENT_ID,
            'refresh_token': self.refresh_token,
        }, proxies=self.proxies, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        data['expires_at'] = time.time() + int(data.get('expires_in', 3600))
        if 'refresh_token' not in data:
            data['refresh_token'] = self.refresh_token
        self.access_token = data.get('access_token')
        self.refresh_token = data.get('refresh_token')
        self.expires_at = data['expires_at']
        self.save(data)
        log(f"Refresh OK expires_in={int(self.expires_at - time.time())}s")
        return self.access_token


def make_proxy_handler(token_mgr: TokenManager):
    class ProxyHandler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, fmt, *args):
            pass

        def _send_json_error(self, code, msg):
            body = json.dumps({'error': {'message': str(msg), 'type': 'supergrok_proxy_error'}}).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _target_url(self):
            path = self.path
            if path.startswith('/v1/'):
                path = path[3:]
            elif path == '/v1':
                path = ''
            return XAI_API_BASE + path

        def do_GET(self):
            try:
                token = token_mgr.get_token()
                target = self._target_url()
                log(f"GET {self.path} -> {target}")
                resp = requests.get(target, headers={
                    'Authorization': f'Bearer {token}',
                    'Accept': 'application/json',
                    'User-Agent': 'GenericAgent-SuperGrok-Proxy/1.0',
                }, proxies=token_mgr.proxies, timeout=60)
                content = resp.content
                self.send_response(resp.status_code)
                self.send_header('Content-Type', resp.headers.get('content-type', 'application/json'))
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                log(f"RESP {resp.status_code}")
            except Exception as e:
                log(f"GET error: {e}")
                self._send_json_error(502, e)

        def do_POST(self):
            try:
                length = int(self.headers.get('Content-Length', 0))
                raw = self.rfile.read(length) if length else b'{}'
                try:
                    body = json.loads(raw.decode('utf-8')) if raw else {}
                except Exception:
                    body = None
                stream = bool(body.get('stream')) if isinstance(body, dict) else False
                model = body.get('model', '?') if isinstance(body, dict) else '?'
                token = token_mgr.get_token()
                target = self._target_url()
                log(f"POST {self.path} model={model} stream={stream}")
                resp = requests.post(target, headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type': self.headers.get('Content-Type', 'application/json'),
                    'Accept': 'text/event-stream' if stream else 'application/json',
                    'User-Agent': 'GenericAgent-SuperGrok-Proxy/1.0',
                    'x-request-id': str(uuid.uuid4()),
                }, data=raw, proxies=token_mgr.proxies, timeout=180, stream=stream)

                ctype = resp.headers.get('content-type', '')
                if stream or 'text/event-stream' in ctype:
                    self.send_response(resp.status_code)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Cache-Control', 'no-cache')
                    self.end_headers()
                    for chunk in resp.iter_content(chunk_size=None):
                        if chunk:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                else:
                    content = resp.content
                    self.send_response(resp.status_code)
                    self.send_header('Content-Type', ctype or 'application/json')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)

                if resp.status_code >= 400:
                    log(f"RESP {resp.status_code} {'' if stream else resp.text[:500]}")
                else:
                    log(f"RESP {resp.status_code}")
            except Exception as e:
                log(f"POST error: {e}")
                self._send_json_error(502, e)

    return ProxyHandler


def cmd_login(args):
    TokenManager(args.store, args.upstream_proxy).login(open_browser=not args.no_browser, timeout=args.timeout)


def cmd_refresh(args):
    TokenManager(args.store, args.upstream_proxy).refresh()


def cmd_serve(args):
    mgr = TokenManager(args.store, args.upstream_proxy)
    if not mgr.access_token:
        log("No token found. Starting login first...")
        mgr.login(open_browser=not args.no_browser, timeout=args.timeout)
    else:
        mgr.get_token()
    server = ThreadingHTTPServer((args.host, args.port), make_proxy_handler(mgr))
    log(f"Serving OpenAI-compatible proxy at http://{args.host}:{args.port}/v1")
    log("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Stopping...")
    finally:
        server.server_close()


def cmd_models(args):
    mgr = TokenManager(args.store, args.upstream_proxy)
    token = mgr.get_token()
    resp = requests.get(f'{XAI_API_BASE}/models', headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'User-Agent': 'GenericAgent-SuperGrok-Proxy/1.0',
    }, proxies=mgr.proxies, timeout=60)
    print(resp.status_code)
    print(resp.text)
    resp.raise_for_status()


def cmd_test(args):
    mgr = TokenManager(args.store, args.upstream_proxy)
    token = mgr.get_token()
    payload = {'model': args.model, 'messages': [{'role': 'user', 'content': args.prompt}], 'stream': False}
    resp = requests.post(f'{XAI_API_BASE}/chat/completions', headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'GenericAgent-SuperGrok-Proxy/1.0',
    }, json=payload, proxies=mgr.proxies, timeout=120)
    print(resp.status_code)
    print(resp.text)
    resp.raise_for_status()


def build_parser():
    p = argparse.ArgumentParser(description='SuperGrok xAI OAuth local OpenAI-compatible proxy')
    p.add_argument('--store', default=DEFAULT_STORE, help=f'token store path, default: {DEFAULT_STORE}')
    p.add_argument('--upstream-proxy', default='http://127.0.0.1:2082', help='proxy for xAI auth/api; empty disables')
    # Defaults for zero-argument mode: run once, login if needed, then serve.
    p.set_defaults(func=cmd_serve, host='127.0.0.1', port=DEFAULT_PROXY_PORT, no_browser=False, timeout=300)
    sub = p.add_subparsers(dest='cmd')

    sp = sub.add_parser('login', help='open browser and login xAI OAuth')
    sp.add_argument('--no-browser', action='store_true')
    sp.add_argument('--timeout', type=int, default=300)
    sp.set_defaults(func=cmd_login)

    sp = sub.add_parser('refresh', help='refresh saved token')
    sp.set_defaults(func=cmd_refresh)

    sp = sub.add_parser('serve', help='serve local OpenAI-compatible proxy')
    sp.add_argument('--host', default='127.0.0.1')
    sp.add_argument('--port', type=int, default=DEFAULT_PROXY_PORT)
    sp.add_argument('--no-browser', action='store_true')
    sp.add_argument('--timeout', type=int, default=300)
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser('models', help='call /v1/models directly')
    sp.set_defaults(func=cmd_models)

    sp = sub.add_parser('test', help='send one chat completion request directly')
    sp.add_argument('--model', default='grok-4.3')
    sp.add_argument('--prompt', default='Say OK in one word.')
    sp.set_defaults(func=cmd_test)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.upstream_proxy == '':
        args.upstream_proxy = None
    args.func(args)


if __name__ == '__main__':
    main()
