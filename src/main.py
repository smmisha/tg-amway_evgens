"""Amway Telegram Bot — main orchestrator.

Pipeline:
1. Scrape → get articles from amway.ua
2. Filter → remove already published + in-cooldown failed candidates
3. Enrich → optionally add book context (30% of posts)
4. Rewrite → LLM rewriting in brand-ambassador style
5. Media → download images
6. Publish → send to Telegram group
7. Save → mark as published

Candidates are processed as a POOL: if one fails (image download, rewrite,
Gemini vision rejection, publish), it is recorded in attempted.json and the
next candidate is tried until the day's goal (1 post) is reached.

Usage:
    python -m src.main              # Full pipeline
    python -m src.main --dry-run    # No Telegram publishing
"""

import asyncio
import logging
import random
import sys

from config.settings import (
    ATTEMPTED_JSON,
    BOOK_ENRICHMENT_PROBABILITY,
    CANDIDATE_POOL_SIZE,
    MAX_ARTICLES_PER_RUN,
    PUBLISHED_JSON,
    SCRAPE_DELAY_SECONDS,
    SCRAPE_SECTIONS,
    SCRAPE_BASE_URL,
    TELEGRAM_ADMIN_CHAT_ID,
    TELEGRAM_GROUP_CHAT_ID,
    TELEGRAM_CHAT_ID,
)
from src.book_enricher import get_book_enrichment
from src.media import download_first_image, cleanup_temp_media
from src.media_validator import validate_image_with_gemini_vision
from src.publisher import publish_post
from src.rewriter import rewrite_article
from src.scraper import scrape_amway, Article
from src.storage import AttemptStorage, Storage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _log_telegram_targets():
    """Log the effective Telegram publish target to spot fallback problems."""
    logger.info(
        f"Telegram targets -> GROUP={TELEGRAM_GROUP_CHAT_ID or '(not set)'} "
        f"| ADMIN={TELEGRAM_ADMIN_CHAT_ID or '(not set)'} "
        f"| CHAT={TELEGRAM_CHAT_ID or '(not set)'}"
    )
    if not TELEGRAM_GROUP_CHAT_ID:
        logger.error(
            "TELEGRAM_GROUP_CHAT_ID is EMPTY in this environment -> posts will "
            "fall back to ADMIN/CHAT chat, not the group. Update the GitHub "
            "secret TELEGRAM_GROUP_CHAT_ID."
        )


