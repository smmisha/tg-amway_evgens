"""Media handler — downloads and validates images for Telegram posts."""

import hashlib
import logging
import os
import tempfile
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB Telegram limit for photos
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


async def download_image(url: str, output_dir: str | None = None) -> str | None:
    """Download an image from URL and return the local file path.

    Also supports local repository-relative paths (e.g. "data/media/post_7_xxx.jpg"):
    the file is validated and returned as-is without downloading.
    """
    if not url:
        return None

    parsed = urlparse(url)

    # Local file path (repo-relative or absolute) — no download needed
    if parsed.scheme not in ("http", "https"):
        local_path = os.path.normpath(url)
        if os.path.exists(local_path) and os.path.isfile(local_path):
            ext = os.path.splitext(local_path)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                logger.warning(f"Unsupported local image extension: {local_path}")
                return None
            size = os.path.getsize(local_path)
            if size > MAX_IMAGE_SIZE:
                logger.warning(f"Local image too large ({size} bytes): {local_path}")
                return None
            logger.info(f"Using local image: {local_path} ({size} bytes)")
            return local_path
        logger.warning(f"Local image file not found: {local_path}")
        return None

    try:
        ext = os.path.splitext(parsed.path)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            ext = ".jpg"

        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="amway_media_")
        os.makedirs(output_dir, exist_ok=True)

        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
        filename = f"image_{url_hash}{ext}"
        filepath = os.path.join(output_dir, filename)

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    )
                },
            )
            resp.raise_for_status()

            if len(resp.content) > MAX_IMAGE_SIZE:
                logger.warning(f"Image too large ({len(resp.content)} bytes): {url}")
                return None

            with open(filepath, "wb") as f:
                f.write(resp.content)

        logger.info(f"Downloaded image: {filepath} ({len(resp.content)} bytes)")
        return filepath

    except Exception as e:
        logger.warning(f"Failed to download image {url}: {e}")
        return None


