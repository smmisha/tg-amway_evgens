"""Book-based post enrichment — ported from threads/generate_book_post.js.

Selects a random book from the knowledge bundle (40 books on psychology
and marketing) and creates context for the LLM to enrich Amway posts
with psychological/marketing insights.
"""

import json
import logging
import os
import random

from config.settings import BOOKS_BUNDLE_JSON

logger = logging.getLogger(__name__)

HOOK_TYPES = ["contrarian", "conflict_debate", "micro_case", "actionable_script"]


def load_books_bundle() -> dict:
    """Load the books knowledge bundle."""
    if not os.path.exists(BOOKS_BUNDLE_JSON):
        logger.warning(f"Books bundle not found: {BOOKS_BUNDLE_JSON}")
        return {"books": []}

    with open(BOOKS_BUNDLE_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def select_book_and_hook(
    bundle: dict,
    mechanism: str | None = None,
) -> tuple[dict, str] | None:
    """Select a random book and hook type.

    Args:
        bundle: Books knowledge bundle
        mechanism: Optional mechanism tag to filter books

    Returns:
        Tuple of (book, hook_type) or None if no books available
    """
    books = bundle.get("books", [])
    if not books:
        return None

    if mechanism:
        target = mechanism.lower().replace("#", "")
        books = [b for b in books if any(target in m.lower() for m in b.get("mechanisms", []))]
        if not books:
            logger.warning(f"No books with mechanism '{mechanism}', using all books")
            books = bundle["books"]

    selected_book = random.choice(books)
    selected_hook = random.choice(HOOK_TYPES)

    return selected_book, selected_hook


def build_book_context(book: dict, hook_type: str) -> str:
    """Build the book enrichment context string for the LLM prompt.

    This is included in the user prompt alongside the article text.
    """
    hooks = book.get("threads_hooks", {})
    hook_template = hooks.get(hook_type, hooks.get("contrarian", ""))

    cases = book.get("key_experiments_and_cases", [])
    cases_summary = "\n".join(
        f"- {c['title']}: {c['summary']} (Вывод: {c.get('takeaway_for_threads', '')})"
        for c in cases
    )

    return f"""
ОБОГАЩЕНИЕ ЧЕРЕЗ КНИГУ:
КНИГА: "{book['title_ru']}" ({book['author']})
СУТЬ: {book['core_concept']}
МЕХАНИЗМЫ: {', '.join(book.get('mechanisms', []))}

КЕЙСЫ И ЭКСПЕРИМЕНТЫ:
{cases_summary}

ОПОРНЫЙ ХУК:
"{hook_template}"

Используй концепцию из этой книги как психологическую «оболочку» для поста о продукте Amway.
Не пересказывай книгу — сфокусируйся на 1 сильной мысли, которая объясняет ценность продукта.
""".strip()


def get_book_enrichment() -> str | None:
    """Get a random book enrichment context, or None."""
    bundle = load_books_bundle()
    result = select_book_and_hook(bundle)
    if result is None:
        return None

    book, hook_type = result
    logger.info(f"Book enrichment: \"{book['title_ru']}\" [{hook_type}]")
    return build_book_context(book, hook_type)