async def run(dry_run: bool = False):
    """Execute the full pipeline."""
    logger.info("=" * 50)
    logger.info("Amway Telegram Bot — starting pipeline")
    logger.info("=" * 50)

    storage = Storage(PUBLISHED_JSON)
    attempts = AttemptStorage(ATTEMPTED_JSON)
    logger.info(f"Published articles in DB: {storage.count()}")
    logger.info(f"Attempted (failed, in cooldown) candidates: {attempts.count()}")

    # ── Telegram target diagnostics ─────────────────────────────────────
    _log_telegram_targets()

    # ── Step 1: Scrape ────────────────────────────────────────────────
    logger.info("\n[Step 1/6] Scraping amway.ua...")
    articles = await scrape_amway(
        sections=SCRAPE_SECTIONS,
        base_url=SCRAPE_BASE_URL,
        delay=SCRAPE_DELAY_SECONDS,
        max_articles=CANDIDATE_POOL_SIZE * 2,  # Extra to survive filtering
    )
    logger.info(f"Scraped {len(articles)} articles")

    new_articles = [
        a
        for a in articles
        if not storage.is_published(a.url) and not attempts.is_attempted(a.url)
    ]
    logger.info(f"New articles after filtering: {len(new_articles)}")

    if not new_articles:
        logger.error(
            "No fresh candidates after filtering published + failed(cooldown) "
            "articles. Skipping run (no posts published)."
        )
        sys.exit(2)

    # Iterate over a POOL of candidates. We stop on the first that fully
    # succeeds (goal: MAX_ARTICLES_PER_RUN=1 post per day) instead of
    # aborting on the first failure. Failed candidates are recorded so next
    # run starts from the next article and not the same broken one.
    selected = new_articles[:CANDIDATE_POOL_SIZE]

    logger.info(f"Selected {len(selected)} items for processing (pool={CANDIDATE_POOL_SIZE})")

    published_count = 0
    failures: list[str] = []

    for i, article in enumerate(selected, 1):
        logger.info(f"\n{'─' * 40}")
        logger.info(f"Processing article {i}/{len(selected)}: {article.title}")
        logger.info(f"Product line: {article.product_line}")
        logger.info(f"URL: {article.url}")

        image_path = None
        try:
            # ── Step 3: Book Enrichment (30% chance) ─────────────────────
            book_context = None
            if random.random() < BOOK_ENRICHMENT_PROBABILITY:
                logger.info("[Step 3/6] Adding book enrichment...")
                book_context = get_book_enrichment()
            else:
                logger.info("[Step 3/6] Skipping book enrichment (random)")

            # ── Step 4: Media Selection ──────────────────────────────────
            logger.info("[Step 4/6] Selecting topic-matched product image...")
            try:
                image_path = await download_first_image(
                    article.images,
                    article.product_line,
                    title=article.title,
                )
            except Exception as e:
                logger.error(f"Image download failed: {e}. Skipping article.")
                if not dry_run:
                    attempts.mark_attempted(article.url, reason=f"image_download: {e}")
                failures.append(f"{article.title} — image_download: {e}")
                continue
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
                if not dry_run:
                    attempts.mark_attempted(article.url, reason=f"rewrite: {e}")
                failures.append(f"{article.title} — rewrite: {e}")
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
                        "Gemini rejected the post (image/text mismatch). "
                        "Marking candidate failed; trying the next one."
                    )
                    if not dry_run:
                        attempts.mark_attempted(
                            article.url, reason="gemini_vision_mismatch"
                        )
                    failures.append(f"{article.title} — gemini_vision_mismatch")
                    continue
                logger.info("Gemini approved the post (image + text match).")

            # ── Step 6: Publish ──────────────────────────────────────────
            if dry_run:
                logger.info("[Step 6/6] DRY RUN — skipping Telegram publish")
                message_id = "dry-run"
            else:
                needs_preview = (
                    TELEGRAM_ADMIN_CHAT_ID and TELEGRAM_GROUP_CHAT_ID != TELEGRAM_ADMIN_CHAT_ID
                )
                if needs_preview:
                    logger.info("[Step 6/6] Sending preview to executor (admin chat)...")
                    await publish_post(
                        text=post_text,
                        image_path=image_path,
                        use_html=False,  # Plain text — emojis don't need HTML
                        chat_id=TELEGRAM_ADMIN_CHAT_ID,
                    )
                logger.info("[Step 6/6] Publishing to Telegram group...")
                try:
                    message_id = await publish_post(
                        text=post_text,
                        image_path=image_path,
                        use_html=False,  # Plain text — emojis don't need HTML
                    )
                except Exception as e:
                    logger.error(f"Publish failed: {e}. Skipping article.")
                    if not dry_run:
                        attempts.mark_attempted(article.url, reason=f"publish: {e}")
                    failures.append(f"{article.title} — publish: {e}")
                    continue
                if not message_id:
                    logger.error("Failed to publish. Skipping.")
                    if not dry_run:
                        attempts.mark_attempted(article.url, reason="publish_empty")
                    failures.append(f"{article.title} — publish returned no message_id")
                    continue

            # ── Step 7: Save ─────────────────────────────────────────────
            # Only persist real publications. Dry-run must NOT mutate state
            # (otherwise a rehearsal run destroys the candidate queue).
            if not dry_run:
                storage.mark_published(
                    url=article.url,
                    title=article.title,
                    telegram_message_id=message_id or "",
                )
            published_count += 1
            logger.info(
                f"Marked as published (dry_run={dry_run}). Message ID: {message_id}"
            )
            logger.info(
                f"Day's goal reached ({MAX_ARTICLES_PER_RUN} post). Stopping loop."
            )
            break
        finally:
            cleanup_temp_media(image_path)

    logger.info(f"\n{'=' * 50}")
    logger.info(f"Pipeline complete. Published {published_count}/{len(selected)} posts.")
    logger.info(f"Total in DB: {storage.count()}")

    if published_count == 0:
        logger.error("No posts were published this run. Exiting with non-zero code.")
        if failures:
            logger.error("Reasons (per attempted candidate):")
            for reason in failures:
                logger.error(f"  - {reason}")
        sys.exit(4)


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
