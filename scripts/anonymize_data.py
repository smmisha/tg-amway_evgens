#!/usr/bin/env python3
"""Anonymize PII in JSON files under data/ by replacing emails, phones, and credit-card-like numbers.
Creates backups with .bak extension before modifying.
Usage: python scripts/anonymize_data.py [--dry-run]
"""
import re
import json
from pathlib import Path
import argparse

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\-() ]{5,}\d")
CC_RE = re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b")

PLACEHOLDERS = {
    'email': 'redacted@example.com',
    'phone': '+00000000000',
    'cc': '4111 1111 1111 1111'
}


def anonymize_value(v):
    if not isinstance(v, str):
        return v
    s = v
    s = EMAIL_RE.sub(PLACEHOLDERS['email'], s)
    # Replace phone-like patterns but avoid ISO dates (YYYY-MM-DD with following 'T')
    def phone_replacer(match):
        m = match.group(0)
        start = match.start()
        end = match.end()
        after = v[end] if end < len(v) else ''
        # If this looks like an ISO date (e.g. 2026-08-02) followed by 'T', skip replacement
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", m) and after == 'T':
            return m
        return PLACEHOLDERS['phone']

    s = PHONE_RE.sub(phone_replacer, s)
    s = CC_RE.sub(PLACEHOLDERS['cc'], s)
    return s


def anonymize(obj):
    if isinstance(obj, dict):
        return {k: anonymize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [anonymize(v) for v in obj]
    return anonymize_value(obj)


def process_file(path: Path, dry_run: bool = False):
    text = path.read_text(encoding='utf-8')
    try:
        data = json.loads(text)
    except Exception:
        print(f"Skipping non-json or unreadable file: {path}")
        return False

    new = anonymize(data)
    new_text = json.dumps(new, ensure_ascii=False, indent=2)
    if new_text == text:
        print(f"No changes for {path}")
        return False

    print(f"PII found and replaced in {path}")
    if dry_run:
        return True

    bak = path.with_suffix(path.suffix + '.bak')
    if not bak.exists():
        path.rename(bak)
        bak.write_text(text, encoding='utf-8')
        path.write_text(new_text, encoding='utf-8')
        print(f"Backed up {path} -> {bak}")
    else:
        # If backup exists, overwrite original directly
        path.write_text(new_text, encoding='utf-8')
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    data_dir = Path(__file__).resolve().parents[1] / 'data'
    changed = False
    for p in sorted(data_dir.glob('*.json')):
        ok = process_file(p, dry_run=args.dry_run)
        changed = changed or ok

    if not changed:
        print('No PII replacements done.')

if __name__ == '__main__':
    main()
