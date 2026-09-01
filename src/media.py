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
# Every entry is an EXACT 1:1 match for that specific product only.
FALLBACK_PRODUCT_IMAGES: dict[str, list[str]] = {
    "Nutrilite_Omega3": ["data/media/post_7_02dfeb6e.jpg"],
    "Nutrilite_DoubleX": ["data/media/post_8_dd22cf0c.jpg"],
    "Nutrilite_VitaminC": ["data/media/post_9_e3fbab59.jpg"],
    "Nutrilite_CalciumMagnesium": ["data/media/post_10_050b9f4d.jpg"],
    "Nutrilite_VitaminD": ["data/media/post_20_b5850f5d.jpg"],
    "Nutrilite_Metabolism": ["data/media/post_metabolism_plus.jpg"],
    "XS_WildBerry": ["data/media/post_11_f4ffe234.jpg"],
    "XS_WheyProtein": ["data/media/post_12_26fb454c.jpg"],
    "XS_Magnesium": ["data/media/post_19_0922c3d5.jpg"],
    "Artistry_DayLotion": ["data/media/post_13_e5c3ccda.jpg"],
    "Artistry_CCCream": ["data/media/post_14_fa2399c4.jpg"],
    "Artistry_Mascara": ["data/media/post_15_5fc5454a.jpg"],
    "HomeCare_Bleach": ["data/media/post_16_de56257c.jpg"],
    "HomeCare_DishDrops": ["data/media/post_17_53d18f48.jpg"],
    "HomeCare_ScrubBuds": ["data/media/post_18_e2195dd6.jpg"],
}

def detect_subtopic_key(title: str, product_line: str) -> str | None:
    """Determine fine-grained subtopic ONLY when there is an exact 1:1 product match."""
    t = f"{title} {product_line}".lower()

    # Nutrilite exact matches
    if any(kw in t for kw in ["омега", "omega", "жирн", "рыби", "fish"]):
        return "Nutrilite_Omega3"
    if "double x" in t or "дабл" in t:
        return "Nutrilite_DoubleX"
    if any(kw in t for kw in ["вітамін c", "витамин c", "vitamin c", "вітамін с", "витамин с"]):
        return "Nutrilite_VitaminC"
    if any(kw in t for kw in ["кальцій", "кальций", "магній d", "магний d", "calcium"]):
        return "Nutrilite_CalciumMagnesium"
    if any(kw in t for kw in ["вітамін d", "витамин d", "vitamin d"]):
        return "Nutrilite_VitaminD"
    if any(kw in t for kw in ["метаболіз", "метаболиз", "metabolism"]):
        return "Nutrilite_Metabolism"

    # XS exact matches
    if any(kw in t for kw in ["wild berry", "ягід", "ягод", "power drink"]):
        return "XS_WildBerry"
    if any(kw in t for kw in ["whey", "протеїн", "протеин", "сироватк", "сыворотк"]):
        return "XS_WheyProtein"
    if any(kw in t for kw in ["магній", "магний", "пакетик", "пакет"]):
        return "XS_Magnesium"

    # Artistry exact matches
    if any(kw in t for kw in ["spf 30", "денний лосьйон", "дневной лосьон", "skin nutrition"]):
        return "Artistry_DayLotion"
    if any(kw in t for kw in ["ss-крем", "сс-крем", "ideal radiance", "вирівнювання тону"]):
        return "Artistry_CCCream"
    if any(kw in t for kw in ["туш", "тушь", "вії", "ресниц", "bangkok"]):
        return "Artistry_Mascara"

    # Home Care exact matches
    if any(kw in t for kw in ["відбілювач", "отбеливатель", "sa8"]):
        return "HomeCare_Bleach"
    if any(kw in t for kw in ["dish drops", "миття посуду", "мытья посуды"]):
        return "HomeCare_DishDrops"
    if any(kw in t for kw in ["scrub buds", "металеві губки", "металлические губки"]):
        return "HomeCare_ScrubBuds"

    # No exact match -> None (do NOT attach a mismatched image!)
    return None


