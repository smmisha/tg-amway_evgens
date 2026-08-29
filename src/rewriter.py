"""LLM-powered article rewriter with Groq (primary) and Gemini (fallback).

Includes retry logic and anti-AI artifact validation
from threads/publish.js.
"""

import asyncio
import json
import logging
import random

import httpx

from config.settings import (
    CTA_PROBABILITY,
    GEMINI_API_KEY,
    GEMINI_MODELS,
    GROQ_API_KEY,
    GROQ_MODEL,
    LLM_MAX_RETRIES,
    LLM_MAX_TOKENS,
    LLM_PROVIDER,
    LLM_TEMPERATURE,
    POST_MAX_LENGTH,
)
from config.cta_templates import get_cta_instruction
from config.prompts import (
    REWRITER_SYSTEM_INSTRUCTION,
    BOOK_ENRICHED_SYSTEM_INSTRUCTION,
    VALIDATION_SYSTEM_INSTRUCTION,
)
from src.humanizer import looks_like_model_artifact, clean_post_text
from src.scraper import Article

logger = logging.getLogger(__name__)


async def call_groq(system_prompt: str, user_prompt: str) -> str:
    """Call Groq API with model fallback chain."""
    from config.settings import GROQ_FALLBACK_MODELS

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    models = [GROQ_MODEL] + [m for m in GROQ_FALLBACK_MODELS if m != GROQ_MODEL]

    async with httpx.AsyncClient(timeout=60) as client:
        for model in models:
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": LLM_TEMPERATURE,
                "max_tokens": LLM_MAX_TOKENS,
            }
            for attempt in range(1, 3):
                try:
                    resp = await client.post(url, headers=headers, json=body)
                    if resp.status_code == 429:
                        logger.warning(f"Groq {model} rate limited (attempt {attempt}). Waiting...")
                        await asyncio.sleep(5 * attempt)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data["choices"][0]
                    content = choice["message"]["content"].strip()
                    if choice.get("finish_reason") == "length":
                        logger.warning(f"Groq response truncated. Retrying...")
                        raise RuntimeError("Groq response truncated")
                    return content
                except Exception as e:
                    logger.warning(f"Groq {model} attempt {attempt} failed: {e}")
                    if attempt < 2:
                        await asyncio.sleep(2)
    raise RuntimeError("All Groq models failed after retries")


async def call_gemini(system_prompt: str, user_prompt: str, image_path: str | None = None) -> str:
    """Call Gemini API with model fallback chain, supporting multimodal image input."""
    from src.media_validator import encode_image_to_base64

    parts = []
    if image_path:
        encoded = encode_image_to_base64(image_path)
        if encoded:
            mime_type, base64_data = encoded
            parts.append({
                "inlineData": {
                    "mimeType": mime_type,
                    "data": base64_data,
                }
            })
            # Add instruction for image context
            user_prompt = "ВНИМАНИЕ: Ознакомься с изображением выше. Напиши пост, который 100% визуально соотносится с этой картинкой и продуктом!\n\n" + user_prompt

    parts.append({"text": user_prompt})

    async with httpx.AsyncClient(timeout=60) as client:
        for model in GEMINI_MODELS:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
                f":generateContent?key={GEMINI_API_KEY}"
            )
            body = {
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "temperature": LLM_TEMPERATURE,
                    "maxOutputTokens": LLM_MAX_TOKENS,
                },
            }

            for attempt in range(1, 4):
                try:
                    resp = await client.post(url, json=body)
                    data = resp.json()
                    if resp.status_code in (429, 503):
                        logger.warning(f"Gemini {model} rate limit (status {resp.status_code}, attempt {attempt}/3), waiting {25 * attempt}s...")
                        await asyncio.sleep(25 * attempt)
                        continue
                    if "error" in data:
                        logger.error(f"Gemini {model} error body: {data['error']}")
                        raise RuntimeError(f"Gemini error: {data['error']}")
                    candidates = data.get("candidates", [])
                    if candidates and candidates[0].get("content", {}).get("parts"):
                        return candidates[0]["content"]["parts"][0]["text"].strip()
                except Exception as e:
                    logger.warning(f"Gemini {model} attempt {attempt} failed: {e}")
                    if attempt < 3:
                        await asyncio.sleep(5 * attempt)
            logger.warning(f"Model {model} exhausted, trying next...")

    raise RuntimeError("All Gemini models failed")


