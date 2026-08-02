# 🤖 Amway Telegram Bot — Content Rewriter & Publisher

Автоматический бот, который парсит статьи и продукты с [amway.ua](https://www.amway.ua),
перефразирует их через LLM в стиле бренд-амбассадора, и публикует в Telegram-группу.

## Возможности

- 🕷️ **Парсинг** amway.ua через Playwright (headless Chromium)
- 🧠 **Перефразирование** через Groq (Llama 3.3 70B) с Gemini fallback
- 📚 **Обогащение** постов через базу из 40 книг по психологии и маркетингу
- 🤖 **Хуманизация** — система Anti-AI для проверки качества генерации
- 📸 **Изображения** — автоматическое скачивание и прикрепление
- 📢 **Публикация** в Telegram-группу
- ⏰ **Автоматизация** через GitHub Actions (каждые 6 часов)

## Быстрый старт

### 1. Клонирование

```bash
git clone https://github.com/your-username/Coworker.git
cd Coworker
```

### 2. Установка зависимостей

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Настройка

Скопируйте `.env.example` в `.env` и заполните:

```bash
cp .env.example .env
```

| Переменная | Описание |
|-----------|----------|
| `TELEGRAM_BOT_TOKEN` | Токен бота от @BotFather |
| `TELEGRAM_CHAT_ID` | ID группы (начинается с `-100`) |
| `GROQ_API_KEY` | API ключ Groq (бесплатно на console.groq.com) |
| `GEMINI_API_KEY` | API ключ Gemini (бесплатно на aistudio.google.com) |

### 4. Запуск

```bash
# Полный запуск
python -m src.main

# Тестовый запуск (без публикации в Telegram)
python -m src.main --dry-run
```

## GitHub Actions

1. Зайдите в Settings → Secrets → Actions в вашем GitHub-репозитории
2. Добавьте секреты: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GROQ_API_KEY`, `GEMINI_API_KEY`
3. Бот будет запускаться автоматически каждые 6 часов
4. Ручной запуск: Actions → "Amway Bot — Publish Posts" → Run workflow

## Архитектура

```
src/
├── main.py          — Оркестратор (точка входа)
├── scraper.py       — Парсер amway.ua (Playwright)
├── rewriter.py      — LLM перефразирование (Groq → Gemini)
├── humanizer.py     — Anti-AI валидация (из voice.js)
├── book_enricher.py — Обогащение через книги
├── publisher.py     — Telegram publisher
├── media.py         — Скачивание изображений
└── storage.py       — Трекинг опубликованных
```

## Пайплайн

```
Scrape → Filter → Enrich (30%) → Rewrite → Media → Publish → Save
```

## Книжная база

40 книг-бестселлеров (20 психология + 20 маркетинг):
Канеман, Чалдини, Ариели, Талер, Клир, Грин, Сторр, Хайдт, Эяль,
Райс/Траут, Годин, Бергер, Шоттон, Шварц, Хормози и другие.

Концепции из книг используются как психологическая «оболочка» для постов
о продуктах Amway (30% постов обогащены книжным контекстом).

## TOV (Tone of Voice)

- **Стиль**: промо/бренд-амбассадор (MLM Amway)
- **Хук**: вопрос-триггер "Знаете ли вы, что..."
- **Эмодзи**: после каждой смысловой фразы
- **Тон**: гипертрофированный с усилителями
- **CTA**: 60% постов с призывом к действию
- **Язык**: русский

## Лицензия

MIT
