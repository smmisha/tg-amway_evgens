"""Проверка исходящего текста перед публикацией в Telegram (аудит F-01).

Модель угрозы: контент статьи с amway.ua считается НЕДОВЕРЕННЫМ. Prompt
injection в тексте статьи может заставить LLM выдать в посте чужую ссылку,
HTML-разметку или @-упоминание чужого канала. Поэтому исходящий текст
централизованно очищается перед отправкой (и до выставления ParseMode).
"""

import logging
import re
from urllib.parse import urlparse

from src.net_safety import is_host_allowed

logger = logging.getLogger(__name__)

# SECURITY: ссылки на эти хосты допустимы в публикуемом посте (иначе URL вырезается).
ALLOWED_PUBLICATION_HOSTS = ("amway.ua", "amway.com", "amway.eu")
# Собственный аккаунт автора — единственное разрешённое @-упоминание в посте.
OWN_MENTION = "evgen_blago"

_HTML_TAG_RE = re.compile(r"<[^<>]{0,2000}>")
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_MENTION_RE = re.compile(r"@([A-Za-z0-9_]{2,64})")
_EMPTY_BRACKETS_RE = re.compile(r"\(\s*\)|\[\s*\]")
_SPACES_RE = re.compile(r"[ \t\f\v\u00a0]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


class PublicationPolicyError(ValueError):
    """Текст не прошёл публикационную политику (после очистки не осталось текста)."""


def _filter_url(match: re.Match[str]) -> str:
    """Оставить URL только если его hostname в allowlist, иначе удалить."""
    raw = match.group(0)
    try:
        host = (urlparse(raw).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return raw if is_host_allowed(host, ALLOWED_PUBLICATION_HOSTS) else ""


def _filter_mention(match: re.Match[str]) -> str:
    """Оставить только собственное @-упоминание автора."""
    return match.group(0) if match.group(1).lower() == OWN_MENTION else ""


def enforce_publication_policy(text: str) -> str:
    """Очистить текст перед публикацией и вернуть безопасный вариант.

    - удаляет HTML-теги;
    - удаляет URL, чей хост не входит в ``ALLOWED_PUBLICATION_HOSTS``;
    - оставляет только собственное @-упоминание (``OWN_MENTION``);
    - схлопывает пробелы (структура абзацев сохраняется).

    Raises:
        PublicationPolicyError: если после очистки не осталось текста —
            такой пост не должен публиковаться.
    """
    cleaned = _HTML_TAG_RE.sub("", text or "")
    cleaned = _URL_RE.sub(_filter_url, cleaned)
    cleaned = _MENTION_RE.sub(_filter_mention, cleaned)
    # От удалённых ссылок/упоминаний могут остаться пустые скобки — убираем.
    cleaned = _EMPTY_BRACKETS_RE.sub("", cleaned)
    cleaned = _SPACES_RE.sub(" ", cleaned)
    cleaned = "\n".join(line.strip() for line in cleaned.splitlines())
    cleaned = _BLANK_LINES_RE.sub("\n\n", cleaned).strip()

    if not cleaned:
        raise PublicationPolicyError("Текст пуст после очистки — публикация отменена")
    return cleaned
