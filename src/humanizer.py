"""Humanization validation — ported from threads/voice.js.

Detects when the LLM returns its own reasoning, checklists, or English text
instead of a ready-to-publish Russian post.
"""

import re


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
    cyrillic = len(re.findall(r"[а-яА-ЯеЕ]", t))
    latin = len(re.findall(r"[a-zA-Z]", t))
    if cyrillic + latin > 0 and latin / (cyrillic + latin) > 0.5:
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

    return False


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

    return t
