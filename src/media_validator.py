"""Multimodal AI Image Validator using Gemini 3.6 Flash Vision API.

Inspects images before publishing to verify whether the image visually matches
the specific product topic (e.g. Omega-3 vs skincare vs energy drink).

SECURITY POLICY (TG-F-06): the vision gate is FAIL-CLOSED. ``True`` is returned
only when a model explicitly answered with a well-formed approval. Everything
else — no image, no API key, unreadable/undecodable image, non-JSON answer,
malformed verdict, HTTP error, every model failed, unexpected exception — means
"the image was NOT verified" and returns ``False``. The reason is always logged,
and callers must publish without the image (text-only) instead of publishing an
unvetted picture.
"""

import base64
import json
import logging
import mimetypes
import os
import re

import httpx

from config.settings import GEMINI_API_KEY, GEMINI_MODELS

logger = logging.getLogger(__name__)


def encode_image_to_base64(image_path: str) -> tuple[str, str] | None:
    """Read local image file and return (mime_type, base64_str)."""
    if not os.path.exists(image_path):
        return None
    try:
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type:
            mime_type = "image/jpeg"
        with open(image_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        return mime_type, data
    except Exception as e:
        logger.warning(f"Failed to encode image {image_path}: {e}")
        return None


async def validate_image_with_gemini_vision(
    image_path: str | None,
    topic_title: str,
    product_line: str,
    post_text: str | None = None,
) -> bool:
    """Use Gemini Vision to verify that the image AND the post text match the topic.

    Gemini literally "looks" at the image and reads the post text, checking
    visual match and text quality before publishing.

    Args:
        image_path: Path to local downloaded image file
        topic_title: Article or product title (e.g. "Nutrilite Омега-3")
        product_line: Product category (e.g. "Nutrilite", "XS", "Artistry", "Home Care")
        post_text: Optional generated post text to check together with the image

    Returns:
        True only when the model explicitly approved the image (and the post
        text, when provided). False on rejection AND on every "could not
        verify" branch (fail-closed, TG-F-06).
    """
    if not image_path or not os.path.exists(image_path):
        logger.warning(
            "VISION GATE (fail-closed): no image to validate for "
            f"'{topic_title}' — rejecting media"
        )
        return False

    if not GEMINI_API_KEY:
        logger.warning(
            "VISION GATE (fail-closed): GEMINI_API_KEY is not configured — "
            f"cannot verify {os.path.basename(image_path)}; rejecting media"
        )
        return False

    encoded = encode_image_to_base64(image_path)
    if not encoded:
        logger.warning(
            "VISION GATE (fail-closed): could not read/encode image "
            f"{image_path} — rejecting media"
        )
        return False

    mime_type, base64_data = encoded
    models = GEMINI_MODELS if GEMINI_MODELS else ["gemini-3.7-flash", "gemini-3.6-flash"]

    if post_text:
        text_check = f"""
3. Прочитай текст поста (ниже) и проверь: соответствует ли он теме и картинке?
4. Качественный ли текст (живой, продающий, без ИИ-штампов, без явных ошибок)?

ТЕКСТ ПОСТА:
\"\"\"
{post_text[:2000]}
\"\"\"
"""
    else:
        text_check = ""

    prompt_text = f"""
Проанализируй это изображение для поста в Telegram.
Тема поста: "{topic_title}" (Линейка: {product_line}).

Оцени визуальное соответствие:
1. Подходит ли это изображение по смыслу к теме "{topic_title}"?
   (Например: если тема Омега-3 / рыбий жир — подходят капсулы с золотистым жиром, баночки с Омега-3, морские визуализации, рыбы/природа. НЕ подходят: другой препарат, например витамины Double X или косметика, случайные несвязанные продукты).
2. Является ли изображение качественным и привлекательным для поста?
{text_check}
Ответь СТРОГО в формате JSON:
{{"is_matching": true/false, "text_ok": true/false, "reason": "краткое объяснение"}}
""".strip()

    body = {
        "contents": [
            {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": base64_data,
                        }
                    },
                    {"text": prompt_text},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1000,
        },
    }

    image_name = os.path.basename(image_path)
    async with httpx.AsyncClient(timeout=30) as client:
        for model_name in models:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}"
                f":generateContent?key={GEMINI_API_KEY}"
            )
            try:
                resp = await client.post(url, json=body)
            except Exception as e:
                logger.warning(f"Gemini Vision {model_name} request error: {e}; trying next model")
                continue

            if resp.status_code in (429, 503):
                logger.warning(f"Gemini Vision {model_name} status {resp.status_code}, trying next model...")
                continue
            if resp.status_code != 200:
                logger.warning(
                    f"Gemini Vision {model_name} returned HTTP {resp.status_code}; trying next model"
                )
                continue

            try:
                data = resp.json()
            except Exception as e:
                logger.warning(
                    f"Gemini Vision {model_name} returned an invalid JSON envelope: {e}; "
                    "trying next model"
                )
                continue

            candidates = data.get("candidates") if isinstance(data, dict) else None
            if not candidates:
                logger.warning(
                    f"Gemini Vision {model_name} returned no candidates "
                    "(safety block or empty answer); trying next model"
                )
                continue

            parts = candidates[0].get("content", {}).get("parts", []) or []
            resp_text = (parts[0].get("text") or "").strip() if parts else ""
            if not resp_text:
                logger.warning(f"Gemini Vision {model_name} returned an empty answer; trying next model")
                continue

            logger.info(f"Gemini Vision ({model_name}) validation output: {resp_text}")

            parsed = _parse_validation_json(resp_text)
            if parsed is None:
                logger.warning(
                    f"Gemini Vision {model_name} returned non-JSON for {image_name}; "
                    f"cannot verify (raw: {resp_text[:120]}); trying next model"
                )
                continue

            verdict = _extract_verdict(parsed, require_text=bool(post_text))
            if verdict is None:
                logger.warning(
                    f"Gemini Vision {model_name} returned a malformed verdict for {image_name}: "
                    f"{parsed!r}; trying next model"
                )
                continue

            is_approved, reason = verdict
            if is_approved:
                logger.info(f"Image {image_name} APPROVED by Gemini Vision")
                return True

            logger.warning(
                f"Image {image_name} REJECTED by Gemini Vision: {reason or resp_text}"
            )
            return False

    logger.warning(
        "VISION GATE (fail-closed): all Gemini Vision models failed or returned unusable "
        f"answers — image {image_name} rejected"
    )
    return False


