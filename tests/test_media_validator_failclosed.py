"""Fail-closed unit tests for src/media_validator.py (security finding TG-F-06).

No network is used: ``httpx.AsyncClient`` is replaced by a scripted fake, so the
tests only exercise the decision logic. Every "could not verify" branch must
return False (reject the image), never True.
"""

import asyncio

import pytest

import src.media_validator as mv


class _FakeResponse:
    """Minimal stand-in for httpx.Response (status_code + json())."""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _reply(text: str) -> _FakeResponse:
    """Build a Gemini-shaped HTTP 200 response carrying *text*."""
    return _FakeResponse(
        200, {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    )


def _install_client(monkeypatch, responses):
    """Patch ``httpx.AsyncClient`` with a scripted fake and return the call log."""
    calls: list[str] = []

    class _ScriptedClient:
        def __init__(self, *args, **kwargs):
            self._pos = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, json=None):
            calls.append(url)
            index = self._pos
            self._pos += 1
            if index >= len(responses):
                raise AssertionError("unexpected extra Gemini request")
            item = responses[index]
            if isinstance(item, Exception):
                raise item
            return item

    monkeypatch.setattr(mv.httpx, "AsyncClient", _ScriptedClient)
    return calls


@pytest.fixture
def vision_env(monkeypatch, tmp_path):
    """Real temp image + fake API key + deterministic model list."""
    image = tmp_path / "omega.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    monkeypatch.setattr(mv, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(mv, "GEMINI_MODELS", ["gemini-test-a", "gemini-test-b"])
    return str(image)


def _validate(image_path, post_text="Пост про Nutrilite Омега-3"):
    return asyncio.run(
        mv.validate_image_with_gemini_vision(
            image_path=image_path,
            topic_title="Nutrilite Омега-3",
            product_line="Nutrilite",
            post_text=post_text,
        )
    )


def test_approval_returns_true(vision_env, monkeypatch):
    calls = _install_client(
        monkeypatch,
        [_reply('{"is_matching": true, "text_ok": true, "reason": "ok"}')],
    )

    assert _validate(vision_env) is True
    assert len(calls) == 1


def test_markdown_fenced_approval_returns_true(vision_env, monkeypatch):
    _install_client(
        monkeypatch,
        [_reply('```json\n{"is_matching": true, "text_ok": true}\n```')],
    )

    assert _validate(vision_env) is True


def test_missing_image_is_rejected_without_network(monkeypatch, tmp_path):
    calls = _install_client(monkeypatch, [])
    monkeypatch.setattr(mv, "GEMINI_API_KEY", "test-key")

    assert _validate(None) is False
    assert _validate(str(tmp_path / "does-not-exist.jpg")) is False
    assert calls == []


def test_directory_instead_of_image_is_rejected_without_network(
    monkeypatch, tmp_path
):
    calls = _install_client(monkeypatch, [])
    monkeypatch.setattr(mv, "GEMINI_API_KEY", "test-key")

    # The path exists but is a directory -> encoding fails -> fail-closed.
    assert _validate(str(tmp_path)) is False
    assert calls == []


def test_missing_api_key_is_rejected_without_network(vision_env, monkeypatch):
    calls = _install_client(monkeypatch, [])
    monkeypatch.setattr(mv, "GEMINI_API_KEY", "")

    assert _validate(vision_env) is False
    assert calls == []


@pytest.mark.parametrize(
    "verdict",
    [
        '{"is_matching": false, "text_ok": true, "reason": "wrong product"}',
        '{"is_matching": true, "text_ok": false, "reason": "bad text"}',
        "not a json answer at all",
        '{"is_matching": "yes", "text_ok": true}',
        '{"is_matching": true}',
    ],
)
def test_non_approval_reply_is_rejected(vision_env, monkeypatch, verdict):
    # Fail-closed: both models are tried before a non-verifiable answer is refused.
    _install_client(monkeypatch, [_reply(verdict), _reply(verdict)])

    assert _validate(vision_env) is False


def test_http_errors_from_all_models_are_rejected(vision_env, monkeypatch):
    calls = _install_client(
        monkeypatch,
        [_FakeResponse(503), _FakeResponse(500, {"error": "internal"})],
    )

    assert _validate(vision_env) is False
    assert len(calls) == 2


def test_network_exceptions_from_all_models_are_rejected(vision_env, monkeypatch):
    calls = _install_client(
        monkeypatch,
        [RuntimeError("connection reset"), _FakeResponse(429)],
    )

    assert _validate(vision_env) is False
    assert len(calls) == 2


def test_safety_block_without_candidates_is_rejected(vision_env, monkeypatch):
    blocked = _FakeResponse(200, {"promptFeedback": {"blockReason": "SAFETY"}})
    _install_client(monkeypatch, [blocked, blocked])

    assert _validate(vision_env) is False


def test_invalid_json_envelope_is_rejected(vision_env, monkeypatch):
    bad = _FakeResponse(200, ValueError("body is not JSON"))
    _install_client(monkeypatch, [bad, bad])

    assert _validate(vision_env) is False


def test_empty_answer_is_rejected(vision_env, monkeypatch):
    empty = _FakeResponse(
        200, {"candidates": [{"content": {"parts": [{"text": "   "}]}}]}
    )
    _install_client(monkeypatch, [empty, empty])

    assert _validate(vision_env) is False
