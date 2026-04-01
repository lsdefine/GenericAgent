import os, sys, re, threading, queue, time, socket, json, struct, base64, uuid, webbrowser, hashlib, math
from pathlib import Path
from urllib.parse import quote
import requests, qrcode
from Crypto.Cipher import AES
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'temp')
from agentmain import GeneraticAgent

# ── WxBotClient (inline from wx_bot_client.py) ──
API = 'https://ilinkai.weixin.qq.com'
TOKEN_FILE = Path.home() / '.wxbot' / 'token.json'
TOKEN_FILE.parent.mkdir(exist_ok=True)
VER, MSG_USER, MSG_BOT, ITEM_TEXT, STATE_FINISH = '0.2.5', 1, 2, 1, 2
ITEM_FILE = 4
CDN_BASE = 'https://novac2c.cdn.weixin.qq.com/c2c'

def _uin():
    return base64.b64encode(str(struct.unpack('>I', os.urandom(4))[0]).encode()).decode()

class WxBotClient:
    def __init__(self, token=None, token_file=None):
        self._tf = Path(token_file) if token_file else TOKEN_FILE
        self.token = token
        self.bot_id = None
        self._buf = ''
        if not self.token: self._load()

    def _load(self):
        if self._tf.exists():
            d = json.loads(self._tf.read_text('utf-8'))
            self.token, self.bot_id, self._buf = d.get('bot_token',''), d.get('ilink_bot_id',''), d.get('updates_buf','')

    def _save(self, **kw):
        d = {'bot_token': self.token or '', 'ilink_bot_id': self.bot_id or '',
             'updates_buf': self._buf or '', **kw}
        self._tf.write_text(json.dumps(d, ensure_ascii=False, indent=2), 'utf-8')

    def _post(self, ep, body, timeout=15):
        h = {'Content-Type': 'application/json', 'AuthorizationType': 'ilink_bot_token', 'X-WECHAT-UIN': _uin()}
        if self.token: h['Authorization'] = f'Bearer {self.token}'
        r = requests.post(f'{API}/{ep}', json=body, headers=h, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def login_qr(self, poll_interval=2):
        r = requests.get(f'{API}/ilink/bot/get_bot_qrcode', params={'bot_type': 3}, timeout=10)
        r.raise_for_status()
        d = r.json()
        qr_id, url = d['qrcode'], d.get('qrcode_img_content', '')
        print(f'[QR登录] ID: {qr_id}')
        if url:
            img = self._tf.parent / 'wx_qr.png'
            qrcode.make(url).save(str(img)); webbrowser.open(str(img))
        last = ''
        while True:
            time.sleep(poll_interval)
            try: s = requests.get(f'{API}/ilink/bot/get_qrcode_status', params={'qrcode': qr_id}, timeout=60).json()
            except requests.exceptions.ReadTimeout: continue
            st = s.get('status', '')
            if st != last: print(f'  状态: {st}'); last = st
            if st == 'confirmed':
                self.token, self.bot_id = s.get('bot_token', ''), s.get('ilink_bot_id', '')
                self._save(login_time=time.strftime('%Y-%m-%d %H:%M:%S'))
                print(f'[QR登录] 成功! bot_id={self.bot_id}')
                return s
            if st == 'expired': raise RuntimeError('二维码过期')

    def get_updates(self, timeout=30):
        try:
            resp = self._post('ilink/bot/getupdates',
                              {'get_updates_buf': self._buf or '', 'base_info': {'channel_version': VER}},
                              timeout=timeout + 5)
        except requests.exceptions.ReadTimeout:
            return []
        if resp.get('errcode'):
            print(f'[getUpdates] err: {resp.get("errcode")} {resp.get("errmsg","")}')
            if resp['errcode'] == -14: self._buf = ''; self._save()
            return []
        nb = resp.get('get_updates_buf', '')
        if nb: self._buf = nb; self._save()
        return resp.get('msgs') or []

    def send_text(self, to_user_id, text, context_token=''):
        msg = {'from_user_id': '', 'to_user_id': to_user_id,
               'client_id': f'pyclient-{uuid.uuid4().hex[:16]}',
               'message_type': MSG_BOT, 'message_state': STATE_FINISH,
               'item_list': [{'type': ITEM_TEXT, 'text_item': {'text': text}}]}
        if context_token: msg['context_token'] = context_token
        return self._post('ilink/bot/sendmessage', {'msg': msg, 'base_info': {'channel_version': VER}})

    def send_typing(self, to_user_id, typing_ticket='', cancel=False):
        return self._post('ilink/bot/sendtyping', {
            'to_user_id': to_user_id, 'typing_ticket': typing_ticket,
            'typing_status': 2 if cancel else 1, 'base_info': {'channel_version': VER}})

    def send_file(self, to_user_id, file_path, context_token=''):
        """Send a file to user via CDN upload."""
        fp = Path(file_path)
        raw = fp.read_bytes()
        rawsize = len(raw)
        rawfilemd5 = hashlib.md5(raw).hexdigest()
        aes_key = os.urandom(16)
        filekey = uuid.uuid4().hex
        ciphertext_size = ((rawsize // 16) + 1) * 16
        # 1. get upload url
        resp = self._post('ilink/bot/getuploadurl', {
            'filekey': filekey, 'media_type': 3, 'to_user_id': to_user_id,
            'rawsize': rawsize, 'rawfilemd5': rawfilemd5,
            'filesize': ciphertext_size, 'no_need_thumb': True,
            'aeskey': aes_key.hex(),
            'base_info': {'channel_version': VER}})
        upload_param = resp.get('upload_param', '')
        if not upload_param:
            raise RuntimeError(f'getuploadurl failed: {resp}')
        # 2. AES-128-ECB encrypt (PKCS7)
        cipher = AES.new(aes_key, AES.MODE_ECB)
        pad_len = 16 - (rawsize % 16)
        ciphertext = cipher.encrypt(raw + bytes([pad_len] * pad_len))
        # 3. upload to CDN
        upload_url = (f'{CDN_BASE}/upload?encrypted_query_param='
                      f'{quote(upload_param)}&filekey={filekey}')
        r = requests.post(upload_url, data=ciphertext, headers={'Content-Type': 'application/octet-stream'}, timeout=120)
        r.raise_for_status()
        download_param = r.headers.get('x-encrypted-param', '')
        if not download_param:
            raise RuntimeError(f'CDN upload: no x-encrypted-param. status={r.status_code}')
        # 4. send message with file attachment
        msg = {'from_user_id': '', 'to_user_id': to_user_id,
               'client_id': f'pyclient-{uuid.uuid4().hex[:16]}',
               'message_type': MSG_BOT, 'message_state': STATE_FINISH,
               'item_list': [{'type': ITEM_FILE, 'file_item': {
                   'media': {'encrypt_query_param': download_param,
                             'aes_key': base64.b64encode(aes_key.hex().encode()).decode(), 'encrypt_type': 1},
                   'file_name': fp.name, 'len': str(rawsize)}}]}
        if context_token: msg['context_token'] = context_token
        return self._post('ilink/bot/sendmessage', {'msg': msg, 'base_info': {'channel_version': VER}})

    @staticmethod
    def extract_text(msg):
        return '\n'.join(it['text_item'].get('text', '')
                         for it in msg.get('item_list', [])
                         if it.get('type') == ITEM_TEXT and it.get('text_item'))

    @staticmethod
    def is_user_msg(msg): return msg.get('message_type') == MSG_USER

    def run_loop(self, on_message, poll_timeout=30):
        print(f'[Bot] 监听中... (bot_id={self.bot_id})')
        seen = set()
        while True:
            try:
                for msg in self.get_updates(poll_timeout):
                    mid = msg.get('message_id', 0)
                    if not self.is_user_msg(msg) or mid in seen: continue
                    seen.add(mid)
                    if len(seen) > 5000: seen = set(list(seen)[-2000:])
                    try: on_message(self, msg)
                    except Exception as e: print(f'[Bot] 回调异常: {e}')
            except KeyboardInterrupt: print('[Bot] 退出'); break
            except Exception as e: print(f'[Bot] 异常: {e}，5s重试'); time.sleep(5)

# ── Unified media download (IMAGE/VIDEO/FILE/VOICE) ──
_MEDIA_KEYS = {'image_item': '.jpg', 'video_item': '.mp4', 'file_item': '', 'voice_item': '.silk'}

def _dl_media(items):
    """Download & decrypt all media items → list of local file paths."""
    paths = []
    for item in items:
        for key, ext in _MEDIA_KEYS.items():
            sub = item.get(key)
            if not sub: continue
            eq = (sub.get('media') or {}).get('encrypt_query_param')
            if not eq: continue
            ak = (sub.get('media') or {}).get('aes_key', '') or sub.get('aeskey', '')
            if not ak: continue
            try:
                aes_key = (bytes.fromhex(base64.b64decode(ak).decode())
                           if sub.get('media', {}).get('aes_key') else bytes.fromhex(ak))
                ct = requests.get(f'{CDN_BASE}/download?encrypted_query_param={quote(eq)}', timeout=60).content
                pt = AES.new(aes_key, AES.MODE_ECB).decrypt(ct); pt = pt[:-pt[-1]]
                fname = sub.get('file_name') or f'{uuid.uuid4().hex[:8]}{ext or ".bin"}'
                p = os.path.join(_TEMP_DIR, fname); open(p, 'wb').write(pt)
                paths.append(p); print(f'[WX] media saved: {fname}', file=sys.__stdout__)
            except Exception as e:
                print(f'[WX] media dl err ({key}): {e}', file=sys.__stdout__)
            break  # one media per item
    return paths

agent = GeneraticAgent()
agent.verbose = False

_TAG_PATS = [r'<' + t + r'>.*?</' + t + r'>' for t in ('thinking', 'summary', 'tool_use')]
_TAG_PATS.append(r'<file_content>.*?</file_content>')

def _strip_md(t):
    def _trunc_code(m):
        body = m.group().strip('`')
        if '\n' not in body: return body
        lines = body.split('\n', 1)[-1].split('\n')  # drop language line
        if len(lines) > 10: return '\n'.join(lines[:10]) + '\n...'
        return '\n'.join(lines)
    t = re.sub(r'(`{3,})[\s\S]*?\1', _trunc_code, t)
    t = re.sub(r'`([^`]+)`', r'\1', t)
    t = re.sub(r'!\[.*?\]\(.*?\)', '', t)
    t = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', t)
    t = re.sub(r'^#{1,6}\s+', '', t, flags=re.M)
    t = re.sub(r'(\*{1,3})(.*?)\1', r'\2', t)
    t = re.sub(r'^\s*[-*+]\s+', '• ', t, flags=re.M)
    t = re.sub(r'^\s*\d+\.\s+', '', t, flags=re.M)
    t = re.sub(r'^\s*>\s?', '', t, flags=re.M)
    t = re.sub(r'^---+$', '', t, flags=re.M)
    return re.sub(r'\n{3,}', '\n\n', t).strip()

def _clean(t):
    for p in _TAG_PATS:
        t = re.sub(p, '', t, flags=re.DOTALL)
    return re.sub(r'\n{3,}', '\n\n', _strip_md(t)).strip() or '...'

def _split(text, limit=1800):
    """Split text into chunks respecting line boundaries."""
    if len(text) <= limit: return [text]
    chunks, cur = [], ''
    for line in text.split('\n'):
        if len(cur) + len(line) + 1 > limit and cur:
            chunks.append(cur); cur = line
        else:
            cur = cur + '\n' + line if cur else line
    if cur: chunks.append(cur)
    return chunks or ['...']

def on_message(bot, msg):
    text = bot.extract_text(msg).strip()
    uid = msg.get('from_user_id', '')
    ctx = msg.get('context_token', '')
    media_paths = _dl_media(msg.get('item_list', []))
    if not text and not media_paths: return
    if media_paths:
        text = (text + '\n' if text else '') + '\n'.join(f'[用户发送文件: {p}]' for p in media_paths)
    print(f'[WX] 收到: {text[:80]}', file=sys.__stdout__)

    # Commands
    if text in ('/stop', '/abort'):
        agent.abort()
        bot.send_text(uid, '已停止', context_token=ctx)
        return
    if text.startswith('/llm'):
        args = text.split()
        if len(args) > 1:
            try:
                n = int(args[1]); agent.next_llm(n)
                bot.send_text(uid, f'切换到 [{agent.llm_no}] {agent.get_llm_name()}', context_token=ctx)
            except (ValueError, IndexError):
                bot.send_text(uid, f'用法: /llm <0-{len(agent.list_llms())-1}>', context_token=ctx)
        else:
            lines = [f"{'→' if cur else '  '} [{i}] {name}" for i, name, cur in agent.list_llms()]
            bot.send_text(uid, 'LLMs:\n' + '\n'.join(lines), context_token=ctx)
        return

    def _handle():
        prompt = f"If you need to show files to user, use [FILE:filepath] in your response.\n\n{text}"
        dq = agent.put_task(prompt, source="wechat")
        try: bot.send_typing(uid)
        except: pass
        # Wait for completion
        result = ''
        try:
            while True:
                item = dq.get(timeout=300)
                if 'done' in item: result = item['done']; break
        except queue.Empty: result = '[超时]'
        files = re.findall(r'\[FILE:([^\]]+)\]', result)
        files = [f for f in files if (f if os.path.isabs(f) else os.path.join(_TEMP_DIR, f)) not in media_paths]
        show = _clean(result)
        chunks = _split(show)
        _MAX_MSGS = 6
        if len(chunks) > _MAX_MSGS:
            keep = chunks[:3] + [f'...（省略{len(chunks) - 5}条）...'] + chunks[-2:]
            chunks = keep
        for chunk in chunks:
            try: bot.send_text(uid, chunk, context_token=ctx)
            except Exception as e: print(f'[WX] send err: {e}', file=sys.__stdout__)
            time.sleep(0.3)
        for fpath in set(files):
            if not os.path.isabs(fpath): fpath = os.path.join(_TEMP_DIR, fpath)
            try:
                if not os.path.exists(fpath): raise FileNotFoundError(f"文件不存在: {fpath}")
                bot.send_file(uid, fpath, context_token=ctx)
                print(f'[WX] sent file: {fpath}', file=sys.__stdout__)
            except Exception as e: print(f'[WX] send_file err: {e}', file=sys.__stdout__)

    threading.Thread(target=_handle, daemon=True).start()

if __name__ == '__main__':
    try: _lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); _lock.bind(('127.0.0.1', 19528))
    except OSError: print('[WeChat] Another instance running, exiting.'); sys.exit(1)
    _logf = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp', 'wechatapp.log'), 'a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = _logf
    print(f'[NEW] Process starting {time.strftime("%m-%d %H:%M")}')
    bot = WxBotClient()
    if not bot.token:
        sys.stdout = sys.stderr = sys.__stdout__  # restore for QR display
        bot.login_qr()
        sys.stdout = sys.stderr = _logf
    threading.Thread(target=agent.run, daemon=True).start()
    print(f'WeChat Bot 已启动 (bot_id={bot.bot_id})', file=sys.__stdout__)
    bot.run_loop(on_message)