# Fallback product images from Amway's own catalog (web.archive.org mirrors).
# These are REAL product shots, not random stock photos.
FALLBACK_PRODUCT_IMAGES = {
    "Nutrilite_Omega3": [
        "https://web.archive.org/web/20220305135006im_/https://www.amway.ua/common/medias/EIA.w600.h600.4298-20210623.jpg?context=bWFzdGVyfHJvb3R8MjkxNjJ8aW1hZ2UvanBlZ3xoOGEvaDNjLzk1MjUwNjQ3NjEzNzQuanBnfDNkN2NkMWMwNmY4YWM5NWFmNWFlODU4ZGNhYTM0ZjRlZDNlZTY4Y2IwN2IyMTRjNWFlYWQ3Mzc0OTM3ZWFkNWI&ccv=VUtSLU8=",
    ],
    "Nutrilite_Vitamins": [
        "https://web.archive.org/web/20220305144934im_/https://www.amway.ua/common/medias/EIA.w600.h600.121576-2-20210623.jpg?context=bWFzdGVyfHJvb3R8MzU2MjN8aW1hZ2UvanBlZ3xoMWMvaDljLzk1MjUwNTEyMjgxOTAuanBnfGUwNGYzM2U4OWQ0M2Y1Nzg0ZDNlZmEzOTJhMmFhMDQ1OWJmNjgyN2VlMjY3M2JhNTg0MDQ2MDE4MjE2ZmJlOTU&ccv=VUtSLU8=",
        "https://web.archive.org/web/20220525115103im_/https://www.amway.ua/common/medias/EIA.w600.h600.109741-20210623.jpg?context=bWFzdGVyfHJvb3R8MjkyNTJ8aW1hZ2UvanBlZ3xoODkvaGRiLzk1MjUwNjEyODc5NjYuanBnfDE0NDMyNDg3MmI1ODczOGIzMDE5NmJkMzQ1NzFhMDVkNmU5ODllYmQ4MDViZDViZjFjZDIzYzRjMWJiYTk5OWU&ccv=VUtSLU8=",
    ],
    "Nutrilite_Default": [
        "https://web.archive.org/web/20220322173449im_/https://www.amway.ua/common/medias/EIA.w600.h600.119797-20210623.jpg?context=bWFzdGVyfHJvb3R8Mjk0ODR8aW1hZ2UvanBlZ3xoZTcvaDIzLzk1MjUwNjU4NzU0ODYuanBnfGM0MDNmOTU2YTIyZWM5Zjg4YzBmZDAxZTg3NjRkYWY2NGMwMjNhNzVhZTUyZDY5Y2FhY2ExYWYwYzRkZTE5YzQ&ccv=VUtSLU8=",
    ],
    "XS": [
        "https://web.archive.org/web/20220902184943im_/https://media.amway.ua/sys-master/h8f/hda/9524920778782.jpg",
        "https://web.archive.org/web/20220524124712im_/https://www.amway.ua/common/medias/EIA.w600.h600.121062-new-800-800.jpg?context=bWFzdGVyfHJvb3R8Mjc2MjV8aW1hZ2UvanBlZ3xoZWQvaDhiLzk4ODI5MjA3MTQyNzAuanBnfGMzNzk3MjE3ZWQwY2I1YWFhMTQ0YTgwZDk3ODc1ZGZkMjdjY2QwNzcyMjQ5MjA4YTNiYjcwNmRmMGJmZDk2ZTY&ccv=VUtSLU8=",
    ],
    "Artistry": [
        "https://web.archive.org/web/20211011111853im_/https://www.amway.ua/common/medias/EIA.w600.h600.123800-2-170221.png?context=bWFzdGVyfHJvb3R8MTUyMzYzfGltYWdlL3BuZ3xoZmUvaDlkLzk0OTAxODc0ODUyMTQucG5nfGJmODEwYmQ3MjQ0OTZjN2QyZGQ5NjMxNTkxY2M5ZTEwMDJlYThkMzk3NGU2NmI5NDk4ZjNjMjllNmI2MTg5NGU&ccv=VUtSLU8=",
        "https://web.archive.org/web/20220330222304im_/https://www.amway.ua/common/medias/EIA.w600.h600.118208-1-11.02.21.jpg?context=bWFzdGVyfHJvb3R8MTU1MjF8aW1hZ2UvanBlZ3xoM2YvaGMwLzk1MDk4NTI2MTA1OTAuanBnfGY0NjAwYzZhYzBmZmZmNTQ1NzQyYWQxMWZkYjhiMDcxMjIxNGMyZTgzODAwMzVkZWM1N2M5OGMxMzFiMDhjYjQ&ccv=VUtSLU8=",
    ],
    "Home Care": [
        "https://web.archive.org/web/20220305140333im_/https://www.amway.ua/common/medias/EIA.w600.h600.124485-E-20210623.jpg?context=bWFzdGVyfHJvb3R8NDY1NzN8aW1hZ2UvanBlZ3xoZmQvaGE3Lzk1MjUwNzc2MDY0MzAuanBnfDZkYmQ1YTBhOTQxY2FhZjg2MWJlMWZjZDE5MzhlMTVjYzkyYTZlMDgxZWE4MjBiYzY2NDcxY2RkYzZlYWJkODY&ccv=VUtSLU8=",
        "https://web.archive.org/web/20220305141444im_/https://www.amway.ua/common/medias/EIA.w600.h600.110488-E-20210623.jpg?context=bWFzdGVyfHJvb3R8MjE0Njh8aW1hZ2UvanBlZ3xoMzQvaDgyLzk1MjUwOTAyMjIxMTAuanBnfGM4NmM4ZjIwMTRjNWI1ZTUyNDc5ZGJjYWFiZmUyZGI0ZWYzNDllM2JjYThhZmIxNGM4ODhkMjRmZjYwMzk0MGM&ccv=VUtSLU8=",
    ],
    "default": [
        "https://web.archive.org/web/20220322173449im_/https://www.amway.ua/common/medias/EIA.w600.h600.119797-20210623.jpg?context=bWFzdGVyfHJvb3R8Mjk0ODR8aW1hZ2UvanBlZ3xoZTcvaDIzLzk1MjUwNjU4NzU0ODYuanBnfGM0MDNmOTU2YTIyZWM5Zjg4YzBmZDAxZTg3NjRkYWY2NGMwMjNhNzVhZTUyZDY5Y2FhY2ExYWYwYzRkZTE5YzQ&ccv=VUtSLU8=",
    ],
}

