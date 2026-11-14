"""Offline tests for the fail-closed vision gate in src/main.py (TG-F-06).

Every network / LLM / Telegram call is monkeypatched, so nothing leaves the
process. The pipeline must publish the generated text WITHOUT media whenever the
vision gate rejects the image or cannot verify it.
"""

import asyncio
import json

import pytest

pytest.importorskip(
    "scrapling", reason="src.main imports src.scraper, which requires scrapling"
)

import src.main as main_mod
from src.scraper import Article


POST_TEXT = "Текст поста про Nutrilite Омега-3. #Amway"


@pytest.fixture
def env(monkeypatch, tmp_path):
    article = Article(
        url="https://www.amway.ua/nutrilite-omega-3/p/123456",
        title="Nutrilite Омега-3",
        body="Описание продукта",
        images=["https://media.amway.ua/omega.jpg"],
        product_line="Nutrilite",
    )
    # Persistent (non temp-dir) file: cleanup_temp_media() must leave it alone.
    media_path = tmp_path / "omega.jpg"
    media_path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    paths = {
        "published": str(tmp_path / "published.json"),
        "attempted": str(tmp_path / "attempted.json"),
        "prepared": str(tmp_path / "prepared_posts.json"),
    }
    publish_calls = []

    async def fake_scrape(*args, **kwargs):
        return [article]

    async def fake_download(*args, **kwargs):
        return str(media_path)

    async def fake_rewrite(*args, **kwargs):
        return POST_TEXT

    async def fake_publish(*args, **kwargs):
        publish_calls.append(dict(kwargs))
        return "4242"

    monkeypatch.setattr(main_mod, "PUBLISHED_JSON", paths["published"])
    monkeypatch.setattr(main_mod, "ATTEMPTED_JSON", paths["attempted"])
    monkeypatch.setattr(main_mod, "TELEGRAM_GROUP_CHAT_ID", "-100123456")
    monkeypatch.setattr(main_mod, "TELEGRAM_ADMIN_CHAT_ID", "")
    monkeypatch.setattr(main_mod, "scrape_amway", fake_scrape)
    monkeypatch.setattr(main_mod, "select_candidates", lambda *a, **k: [article])
    monkeypatch.setattr(main_mod, "download_first_image", fake_download)
    monkeypatch.setattr(main_mod, "rewrite_article", fake_rewrite)
    monkeypatch.setattr(main_mod, "publish_post", fake_publish)
    # Skip the random "book enrichment" step (it would read data/books_bundle.json).
    monkeypatch.setattr(main_mod.random, "random", lambda: 1.0)

    return {
        "article": article,
        "media_path": str(media_path),
        "published_json": paths["published"],
        "attempted_json": paths["attempted"],
        "prepared_json": paths["prepared"],
        "publish_calls": publish_calls,
    }


def _run_pipeline(env, monkeypatch, validator):
    monkeypatch.setattr(main_mod, "validate_image_with_gemini_vision", validator)
    asyncio.run(main_mod.run(dry_run=False))


def test_vision_rejection_publishes_text_only(env, monkeypatch):
    async def reject(**kwargs):
        return False

    _run_pipeline(env, monkeypatch, reject)

    assert len(env["publish_calls"]) == 1
    call = env["publish_calls"][0]
    assert call["image_path"] is None
    assert call["text"] == POST_TEXT

    with open(env["published_json"], encoding="utf-8") as f:
        published = json.load(f)
    assert len(published) == 1
    assert published[0]["url"] == env["article"].url


def test_vision_exception_publishes_text_only(env, monkeypatch):
    async def crash(**kwargs):
        raise RuntimeError("Gemini API crashed")

    _run_pipeline(env, monkeypatch, crash)

    assert len(env["publish_calls"]) == 1
    assert env["publish_calls"][0]["image_path"] is None


def test_vision_approval_publishes_with_image(env, monkeypatch):
    async def approve(**kwargs):
        return True

    _run_pipeline(env, monkeypatch, approve)

    assert len(env["publish_calls"]) == 1
    assert env["publish_calls"][0]["image_path"] == env["media_path"]


def test_prepare_draft_is_text_only_when_vision_fails(env, monkeypatch):
    async def reject(**kwargs):
        return False

    monkeypatch.setattr(main_mod, "validate_image_with_gemini_vision", reject)
    attempts = main_mod.AttemptStorage(env["attempted_json"])

    draft = asyncio.run(main_mod.prepare_article_draft(env["article"], attempts))

    assert draft is not None
    assert draft["no_media"] is True
    assert draft["image_path"] is None
    assert draft["image_url"] == ""
    assert draft["text"] == POST_TEXT
    # The candidate is usable (text-only), so it must not be parked in cooldown.
    assert attempts.count() == 0


def test_publish_prepared_does_not_reattach_media(env, monkeypatch):
    import config.settings as settings
    from src.storage import PreparedStorage

    prepared = PreparedStorage(env["prepared_json"])
    prepared.add_prepared(
        {
            "url": env["article"].url,
            "title": env["article"].title,
            "text": POST_TEXT,
            "image_url": "",
            "no_media": True,
        }
    )
    monkeypatch.setattr(settings, "PREPARED_POSTS_JSON", env["prepared_json"])
    monkeypatch.setattr(settings, "TELEGRAM_GROUP_CHAT_ID", "-100123456")

    async def must_not_download(*args, **kwargs):
        raise AssertionError("a text-only draft must not resolve media again")

    monkeypatch.setattr(main_mod, "download_first_image", must_not_download)

    asyncio.run(main_mod.run_publish_prepared(dry_run=False))

    assert len(env["publish_calls"]) == 1
    assert env["publish_calls"][0]["image_path"] is None
    assert env["publish_calls"][0]["text"] == POST_TEXT
