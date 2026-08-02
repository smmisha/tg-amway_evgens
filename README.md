# 🤖 Amway Telegram Bot — Content Rewriter & Publisher

Автоматический бот, который парсит статьи и продукты с [amway.ua](https://www.amway.ua),
перефразирует их через LLM в стиле бренд-амбассадора, и публикует в Telegram.

## Возможности

- 🕷️ **Парсинг** amway.ua через Playwright (headless Chromium)
- 🧠 **Перефразирование** через Gemini (primary) с Groq fallback
- 👁️ **Визуальная проверка** — Gemini «глазами» сверяет текст поста и картинку до публикации
- 📚 **Обогащение** постов через базу из 40 книг по психологии и маркетингу
- 🤖 **Хуманизация** — система Anti-AI для проверки качества генерации
- 📸 **Изображения** — автоматическое скачивание, проверка и прикрепление
- 📢 **Публикация** в Telegram (группа или личный чат после /start)
- ⏰ **Автоматизация** через GitHub Actions (ежедневно в 20:00 Киев)

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
| `TELEGRAM_CHAT_ID` | ID чата для публикации (группа с `-100` или личный chat_id) |
| `LLM_PROVIDER` | `gemini` (default) или `groq` |
| `GEMINI_API_KEY` | API ключ Gemini (бесплатно на aistudio.google.com) |
| `GROQ_API_KEY` | API ключ Groq (fallback, бесплатно на console.groq.com) |

### 4. Запуск

```bash
# Полный запуск
python -m src.main

# Тестовый запуск (без публикации в Telegram)
python -m src.main --dry-run
```

## GitHub Actions

1. Зайдите в Settings → Secrets → Actions в вашем GitHub-репозитории
2. Добавьте секреты: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`, `GROQ_API_KEY`
3. `publish.yml` — публикация постов ежедневно в 20:00 Киев (`0 17 * * *` UTC)
4. `responder.yml` — отвечает на команды (`/start` и т.д.) каждые 5 минут
5. Ручной запуск: Actions → "Amway Bot — Publish Posts" → Run workflow

## Архитектура

```
src/
├── main.py            — Оркестратор (точка входа)
├── scraper.py         — Парсер amway.ua (Playwright)
├── rewriter.py        — LLM перефразирование (Gemini → Groq)
├── humanizer.py       — Anti-AI валидация (из voice.js)
├── book_enricher.py   — Обогащение через книги
├── publisher.py       — Telegram publisher
├── media.py           — Скачивание изображений
├── media_validator.py — Gemini Vision: проверка картинки + текста поста
├── bot_listener.py    — Long-polling обработчик команд бота
├── responder.py       — Ответы на /start через getUpdates (для GitHub Actions)
└── storage.py         — Трекинг опубликованных
```

## Пайплайн

```
Scrape → Filter → Enrich (30%) → Rewrite → Media → Gemini Vision (текст+картинка) → Publish → Save
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
