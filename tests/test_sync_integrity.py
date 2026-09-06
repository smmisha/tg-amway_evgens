import json
import os
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_env_exists():
    env_path = os.path.join(ROOT, ".env")
    assert os.path.exists(env_path), ".env must exist in Projectorium"
    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "TELEGRAM_BOT_TOKEN" in content
    assert "TELEGRAM_GROUP_CHAT_ID" in content


def test_data_files_exist():
    data_dir = os.path.join(ROOT, "data")
    required = [
        "published.json",
        "attempted.json",
        "prepared_posts.json",
        "prepared_posts.json.bak",
        "products_catalog.json",
        "books_bundle.json",
    ]
    for req in required:
        p = os.path.join(data_dir, req)
        assert os.path.exists(p), f"Missing {req}"


def test_published_data_integrity():
    p = os.path.join(ROOT, "data", "published.json")
    with open(p, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert len(data) >= 37
    # Check that required keys exist in each entry
    for entry in data:
        assert "hash" in entry
        assert "url" in entry
        assert "telegram_message_id" in entry
        assert "published_at" in entry


def test_catalog_and_media_exist():
    catalog_path = os.path.join(ROOT, "data", "products_catalog.json")
    with open(catalog_path, "r", encoding="utf-8-sig") as f:
        catalog = json.load(f)
    assert len(catalog) >= 17
    for item in catalog:
        local_img = item.get("local_image")
        if local_img:
            full_path = os.path.join(ROOT, local_img)
            assert os.path.exists(full_path), f"Missing media for catalog item {item.get('name')}: {local_img}"


def test_fallback_media_exist():
    from src.media import FALLBACK_PRODUCT_IMAGES
    for category, paths in FALLBACK_PRODUCT_IMAGES.items():
        for path in paths:
            if path.startswith("data/"):
                full_path = os.path.join(ROOT, path)
                assert os.path.exists(full_path), f"Missing fallback media: {path}"


def test_storage_classes():
    from src.storage import Storage, AttemptStorage, PreparedStorage
    
    pub_path = os.path.join(ROOT, "data", "published.json")
    storage = Storage(pub_path)
    assert storage.count() >= 37

    att_path = os.path.join(ROOT, "data", "attempted.json")
    att = AttemptStorage(att_path)
    assert len(att._data) >= 12

    prep_path = os.path.join(ROOT, "data", "prepared_posts.json")
    prep = PreparedStorage(prep_path)
    assert isinstance(prep._data, list)

    prep_bak_path = os.path.join(ROOT, "data", "prepared_posts.json.bak")
    prep_bak = PreparedStorage(prep_bak_path)
    assert isinstance(prep_bak._data, list)


def test_storage_cooldown_and_last_published():
    import tempfile
    from datetime import datetime, timedelta, timezone
    from src.storage import Storage

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test_pub.json")
        s = Storage(test_file)

        now = datetime.now(timezone.utc)
        url_old = "https://example.com/old"
        url_recent = "https://example.com/recent"
        url_fresh = "https://example.com/fresh"

        # Record old publication (20 days ago)
        old_time = (now - timedelta(days=20)).isoformat()
        s._data.append({
            "hash": Storage._hash_url(url_old),
            "url": url_old,
            "title": "Old Post",
            "published_at": old_time,
        })

        # Record recent publication (3 days ago)
        recent_time = (now - timedelta(days=3)).isoformat()
        s._data.append({
            "hash": Storage._hash_url(url_recent),
            "url": url_recent,
            "title": "Recent Post",
            "published_at": recent_time,
        })
        s._save()

        # Check is_published without cooldown (all recorded are True, fresh is False)
        assert s.is_published(url_old) is True
        assert s.is_published(url_recent) is True
        assert s.is_published(url_fresh) is False

        # Check with 14-day cooldown:
        # url_old was 20 days ago -> cooldown elapsed -> is_published returns False (eligible for recycling)
        assert s.is_published(url_old, cooldown_days=14) is False
        # url_recent was 3 days ago -> cooldown active -> is_published returns True
        assert s.is_published(url_recent, cooldown_days=14) is True

        # Check get_last_published_at
        last_old = s.get_last_published_at(url_old)
        assert last_old is not None
        assert abs((last_old - (now - timedelta(days=20))).total_seconds()) < 60
        assert s.get_last_published_at(url_fresh) is None

        # Check multi-entry resilience: article published 20 days ago, but also has an older legacy entry without published_at
        url_multi = "https://example.com/multi"
        s._data.append({
            "hash": Storage._hash_url(url_multi),
            "url": url_multi,
            "title": "Ancient publication with no timestamp",
        })
        s._data.append({
            "hash": Storage._hash_url(url_multi),
            "url": url_multi,
            "title": "Recent publication 20 days ago",
            "published_at": (now - timedelta(days=20)).isoformat(),
        })
        s._save()
        # Most recent publication was 20 days ago (> 14 days) -> must be eligible for recycling (False)
        assert s.is_published(url_multi, cooldown_days=14) is False


def test_select_candidates_logic():
    import tempfile
    from datetime import datetime, timedelta, timezone
    from src.main import select_candidates
    from src.scraper import Article
    from src.storage import Storage, AttemptStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        pub_file = os.path.join(tmpdir, "pub.json")
        att_file = os.path.join(tmpdir, "att.json")
        storage = Storage(pub_file)
        attempts = AttemptStorage(att_file)

        now = datetime.now(timezone.utc)
        a_fresh = Article(url="https://example.com/fresh", title="Fresh Product", body="", images=["data/media/post_8_dd22cf0c.jpg"], product_line="Nutrilite")
        a_old = Article(url="https://example.com/old", title="Old Product", body="", images=["data/media/post_9_e3fbab59.jpg"], product_line="Nutrilite")
        a_recent = Article(url="https://example.com/recent", title="Recent Product", body="", images=["data/media/post_10_050b9f4d.jpg"], product_line="Nutrilite")
        a_failed = Article(url="https://example.com/failed", title="Failed Product", body="", images=[], product_line="Nutrilite")

        # Mark old (25 days ago) and recent (2 days ago)
        storage._data.append({"hash": Storage._hash_url(a_old.url), "url": a_old.url, "published_at": (now - timedelta(days=25)).isoformat()})
        storage._data.append({"hash": Storage._hash_url(a_recent.url), "url": a_recent.url, "published_at": (now - timedelta(days=2)).isoformat()})
        storage._save()

        # Mark failed candidate in attempts
        attempts.mark_attempted(a_failed.url, reason="test_error")

        # Scenario 1: Fresh candidate exists -> pool_size=1 picks only fresh
        pool1 = select_candidates([a_fresh, a_old, a_recent, a_failed], storage, attempts, pool_size=1)
        assert len(pool1) == 1
        assert pool1[0].url == a_fresh.url

        # Scenario 2: Fresh candidate exists and pool_size=4 -> picks fresh first, then supplements with eligible evergreen (a_old)
        # a_recent is skipped (< 14 days), a_failed is skipped (attempted)
        pool2 = select_candidates([a_fresh, a_old, a_recent, a_failed], storage, attempts, pool_size=4)
        assert len(pool2) == 2
        assert pool2[0].url == a_fresh.url
        assert pool2[1].url == a_old.url

        # Scenario 3: No fresh candidates -> must recycle eligible old candidate (published > 14 days ago)
        pool3 = select_candidates([a_old, a_recent, a_failed], storage, attempts, pool_size=4)
        assert len(pool3) == 1
        assert pool3[0].url == a_old.url

        # Scenario 4: Only recent and failed candidates -> returns empty list
        pool4 = select_candidates([a_recent, a_failed], storage, attempts, pool_size=4)
        assert len(pool4) == 0


def test_storage_handles_bom():
    import tempfile
    from src.storage import Storage, AttemptStorage, PreparedStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test_bom.json")
        url = "https://example.com"
        u_hash = Storage._hash_url(url)
        with open(test_file, "wb") as f:
            f.write(f'\ufeff[{{"hash": "{u_hash}", "url": "{url}"}}]'.encode("utf-8"))

        s = Storage(test_file)
        assert s.count() == 1
        assert s.is_published(url)

        att_file = os.path.join(tmpdir, "test_att_bom.json")
        with open(att_file, "wb") as f:
            f.write(b'\xef\xbb\xbf[{"hash": "abc", "url": "https://example.com", "attempted_at": "2026-09-06T00:00:00+00:00"}]')
        att = AttemptStorage(att_file)
        assert att.count() == 1

        prep_file = os.path.join(tmpdir, "test_prep_bom.json")
        with open(prep_file, "wb") as f:
            f.write(b'\xef\xbb\xbf[{"url": "https://example.com", "title": "Test"}]')
        prep = PreparedStorage(prep_file)
        assert prep.count() == 1


def test_catalog_fallback_no_truncation():
    catalog_path = os.path.join(ROOT, "data", "products_catalog.json")
    with open(catalog_path, "r", encoding="utf-8-sig") as f:
        catalog_data = json.load(f)
    assert len(catalog_data) >= 17

    from src.scraper import Article, detect_product_line
    articles = []
    scraped_urls = set()
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
    assert len(articles) == len(catalog_data)
    assert len(articles) >= 17


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_publish_prepared_queue_rollback(monkeypatch):
    import tempfile
    from src.storage import PreparedStorage
    import config.settings as settings
    import src.main as main_mod

    with tempfile.TemporaryDirectory() as tmpdir:
        prep_file = os.path.join(tmpdir, "prep.json")
        pub_file = os.path.join(tmpdir, "pub.json")
        att_file = os.path.join(tmpdir, "att.json")

        prep = PreparedStorage(prep_file)
        prep.add_prepared({"url": "https://example.com/item1", "title": "Item 1", "text": "Hello"})
        assert prep.count() == 1

        monkeypatch.setattr(settings, "PREPARED_POSTS_JSON", prep_file)
        monkeypatch.setattr(settings, "PUBLISHED_JSON", pub_file)
        monkeypatch.setattr(settings, "ATTEMPTED_JSON", att_file)
        monkeypatch.setattr(settings, "TELEGRAM_GROUP_CHAT_ID", "-10012345")
        monkeypatch.setattr(main_mod, "PUBLISHED_JSON", pub_file)
        monkeypatch.setattr(main_mod, "ATTEMPTED_JSON", att_file)

        # Mock publish_post to simulate network failure
        async def mock_fail_publish(*args, **kwargs):
            raise ConnectionError("Telegram API unreachable")

        async def mock_download_img(*args, **kwargs):
            return None

        monkeypatch.setattr(main_mod, "publish_post", mock_fail_publish)
        monkeypatch.setattr(main_mod, "download_first_image", mock_download_img)

        with pytest.raises(ConnectionError):
            await main_mod.run_publish_prepared(dry_run=False)

        # Verify that the draft was rolled back into the queue and not dropped
        reloaded_prep = PreparedStorage(prep_file)
        assert reloaded_prep.count() == 1
        assert reloaded_prep._data[0]["url"] == "https://example.com/item1"