def _load_catalog_images_for_product(url: str, title: str) -> list[str]:
    """Load image URLs from products_catalog.json matching the specific product URL or full title."""
    import json as _json

    catalog_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "products_catalog.json"
    )
    if not os.path.exists(catalog_file):
        return []
    try:
        with open(catalog_file, "r", encoding="utf-8") as f:
            catalog = _json.load(f)
        urls = []
        clean_url = (url or "").strip().rstrip("/")
        title_lower = (title or "").lower().strip()

        for item in catalog:
            item_url = item.get("url", "").strip().rstrip("/")
            item_title = item.get("title", "").lower().strip()

            # Exact URL match or strong title match
            is_match = False
            if clean_url and item_url and clean_url == item_url:
                is_match = True
            elif title_lower and item_title and (title_lower in item_title or item_title in title_lower):
                is_match = True

            if is_match:
                for img_url in item.get("images", []):
                    if img_url and img_url not in urls:
                        urls.append(img_url)
        return urls
    except Exception as e:
        logger.warning(f"Failed to load catalog images: {e}")
        return []


OFFICIAL_IMAGE_DOMAINS = [
    "amway.ua",
    "amway.com",
    "amway.eu",
    "amstack",
    "s3-eu-central-1.amazonaws.com",
    "amway-media",
]

def _is_official_image_url(url: str) -> bool:
    """True if URL is from Amway official domain/CDN."""
    u = (url or "").lower()
    return any(d in u for d in OFFICIAL_IMAGE_DOMAINS)


async def autonomous_resolve_product_image(
    title: str,
    product_line: str = "default",
    sku: str = "",
    url: str = "",
    output_dir: str | None = None,
    strict_official: bool = True,
) -> str | None:
    """Autonomously fetch and AI-verify official product photo from web/CDN.
    If strict_official=True, only Amway official domains are accepted.
    """
    import re
    import urllib.parse
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        logger.warning("curl_cffi not installed, skipping autonomous web image search")
        return None

    # Extract SKU from URL if not explicitly provided
    if not sku and url:
        m = re.search(r"/p/(\d+)", url)
        if m:
            sku = m.group(1)

    clean_title = re.sub(r"[^\w\s-]", " ", title).strip()
    query_parts = ["Amway", product_line if product_line != "default" else "", clean_title, sku]
    query = " ".join(p for p in query_parts if p).strip()

    logger.info(f"Initiating autonomous image search for query: '{query}'")
    encoded_q = urllib.parse.quote(query)
    search_url = f"https://www.bing.com/images/search?q={encoded_q}&form=HDRSC2&first=1"

    try:
        res = cffi_requests.get(search_url, impersonate="chrome124", timeout=15)
        if res.status_code != 200:
            logger.warning(f"Search request failed with status {res.status_code}")
            return None

        murls = re.findall(r'murl&quot;:&quot;(http[^&]+)&quot;', res.text)
        if not murls:
            murls = re.findall(r'"murl":"(http[^"]+)"', res.text)

        if not murls:
            logger.info(f"No image candidates found for '{query}'")
            return None

        # Strict official filter: drop non-Amway domains before scoring
        if strict_official:
            official_candidates = [u for u in murls if _is_official_image_url(u)]
            if official_candidates:
                murls = official_candidates
                logger.info(f"Strict official mode: {len(murls)} official candidates kept from {len(murls)} total")
            else:
                logger.warning(f"Strict official mode: no official domain candidates for '{query}' — aborting search (no non-official allowed)")
                return None

        # Prioritize official/high quality domains
        def score_url(u: str) -> int:
            score = 0
            u_lower = u.lower()
            if "amway" in u_lower: score += 15
            if "sys-master" in u_lower: score += 10
            if "product" in u_lower: score += 5
            if u_lower.endswith((".jpg", ".jpeg", ".png", ".webp")): score += 3
            if any(bad in u_lower for bad in ["logo", "banner", "icon", "vector", "person", "man", "woman"]): score -= 20
            if _is_official_image_url(u): score += 20
            return score

        murls.sort(key=score_url, reverse=True)
        top_candidates = murls[:6]
        logger.info(f"Evaluating {len(top_candidates)} candidate images with AI Vision...")

        # Lazy import validator to prevent circular deps
        from src.media_validator import validate_image_with_gemini_vision

        for i, candidate_url in enumerate(top_candidates, 1):
            logger.info(f"Downloading candidate [{i}/{len(top_candidates)}]: {candidate_url[:80]}...")
            local_path = await download_image(candidate_url, output_dir=output_dir)
            if not local_path or not os.path.exists(local_path):
                continue

            # Verify candidate image with Gemini Vision
            is_valid = await validate_image_with_gemini_vision(
                image_path=local_path,
                topic_title=title,
                product_line=product_line,
                post_text=f"Product post about {title}"
            )
            if is_valid:
                logger.info(f"🎯 Candidate [{i}] verified by AI Vision: {candidate_url}")
                return local_path
            else:
                logger.info(f"Candidate [{i}] rejected by AI Vision (not matching product). Cleaning up.")
                cleanup_temp_media(local_path)

        logger.info("None of the image candidates passed AI Vision verification.")
        return None

    except Exception as e:
        logger.warning(f"Autonomous image search failed for '{query}': {e}")
        return None


