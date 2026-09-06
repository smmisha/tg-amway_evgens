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
    assert prep.count() == 0

    prep_bak_path = os.path.join(ROOT, "data", "prepared_posts.json.bak")
    prep_bak = PreparedStorage(prep_bak_path)
    assert prep_bak.count() == 4


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

