"""Amway Telegram Bot — main orchestrator.

Pipeline:
1. Scrape → get articles from amway.ua
2. Filter → remove already published
3. Enrich → optionally add book context (30% of posts)
4. Rewrite → LLM rewriting in brand-ambassador style
5. Media → download images
6. Publish → send to Telegram group
7. Save → mark as published

Usage:
    python -m src.main              # Full pipeline
    python -m src.main --dry-run    # No Telegram publishing
"""

import asyncio
import logging
import random
import sys

from config.settings import (
    BOOK_ENRICHMENT_PROBABILITY,
    MAX_ARTICLES_PER_RUN,
    PUBLISHED_JSON,
    SCRAPE_DELAY_SECONDS,
    SCRAPE_SECTIONS,
    SCRAPE_BASE_URL,
)
from src.book_enricher import get_book_enrichment
from src.media import download_first_image
from src.media_validator import validate_image_with_gemini_vision
from src.publisher import publish_post
from src.rewriter import rewrite_article
from src.scraper import scrape_amway, Article
from src.storage import Storage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def run(dry_run: bool = False):
    """Execute the full pipeline."""
    logger.info("=" * 50)
    logger.info("Amway Telegram Bot — starting pipeline")
    logger.info("=" * 50)

    storage = Storage(PUBLISHED_JSON)
    logger.info(f"Published articles in DB: {storage.count()}")

    # ── Step 1: Scrape ────────────────────────────────────────────────
    logger.info("\n[Step 1/6] Scraping amway.ua...")
    articles = await scrape_amway(
        sections=SCRAPE_SECTIONS,
        base_url=SCRAPE_BASE_URL,
        delay=SCRAPE_DELAY_SECONDS,
        max_articles=MAX_ARTICLES_PER_RUN * 3,  # Fetch extra for filtering
    )
    logger.info(f"Scraped {len(articles)} articles")

    new_articles = [a for a in articles if not storage.is_published(a.url)]
    logger.info(f"New articles after filtering: {len(new_articles)}")

    if not new_articles:
        logger.info("No new scraped articles found. Falling back to Books Knowledge Bundle post...")
        book_context = get_book_enrichment()
        if not book_context:
            logger.warning("No book context available for fallback. Exiting.")
            return

        # Create a fallback synthetic article object for the book-based post
        fallback_article = Article(
            url=f"https://www.amway.ua/fallback-{random.randint(1000, 9999)}",
            title="Советы по здоровью и уходу",
            body="Инновационные решения Amway для здоровья, красоты и дома.",
            product_line=random.choice(["Nutrilite", "Artistry", "XS", "Home Care"]),
        )
        selected = [fallback_article]
    else:
        selected = new_articles[:MAX_ARTICLES_PER_RUN]

    logger.info(f"Selected {len(selected)} items for processing")

    published_count = 0

    for i, article in enumerate(selected, 1):
        logger.info(f"\n{'─' * 40}")
        logger.info(f"Processing article {i}/{len(selected)}: {article.title}")
        logger.info(f"Product line: {article.product_line}")
        logger.info(f"URL: {article.url}")

        # ── Step 3: Book Enrichment (30% chance) ─────────────────────
        book_context = None
        if random.random() < BOOK_ENRICHMENT_PROBABILITY:
            logger.info("[Step 3/6] Adding book enrichment...")
            book_context = get_book_enrichment()
        else:
            logger.info("[Step 3/6] Skipping book enrichment (random)")

        # ── Step 4: Media Selection ──────────────────────────────────
        logger.info("[Step 4/6] Selecting topic-matched product image...")
        image_path = await download_first_image(
            article.images,
            article.product_line,
            title=article.title,
        )
        if image_path:
            logger.info(f"Image ready: {image_path}")

        # ── Step 5: Native Multimodal Rewrite via Gemini 3.6 Flash ────
        logger.info("[Step 5/6] Generating post via Gemini 3.6 Flash (Multimodal)...")
        try:
            post_text = await rewrite_article(
                article=article,
                book_context=book_context,
                image_path=image_path,
            )
        except RuntimeError as e:
            logger.error(f"Rewrite failed: {e}. Skipping article.")
            continue

        logger.info(f"Generated post ({len(post_text)} chars):")
        logger.info(f"\n{post_text}\n")

        # ── Step 5.5: Gemini "eyes" — check image + text together ──────
        if image_path:
            logger.info("[Step 5.5/6] Gemini visually checking image + text...")
            try:
                vision_ok = await validate_image_with_gemini_vision(
                    image_path=image_path,
                    topic_title=article.title,
                    product_line=article.product_line,
                    post_text=post_text,
                )
            except Exception as e:
                logger.warning(f"Vision validation error: {e}. Proceeding without it.")
                vision_ok = True

            if not vision_ok:
                logger.warning(
                    "Gemini rejected the post (image/text mismatch). Skipping article."
                )
                continue
            logger.info("Gemini approved the post (image + text match).")

        # ── Step 6: Publish ──────────────────────────────────────────
        if dry_run:
            logger.info("[Step 6/6] DRY RUN — skipping Telegram publish")
            message_id = "dry-run"
        else:
            logger.info("[Step 6/6] Publishing to Telegram...")
            message_id = await publish_post(
                text=post_text,
                image_path=image_path,
                use_html=False,  # Plain text — emojis don't need HTML
            )
            if not message_id:
                logger.error("Failed to publish. Skipping.")
                continue

        # ── Step 7: Save ─────────────────────────────────────────────
        storage.mark_published(
            url=article.url,
            title=article.title,
            telegram_message_id=message_id or "",
        )
        published_count += 1
        logger.info(f"Marked as published. Message ID: {message_id}")

    logger.info(f"\n{'=' * 50}")
    logger.info(f"Pipeline complete. Published {published_count}/{len(selected)} posts.")
    logger.info(f"Total in DB: {storage.count()}")


def main():
    if "--listen" in sys.argv:
        from src.bot_listener import run_bot_listener
        run_bot_listener()
        return

    dry_run = "--dry-run" in sys.argv
    if dry_run:
        logger.info("Running in DRY RUN mode (no Telegram publishing)")
    asyncio.run(run(dry_run=dry_run))


if __name__ == "__main__":
    main()
