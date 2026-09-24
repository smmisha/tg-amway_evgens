"""Scraper for amway.ua articles and product pages.

Uses Scrapling + TLS impersonation (curl_cffi with Chrome 124 fingerprint)
to discover and fetch products directly from Amway's official S3 XML sitemaps
and product pages. This completely bypasses DataDome anti-bot challenges and
eliminates the need for heavy, error-prone browser automation in CI.
"""

import asyncio
import json
import logging
import os
import random
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone

from curl_cffi import requests as cffi_requests
from scrapling import Selector

logger = logging.getLogger(__name__)


@dataclass
class Article:
    """Parsed article/product from amway.ua."""
    url: str
    title: str
    body: str
    images: list[str] = field(default_factory=list)
    category: str = ""
    product_line: str = ""  # XS, Nutrilite, Artistry, Home Care
    sku: str = ""
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now(timezone.utc).isoformat()
        if not self.sku and self.url:
            m = re.search(r"/p/(\d+)", self.url)
            if m:
                self.sku = m.group(1)


def detect_product_line(text: str) -> str:
    """Detect Amway product line from text content (supports UA & RU keywords)."""
    text_lower = text.lower()
    # Check for XS product line (use word boundary for 'xs' to avoid matching 'express', 'pixels', etc.)
    if re.search(r"\bxs\b", text_lower) or any(kw in text_lower for kw in ["енергетик", "энергетик", "xs power", "xs™", "енергетичн"]):
        return "XS"
    if any(kw in text_lower for kw in ["nutrilite", "нутрилайт", "нутрылайт", "вітамін", "витамин", "omega", "омега", "протеин", "протеїн", "дієтичн"]):
        return "Nutrilite"
    if any(kw in text_lower for kw in ["artistry", "артистри", "артистрі", "косметик", "крем", "сыворотк", "сироватк", "уход за кож", "догляд за шкір"]):
        return "Artistry"
    if any(kw in text_lower for kw in ["amway home", "чистящ", "миюч", "моющ", "стирк", "пранн", "засіб для", "средство для", "sa8", "dish drops", "scrub buds"]) or re.search(r"\bloc\b", text_lower):
        return "Home Care"
    if any(kw in text_lower for kw in ["glister", "g&h", "satinique", "зубн", "паст", "шампун"]):
        return "Personal Care"
    return "default"


def _clean_image_url(url: str) -> str:
    """Fix broken URLs like 'https://media.amway.uahttps://amstack...'."""
    url = (url or "").strip()
    last = url.rfind("https://")
    if last > 0:
        url = url[last:]
    return url


