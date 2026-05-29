"""Keychain: save key to a file, then keys.set("name", file="path"); keys.name.use() to retrieve (use but no print)."""
import json, os, hashlib, pathlib, getpass

_PATH = pathlib.Path.home() / "ga_keychain.enc"
try: _user = os.getlogin()
except OSError: _user = getpass.getuser()
_MASK = hashlib.sha256(f"{_user}@ga_keychain".encode()).digest()

def _xor(data: bytes) -> bytes:
    return bytes(b ^ _MASK[i % len(_MASK)] for i, b in enumerate(data))

print('# SecretStr.use() to get raw, do not print raw value! | keys.ls() to list all keys')

class SecretStr:
    def __init__(self, name: str, val: str):
        self._name, self._val = name, val
    def use(self) -> str: return self._val
    def __repr__(self):
        n = len(self._val)
        if n <= 4:     preview = '***'
        elif n <= 16:  preview = f"{self._val[:3]}···{self._val[-3:]}"
        elif n <= 40:  preview = f"{self._val[:6]}···{self._val[-6:]} len={n}"
        else:          preview = f"{self._val[:10]}···{self._val[-6:]} len={n}"
        return f"SecretStr({self._name}={preview})"
    __str__ = __repr__

class _Keys:
    def __init__(self):
        self._d = {}
        if _PATH.exists():
            try:
                raw = json.loads(_xor(_PATH.read_bytes()))
                self._d = {k: SecretStr(k, v) for k, v in raw.items()}
            except Exception as e:
                print(f"[keychain] WARNING: failed to load {_PATH}: {e}")
                print(f"[keychain] Starting with empty keychain. Old file kept as .bak")
                _PATH.rename(_PATH.with_suffix('.enc.bak'))
    def _save(self):
        raw = {k: v.use() for k, v in self._d.items()}
        _PATH.write_bytes(_xor(json.dumps(raw).encode()))
    def __getattr__(self, k):
        if k.startswith('_'): raise AttributeError(k)
        if k not in self._d: raise KeyError(f"No secret: {k}")
        return self._d[k]
    def __repr__(self):
        return f"Keychain({len(self._d)} secrets: {', '.join(self._d.keys())})"
    def set(self, k, v=None, *, file=None):
        if file: v = pathlib.Path(file).read_text().strip()
        self._d[k] = SecretStr(k, v)
        self._save()
    def ls(self): return list(self._d.keys())

keys = _Keys()

def __getattr__(name): return getattr(keys, name)
