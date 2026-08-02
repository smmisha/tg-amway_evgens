"""Scraper for amway.ua articles and product pages.

Uses Playwright (headless Chromium) because the site is a JavaScript SPA
(SAP Commerce Cloud) with Cloudflare protection. Standard HTTP requests
return 403.
"""

import asyncio
import logging
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
    if any(kw in text_lower for kw in ["xs", "энергетик", "energy", "xs power"]):
        return "XS"
    if any(kw in text_lower for kw in ["nutrilite", "нутрилайт", "витамин", "omega", "омега", "протеин"]):
        return "Nutrilite"
    if any(kw in text_lower for kw in ["artistry", "артистри", "косметик", "крем", "сыворотк", "уход за кож"]):
        return "Artistry"
    if any(kw in text_lower for kw in ["amway home", "loc", "моющ", "чистящ", "стирк", "средство для"]):
        return "Home Care"
    return "default"


async def scrape_amway(sections: list[str], base_url: str = "https://www.amway.ua",
                       delay: int = 10, max_articles: int = 5) -> list[Article]:
    """Scrape articles from amway.ua using Playwright.

    Args:
        sections: URL paths to scrape (e.g., ["/uk/expert-advice"])
        base_url: Base URL of the site
        delay: Delay between requests in seconds (robots.txt says 10s)
        max_articles: Maximum number of articles to return

    Returns:
        List of Article objects
    """
    from playwright.async_api import async_playwright

    articles = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="uk-UA",
            )
            page = await context.new_page()

            for section_path in sections:
                if len(articles) >= max_articles:
                    break

                url = f"{base_url}{section_path}"
                logger.info(f"Scraping section: {url}")

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(4000)  # Wait for SPA JS rendering

                    # Scroll down slightly to trigger lazy loading
                    await page.evaluate("window.scrollBy(0, 500)")
                    await page.wait_for_timeout(1000)

                    # Expand selector for Amway product & article links
                    links = await page.eval_on_selector_all(
                        "a[href]",
                        """elements => elements
                            .map(el => ({href: el.href, text: el.textContent.trim()}))
                            .filter(el => {
                                const h = el.href.toLowerCase();
                                return (h.includes('/p/') || h.includes('/c/') || h.includes('/product') ||
                                        h.includes('/article') || h.includes('/advice') || h.includes('/story')) &&
                                       !h.includes('/cart') && !h.includes('/login') && !h.includes('/user');
                            })
                        """
                    )

                    # Deduplicate and filter links
                    seen_urls = set()
                    article_links = []
                    for link in links:
                        href = link.get("href", "")
                        if href and href not in seen_urls and link.get("text"):
                            seen_urls.add(href)
                            article_links.append(href)

                    logger.info(f"Found {len(article_links)} article links in {section_path}")

                    # Visit each article page
                    for article_url in article_links[:max_articles - len(articles)]:
                        try:
                            await asyncio.sleep(delay)
                            await page.goto(article_url, wait_until="domcontentloaded", timeout=20000)
                            await page.wait_for_timeout(3000)

                            # Extract content
                            title = await page.title()
                            title = re.sub(r"\s*[|\-–—]\s*Amway.*$", "", title).strip()

                            # Try multiple selectors for body content
                            body = ""
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
                                # Fallback: get all visible text from body
                                body = await page.eval_on_selector(
                                    "body",
                                    "el => el.innerText"
                                )

                            # Extract images
                            images = await page.eval_on_selector_all(
                                "img[src*='amway'], img[src*='product'], img[data-src]",
                                """elements => elements
                                    .map(el => el.src || el.dataset.src || '')
                                    .filter(src => src && !src.includes('icon') && !src.includes('logo'))
                                """
                            )

                            if title and body:
                                # Clean body text
                                body = re.sub(r"\n{3,}", "\n\n", body)
                                body = body[:5000]  # Limit body length for LLM context

                                article = Article(
                                    url=article_url,
                                    title=title,
                                    body=body,
                                    images=images[:5],
                                    category=section_path.split("/")[-1],
                                    product_line=detect_product_line(f"{title} {body}"),
                                )
                                articles.append(article)
                                logger.info(f"Scraped: {title} [{article.product_line}]")

                        except Exception as e:
                            logger.warning(f"Failed to scrape article {article_url}: {e}")
                            continue

                except Exception as e:
                    logger.warning(f"Failed to scrape section {url}: {e}")
                    continue

            await browser.close()

    except Exception as e:
        logger.error(f"Playwright error: {e}")

    logger.info(f"Total articles scraped: {len(articles)}")
    return articles
