"""CTA templates from the client brief."""

import random

CTA_TEMPLATES = [
    'Пишите в комментариях или напрямую @evgen_blago, чтобы заказать со скидкой! 💬',
    'Для заказа или быстрой консультации пишите @evgen_blago 📩',
    'Заказывайте на сайте → {url} или напишите @evgen_blago для оформления 🛒',
    'Пишите @evgen_blago слово "{keyword}" — помогу подобрать и сделаю отличные условия 👇',
    'Кто хочет попробовать {product}? Напишите @evgen_blago — подберем лучшее решение 📲',
]

# Keywords for CTA templates that require them
CTA_KEYWORDS = {
    'XS': ['ЭНЕРГИЯ', 'XS', 'ЗАРЯД'],
    'Nutrilite': ['ВИТАМИНЫ', 'ЗДОРОВЬЕ', 'NUTRILITE'],
    'Artistry': ['УХОД', 'КРАСОТА', 'ARTISTRY'],
    'Home Care': ['ДОМ', 'ЧИСТОТА', 'HOME'],
    'default': ['ХОЧУ', 'ПОДРОБНОСТИ', 'ИНТЕРЕСНО'],
}


def get_cta(product_line: str = 'default', article_url: str = 'https://www.amway.ua') -> str:
    """Return a random CTA template with placeholders filled."""
    template = random.choice(CTA_TEMPLATES)
    keywords = CTA_KEYWORDS.get(product_line, CTA_KEYWORDS['default'])
    keyword = random.choice(keywords)
    return template.format(
        keyword=keyword,
        product=product_line if product_line != 'default' else 'этот продукт',
        url=article_url,
    )


def get_cta_instruction(include_cta: bool, product_line: str = 'default', article_url: str = 'https://www.amway.ua') -> str:
    """Return CTA instruction for the system prompt."""
    if include_cta:
        cta = get_cta(product_line, article_url)
        return f'Заверши пост этим CTA: «{cta}»'
    return f'Заверши пост ссылкой на продукт для покупки: {article_url}'
