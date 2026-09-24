"""Unit tests for src/scraper.py (Scrapling & S3 Sitemap engine)."""

import os
from unittest.mock import patch, MagicMock
import pytest
from src.scraper import (
    Article,
    detect_product_line,
    _clean_image_url,
    _scrape_product_page,
    scrape_amway,
)


def test_article_dataclass_initialization():
    art = Article(
        url="https://www.amway.ua/product-name/p/123456",
        title="Test Product",
        body="Product description here",
        images=["https://example.com/image.jpg"],
    )
    assert art.sku == "123456"
    assert art.scraped_at != ""
    assert art.category == ""


def test_detect_product_line():
    assert detect_product_line("XS Power Drink Оранж") == "XS"
    assert detect_product_line("Новий енергетик від бренду") == "XS"
    assert detect_product_line("Nutrilite Омега-3 комплекс") == "Nutrilite"
    assert detect_product_line("Дієтична добавка вітамін C") == "Nutrilite"
    assert detect_product_line("Artistry Skin Nutrition крем") == "Artistry"
    assert detect_product_line("Сироватка для обличчя відновлювальна") == "Artistry"
    assert detect_product_line("Dish Drops концентрована рідина для миття посуду") == "Home Care"
    assert detect_product_line("Amway Home SA8 порошок для прання") == "Home Care"
    assert detect_product_line("Glister концентрована зубна паста") == "Personal Care"
    assert detect_product_line("Шампунь для волосся") == "Personal Care"
    assert detect_product_line("Невідомий товар без категорії") == "default"


def test_clean_image_url():
    broken = "https://media.amway.uahttps://amstack-eu-prod01.s3.amazonaws.com/img.jpg"
    assert _clean_image_url(broken) == "https://amstack-eu-prod01.s3.amazonaws.com/img.jpg"

    normal = "https://amstack-eu-prod01.s3.amazonaws.com/img.jpg"
    assert _clean_image_url(normal) == normal

    empty = ""
    assert _clean_image_url(empty) == ""


def test_scrape_product_page_parsing():
    html_content = """<!DOCTYPE html>
    <html>
    <head>
        <title>Artistry Skin Nutrition Крем — купити в інтернет-магазині Amway</title>
        <meta property="og:image" content="https://example.com/artistry.jpg" />
        <meta name="description" content="Зволожувальний крем для обличчя Artistry." />
    </head>
    <body>
        <p>Додатковий опис товару для перевірки парсингу тексту.</p>
    </body>
    </html>"""

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = html_content.encode("utf-8")
    mock_resp.text = html_content

    with patch("curl_cffi.requests.get", return_value=mock_resp):
        art = _scrape_product_page("https://www.amway.ua/skin-nutrition-cream/p/998877")
        assert art is not None
        assert art.sku == "998877"
        assert "Artistry Skin Nutrition Крем" in art.title
        assert "Amway" not in art.title
        assert art.product_line == "Artistry"
        assert len(art.images) == 1
        assert art.images[0] == "https://example.com/artistry.jpg"


def test_scrape_amway_fallback_on_network_error():
    import asyncio
    # When live sitemap returns empty, scrape_amway must fall back to products_catalog.json
    with patch("src.scraper._fetch_sitemap_product_urls", return_value=[]):
        articles = asyncio.run(scrape_amway(max_articles=3))
        assert len(articles) > 0
        assert all(isinstance(a, Article) for a in articles)
        assert any(a.category == "catalog" or a.product_line != "" for a in articles)
