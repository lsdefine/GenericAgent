"""L4 Session Log Processor — compress & extract history.
Format A (JSON): kept as-is.  Format B (Raw): strip sys prompt & assistant echo.
"""
import re, os, json, ast
from datetime import datetime

L4_DIR = os.path.dirname(os.path.abspath(__file__))

_RE_PROMPT   = re.compile(r'^=== Prompt ===(?: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}))?', re.M)
_RE_RESPONSE = re.compile(r'^=== Response ===(?: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}))?', re.M)
_RE_USER     = re.compile(r'^=== USER ===$', re.M)
_RE_ASST     = re.compile(r'^=== ASSISTANT ===$', re.M)
_RE_ANY_MARKER = re.compile(r'^=== (?:Prompt|Response|USER|ASSISTANT) ===(?:.*)?$', re.M)

def _ts_fmt(ts_str):
    """'2026-04-03 20:13:06' → '0403_2013'"""
    try: return datetime.strptime(ts_str.strip(), '%Y-%m-%d %H:%M:%S').strftime('%m%d_%H%M')
    except Exception: return None

def _detect_format(text):
    """Detect A (json) vs B (raw) by checking content after first Prompt marker."""
    m = _RE_PROMPT.search(text)
    if not m: return 'unknown'
    return 'json' if re.match(r'\s*\{', text[m.end():m.end()+200]) else 'raw'

def _parse_sections(text):
    """Split text into (type, marker_line, body) tuples."""
    markers = list(_RE_ANY_MARKER.finditer(text))
    if not markers:
        return [('preamble', '', text)]
    _MAP = {'Prompt': 'prompt', 'Response': 'response', 'USER': 'user', 'ASSISTANT': 'assistant'}
    sections = []
    if markers[0].start() > 0:
        sections.append(('preamble', '', text[:markers[0].start()]))
    for i, m in enumerate(markers):
        line = m.group()
        end = markers[i+1].start() if i+1 < len(markers) else len(text)
        typ = next((v for k, v in _MAP.items() if line.startswith(f'=== {k}')), None)
        if typ:
            sections.append((typ, line, text[m.end():end]))
    return sections

