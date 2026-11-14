"""Безопасная настройка логирования: секреты/метадата не попадают в логи.

TG-F-09 — секреты (токены/API-ключи); TG-F-13 — идентификаторы чатов/юзеров.

Дизайн Bot API и Gemini API кладёт секреты в URL: Telegram — токен в пути
(``https://api.telegram.org/bot<token>/sendMessage``), Gemini — API-ключ в
query-string (``...:generateContent?key=<key>``). httpx на уровне INFO пишет
каждую HTTP-строку вместе с полным URL, а текст ``httpx.HTTPStatusError``
содержит тот же URL — значит, любой warning/error с ``{e}`` тоже утекает.

Модуль закрывает это централизованно, без новых зависимостей:

1. ``harden_http_loggers()`` переводит ``httpx``/``httpcore`` (и их уже
   созданные дочерние логгеры) в ``WARNING`` — INFO-строки с URL не пишутся.
2. ``install_secret_filter()`` ставит на все корневые обработчики два фильтра:
   ``DropTransportInfoFilter`` (не пропускает INFO-записи httpx/httpcore даже
   при собственном уровне дочернего логгера) и ``SecretRedactionFilter``,
   который вырезает ``bot<token>``, «голые» токены формата ``<id>:<secret>`` и
   значения ``key=``/``token=``/``secret=`` из любого сообщения.
   Это defense-in-depth для WARNING/ERROR и для наших собственных f-строк.
3. ``mask_identifier()`` — утилита для TG-F-13: ``chat_id``/``user_id``
   пользователей не попадают в логи в открытом виде. В сообщении остаются
   только последние три цифры (``***890``): этого хватает, чтобы
   сопоставлять записи между запусками, но сам идентификатор не утекает.

Секреты по-прежнему остаются в URL (так устроены API) — меняется только то,
что попадает в логи. Вызывать ``configure_safe_logging()`` нужно в каждой
точке входа, где настраивается logging (``src/main.py``, ``src/responder.py``,
``src/bot_listener.py``, ``src/diag_*.py``).
"""

import logging
import re

# SECURITY: токен бота в пути URL: https://api.telegram.org/bot<id>:<secret>/...
# secret-часть — 35 символов [A-Za-z0-9_-]; берём с запасом от 10.
_BOT_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]{10,}", re.IGNORECASE)

# SECURITY: «голый» токен без префикса bot (например, из repr/исключения):
# <id>:<secret>. Форма специфична для Bot API, поэтому ложных срабатываний мало.
_BARE_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{25,}")

# SECURITY: секреты в query-string: ?key=..., &api_key=..., &token=...
# (?<![\w-]) не даёт сработать на «monkey=»/«my-token=» (иначе остаётся хвост).
# Значение — минимум 1 символ: иначе повторный проход по уже отредактированному
# «key=<redacted>» вставил бы второй маркер.
_QUERY_SECRET_RE = re.compile(
    r"(?i)(?<![\w-])((?:api_key|apikey|access_token|secret|token|key)=)[^&\s\"'<>]+"
)

_REDACTIONS = (
    (_BOT_TOKEN_RE, "bot<redacted>"),
    (_BARE_TOKEN_RE, "<redacted-token>"),
    (_QUERY_SECRET_RE, r"\1<redacted>"),
)

# Логгеры транспорта: httpx/httpcore пишут полный URL на INFO.
_HTTP_LOGGERS = ("httpx", "httpcore")

# Метка на LogRecord: фильтр может быть установлен и на логгер, и на обработчик,
# повторно редактировать тот же record нельзя (иначе маркеры дублируются).
_REDACTED_FLAG = "_tg_secrets_redacted"