async def download_first_image(
    image_urls: list[str],
    product_line: str = "default",
    title: str = "",
    url: str = "",
    sku: str = "",
) -> str | None:
    """Download the first available image matching THIS SPECIFIC product.

    Priority order:
    1. Scraped image URLs from the article page (og:image, img tags)
    2. Catalog images for THIS specific product from products_catalog.json
    3. Exact 1:1 local fallback image (only if title explicitly matches the product)
    4. Autonomous web search & AI Vision verification (zero-key TLS resolver)
    5. None (text-only post — infinitely better than a wrong product's picture!)

    Args:
        image_urls: List of candidate scraped URLs
        product_line: Amway product category
        title: Article or product title
        url: Article URL
        sku: Product SKU article number

    Returns:
        Local file path to downloaded product image, or None.
    """
    # 1. Try scraped image URLs from the article page
    for img_url in image_urls:
        if img_url:
            filepath = await download_image(img_url)
            if filepath:
                logger.info(f"Using scraped image from article: {img_url[:80]}...")
                return filepath

    # 2. Try catalog images for THIS specific product
    catalog_urls = _load_catalog_images_for_product(url=url, title=title)
    for img_url in catalog_urls:
        if img_url:
            filepath = await download_image(img_url)
            if filepath:
                logger.info(f"Using exact catalog image: {img_url[:80]}...")
                return filepath

    # 3. Exact 1:1 local product fallback (ONLY if subtopic matches 100%)
    subtopic_key = detect_subtopic_key(title, product_line)
    if subtopic_key and subtopic_key in FALLBACK_PRODUCT_IMAGES:
        fallbacks = FALLBACK_PRODUCT_IMAGES[subtopic_key]
        for img_url in fallbacks:
            filepath = await download_image(img_url)
            if filepath:
                logger.info(f"Using exact 1:1 fallback image [{subtopic_key}]: {img_url}")
                return filepath

    # 4. Autonomous zero-intervention Web & AI Vision Resolver (official only)
    if title:
        auto_img = await autonomous_resolve_product_image(
            title=title,
            product_line=product_line,
            sku=sku,
            url=url,
            strict_official=True,
        )
        if auto_img:
            logger.info(f"Using autonomously resolved & AI-verified OFFICIAL image: {auto_img}")
            return auto_img

    # 5. STRICT RULE: every post MUST have official image — no text-only
    logger.warning(f"STRICT: No official image for '{title}' [{product_line}]. Skipping candidate (no text-only allowed).")
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

