"""Сетевая безопасность: SSRF-защищённая загрузка по HTTP(S).

Новых зависимостей нет: только stdlib (``ipaddress``, ``socket``, ``urllib.parse``)
и уже используемый в проекте ``httpx``.

Политика (см. аудит F-03):
- разрешены только схемы http/https;
- userinfo (``user:pass@host``) в URL запрещён;
- hostname резолвится через ``socket.getaddrinfo``; если хотя бы один полученный
  адрес приватный/loopback/link-local/multicast/reserved — запрос запрещён
  (fail-closed). ``localhost`` и ``*.localhost`` запрещены всегда;
- необязательный allowlist хостов: точное совпадение или суффикс ``.<domain>``
  (НЕ подстрока);
- редиректы выполняются вручную (``follow_redirects=False``), не более
  ``MAX_REDIRECTS`` хопов, каждый хоп проверяется заново;
- тело ответа читается потоком и обрывается при превышении ``max_bytes`` —
  полной буферизации «до проверки лимита» нет.
"""

import ipaddress
import logging
import socket
from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

# Сколько редиректов разрешено пройти (каждый проверяется как новый URL).
MAX_REDIRECTS = 3
# Размер чанка при потоковом чтении тела ответа.
_CHUNK_SIZE = 64 * 1024
_ALLOWED_SCHEMES = ("http", "https")

# UA как в исходном media.download_image — чтобы не менять поведение сайта Amway.
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# SECURITY: диапазоны, которые не всегда попадают в is_private/is_reserved
# (CGNAT, 0.0.0.0/8, IETF-протоколы, benchmark) — блокируем явно.
_EXTRA_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("64:ff9b::/96"),
)


class NetSafetyError(ValueError):
    """Базовое исключение сетевой политики."""


class UnsafeUrlError(NetSafetyError):
    """URL не прошёл проверку безопасности (SSRF/allowlist/редиректы)."""


class ResponseTooLargeError(NetSafetyError):
    """Ответ превысил допустимый размер и был оборван."""


def is_public_ip(address: str) -> bool:
    """True, если IP-адрес глобально маршрутизируемый.

    Отклоняются private/loopback/link-local/multicast/reserved/unspecified
    и IPv4-mapped IPv6-обёртки приватных адресов.
    """
    try:
        # У IPv6-адреса может быть scope id (fe80::1%eth0) — он не относится к адресу.
        ip = ipaddress.ip_address(str(address).split("%", 1)[0])
    except ValueError:
        return False

    # SECURITY: ::ffff:127.0.0.1 — это loopback; проверяем вложенный IPv4.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    if any(ip in network for network in _EXTRA_BLOCKED_NETWORKS if ip.version == network.version):
        return False

    return bool(
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
    )


def is_host_allowed(host: str, allowed_hosts: Iterable[str] | None) -> bool:
    """True, если hostname входит в allowlist.

    Сравнение строгое: точное совпадение или суффикс ``.<domain>``.
    Подстрочное сравнение (``"amway.ua" in url``) недопустимо: оно пропускает
    ``https://attacker.tld/x.jpg?ref=amway.ua``.

    ``allowed_hosts=None`` означает «allowlist не задан» — проверяется только
    IP-политика (вызывающая сторона решает, нужно ли ограничение).
    """
    if not allowed_hosts:
        return True

    normalized = (host or "").strip().lower().rstrip(".")
    if not normalized:
        return False

    for allowed in allowed_hosts:
        domain = str(allowed or "").strip().lower().rstrip(".")
        if not domain:
            continue
        if normalized == domain or normalized.endswith("." + domain):
            return True
    return False


