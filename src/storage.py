"""Track published articles to avoid duplicates.

Stores a JSON list of published article hashes. The file is committed
to the repo so GitHub Actions can persist state across runs.
"""

import hashlib
import json
import os
from datetime import datetime, timezone


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
