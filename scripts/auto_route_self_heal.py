import argparse
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTENDS_DIR = PROJECT_ROOT / 'frontends'

TARGET_FILES = (
    'dingtalkapp.py',
    'fsapp.py',
    'qqapp.py',
    'qtapp.py',
    'stapp2.py',
    'tgapp.py',
    'wechatapp.py',
    'wecomapp.py',
)


IMPORT_OLD = 'from agentmain import GeneraticAgent'
IMPORT_NEW = 'from agent_factory import create_agent'


def _replace_import_minimal(updated: str) -> tuple[str, bool, list[str]]:
    notes = []
    changed = False

    if IMPORT_NEW in updated:
        return updated, changed, notes

    if IMPORT_OLD not in updated:
        notes.append('missing expected import anchor')
        return updated, changed, notes

    updated = updated.replace(IMPORT_OLD, IMPORT_NEW, 1)
    changed = True
    return updated, changed, notes


def _replace_ctor_minimal(updated: str) -> tuple[str, bool]:
    changed = False

    # Only patch known agent construction statements for routing wiring.
    ctor_patterns = (
        (r'(^\s*agent\s*=\s*)GeneraticAgent\s*\(\s*\)\s*;\s*(agent\.verbose\s*=\s*False\s*$)', r'\1create_agent(); \2'),
        (r'(^\s*agent\s*=\s*)GeneraticAgent\s*\(\s*\)\s*$', r'\1create_agent()'),
    )

    for pattern, repl in ctor_patterns:
        next_text, count = re.subn(pattern, repl, updated, flags=re.MULTILINE)
        if count > 0:
            updated = next_text
            changed = True

    return updated, changed


def patch_file(path: Path) -> tuple[bool, str, list[str]]:
    original = path.read_text(encoding='utf-8')
    updated = original
    notes = []
    changed = False

    updated, import_changed, import_notes = _replace_import_minimal(updated)
    changed = changed or import_changed
    notes.extend(import_notes)

    updated, ctor_changed = _replace_ctor_minimal(updated)
    changed = changed or ctor_changed

    # Principle: only auto-route wiring is auto-restored; never force overwrite unknown updates.
    if re.search(r'\bGeneraticAgent\s*\(', updated):
        notes.append('contains unmatched GeneraticAgent usage; skipped non-minimal overwrite')

    if changed:
        path.write_text(updated, encoding='utf-8')
    return changed, updated, notes


def validate_content(name: str, content: str) -> list[str]:
    errors = []
    if 'from agent_factory import create_agent' not in content:
        errors.append(f'{name}: missing create_agent import')
    if re.search(r'\bGeneraticAgent\s*\(', content):
        errors.append(f'{name}: still contains direct GeneraticAgent() call')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description='Self-heal frontend auto-routing wiring.')
    parser.add_argument('--check-only', action='store_true', help='Only check; do not modify files')
    args = parser.parse_args()

    changed_files: list[str] = []
    all_errors: list[str] = []
    warning_notes: list[str] = []

    for filename in TARGET_FILES:
        path = FRONTENDS_DIR / filename
        if not path.exists():
            all_errors.append(f'{filename}: file not found')
            continue

        if not args.check_only:
            changed, content, notes = patch_file(path)
            if changed:
                changed_files.append(filename)
            for note in notes:
                warning_notes.append(f'{filename}: {note}')
        else:
            content = path.read_text(encoding='utf-8')

        all_errors.extend(validate_content(filename, content))

    if changed_files:
        print('[SELF-HEAL] patched files:', ', '.join(changed_files))
    else:
        print('[SELF-HEAL] no patch needed')

    if warning_notes:
        print('[SELF-HEAL] notes:')
        for note in warning_notes:
            print(f'  - {note}')

    if all_errors:
        print('[SELF-HEAL] validation failed:')
        for err in all_errors:
            print(f'  - {err}')
        return 1

    print('[SELF-HEAL] validation passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
