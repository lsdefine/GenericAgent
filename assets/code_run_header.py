import sys, os, json, re, time, subprocess
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'memory'))
_r = subprocess.run
def _d(b):
    if not b: return ''
    if isinstance(b, str): return b
    try: return b.decode()
    except: return b.decode('gbk', 'replace')
def _run(*a, **k):
    t = k.pop('text', 0) | k.pop('universal_newlines', 0); r = _r(*a, **k)
    if t:
        if r.stdout is not None: r.stdout = _d(r.stdout)
        if r.stderr is not None: r.stderr = _d(r.stderr)
    return r
subprocess.run = _run