def compress_session(src, dst_dir=None):
    """Compress model_responses_xxx.txt → MMDD_HHMM-MMDD_HHMM.txt. Returns (dst, stats) or (None, reason)."""
    dst_dir = dst_dir or L4_DIR
    with open(src, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()
    timestamps = [m.group(1) for m in _RE_PROMPT.finditer(text) if m.group(1)]
    if not timestamps:  # fallback to Response timestamps
        timestamps = [m.group(1) for m in _RE_RESPONSE.finditer(text) if m.group(1)]
    if not timestamps:
        return None, 'no timestamps found'
    ts_first, ts_last = _ts_fmt(timestamps[0]), _ts_fmt(timestamps[-1])
    if not ts_first:
        return None, 'bad timestamp format'
    name = f"{ts_first}-{ts_last or ts_first}.txt"
    fmt = _detect_format(text)
    compressed = _compress_raw(text) if fmt == 'raw' else text
    if len(compressed.encode('utf-8')) < 4500:
        return None, f'too small after compress ({len(compressed)}B)'
    dst = os.path.join(dst_dir, name)
    with open(dst, 'w', encoding='utf-8', newline='') as f:
        f.write(compressed)
    orig_kb, new_kb = os.path.getsize(src) // 1024, os.path.getsize(dst) // 1024
    ratio = (1 - new_kb / max(orig_kb, 1)) * 100
    return dst, {'src': os.path.basename(src), 'dst': name, 'fmt': fmt,
                 'orig_kb': orig_kb, 'new_kb': new_kb, 'ratio': f'{ratio:.0f}%',
                 'year': timestamps[0][:4]}

def _compress_raw(text):
    """Format B: strip system prompt (Prompt→USER) and assistant echo (ASSISTANT→Response)."""
    sections = _parse_sections(text)
    out = []
    for i, (typ, line, body) in enumerate(sections):
        if typ == 'prompt':
            out.append(line + '\n')
            if not (i+1 < len(sections) and sections[i+1][0] == 'user'):
                out.append(body)  # no USER follows → keep body
        elif typ in ('user', 'response'):
            out.append(line + '\n')
            out.append(body)
        elif typ == 'preamble':
            out.append(body)
        # assistant → skip (redundant echo)
    return ''.join(out)

_RE_HISTORY = re.compile(r'<history>(.*?)</history>', re.S)

def _parse_history_block(raw):
    """Parse <history> block into ['[USER]...', '[Agent]...'] lines."""
    lines = [l.strip() for l in raw.split('\n') if l.strip()]
    parsed = [l for l in lines if l.startswith('[USER]') or l.startswith('[Agent]')]
    if len(parsed) >= 2:
        return parsed
    # JSON format: literal \\n separators
    joined = raw.strip()
    if '\\n[USER]' in joined or '\\n[Agent]' in joined:
        parts = joined.replace('\\n', '\n').split('\n')
        parsed = [p.strip() for p in parts if p.strip() and (p.strip().startswith('[USER]') or p.strip().startswith('[Agent]'))]
        if parsed: return parsed
    return parsed or []

def _merge_history_blocks(all_blocks):
    """Merge sliding-window history blocks into one deduplicated list."""
    if not all_blocks: return []
    acc = list(all_blocks[0])
    for block in all_blocks[1:]:
        if not block: continue
        if not acc:
            acc = list(block); continue
        best = 0
        for k in range(1, min(len(acc), len(block)) + 1):
            if acc[-k:] == block[:k]: best = k
        if best > 0:
            acc.extend(block[best:])
        elif block[0] in acc:
            idx = len(acc) - 1 - acc[::-1].index(block[0])
            match_len = 0
            for j in range(min(len(block), len(acc) - idx)):
                if acc[idx + j] == block[j]: match_len = j + 1
                else: break
            acc.extend(block[match_len:])
        else:
            acc.extend(block)
    return acc

def extract_history(src, session_name=None):
    """Extract [USER]/[Agent] history from session file."""
    with open(src, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()
    if session_name is None:
        session_name = os.path.splitext(os.path.basename(src))[0]
    all_blocks = [parsed for m in _RE_HISTORY.finditer(text)
                  if (parsed := _parse_history_block(m.group(1)))]
    if all_blocks:
        return _merge_history_blocks(all_blocks)
    return []

def format_history_block(session_name, history_lines):
    """Format history lines into all_histories.txt block format."""
    sep = '=' * 60
    return f"{sep}\nSESSION: {session_name}\n{sep}\n" + '\n'.join(history_lines) + '\n'

import tempfile, shutil, zipfile, glob
from collections import defaultdict

def _existing_sessions(l4_dir):
    """Read session names already in all_histories.txt."""
    hist_path = os.path.join(l4_dir, 'all_histories.txt')
    if not os.path.exists(hist_path): return set()
    with open(hist_path, 'r', encoding='utf-8') as f:
        return {l.strip().replace('SESSION: ', '') for l in f if l.startswith('SESSION: ')}

def batch_process(src, l4_dir=None, dry_run=True):
    """Batch compress + extract history + archive. dry_run=True is safe default."""
    l4_dir = os.path.normpath(l4_dir or L4_DIR)
    raw_files = sorted(src) if isinstance(src, (list, tuple)) else \
                sorted(glob.glob(os.path.join(src, 'model_responses_*.txt')))
    if not raw_files:
        print("No raw files found"); return {'processed': 0, 'skipped': 0, 'errors': 0, 'new_sessions': 0}

    existing = _existing_sessions(l4_dir)
    print(f"Found {len(raw_files)} raw, {len(existing)} existing in L4")

    tmp_dir = tempfile.mkdtemp(prefix='cs_batch_')
    results, skipped, errors = [], [], []

    import time
    cutoff = time.time() - 7200  # skip files modified within 2h

    # Phase 1: Compress + Extract (to temp dir)
    for fp in raw_files:
        fname = os.path.basename(fp)
        if os.path.getmtime(fp) > cutoff:
            skipped.append((fname, 'recent(<2h)')); continue
        try:
            dst, info = compress_session(fp, tmp_dir)
            if dst is None:
                skipped.append((fname, info)); continue
            sn = os.path.splitext(os.path.basename(dst))[0]
            if sn in existing:
                skipped.append((fname, f'dup:{sn}')); os.remove(dst); continue
            results.append((sn, dst, extract_history(dst), info, fp))
        except Exception as e:
            errors.append((fname, str(e)))
    results.sort(key=lambda x: x[0])

    print(f"\nP1: {len(results)} new, {len(skipped)} skip, {len(errors)} err")
    for f, r in skipped[:5]: print(f"  SKIP {f}: {r}")
    for f, e in errors[:5]:  print(f"  ERR  {f}: {e}")
    if results: print(f"  Range: {results[0][0]} → {results[-1][0]}")

    if dry_run:
        print("\n[DRY RUN] Pass dry_run=False to execute.")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return {'processed': len(results), 'skipped': len(skipped),
                'errors': len(errors), 'new_sessions': len(results),
                'sessions': [r[0] for r in results]}

    # Phase 2: Append history
    with open(os.path.join(l4_dir, 'all_histories.txt'), 'a', encoding='utf-8') as f:
        for sn, _, hist, _, _ in results:
            if hist: f.write('\n' + format_history_block(sn, hist))
    print(f"Appended {len(results)} sessions to all_histories.txt")

    # Phase 3: Archive to monthly zips
    by_month = defaultdict(list)
    for sn, cpath, _, info, _ in results:
        year = info.get('year', '2026') if isinstance(info, dict) else '2026'
        by_month[f"{year}-{sn[:2]}"].append((sn, cpath))
    for mk, items in sorted(by_month.items()):
        zpath = os.path.join(l4_dir, f"{mk}.zip")
        mode = 'a' if os.path.exists(zpath) else 'w'
        with zipfile.ZipFile(zpath, mode, zipfile.ZIP_DEFLATED) as zf:
            names = set(zf.namelist()) if mode == 'a' else set()
            for sn, cp in items:
                if f"{sn}.txt" not in names: zf.write(cp, f"{sn}.txt")
        print(f"  {mk}.zip: +{len(items)}")

    # Phase 4: Delete raw files
    to_del = [rp for *_, rp in results]
    for fname, _ in skipped:
        m = [f for f in raw_files if os.path.basename(f) == fname]
        if m: to_del.append(m[0])
    deleted = 0
    for rp in to_del:
        try: os.remove(rp); deleted += 1
        except Exception: pass
    print(f"Deleted {deleted}/{len(to_del)} raw files")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    report = {'processed': len(results), 'skipped': len(skipped),
              'errors': len(errors), 'new_sessions': len(results), 'deleted_raw': deleted}
    print(f"\nDone: {report}")
    return report

# ── CLI ──
RAW_DIR = os.path.join(os.path.dirname(os.path.dirname(L4_DIR)), 'temp', 'model_responses')

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='L4 session archiver')
    ap.add_argument('src', nargs='?', default=RAW_DIR, help='raw files dir')
    ap.add_argument('--run', action='store_true', help='actually execute (default: dry run)')
    args = ap.parse_args()
    batch_process(args.src, dry_run=not args.run)