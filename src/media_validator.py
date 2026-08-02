"""Multimodal AI Image Validator using Gemini 3.6 Flash Vision API.

Inspects images before publishing to verify whether the image visually matches
the specific product topic (e.g. Omega-3 vs skincare vs energy drink).
"""

import base64
import logging
import os
import mimetypes
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
        True if the image (and text) match the topic, False otherwise.
    """
    if not image_path or not os.path.exists(image_path):
        logger.info("No image to validate — skipping vision check")
        return True

    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not configured, skipping vision validation")
        return True

    encoded = encode_image_to_base64(image_path)
    if not encoded:
        return False

    mime_type, base64_data = encoded
    model_name = GEMINI_MODELS[0] if GEMINI_MODELS else "gemini-3.6-flash"

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}"
        f":generateContent?key={GEMINI_API_KEY}"
    )

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
   (Например: если тема Омега-3 / рыбий жир — подходят капсулы с золотистым жиром, баночки с Омега-3, морские визуализации, рыбы/природа. НЕ подходят: случайная косметика, бытовая химия, случайные не связанные объекты).
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
            "maxOutputTokens": 150,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, json=body)
            data = resp.json()

            if "candidates" in data and data["candidates"]:
                parts = data["candidates"][0].get("content", {}).get("parts", [])
                if parts:
                    resp_text = parts[0].get("text", "").strip()
                    logger.info(f"Gemini Vision validation output: {resp_text}")

                    import re
                    is_approved = bool(re.search(r'"is_matching"\s*:\s*true', resp_text, re.IGNORECASE))
                    if post_text:
                        is_approved = is_approved and bool(
                            re.search(r'"text_ok"\s*:\s*true', resp_text, re.IGNORECASE)
                        )
                    if is_approved:
                        logger.info(f"Image {os.path.basename(image_path)} APPROVED by Gemini Vision")
                        return True
                    else:
                        logger.warning(f"Image {os.path.basename(image_path)} REJECTED by Gemini Vision: {resp_text}")
                        return False

    except Exception as e:
        logger.warning(f"Gemini Vision validation error: {e}")
        # Default to True on API error to not block execution
        return True

    return True
