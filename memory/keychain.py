"""Keychain: save key to a file, then keys.set("name", file="path"); keys.name.use() to retrieve (use but no print)."""
import json, os, pathlib, getpass
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

_PATH = pathlib.Path.home() / "ga_keychain.enc"
try: _user = os.getlogin()
except OSError: _user = getpass.getuser()

def _get_fernet(password: str) -> Fernet:
    salt = b"ga_keychain_salt_v1"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480000)
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return Fernet(key)

class SecretStr:
    def __init__(self, name: str, val: str):
        self._name, self._val = name, val
    def use(self) -> str:
        return self._val
    def __repr__(self):
        n = len(self._val)
        if n <= 4:     preview = '***'
        elif n <= 16:  preview = f"{self._val[:3]}···{self._val[-3:]}"
        elif n <= 40:  preview = f"{self._val[:6]}···{self._val[-6:]} len={n}"
        else:          preview = f"{self._val[:10]}···{self._val[-6:]} len={n}"
        return f"SecretStr({self._name}={preview}) # .use() to get raw, do not print raw value"
    __str__ = __repr__

class _Keys:
    def __init__(self):
        self._d = {}
        self._fernet = None
        if _PATH.exists():
            try:
                data = _PATH.read_bytes()
                if data:
                    password = getpass.getpass("[keychain] Enter password to decrypt: ")
                    self._fernet = _get_fernet(password)
                    self._d = json.loads(self._fernet.decrypt(data))
            except Exception as e:
                print(f"[keychain] WARNING: failed to load {_PATH}: {e}")
                print(f"[keychain] Starting with empty keychain. Old file kept as .bak")
                _PATH.rename(_PATH.with_suffix('.enc.bak'))
    def __getattr__(self, k):
        if k.startswith('_'): raise AttributeError(k)
        if k not in self._d: raise KeyError(f"No secret: {k}")
        return SecretStr(k, self._d[k])
    def set(self, k, v=None, *, file=None):
        if file: v = pathlib.Path(file).read_text().strip()
        self._d[k] = v
        if self._fernet is None:
            password = getpass.getpass("[keychain] Set a password for encryption: ")
            self._fernet = _get_fernet(password)
        _PATH.write_bytes(self._fernet.encrypt(json.dumps(self._d).encode()))
    def ls(self): return list(self._d.keys())

keys = _Keys()

def __getattr__(name): return getattr(keys, name)
