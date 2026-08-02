"""Track published articles to avoid duplicates.

Stores a JSON list of published article hashes. The file is committed
to the repo so GitHub Actions can persist state across runs.
"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

ATTEMPTED_COOLDOWN_DEFAULT_DAYS = 7


class Storage:
    """Simple JSON-file storage for published article tracking."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._data: list[dict] = []
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    self._data = json.loads(content) if content else []
            except (json.JSONDecodeError, IOError):
                self._data = []
        else:
            self._data = []

    def _save(self):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        # Keep only last 500 entries
        trimmed = self._data[-500:]
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _hash_url(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    def is_published(self, url: str) -> bool:
        url_hash = self._hash_url(url)
        return any(item.get("hash") == url_hash for item in self._data)

    def mark_published(self, url: str, title: str = "", telegram_message_id: str = ""):
        self._data.append({
            "hash": self._hash_url(url),
            "url": url,
            "title": title,
            "telegram_message_id": telegram_message_id,
            "published_at": datetime.now(timezone.utc).isoformat(),
        })
        self._save()

    def count(self) -> int:
        return len(self._data)


class AttemptStorage:
    """Tracks article URLs we already tried and failed, so a single bad
    candidate can't block the pipeline day after day.

    A failed candidate is recorded with a timestamp and reason. While the
    cooldown (default 7 days) has not elapsed, the URL is excluded from the
    candidate pool; after the cooldown it becomes eligible again in case the
    failure was transient (API glitch, bad image that got refreshed...).
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._data: list[dict] = []
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    self._data = json.loads(content) if content else []
            except (json.JSONDecodeError, IOError):
                self._data = []
        else:
            self._data = []

    def _save(self):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        trimmed = self._data[-2000:]
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _hash_url(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    def is_attempted(self, url: str, cooldown_days: int = ATTEMPTED_COOLDOWN_DEFAULT_DAYS) -> bool:
        """True if the URL failed recently and is still inside its cooldown."""
        url_hash = self._hash_url(url)
        cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)
        for item in self._data:
            if item.get("hash") != url_hash:
                continue
            try:
                attempted_at = datetime.fromisoformat(item.get("attempted_at", ""))
            except (ValueError, TypeError):
                # No/invalid timestamp → treat as still in cooldown
                return True
            if attempted_at >= cutoff:
                return True
        return False

    def mark_attempted(self, url: str, reason: str = ""):
        existing = [item for item in self._data if item.get("hash") == self._hash_url(url)]
        now = datetime.now(timezone.utc).isoformat()
        if existing:
            existing[0]["reason"] = reason
            existing[0]["attempted_at"] = now
        else:
            self._data.append({
                "hash": self._hash_url(url),
                "url": url,
                "reason": reason,
                "attempted_at": now,
            })
        self._save()

    def count(self) -> int:
        return len(self._data)
