#!/usr/bin/env python3
"""Anonymize PII in JSON files under data/ by replacing emails, phones, and credit-card-like numbers.
Creates backups with .bak extension before modifying.
Usage: python scripts/anonymize_data.py [--dry-run]

SECURITY (TG-F-11): телефонный шаблон ограничен реальными телефонными форматами
UA/RU/международными (``+380 ...``, ``0XX XXX XX XX``, ``+7 (999) ...``,
``8 (999) ...``, разделители ``- ( )`` и пробелы). Даты, ID, цены и прочие
числовые последовательности больше не переписываются: «любые 7+ цифр» — это
слишком широко и портило данные.
"""
import re
import json
from pathlib import Path
import argparse

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# SECURITY (TG-F-11): только телефонные форматы. Каждая ветка требует
# «телефонный» префикс (+ или код оператора/страны) и/или разделитель, поэтому
# голые цифровые ID, даты (2026-08-02, 08.02.2026) и цены не матчатся.
# [ \t\u00a0-] — пробел, таб, NBSP, дефис (переводы строк намеренно исключены).
PHONE_RE = re.compile(
    r"""
    (?<![\w+])
    (?:
        # +380 XX XXX XX XX / +380671234567 (UA)
        \+38[ \t\u00a0\-]?\(?0\d{2}\)?[ \t\u00a0\-]?\d{3}[ \t\u00a0\-]?\d{2}[ \t\u00a0\-]?\d{2}
        # прочие международные: +7 (999) 123-45-67, +1 555 123 4567, +44 20 7946 0958
      | \+\d{1,3}[ \t\u00a0\-]?\(?\d{1,4}\)?(?:[ \t\u00a0\-]?\d{2,4}){2,4}
        # 0XX XXX XX XX / (067) 123-45-67 — обязательный разделитель после кода
        # оператора, поэтому слитный 10-значный ID не матчится
      | \(?0\d{2}\)?[ \t\u00a0\-]\(?\d{2,3}\)?[ \t\u00a0\-]?\d{2}[ \t\u00a0\-]?\d{2}
        # 8 (9XX) XXX-XX-XX — обязательный разделитель после 8
      | 8[ \t\u00a0\-]\(?9\d{2}\)?[ \t\u00a0\-]?\d{3}[ \t\u00a0\-]?\d{2}[ \t\u00a0\-]?\d{2}
    )
    (?![\w])
    """,
    re.VERBOSE,
)

# Даты/время, которые не должны считаться телефоном даже при совпадении формы.
_DATE_LIKE_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}|\d{2}[./]\d{2}[./]\d{4}|\d{2}:\d{2}"
)

CC_RE = re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b")

PLACEHOLDERS = {
    'email': 'redacted@example.com',
    'phone': '+00000000000',
    'cc': '4111 1111 1111 1111'
}


def _is_phone(candidate: str) -> bool:
    """Проверка кандидата: телефонный диапазон цифр и «телефонное» начало."""
    if _DATE_LIKE_RE.search(candidate):
        return False
    digits = re.sub(r"\D", "", candidate)
    if not 9 <= len(digits) <= 15:
        return False
    if candidate.startswith("+"):
        return True
    if digits.startswith("0"):
        return len(digits) in (10, 11)  # 0XX XXX XX XX (+ код города)
    return digits.startswith("89") and len(digits) == 11  # 8 (9XX) XXX-XX-XX


def _replace_phone(match: "re.Match[str]") -> str:
    candidate = match.group(0)
    if _is_phone(candidate):
        return PLACEHOLDERS['phone']
    return candidate


def anonymize_value(v):
    if not isinstance(v, str):
        return v
    s = v
    s = EMAIL_RE.sub(PLACEHOLDERS['email'], s)
    s = PHONE_RE.sub(_replace_phone, s)
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
