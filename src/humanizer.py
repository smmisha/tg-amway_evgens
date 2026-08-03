"""Humanization validation — ported from threads/voice.js.

Detects when the LLM returns its own reasoning, checklists, or English text
instead of a ready-to-publish Russian post.  Also catches Ukrainian word
contamination (amway.ua serves content in Ukrainian) and missing mandatory
post elements (CTA, hashtags).
"""

import re
import logging

logger = logging.getLogger(__name__)

# Ukrainian-only letters that never appear in correct Russian text.
# і (U+0456), ї (U+0457), є (U+0454), ґ (U+0491)
_UKRAINIAN_ONLY_LETTERS = re.compile(r'[іїєґІЇЄҐ]')


def looks_like_model_artifact(text: str) -> bool:
    """Return True if *text* looks like model meta-output rather than a real post.

    Ported from looksLikeModelArtifact() in voice.js.
    """
    t = (text or "").strip()
    if not t:
        return True

    # Markdown bold or headers — never appear in a valid post
    if re.search(r"\*\*", t) or re.search(r"^#{1,6}\s", t, re.MULTILINE):
        return True

    # Numbered reasoning steps like "6. **Final Polish:**"
    if re.search(r"^\s*\d+\.\s+\*\*", t, re.MULTILINE):
        return True

    # Self-check markers (English or mixed)
    if re.search(
        r"\b(Check words|Final Polish|no hashtags|no CTA|system rules)\b",
        t,
        re.IGNORECASE,
    ):
        return True
    if re.search(r"^\s*-\s*(No|Yes)\b", t, re.MULTILINE | re.IGNORECASE):
        return True
    # Word-by-word notes like "сделал (е), баг (нет)"
    if re.search(r"\((?:е|нет|да)\)[,.\s]", t, re.IGNORECASE):
        return True

    # Too much Latin script — real posts are Russian
    cyrillic = len(re.findall(r"[а-яА-ЯёЁ]", t))
    latin = len(re.findall(r"[a-zA-Z]", t))
    if cyrillic + latin > 0 and latin / (cyrillic + latin) > 0.5:
        return True

    # Ukrainian words leaked into Russian text (source site is Ukrainian)
    if has_ukrainian_contamination(t):
        logger.warning("Post contains Ukrainian letters (і/ї/є/ґ) — rejecting as artifact")
        return True

    # Truncated text: ends with comma or dangling conjunction
    if re.search(r",\s*$", t):
        return True
    if re.search(
        r"(?:^|\s)(?:а|и|но|с|в|на|к|о|об|у|из|для|что|как|за|по)\s*$",
        t,
        re.IGNORECASE,
    ):
        return True

    # "Вот ваш текст:" or "Перевод:" preamble
    if re.search(r"^\s*(?:Вот|Перевод|Готовый текст|Ваш пост)\s*:", t, re.IGNORECASE):
        return True

    # Missing mandatory post elements
    if "@evgen_blago" not in t:
        logger.warning("Post missing @evgen_blago CTA — rejecting as artifact")
        return True
    if "#" not in t:
        logger.warning("Post missing hashtags — rejecting as artifact")
        return True

    return False


def has_ukrainian_contamination(text: str) -> bool:
    """Return True if *text* contains Ukrainian-only letters (і, ї, є, ґ).

    These letters do not exist in the Russian alphabet. Their presence in a
    post that should be pure Russian means the LLM failed to translate from
    the Ukrainian source content.
    """
    # Ignore brand names and URLs — only check prose
    # Strip URLs and @mentions first
    prose = re.sub(r'https?://\S+', '', text)
    prose = re.sub(r'@\w+', '', prose)
    return bool(_UKRAINIAN_ONLY_LETTERS.search(prose))


def clean_post_text(text: str) -> str:
    """Apply final cleanup to a generated post."""
    t = text.strip()

    # Remove trailing period (unless ellipsis)
    if t.endswith(".") and not t.endswith("..."):
        t = t[:-1].strip()

    # Remove any markdown bold markers that slipped through
    t = t.replace("**", "")

    # Replace 'ё' with 'е' (typography rule from voice.js)
    t = t.replace("ё", "е").replace("Ё", "Е")

    # Replace en-dash with em-dash
    t = t.replace(" – ", " — ").replace("–", "—")

    # Clean dangling or empty hashtags at the end
    t = re.sub(r"#\s*$", "", t).strip()
    t = re.sub(r"#\s*#", "#", t).strip()

    return t