def assert_public_http_url(url: str, *, allowed_hosts: Iterable[str] | None = None) -> None:
    """Проверить, что URL можно безопасно запрашивать.

    Raises:
        UnsafeUrlError: если схема не http(s), есть userinfo, hostname пустой/
            ``localhost``/вне allowlist либо резолвится в непубличный IP.
    """
    raw = (url or "").strip()
    if not raw:
        raise UnsafeUrlError("пустой URL")

    try:
        parsed = urlparse(raw)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError(f"некорректный URL {raw!r}: {exc}") from exc

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"разрешены только http/https, получено {scheme or '<без схемы>'!r}: {raw}")

    # SECURITY: userinfo позволяет маскировать реальный хост (http://amway.ua@attacker.tld).
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError(f"userinfo в URL запрещён: {raw}")

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise UnsafeUrlError(f"в URL отсутствует hostname: {raw}")
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeUrlError(f"localhost запрещён: {raw}")

    if not is_host_allowed(host, allowed_hosts):
        raise UnsafeUrlError(f"hostname {host!r} не входит в allowlist: {raw}")

    try:
        infos = socket.getaddrinfo(
            host, port or (443 if scheme == "https" else 80), type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"не удалось разрешить hostname {host!r}: {exc}") from exc

    if not infos:
        raise UnsafeUrlError(f"DNS не вернул адресов для {host!r}: {raw}")

    # SECURITY: fail-closed — при любом непубличном адресе в ответе DNS запрос запрещён
    # (DNS rebinding и «внутренние» A-записи не должны доходить до сокета).
    for info in infos:
        address = info[4][0] if len(info) > 4 else ""
        if not is_public_ip(address):
            raise UnsafeUrlError(
                f"hostname {host!r} резолвится в непубличный адрес {address!r}: {raw}"
            )


async def safe_get_bytes(
    url: str,
    *,
    timeout: float | httpx.Timeout = 20.0,
    max_bytes: int = 10 * 1024 * 1024,
    allowed_hosts: Iterable[str] | None = None,
) -> tuple[bytes, str, str]:
    """Скачать URL с SSRF-проверкой, ручными редиректами и лимитом размера.

    Args:
        url: исходный http(s) URL.
        timeout: таймаут httpx (секунды или готовый ``httpx.Timeout``).
        max_bytes: максимальный размер тела ответа; при превышении чтение
            обрывается и поднимается :class:`ResponseTooLargeError`.
        allowed_hosts: необязательный allowlist хостов (точное совпадение или
            суффикс ``.<domain>``); применяется к каждому хопу редиректа.

    Returns:
        ``(data, content_type, final_url)``: тело ответа, MIME-тип без параметров
        (в нижнем регистре) и финальный URL после редиректов.

    Raises:
        UnsafeUrlError: URL/редирект не прошёл проверку безопасности.
        ResponseTooLargeError: ответ больше ``max_bytes``.
        httpx.HTTPError: сетевые ошибки и HTTP-статусы >= 400.
    """
    current = (url or "").strip()
    if not current:
        raise UnsafeUrlError("пустой URL")

    timeout_config = httpx.Timeout(timeout) if isinstance(timeout, (int, float)) else timeout

    # SECURITY: follow_redirects=False — каждый хоп проверяем сами, иначе сервер
    # может увести запрос на внутренний адрес в обход allowlist/IP-политики.
    async with httpx.AsyncClient(
        timeout=timeout_config,
        follow_redirects=False,
        headers=_DEFAULT_HEADERS,
    ) as client:
        for hop in range(MAX_REDIRECTS + 1):
            assert_public_http_url(current, allowed_hosts=allowed_hosts)

            async with client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise UnsafeUrlError(f"редирект без Location: {current}")
                    if hop >= MAX_REDIRECTS:
                        raise UnsafeUrlError(f"больше {MAX_REDIRECTS} редиректов: {url}")
                    current = urljoin(current, location)
                    logger.info(f"Redirect hop {hop + 1}/{MAX_REDIRECTS}: {current}")
                    continue

                if 300 <= response.status_code < 400:
                    raise UnsafeUrlError(
                        f"неожиданный ответ {response.status_code} без Location: {current}"
                    )

                response.raise_for_status()

                content_type = (response.headers.get("content-type") or "")
                content_type = content_type.split(";", 1)[0].strip().lower()

                # Ранний отказ по Content-Length: тело даже не начинаем читать.
                declared_length = (response.headers.get("content-length") or "").strip()
                if declared_length.isdigit() and int(declared_length) > max_bytes:
                    raise ResponseTooLargeError(
                        f"Content-Length {declared_length} больше лимита {max_bytes}: {current}"
                    )

                # SECURITY: потоковое чтение с лимитом — тело не буферизуется целиком
                # до проверки размера (в отличие от resp.content).
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes(_CHUNK_SIZE):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ResponseTooLargeError(
                            f"ответ больше лимита {max_bytes} байт: {current}"
                        )
                    chunks.append(chunk)

                return b"".join(chunks), content_type, str(response.url)

        raise UnsafeUrlError(f"больше {MAX_REDIRECTS} редиректов: {url}")
