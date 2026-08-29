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


# Fallback product images: local repository images of real Amway products.
# Guaranteed 100% reliable, zero network dependency, never 503.
FALLBACK_PRODUCT_IMAGES = {
    "Nutrilite_Omega3": [
        "data/media/post_7_02dfeb6e.jpg",
    ],
    "Nutrilite_Vitamins": [
        "data/media/post_8_dd22cf0c.jpg",
        "data/media/post_9_e3fbab59.jpg",
        "data/media/post_10_050b9f4d.jpg",
        "data/media/post_20_b5850f5d.jpg",
    ],
    "Nutrilite_Default": [
        "data/media/post_8_dd22cf0c.jpg",
        "data/media/post_20_b5850f5d.jpg",
    ],
    "XS": [
        "data/media/post_11_f4ffe234.jpg",
        "data/media/post_12_26fb454c.jpg",
        "data/media/post_19_0922c3d5.jpg",
    ],
    "Artistry": [
        "data/media/post_13_e5c3ccda.jpg",
        "data/media/post_14_fa2399c4.jpg",
        "data/media/post_15_5fc5454a.jpg",
    ],
    "Home Care": [
        "data/media/post_16_de56257c.jpg",
        "data/media/post_17_53d18f48.jpg",
        "data/media/post_18_e2195dd6.jpg",
    ],
    "default": [
        "data/media/post_8_dd22cf0c.jpg",
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

