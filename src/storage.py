"""Track published articles to avoid duplicates.

Stores a JSON list of published article hashes, URLs, SKUs, and titles.
The file is committed to the repo or persisted via artifacts so GitHub Actions
can persist state across runs.
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ATTEMPTED_COOLDOWN_DEFAULT_DAYS = 7


def normalize_url(url: str) -> str:
    """Normalize article/product URL for reliable duplicate detection.
    Strips query parameters, fragments, language prefix (/uk/), and trailing slashes.
    """
    if not url:
        return ""
    u = url.strip()
    parsed = urlparse(u)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or ""
    # Strip language prefix /uk/ or /uk
    path = re.sub(r"^/uk(?=/|$)", "", path)
    # Strip trailing slashes
    path = path.rstrip("/")
    return f"{scheme}://{netloc}{path}"


def extract_sku(url: str) -> str | None:
    """Extract product SKU number from URL (e.g. /p/126725 -> '126725')."""
    if not url:
        return None
    m = re.search(r"/p/(\d+)", url)
    return m.group(1) if m else None


def normalize_title(title: str) -> str:
    """Normalize title for fuzzy deduplication."""
    if not title:
        return ""
    t = title.lower()
    # Strip common site/brand marketing suffixes
    t = re.sub(r"—\s*купить.*$", "", t)
    t = re.sub(r"\|\s*amway.*$", "", t)
    t = re.sub(r"—\s*amway.*$", "", t)
    # Remove punctuation, symbols, emojis
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


class Storage:
    """Simple JSON-file storage for published article tracking with multi-attribute deduplication."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._data: list[dict] = []
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8-sig") as f:
                    content = f.read().strip()
                    self._data = json.loads(content) if content else []
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load storage from {self.filepath}: {e}")
                self._data = []
        else:
            self._data = []

    def _save(self):
        dirname = os.path.dirname(self.filepath)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        # Keep only last 500 entries
        self._data = self._data[-500:]
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _hash_url(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def normalize_url(url: str) -> str:
        return normalize_url(url)

    @staticmethod
    def extract_sku(url: str) -> str | None:
        return extract_sku(url)

    @staticmethod
    def normalize_title(title: str) -> str:
        return normalize_title(title)

    def _item_matches(
        self,
        item: dict,
        url_hash: str,
        target_norm_url: str,
        target_sku: str | None,
        target_norm_title: str,
    ) -> bool:
        """Check if a stored publication entry matches the candidate by URL hash,
        normalized URL, SKU, or normalized title."""
        # 1. Exact raw URL hash match
        if item.get("hash") == url_hash:
            return True

        item_url = item.get("url", "")

        # 2. Normalized URL match
        if target_norm_url and item_url:
            if normalize_url(item_url) == target_norm_url:
                return True

        # 3. Product SKU match (e.g. /p/126725)
        item_sku = item.get("sku") or extract_sku(item_url)
        if target_sku and item_sku and target_sku == item_sku:
            return True

        # 4. Normalized title match (only if sufficiently distinctive, >= 10 chars)
        if target_norm_title and len(target_norm_title) >= 10:
            item_norm_title = normalize_title(item.get("title", ""))
            if item_norm_title and target_norm_title == item_norm_title:
                return True

        return False

    def is_published(
        self,
        url: str,
        sku: str | None = None,
        title: str | None = None,
        cooldown_days: int | None = None,
    ) -> bool:
        """Check if an article has been published.
        Matches by URL hash, normalized URL, SKU, or Title.
        If cooldown_days is provided (and > 0), returns True only if published within the last
        cooldown_days (allowing evergreen content recycling after the cooldown).
        If cooldown_days <= 0, recycling is disabled and True is returned if ever published.
        """
        url_hash = self._hash_url(url)
        target_norm_url = normalize_url(url)
        target_sku = sku or extract_sku(url)
        target_norm_title = normalize_title(title) if title else ""

        # Find matching entries in reverse chronological order
        matching_items = [
            item for item in reversed(self._data)
            if self._item_matches(item, url_hash, target_norm_url, target_sku, target_norm_title)
        ]

        if not matching_items:
            return False

        if cooldown_days is None or cooldown_days <= 0:
            return True

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=cooldown_days)
        # Check the most recently published match
        for item in matching_items:
            published_at_str = item.get("published_at")
            if not published_at_str:
                return True
            try:
                pub_dt = datetime.fromisoformat(published_at_str)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                return pub_dt > cutoff
            except (ValueError, TypeError):
                return True
        return False

    def get_last_published_at(
        self,
        url: str,
        sku: str | None = None,
        title: str | None = None,
    ) -> datetime | None:
        """Return the datetime when this article/product was most recently published, or None."""
        url_hash = self._hash_url(url)
        target_norm_url = normalize_url(url)
        target_sku = sku or extract_sku(url)
        target_norm_title = normalize_title(title) if title else ""

        for item in reversed(self._data):
            if self._item_matches(item, url_hash, target_norm_url, target_sku, target_norm_title):
                published_at_str = item.get("published_at")
                if not published_at_str:
                    return None
                try:
                    pub_dt = datetime.fromisoformat(published_at_str)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    return pub_dt
                except (ValueError, TypeError):
                    return None
        return None

    def mark_published(
        self,
        url: str,
        title: str = "",
        telegram_message_id: str = "",
        sku: str = "",
    ):
        item_sku = sku or extract_sku(url) or ""
        self._data.append({
            "hash": self._hash_url(url),
            "url": url,
            "sku": item_sku,
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
                with open(self.filepath, "r", encoding="utf-8-sig") as f:
                    content = f.read().strip()
                    self._data = json.loads(content) if content else []
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load attempt storage from {self.filepath}: {e}")
                self._data = []
        else:
            self._data = []

    def _save(self):
        dirname = os.path.dirname(self.filepath)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        self._data = self._data[-2000:]
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _hash_url(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    def _item_matches(
        self,
        item: dict,
        url_hash: str,
        target_norm_url: str,
        target_sku: str | None,
    ) -> bool:
        if item.get("hash") == url_hash:
            return True
        item_url = item.get("url", "")
        if target_norm_url and item_url and normalize_url(item_url) == target_norm_url:
            return True
        item_sku = item.get("sku") or extract_sku(item_url)
        if target_sku and item_sku and target_sku == item_sku:
            return True
        return False

    def is_attempted(
        self,
        url: str,
        sku: str | None = None,
        cooldown_days: int = ATTEMPTED_COOLDOWN_DEFAULT_DAYS,
    ) -> bool:
        """True if the URL or SKU failed recently and is still inside its cooldown."""
        url_hash = self._hash_url(url)
        target_norm_url = normalize_url(url)
        target_sku = sku or extract_sku(url)
        cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)
        for item in self._data:
            if not self._item_matches(item, url_hash, target_norm_url, target_sku):
                continue
            try:
                attempted_at = datetime.fromisoformat(item.get("attempted_at", ""))
            except (ValueError, TypeError):
                return True
            if attempted_at >= cutoff:
                return True
        return False

    def mark_attempted(self, url: str, sku: str = "", reason: str = ""):
        item_sku = sku or extract_sku(url) or ""
        url_hash = self._hash_url(url)
        target_norm_url = normalize_url(url)
        existing = [
            item for item in self._data
            if self._item_matches(item, url_hash, target_norm_url, item_sku)
        ]
        now = datetime.now(timezone.utc).isoformat()
        if existing:
            existing[0]["reason"] = reason
            existing[0]["attempted_at"] = now
            if item_sku and not existing[0].get("sku"):
                existing[0]["sku"] = item_sku
        else:
            self._data.append({
                "hash": url_hash,
                "url": url,
                "sku": item_sku,
                "reason": reason,
                "attempted_at": now,
            })
        self._save()

    def count(self) -> int:
        return len(self._data)


class PreparedStorage:
    """JSON-file queue for pre-scraped, pre-rewritten, and vision-validated post drafts."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._data: list[dict] = []
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8-sig") as f:
                    content = f.read().strip()
                    self._data = json.loads(content) if content else []
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load prepared storage from {self.filepath}: {e}")
                self._data = []
        else:
            self._data = []

    def _save(self):
        dirname = os.path.dirname(self.filepath)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def add_prepared(self, post_data: dict):
        """Add a validated post draft to the prepared queue."""
        # Avoid duplicate entries for the same URL in prepared queue
        self._data = [item for item in self._data if item.get("url") != post_data.get("url")]
        post_data["prepared_at"] = datetime.now(timezone.utc).isoformat()
        self._data.append(post_data)
        self._save()

    def pop_prepared(self) -> dict | None:
        """Pop and return the oldest prepared post draft from the queue."""
        if not self._data:
            return None
        post = self._data.pop(0)
        self._save()
        return post

    def count(self) -> int:
        return len(self._data)
