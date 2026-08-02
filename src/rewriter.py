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
    HUMANIZER_SYSTEM_INSTRUCTION,
)
from src.humanizer import looks_like_model_artifact, clean_post_text
from src.scraper import Article

logger = logging.getLogger(__name__)


async def call_groq(system_prompt: str, user_prompt: str) -> str:
    """Call Groq API (Llama 3.3 70B)."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": LLM_TEMPERATURE,
        "max_tokens": LLM_MAX_TOKENS,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(1, 3):
            try:
                resp = await client.post(url, headers=headers, json=body)
                data = resp.json()
                if resp.status_code == 429:
                    logger.warning(f"Groq rate limited (attempt {attempt}). Waiting...")
                    await asyncio.sleep(5 * attempt)
                    continue
                resp.raise_for_status()
                return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.warning(f"Groq attempt {attempt} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(3)
    raise RuntimeError("Groq API failed after retries")


async def call_gemini(system_prompt: str, user_prompt: str) -> str:
    """Call Gemini API with model fallback chain."""
    for model in GEMINI_MODELS:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
            f":generateContent?key={GEMINI_API_KEY}"
        )
        body = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": LLM_TEMPERATURE,
                "maxOutputTokens": LLM_MAX_TOKENS,
            },
        }

        async with httpx.AsyncClient(timeout=60) as client:
            for attempt in range(1, 3):
                try:
                    resp = await client.post(url, json=body)
                    data = resp.json()
                    if resp.status_code in (429, 503):
                        logger.warning(f"Gemini {model} transient error (attempt {attempt})")
                        await asyncio.sleep(3 * attempt)
                        continue
                    if "error" in data:
                        raise RuntimeError(f"Gemini error: {data['error']}")
                    candidates = data.get("candidates", [])
                    if candidates and candidates[0].get("content", {}).get("parts"):
                        return candidates[0]["content"]["parts"][0]["text"].strip()
                except Exception as e:
                    logger.warning(f"Gemini {model} attempt {attempt} failed: {e}")
                    if attempt < 2:
                        await asyncio.sleep(2)
        logger.warning(f"Model {model} exhausted, trying next...")

    raise RuntimeError("All Gemini models failed")


async def call_llm(system_prompt: str, user_prompt: str) -> str:
    """Call primary LLM based on LLM_PROVIDER setting, falling back to secondary."""
    primary = LLM_PROVIDER.lower() if LLM_PROVIDER else "gemini"

    if primary == "gemini":
        if GEMINI_API_KEY:
            try:
                return await call_gemini(system_prompt, user_prompt)
            except Exception as e:
                logger.warning(f"Gemini failed: {e}")
                if GROQ_API_KEY:
                    logger.info("Falling back to Groq...")
                    return await call_groq(system_prompt, user_prompt)
                raise
        elif GROQ_API_KEY:
            return await call_groq(system_prompt, user_prompt)
    else:
        if GROQ_API_KEY:
            try:
                return await call_groq(system_prompt, user_prompt)
            except Exception as e:
                logger.warning(f"Groq failed: {e}")
                if GEMINI_API_KEY:
                    logger.info("Falling back to Gemini...")
                    return await call_gemini(system_prompt, user_prompt)
                raise
        elif GEMINI_API_KEY:
            return await call_gemini(system_prompt, user_prompt)

    raise RuntimeError("No LLM API keys configured")


async def rewrite_article(
    article: Article,
    include_cta: bool | None = None,
    book_context: str | None = None,
) -> str:
    """Rewrite an article in the Amway brand-ambassador style.

    Args:
        article: Scraped article to rewrite
        include_cta: Force CTA on/off. None = random based on CTA_PROBABILITY
        book_context: Optional book enrichment context string

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

        result = await call_llm(system_prompt, prompt)

        if not looks_like_model_artifact(result):
            # Valid post
            result = clean_post_text(result)
            if len(result) > POST_MAX_LENGTH:
                result = result[:POST_MAX_LENGTH - 3] + "..."
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