def redact_secrets(text: str) -> str:
    """Вырезать известные секреты (токены/ключи) из произвольной строки."""
    if not text:
        return text
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class SecretRedactionFilter(logging.Filter):
    """Удаляет секреты из сообщения записи лога, не меняя её уровень.

    Для ``%``-шаблонов сначала рендерим сообщение (``getMessage``), при
    срабатывании подстановки сохраняем уже отредактированный текст в
    ``record.msg`` и очищаем ``record.args`` — форматтер выведет его как есть.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, _REDACTED_FLAG, False):
            return True  # уже обработан другим логгером/обработчиком
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - защита от битых аргументов
            message = str(record.msg)
        redacted = redact_secrets(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        elif not isinstance(record.msg, str):
            # Объект без секретов, но не строка: форматтеру нужен str.
            record.msg = str(record.msg)
        setattr(record, _REDACTED_FLAG, True)
        return True


class DropTransportInfoFilter(logging.Filter):
    """Второй слой для TG-F-09: не пропускает INFO-записи httpx/httpcore.

    Уровни выставляются на логгеры ``httpx``/``httpcore``, но дочерний логгер,
    созданный позже с собственным уровнем, мог бы снова начать писать URL.
    Фильтр на обработчике закрывает этот случай независимо от уровней.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        return not record.name.startswith(_HTTP_LOGGERS)


_FILTER = SecretRedactionFilter()
_TRANSPORT_FILTER = DropTransportInfoFilter()


def harden_http_loggers() -> None:
    """Погасить INFO-логи httpx/httpcore, включая уже созданные дочерние."""
    for name in _HTTP_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    prefixes = tuple(name + "." for name in _HTTP_LOGGERS)
    for logger_name, logger_obj in list(logging.Logger.manager.loggerDict.items()):
        if isinstance(logger_obj, logging.Logger) and logger_name.startswith(prefixes):
            logger_obj.setLevel(logging.WARNING)


def install_secret_filter() -> None:
    """Поставить redaction/transport-фильтры на корневые обработчики."""
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, SecretRedactionFilter) for f in handler.filters):
            handler.addFilter(_FILTER)
        if not any(isinstance(f, DropTransportInfoFilter) for f in handler.filters):
            handler.addFilter(_TRANSPORT_FILTER)
    if not any(isinstance(f, SecretRedactionFilter) for f in root.filters):
        root.addFilter(_FILTER)
    # lastResort используется, если обработчиков нет вовсе (warnings до
    # basicConfig) — фильтры нужны и там.
    last_resort = getattr(logging, "lastResort", None)
    if last_resort is not None:
        if not any(isinstance(f, SecretRedactionFilter) for f in last_resort.filters):
            last_resort.addFilter(_FILTER)
        if not any(isinstance(f, DropTransportInfoFilter) for f in last_resort.filters):
            last_resort.addFilter(_TRANSPORT_FILTER)


def configure_safe_logging(
    *,
    level: int = logging.INFO,
    log_format: str | None = None,
    datefmt: str | None = None,
    force: bool = False,
) -> None:
    """``logging.basicConfig`` + подавление HTTP-логов + redaction секретов.

    Повторный вызов безопасен: обработчики не дублируются (без ``force``),
    а ``harden_http_loggers``/``install_secret_filter`` идемпотентны.
    """
    if force or not logging.getLogger().handlers:
        kwargs: dict = {"level": level}
        if log_format is not None:
            kwargs["format"] = log_format
        if datefmt is not None:
            kwargs["datefmt"] = datefmt
        logging.basicConfig(**kwargs)
    harden_http_loggers()
    install_secret_filter()


def mask_identifier(value: object, *, visible_tail: int = 3) -> str:
    """Замаскировать ``chat_id``/``user_id`` для логов (TG-F-13).

    Идентификаторы Telegram — метадата, которой не место в логах CI/публичного
    репозитория: групповой id однозначно указывает на чат, а приватный
    ``chat_id`` совпадает с ``user_id``. Поэтому в сообщении остаются только
    последние ``visible_tail`` цифр — ``-1001234567890`` -> ``***890``. Этого
    достаточно для коррелирования записей между запусками, но восстановить
    по логу исходный id нельзя.

    ``None``, пустая строка и нечисловые значения маскируются полностью.
    """
    if value is None:
        return "***"
    text = str(value).strip()
    digits = text.lstrip("+-")
    if len(digits) <= visible_tail or not digits.isdigit():
        return "***"
    return "***" + digits[-visible_tail:]