def _extract_verdict(parsed: dict, *, require_text: bool) -> tuple[bool, str] | None:
    """Validate Gemini's JSON verdict and return (approved, reason) or None.

    None means the payload is malformed (missing/non-boolean ``is_matching`` or
    ``text_ok``) and must be treated as "could not verify" (fail-closed), not as
    an approval.
    """
    is_matching = parsed.get("is_matching")
    if not isinstance(is_matching, bool):
        return None

    text_ok = parsed.get("text_ok") if require_text else True
    if not isinstance(text_ok, bool):
        return None

    reason = parsed.get("reason", "")
    if not isinstance(reason, str):
        reason = str(reason)

    return (is_matching and text_ok, reason)


def _parse_validation_json(resp_text: str) -> dict | None:
    """Best-effort parse of Gemini's reply into a dict with is_matching/text_ok.

    Handles markdown code fences, stray prose around the JSON, and minor
    formatting drift. Returns None when no valid JSON object can be found.
    """
    if not resp_text:
        return None

    text = resp_text.strip()
    # 1) Drop markdown code fences
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)

    # 2) Try the whole string as-is first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (ValueError, TypeError):
        pass

    # 3) Fall back to the first {...} block in the reply
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
        if isinstance(obj, dict):
            return obj
    except (ValueError, TypeError):
        return None

    return None
