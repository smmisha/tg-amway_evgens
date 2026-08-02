"""Media handler — downloads and validates images for Telegram posts."""

import logging
import os
import tempfile
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB Telegram limit for photos
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


async def download_image(url: str, output_dir: str | None = None) -> str | None:
    """Download an image from URL and return the local file path."""
    if not url:
        return None

    try:
        parsed = urlparse(url)
        ext = os.path.splitext(parsed.path)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            ext = ".jpg"

        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="amway_media_")
        os.makedirs(output_dir, exist_ok=True)

        filename = f"image_{hash(url) & 0xFFFFFFFF:08x}{ext}"
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


# Fine-grained topic-specific fallback product images
FALLBACK_PRODUCT_IMAGES = {
    "Nutrilite_Omega3": [
        "https://images.pexels.com/photos/5938392/pexels-photo-5938392.jpeg?auto=compress&cs=tinysrgb&w=800",
    ],
    "Nutrilite_Vitamins": [
        "https://images.pexels.com/photos/3683074/pexels-photo-3683074.jpeg?auto=compress&cs=tinysrgb&w=800",
    ],
    "Nutrilite_Default": [
        "https://images.pexels.com/photos/5938392/pexels-photo-5938392.jpeg?auto=compress&cs=tinysrgb&w=800",
    ],
    "XS": [
        "https://images.pexels.com/photos/2538107/pexels-photo-2538107.jpeg?auto=compress&cs=tinysrgb&w=800",
    ],
    "Artistry": [
        "https://images.pexels.com/photos/3785147/pexels-photo-3785147.jpeg?auto=compress&cs=tinysrgb&w=800",
    ],
    "Home Care": [
        "https://images.pexels.com/photos/4239091/pexels-photo-4239091.jpeg?auto=compress&cs=tinysrgb&w=800",
    ],
    "default": [
        "https://images.pexels.com/photos/5938392/pexels-photo-5938392.jpeg?auto=compress&cs=tinysrgb&w=800",
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


async def download_first_image(
    image_urls: list[str],
    product_line: str = "default",
    title: str = "",
) -> str | None:
    """Download the first available image from scraped URLs, or topic-matched fallback image.

    Args:
        image_urls: List of candidate scraped URLs
        product_line: Amway product category
        title: Article or product title

    Returns:
        Local file path to downloaded product image, or None.
    """
    # 1. Try scraped image URLs
    for url in image_urls:
        filepath = await download_image(url)
        if filepath:
            return filepath

    # 2. Topic-matched fallback product image
    subtopic_key = detect_subtopic_key(title, product_line)
    fallbacks = FALLBACK_PRODUCT_IMAGES.get(subtopic_key, FALLBACK_PRODUCT_IMAGES["default"])

    for url in fallbacks:
        filepath = await download_image(url)
        if filepath:
            return filepath

    return None