def detect_subtopic_key(title: str, product_line: str) -> str:
    """Determine fine-grained subtopic for fallback image selection."""
    text_lower = f"{title} {product_line}".lower()
    if "nutrilite" in text_lower or "нутрилайт" in text_lower or "витамин" in text_lower:
        if any(kw in text_lower for kw in ["омега", "omega", "жирн", "рыби", "fish"]):
            return "Nutrilite_Omega3"
        return "Nutrilite_Vitamins"
    if product_line in FALLBACK_PRODUCT_IMAGES:
        return product_line
    return "default"


def _load_catalog_images_for_product(product_line: str, title: str) -> list[str]:
    """Load image URLs from products_catalog.json matching the product line or title."""
    import json as _json

    catalog_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "products_catalog.json"
    )
    if not os.path.exists(catalog_file):
        return []
    try:
        with open(catalog_file, "r", encoding="utf-8") as f:
            catalog = _json.load(f)
        # Find entries matching the product line or title keywords
        urls = []
        title_lower = title.lower()
        for item in catalog:
            item_line = item.get("product_line", "")
            item_title = item.get("title", "").lower()
            if item_line == product_line or any(kw in item_title for kw in title_lower.split()[:3] if len(kw) > 3):
                for img_url in item.get("images", []):
                    if img_url.startswith("http") and img_url not in urls:
                        urls.append(img_url)
        return urls
    except Exception as e:
        logger.warning(f"Failed to load catalog images: {e}")
        return []


async def download_first_image(
    image_urls: list[str],
    product_line: str = "default",
    title: str = "",
) -> str | None:
    """Download the first available image from scraped URLs, or topic-matched fallback image.

    Priority order:
    1. Scraped image URLs from the article page (og:image, img tags)
    2. Catalog images from products_catalog.json (real Amway product shots)
    3. Hardcoded Amway product fallbacks from web.archive.org
    4. None (no image — better than a random stock photo)

    Args:
        image_urls: List of candidate scraped URLs
        product_line: Amway product category
        title: Article or product title

    Returns:
        Local file path to downloaded product image, or None.
    """
    # 1. Try scraped image URLs (from the article page — highest priority)
    for url in image_urls:
        filepath = await download_image(url)
        if filepath:
            logger.info(f"Using scraped image from article: {url[:80]}...")
            return filepath

    # 2. Try catalog images from products_catalog.json
    catalog_urls = _load_catalog_images_for_product(product_line, title)
    for url in catalog_urls:
        filepath = await download_image(url)
        if filepath:
            logger.info(f"Using catalog image: {url[:80]}...")
            return filepath

    # 3. Hardcoded Amway product fallbacks (web.archive.org mirrors)
    subtopic_key = detect_subtopic_key(title, product_line)
    fallbacks = FALLBACK_PRODUCT_IMAGES.get(subtopic_key, FALLBACK_PRODUCT_IMAGES["default"])

    for url in fallbacks:
        filepath = await download_image(url)
        if filepath:
            logger.info(f"Using hardcoded fallback image: {url[:80]}...")
            return filepath

    # 4. No image at all — better than irrelevant stock photo
    logger.warning(f"No image found for '{title}' [{product_line}]. Post will be text-only.")
    return None


def cleanup_temp_media(filepath: str | None):
    """Safely remove a temporary downloaded image file and its parent temp directory.

    Only files inside amway_media_ temp directories are removed, so committed
    repository images (data/media/*) are never deleted.
    """
    if not filepath or not os.path.exists(filepath):
        return

    try:
        parent_dir = os.path.dirname(filepath)
        if os.path.basename(parent_dir).startswith("amway_media_"):
            os.remove(filepath)
            try:
                os.rmdir(parent_dir)
            except OSError:
                pass  # Directory not empty or already removed
            logger.info(f"Cleaned up temporary media file: {filepath}")
        else:
            logger.info(f"Skipping cleanup of persistent media file: {filepath}")
    except Exception as e:
        logger.warning(f"Failed to clean up temp media file {filepath}: {e}")

