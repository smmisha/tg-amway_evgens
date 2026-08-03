"""Scraper for amway.ua articles and product pages.

The site is protected by DataDome anti-bot (JS challenge + fingerprinting).
Headless Chromium, TLS impersonation and HTTP clients all get 403. The only
working approach is a REAL browser in headful (visible) mode:

- channel="chrome" (or "msedge") instead of Playwright's bundled Chromium
- headless=False (DataDome blocks even new headless mode)
- persistent context (user data dir) so the DataDome cookie survives restarts
- --disable-blink-features=AutomationControlled + navigator.webdriver spoof
- adaptive wait: the JS challenge resolves after ~10-25 s

Product images live on an S3 CDN (amstack-eu-...s3-eu-central-1.amazonaws.com)
and are NOT on the amway.ua domain, so the old `img[src*='amway']` selector
missed them. We now read `meta[property='og:image']` first, then fall back to
`img` tags. robots.txt: 1 request / 10 s.
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now(timezone.utc).isoformat()


def detect_product_line(text: str) -> str:
    """Detect Amway product line from text content."""
    text_lower = text.lower()
    # Check for XS product line (use word boundary for 'xs' to avoid matching 'express', 'pixels', etc.)
    if re.search(r"\bxs\b", text_lower) or any(kw in text_lower for kw in ["энергетик", "xs power", "xs™"]):
        return "XS"
    if any(kw in text_lower for kw in ["nutrilite", "нутрилайт", "витамин", "omega", "омега", "протеин"]):
        return "Nutrilite"
    if any(kw in text_lower for kw in ["artistry", "артистри", "косметик", "крем", "сыворотк", "уход за кож"]):
        return "Artistry"
    if any(kw in text_lower for kw in ["amway home", " чистящ", " моющ", "стирк", "средство для"]) or re.search(r"\bloc\b", text_lower):
        return "Home Care"
    return "default"


def _clean_image_url(url: str) -> str:
    """Fix broken URLs like 'https://media.amway.uahttps://amstack...'."""
    url = (url or "").strip()
    last = url.rfind("https://")
    if last > 0:
        url = url[last:]
    return url


def _is_article_like(href: str) -> bool:
    h = href.lower()
    return (
        (h.startswith("http") and ("/p/" in h or "/c/" in h))
        and "cart" not in h
        and "login" not in h
        and "user" not in h
    )


async def _launch_browser(p, profile_dir: str):
    """Launch real headful Chrome/Edge with a persistent profile.

    A persistent context is required: the DataDome cookie is stored in the
    profile dir and reused across runs. Without it the site re-challenges
    every time (and repeated automation attempts can flag the IP).
    """
    from config import settings

    channels = settings.CHROME_CHANNELS
    last_err = None
    for channel in channels:
        try:
            context = await p.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                channel=channel,
                viewport={"width": 1280, "height": 900},
                locale="uk-UA",
                args=["--disable-blink-features=AutomationControlled"],
            )
            logger.info(f"Browser launched (channel={channel}, headful, profile={profile_dir})")
            return context
        except Exception as e:
            last_err = e
            logger.warning(f"Failed to launch channel={channel}: {e}")
    raise last_err


async def _wait_until_ready(page, min_links: int, timeout_ms: int) -> None:
    """Wait for DataDome's JS challenge to resolve (content starts appearing)."""
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
    while asyncio.get_event_loop().time() < deadline:
        count = await page.eval_on_selector_all(
            "a[href]", "els => els.filter(el => el.href).length"
        )
        if count >= min_links:
            return
        await page.wait_for_timeout(3000)
    logger.warning("Timed out waiting for page content (DataDome challenge unresolved?)")


async def _collect_links(page, url: str, timeout_ms: int) -> list[str]:
    """Open a page and return deduplicated article-like links."""
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await _wait_until_ready(page, min_links=5, timeout_ms=timeout_ms)

    links = await page.eval_on_selector_all(
        "a[href]",
        "els => els.map(el => el.href)"
    )
    seen = set()
    result = []
    for href in links:
        if _is_article_like(href) and href not in seen:
            seen.add(href)
            result.append(href)
    return result


async def _extract_images(page) -> list[str]:
    """Extract product images: og:image first, then img tags."""
    images = []

    og_images = await page.eval_on_selector_all(
        "meta[property='og:image']",
        "els => els.map(el => el.content || '')"
    )
    for src in og_images:
        src = _clean_image_url(src)
        if src.startswith("http"):
            images.append(src)

    if not images:
        img_tags = await page.eval_on_selector_all(
            "img[src]",
            """els => els.map(el => el.currentSrc || el.src || '')
                 .filter(s => s && s.startsWith('http') &&
                         !s.includes('logo') && !s.includes('icon'))"""
        )
        for src in img_tags:
            src = _clean_image_url(src)
            if src.startswith("http"):
                images.append(src)

    seen = set()
    unique = []
    for src in images:
        if src not in seen:
            seen.add(src)
            unique.append(src)
    return unique[:5]


