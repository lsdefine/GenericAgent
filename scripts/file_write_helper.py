# Helper for safe file writes and constructing <file_content> block for file_write tool
import os
import json
from pathlib import Path

def build_file_content_block(content: str, filename: str=None) -> str:
    # Return the exact <file_content> block expected by the file_write tool.
    header = ''
    if filename:
        header = f'<!-- filename: {filename} -->\n'
    return '<file_content>\n' + header + content + '\n</file_content>'

def write_direct(path: str, content: str, encoding: str='utf-8') -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w', encoding=encoding) as f:
        f.write(content)

def verify_file(path: str, expected: str) -> bool:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            got = f.read()
        return got == expected
    except Exception:
        return False

def journal(entry: dict):
    jpath = Path('memory') / 'file_write_journal.log'
    jpath.parent.mkdir(parents=True, exist_ok=True)
    with jpath.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=['direct','block'], default='direct')
    p.add_argument('--path', required=False)
    p.add_argument('--content', required=False)
    args = p.parse_args()
    if args.mode == 'direct':
        if not args.path or args.content is None:
            print('direct mode requires --path and --content')
            raise SystemExit(1)
        write_direct(args.path, args.content)
        ok = verify_file(args.path, args.content)
        journal({'ts': __import__('time').time(), 'action': 'direct', 'path': args.path, 'ok': ok})
        print('written', args.path, 'ok=', ok)
    else:
        block = build_file_content_block(args.content or '', filename=args.path)
        print(block)