async def call_llm(system_prompt: str, user_prompt: str, image_path: str | None = None) -> str:
    """Call primary LLM based on LLM_PROVIDER setting, falling back to secondary."""
    primary = LLM_PROVIDER.lower() if LLM_PROVIDER else "gemini"

    # Helper to strip image instructions for text-only LLMs like Groq
    def _text_only_prompt(prompt: str) -> str:
        prefix = "ВНИМАНИЕ: Ознакомься с изображением выше. Напиши пост, который 100% визуально соотносится с этой картинкой и продуктом!\n\n"
        return prompt.replace(prefix, "")

    if primary == "gemini":
        if GEMINI_API_KEY:
            try:
                return await call_gemini(system_prompt, user_prompt, image_path=image_path)
            except Exception as e:
                logger.warning(f"Gemini failed: {e}")
                if GROQ_API_KEY:
                    logger.info("Falling back to Groq (text-only)...")
                    return await call_groq(system_prompt, _text_only_prompt(user_prompt))
                raise
        elif GROQ_API_KEY:
            return await call_groq(system_prompt, _text_only_prompt(user_prompt))
    else:
        if GROQ_API_KEY:
            try:
                return await call_groq(system_prompt, _text_only_prompt(user_prompt))
            except Exception as e:
                logger.warning(f"Groq failed: {e}")
                if GEMINI_API_KEY:
                    logger.info("Falling back to Gemini...")
                    return await call_gemini(system_prompt, user_prompt, image_path=image_path)
                raise
        elif GEMINI_API_KEY:
            return await call_gemini(system_prompt, user_prompt, image_path=image_path)

    raise RuntimeError("No LLM API keys configured")


async def validate_with_gemini(post_text: str, product_line: str = "default") -> str:
    """Strictly check and fix the post with Gemini before publishing.

    Runs the full pre-publication checklist (language purity, duplication,
    typography, tone, mandatory CTA + hashtags). Re-checks the result and
    re-asks until the post ends with @evgen_blago + 2 hashtags.
    Returns the corrected text, or the original if Gemini is unavailable.
    """
    if not GEMINI_API_KEY:
        return post_text

    if _has_mandatory_finish(post_text):
        return post_text

    for attempt in range(1, 4):
        user_prompt = (
            "Проверь и исправь этот текст для публикации по всем пунктам инструкции. "
            "Верни ТОЛЬКО исправленный текст целиком (без рассуждений, без списка ошибок).\n\n"
            f"ТЕКСТ:\n{post_text}"
        )
        try:
            corrected = await call_gemini(VALIDATION_SYSTEM_INSTRUCTION, user_prompt)
            corrected = corrected.strip()
            if corrected and _has_mandatory_finish(corrected):
                logger.info(
                    f"Gemini validation passed — final text ({len(corrected)} chars)."
                )
                return corrected
            logger.warning(
                f"Gemini validation attempt {attempt}: missing CTA/hashtags or empty. Retrying..."
            )
        except Exception as e:
            logger.warning(f"Gemini validation attempt {attempt} failed: {e}")
            await asyncio.sleep(2 * attempt)

    logger.error("Gemini validation could not fix post ending. Appending CTA manually.")
    from config.cta_templates import get_cta

    cta = get_cta(product_line=product_line)
    return f"{post_text.rstrip()}\n\n{cta}\n\n#Amway"


def _has_mandatory_finish(text: str) -> bool:
    """Post must contain @evgen_blago and at least one hashtag."""
    return "@evgen_blago" in text and "#" in text


async def rewrite_article(
    article: Article,
    include_cta: bool | None = None,
    book_context: str | None = None,
    image_path: str | None = None,
) -> str:
    """Rewrite an article in the Amway brand-ambassador style.

    Args:
        article: Scraped article to rewrite
        include_cta: Force CTA on/off. None = random based on CTA_PROBABILITY
        book_context: Optional book enrichment context string
        image_path: Optional path to validated product image for multimodal context

    Returns:
        Ready-to-publish post text
    """
    if include_cta is None:
        include_cta = random.random() < CTA_PROBABILITY

    cta_instruction = get_cta_instruction(include_cta, article.product_line, article.url)

    if book_context:
        system_prompt = BOOK_ENRICHED_SYSTEM_INSTRUCTION.replace("{cta_instruction}", cta_instruction)
    else:
        system_prompt = REWRITER_SYSTEM_INSTRUCTION.replace("{cta_instruction}", cta_instruction)

    user_prompt = f"""
Статья с сайта Amway:

Заголовок: {article.title}
Линейка продуктов: {article.product_line}

Текст:
{article.body[:3000]}

{book_context or ''}

Перепиши эту статью для Telegram-группы.
""".strip()

    # Retry loop with anti-AI validation (from publish.js)
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        prompt = user_prompt
        if attempt > 1:
            prompt += (
                "\n\nВАЖНО: Ответь ТОЛЬКО на русском языке. "
                "Выведи ТОЛЬКО готовый текст поста, "
                "без пояснений, без markdown, без рассуждений."
            )

        result = await call_llm(system_prompt, prompt, image_path=image_path)

        if not looks_like_model_artifact(result):
            # Valid post
            result = clean_post_text(result)
            if len(result) > POST_MAX_LENGTH:
                result = result[:POST_MAX_LENGTH - 3] + "..."
            # Strict pre-publication check by Gemini (fixes language/typo/tone)
            result = await validate_with_gemini(result, product_line=article.product_line)
            return result

        if attempt < LLM_MAX_RETRIES:
            logger.warning(
                f"Attempt {attempt}/{LLM_MAX_RETRIES}: model returned artifact. Retrying..."
            )
            await asyncio.sleep(2)
        else:
            logger.error("All LLM attempts returned artifacts")
            raise RuntimeError(
                f"LLM returned model artifacts after {LLM_MAX_RETRIES} attempts"
            )

    # Should not reach here, but just in case
    raise RuntimeError("Rewrite failed unexpectedly")