async def _extract_body(page) -> str:
    """Extract product description text.

    Product pages render the description inside JS tabs (Огляд/Опис/Склад).
    We click each tab and read the .tabbody panel, keeping the longest text.
    Falls back to common content selectors, then to meta description.
    """
    body = ""
    tab_loc = page.locator("a, button, [role='tab'], .tab-title")
    tab_count = await tab_loc.count()
    longest = ""
    for i in range(tab_count):
        try:
            if not await tab_loc.nth(i).is_visible():
                continue
            txt = (await tab_loc.nth(i).inner_text() or "").strip()
        except Exception:
            continue
        if not re.search(r"^(огляд|опис|склад|характеристики|застосування)", txt, re.I) or len(txt) > 60:
            continue
        try:
            await tab_loc.nth(i).click(timeout=3000)
            await page.wait_for_timeout(1500)
            panels = page.locator(".tabbody")
            panel_count = await panels.count()
            for j in range(panel_count):
                try:
                    panel_text = (await panels.nth(j).inner_text()).strip()
                except Exception:
                    continue
                if len(panel_text) > len(longest):
                    longest = panel_text
        except Exception:
            continue

    if len(longest) > 100:
        body = longest

    if len(body) < 100:
        for selector in ["article", ".content-body", ".product-description",
                         "[class*='content']", "main", ".page-content"]:
            try:
                el = await page.query_selector(selector)
                if el:
                    body = await el.inner_text()
                    if len(body) > 100:
                        break
            except Exception:
                continue

    if not body or len(body) < 50:
        meta_desc = await page.eval_on_selector_all(
            "meta[name='description']",
            "els => els.map(el => el.content || '')"
        )
        if meta_desc and meta_desc[0]:
            body = meta_desc[0]

    return body.strip()


async def scrape_amway(sections: list[str], base_url: str = "https://www.amway.ua",
                       delay: int = 10, max_articles: int = 5) -> list[Article]:
    """Scrape product pages from amway.ua using real headful Chrome.

    Strategy: collect category (/c/) links on section pages, then product
    (/p/) links on category pages, then extract title/body/images from
    product pages.

    Args:
        sections: URL paths to scrape (e.g., ["/uk/", "/uk/c/health"])
        base_url: Base URL of the site
        delay: Delay between requests in seconds (robots.txt says 10s)
        max_articles: Maximum number of articles to return
    """
    from playwright.async_api import async_playwright
    from config import settings

    articles = []
    profile_dir = settings.CHROME_PROFILE_DIR
    wait_timeout = settings.SCRAPE_WAIT_TIMEOUT_MS
    os.makedirs(profile_dir, exist_ok=True)

    try:
        async with async_playwright() as p:
            context = await _launch_browser(p, profile_dir)
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.pages[0] if context.pages else await context.new_page()

            for section_path in sections:
                if len(articles) >= max_articles:
                    break

                url = f"{base_url}{section_path}"
                logger.info(f"Scraping section: {url}")

                try:
                    links = await _collect_links(page, url, wait_timeout)
                    product_links = [l for l in links if "/p/" in l.lower()]
                    category_links = [l for l in links if "/c/" in l.lower()]

                    logger.info(
                        f"Found {len(product_links)} product links, "
                        f"{len(category_links)} category links in {section_path}"
                    )

                    # Discover /p/ links from category pages if needed
                    if not product_links and category_links:
                        for cat_url in category_links[:3]:
                            if len(articles) >= max_articles:
                                break
                            try:
                                await asyncio.sleep(delay)
                                cat_links = await _collect_links(page, cat_url, wait_timeout)
                                for l in cat_links:
                                    if "/p/" in l.lower() and l not in product_links:
                                        product_links.append(l)
                                logger.info(f"Category {cat_url}: +{len(product_links)} product links so far")
                            except Exception as e:
                                logger.warning(f"Failed to scan category {cat_url}: {e}")
                                continue

                    # Scrape product pages
                    for product_url in product_links[:max_articles - len(articles)]:
                        try:
                            await asyncio.sleep(delay)
                            await page.goto(product_url, wait_until="domcontentloaded", timeout=40000)
                            await _wait_until_ready(page, min_links=1, timeout_ms=wait_timeout)

                            title = await page.title()
                            title = re.sub(r"\s*[|\-–—]\s*Amway.*$", "", title).strip()
                            if not title:
                                title = product_url.rsplit("/", 1)[-1]

                            body = await _extract_body(page)

                            images = await _extract_images(page)

                            if title and (body or images):
                                body = re.sub(r"\n{3,}", "\n\n", body)
                                body = body[:5000]

                                article = Article(
                                    url=product_url,
                                    title=title,
                                    body=body,
                                    images=images,
                                    category=section_path.split("/")[-1],
                                    product_line=detect_product_line(f"{title} {body}"),
                                )
                                articles.append(article)
                                logger.info(
                                    f"Scraped: {title} [{article.product_line}] "
                                    f"({len(images)} images)"
                                )

                        except Exception as e:
                            logger.warning(f"Failed to scrape product {product_url}: {e}")
                            continue

                except Exception as e:
                    logger.warning(f"Failed to scrape section {url}: {e}")
                    continue

            await context.close()

    except Exception as e:
        logger.error(f"Playwright error: {e}")

    logger.info(f"Total articles scraped: {len(articles)}")
    return articles