def _fetch_sitemap_product_urls() -> list[str]:
    """Fetch all product URLs from amway.ua XML sitemaps via S3."""
    try:
        r = cffi_requests.get("https://www.amway.ua/sitemap.xml", impersonate="chrome124", timeout=15)
        if r.status_code != 200:
            logger.warning(f"Sitemap index returned status {r.status_code}")
            return []
        root = ET.fromstring(r.content)
        sitemap_locs = [elem.text for elem in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc") if elem.text]
        product_sitemaps = [u for u in sitemap_locs if "Product-" in u]
        if not product_sitemaps:
            logger.warning("No Product sitemaps found in sitemap index")
            return []

        all_products: list[str] = []
        for sm_url in product_sitemaps:
            try:
                r_prod = cffi_requests.get(sm_url, impersonate="chrome124", timeout=20)
                if r_prod.status_code == 200:
                    root_prod = ET.fromstring(r_prod.content)
                    urls = [elem.text for elem in root_prod.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc") if elem.text]
                    all_products.extend(urls)
            except Exception as e:
                logger.warning(f"Failed to fetch sub-sitemap {sm_url}: {e}")
                continue

        logger.info(f"Discovered {len(all_products)} product URLs from Amway XML sitemaps.")
        return all_products
    except Exception as e:
        logger.warning(f"Failed to fetch sitemap: {e}")
        return []


def _scrape_product_page(url: str) -> Article | None:
    """Scrape and parse a single product page using Scrapling and TLS impersonation."""
    try:
        r = cffi_requests.get(url, impersonate="chrome124", timeout=15)
        if r.status_code != 200 or not r.text:
            logger.warning(f"Failed to fetch {url}: status {r.status_code}")
            return None

        html_text = r.content.decode("utf-8", errors="replace")
        page = Selector(html_text)
        raw_title = page.css("title::text").get() or ""
        title = re.sub(r"\s*[|\-–—]\s*.*Amway.*$", "", raw_title, flags=re.IGNORECASE).strip()
        if not title:
            title = re.sub(r"\s*[|\-–—]\s*.*$", "", raw_title).strip()
        if not title:
            title = url.rsplit("/", 1)[-1]

        # Extract images
        images = []
        og_img = page.css("meta[property='og:image']::attr(content)").get()
        if og_img:
            cleaned = _clean_image_url(og_img)
            if cleaned.startswith("http"):
                images.append(cleaned)

        # Extract description / body
        body = page.css("meta[name='description']::attr(content)").get() or ""
        if not body:
            paragraphs = page.css("p::text").getall()
            if paragraphs:
                body = " ".join([p.strip() for p in paragraphs if len(p.strip()) > 30])

        if not images and not body:
            return None

        sku = ""
        m = re.search(r"/p/(\d+)", url)
        if m:
            sku = m.group(1)

        product_line = detect_product_line(f"{title} {body}")

        return Article(
            url=url,
            title=title,
            body=body[:5000],
            images=images,
            category=product_line.lower(),
            product_line=product_line,
            sku=sku,
        )
    except Exception as e:
        logger.warning(f"Error scraping product page {url}: {e}")
        return None


async def scrape_amway(
    sections: list[str] | None = None,
    base_url: str = "https://www.amway.ua",
    delay: int = 10,
    max_articles: int = 8,
) -> list[Article]:
    """Scrape articles/products from amway.ua.

    Primary engine: Scrapling + S3 XML Sitemaps (800+ products, zero DataDome challenge).
    Fallback: data/products_catalog.json.
    """
    logger.info("Scraping amway.ua using Scrapling & S3 Sitemap engine...")
    articles: list[Article] = []
    scraped_urls: set[str] = set()

    # 1. Fetch products from sitemaps
    product_urls = _fetch_sitemap_product_urls()
    if product_urls:
        # Shuffle to discover varied products across runs
        # Use day of year as seed for consistent daily candidate pool rotation
        now = datetime.now(timezone.utc)
        random.seed(now.strftime("%Y%m%d%H"))
        sample_pool = list(product_urls)
        random.shuffle(sample_pool)

        # Load published storage to prioritize completely fresh URLs
        try:
            from config.settings import PUBLISHED_JSON, ATTEMPTED_JSON
            from src.storage import Storage, AttemptStorage
            storage = Storage(PUBLISHED_JSON)
            attempts = AttemptStorage(ATTEMPTED_JSON)

            fresh_candidates = [
                u for u in sample_pool
                if not storage.is_published(u) and not attempts.is_attempted(u)
            ]
            candidates = fresh_candidates if fresh_candidates else sample_pool
        except Exception as e:
            logger.warning(f"Storage check error during scraping candidate selection: {e}")
            candidates = sample_pool

        for p_url in candidates:
            if len(articles) >= max_articles:
                break
            art = _scrape_product_page(p_url)
            if art and art.images and art.title:
                articles.append(art)
                scraped_urls.add(art.url)
                logger.info(f"Scraped via Scrapling: {art.title} [{art.product_line}] (SKU: {art.sku})")
            if delay > 0 and len(articles) < max_articles:
                await asyncio.sleep(min(delay, 2))  # courteous small delay

    # 2. Fallback to products_catalog.json if live scraping yielded fewer than max_articles
    if len(articles) < max_articles:
        logger.info(f"Scraped {len(articles)} live articles. Loading product catalog fallback...")
        catalog_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "products_catalog.json"
        )
        if os.path.exists(catalog_file):
            try:
                with open(catalog_file, "r", encoding="utf-8-sig") as f:
                    catalog_data = json.load(f)
                for item in catalog_data:
                    url = item.get("url", "")
                    if url in scraped_urls:
                        continue
                    articles.append(Article(
                        url=url,
                        title=item.get("title", ""),
                        body=item.get("body", ""),
                        images=item.get("images", []),
                        category=item.get("category", "catalog"),
                        product_line=item.get("product_line", detect_product_line(item.get("title", ""))),
                    ))
                    scraped_urls.add(url)
                    logger.info(f"Loaded from catalog: {item.get('title')} [{item.get('product_line')}]")
            except Exception as e:
                logger.warning(f"Failed to load products catalog: {e}")

    logger.info(f"Total articles scraped: {len(articles)}")
    return articles
