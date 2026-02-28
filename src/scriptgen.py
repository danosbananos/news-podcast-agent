"""Podcastscript genereren met Claude Haiku + grammaticacontrole."""

import logging
import re
from collections import Counter

import anthropic
import httpx

logger = logging.getLogger(__name__)

# Language display names for the prompt
_LANGUAGE_NAMES = {
    "nl": "Dutch",
    "en": "English",
    "en-GB": "English",
    "de": "German",
}

# LanguageTool language codes
_LANGUAGETOOL_CODES = {
    "nl": "nl",
    "en": "en-US",
    "en-GB": "en-GB",
    "de": "de-DE",
}

# Beperk automatische LT-edits om inhoudsschade te voorkomen.
_MAX_LT_APPLIED = 20
_LEXICAL_RULE_PREFIXES = (
    "MORFOLOGIK_RULE",
    "HUNSPELL_RULE",
)
_WORD_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ'-]+$")

SYSTEM_PROMPT = """\
You are an editor for a personal news podcast.
Rewrite the following news article into a podcast script.

Style:
- Write in correct, natural {language_name}. No bureaucratic or overly formal phrasing.
- Use short sentences, active voice. No jargon without explanation.
- Use punctuation actively to guide rhythm and intonation:
  - Em dashes (—) for a brief breathing pause or parenthetical.
  - Ellipses (...) for a dramatic or reflective pause.
  - Commas and semicolons for natural resting points.
  - Rhetorical questions for engagement.
- Alternate long and short sentences. A short sentence after a long one draws attention.
- Guide emphasis through word order: place the key word at the end or beginning of the sentence.
- Write numbers in words (fifteen million, not 15,000,000).
- Write abbreviations in full on first use \
(NATO becomes "NATO, the North Atlantic Treaty Organization" — adapt to the target language).
- Use natural transitions between paragraphs.

Intro:
{intro_instructions}

Closing:
- End with a brief one-sentence summary.

Length and format:
- Keep the length under 2 minutes of reading time (max ~1,500 characters).
- Divide the script into short paragraphs (3-5 sentences each), separated by a blank line. \
Each paragraph covers one point or aspect of the story. The blank lines create natural pauses when read aloud.
- Return ONLY the spoken script as plain text.
- Do NOT use markdown, headings, bullet points, or dividers.
- Do NOT use placeholders like [source] or [date] — if information is missing, leave it out.
- Do NOT invent facts, names, or quotes not in the original article."""

_INTRO_NL = """\
- Do NOT start with the same opening sentence every time. Vary the intro.
- Weave the source (NRC, NOS, New York Times, etc.) and topic into the first sentence. \
Examples of varied openings:
  "Uit de NRC: een verhaal over..."
  "De New York Times schrijft vandaag over..."
  "Op NOS.nl verscheen een artikel over..."
  "Een opvallend bericht uit de NRC vandaag..."
  "Volgens de New York Times..."
- If a date is available, incorporate it naturally (e.g., "afgelopen dinsdag", "vandaag"). \
Do NOT mention the date if it's missing.
- If the source is missing, start directly with the topic."""

_INTRO_OTHER = """\
- Start in {language_name} immediately and keep the ENTIRE script in {language_name}.
- Do NOT start with the same opening sentence every time. Vary the intro.
- Weave the source and topic naturally into the first sentence.
- If a date is available, incorporate it naturally. Do NOT mention the date if it's missing.
- If the source is missing, start directly with the topic."""


def generate_script(
    article: dict,
    api_key: str,
    model: str = "claude-haiku-4-5-20251001",
) -> str:
    """Genereer een podcastscript op basis van een artikeltekst.

    Args:
        article: dict met minimaal 'text', optioneel 'title', 'source', 'date', 'language'
        api_key: Anthropic API-key
        model: Claude-model om te gebruiken

    Returns:
        Podcastscript als string
    """
    language = article.get("language", "nl")
    language_name = _LANGUAGE_NAMES.get(language, "Dutch")

    logger.info(
        "Scriptgeneratie gestart: model=%s, taal=%s, titel='%s'",
        model, language, article.get("title", "?"),
    )
    client = anthropic.Anthropic(api_key=api_key)

    # Kies intro-instructies op basis van taal
    if language == "nl":
        intro_instructions = _INTRO_NL
    else:
        intro_instructions = _INTRO_OTHER.format(language_name=language_name)

    system_prompt = SYSTEM_PROMPT.format(
        language_name=language_name,
        intro_instructions=intro_instructions,
    )

    # Bouw de user-prompt op met beschikbare metadata
    parts = []
    if article.get("title"):
        parts.append(f"Title: {article['title']}")
    if article.get("source"):
        parts.append(f"Source: {article['source']}")
    if article.get("date"):
        parts.append(f"Date: {article['date']}")
    parts.append(f"Language: {language_name}")
    parts.append(f"\nArticle:\n{article['text']}")

    user_prompt = "\n".join(parts)
    logger.debug("Prompt opgebouwd: %d chars (artikel: %d chars)", len(user_prompt), len(article.get("text", "")))

    messages: list[anthropic.types.MessageParam] = [
        {"role": "user", "content": user_prompt},
    ]
    message = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=messages,
        system=system_prompt,
    )

    script = message.content[0].text
    usage = message.usage
    logger.info(
        "Claude response ontvangen: script=%d chars, input_tokens=%d, output_tokens=%d",
        len(script), usage.input_tokens, usage.output_tokens,
    )

    # Grammaticacontrole via LanguageTool
    script = _fix_grammar(script, language)

    return script


def _fix_grammar(text: str, language: str = "nl") -> str:
    """Corrigeer grammaticafouten via de gratis LanguageTool API.

    Stuurt de tekst naar de publieke LanguageTool API voor
    grammaticacontrole. Past automatisch correcties toe.
    Bij fouten wordt de originele tekst ongewijzigd teruggegeven.
    """
    lt_lang = _LANGUAGETOOL_CODES.get(language, "nl")
    logger.debug("Grammaticacontrole gestart (%d chars, taal=%s)", len(text), lt_lang)
    try:
        response = httpx.post(
            "https://api.languagetool.org/v2/check",
            data={
                "text": text,
                "language": lt_lang,
                "enabledOnly": "false",
            },
            timeout=10.0,
        )
        response.raise_for_status()
        matches = response.json().get("matches", [])
    except Exception as e:
        logger.warning("LanguageTool API niet bereikbaar (%s), grammaticacontrole overgeslagen", e)
        return text

    if not matches:
        logger.debug("Geen grammaticafouten gevonden")
        return text

    logger.info("LanguageTool: %d mogelijke correcties gevonden", len(matches))

    # Pas veilige correcties toe van achteren naar voren (zodat offsets kloppen)
    corrected = text
    applied = 0
    skipped_reasons: Counter[str] = Counter()
    for match in sorted(matches, key=lambda m: m["offset"], reverse=True):
        if applied >= _MAX_LT_APPLIED:
            logger.info("Grammaticacontrole: maximum van %d correcties bereikt", _MAX_LT_APPLIED)
            skipped_reasons["max_applied_bereikt"] += 1
            break

        should_apply, reason = _should_apply_lt_match(match, corrected)
        if not should_apply:
            skipped_reasons[reason] += 1
            logger.debug("Grammaticacorrectie overgeslagen (%s)", reason)
            continue

        replacements = match.get("replacements", [])
        offset = match["offset"]
        length = match["length"]
        fix = replacements[0]["value"]  # Eerste suggestie is meestal de beste
        original = corrected[offset:offset + length]
        corrected = corrected[:offset] + fix + corrected[offset + length:]
        logger.debug("Grammatica: '%s' → '%s' (regel: %s)", original, fix, match.get("rule", {}).get("id", "?"))
        applied += 1

    skipped_total = sum(skipped_reasons.values())
    top_reasons = ", ".join(f"{k}={v}" for k, v in skipped_reasons.most_common(4)) or "geen"
    logger.info(
        "Grammaticacontrole voltooid: toegepast=%d, overgeslagen=%d, redenen=%s",
        applied, skipped_total, top_reasons,
    )
    return corrected


def _should_apply_lt_match(match: dict, text: str) -> tuple[bool, str]:
    """Filter LanguageTool matches: alleen laag-risico correcties automatisch toepassen."""
    replacements = match.get("replacements", [])
    if not replacements:
        return False, "geen vervanging"

    offset = match.get("offset")
    length = match.get("length")
    if not isinstance(offset, int) or not isinstance(length, int) or offset < 0 or length < 0:
        return False, "ongeldige offset"
    if offset + length > len(text):
        return False, "offset buiten tekst"

    original = text[offset:offset + length]
    fix = replacements[0].get("value", "")
    if not fix or fix == original:
        return False, "lege of identieke vervanging"

    rule_id = match.get("rule", {}).get("id", "")
    if any(rule_id.startswith(prefix) for prefix in _LEXICAL_RULE_PREFIXES):
        return False, f"lexicale regel ({rule_id})"

    # Vermijd grotere herformuleringen; alleen single-token edits.
    if len(original.split()) != 1 or len(fix.split()) != 1:
        return False, "multi-token vervanging"

    # Vermijd edits op eigennamen/acroniemen en numerieke tokens.
    if any(ch.isdigit() for ch in original + fix):
        return False, "numerieke token"
    if original.isupper() or fix.isupper():
        return False, "hoofdlettertoken"

    original_word = original.strip(".,;:!?()[]{}\"'`")
    fix_word = fix.strip(".,;:!?()[]{}\"'`")
    if not original_word or not fix_word:
        return False, "lege woordkern"
    if not _WORD_RE.fullmatch(original_word) or not _WORD_RE.fullmatch(fix_word):
        return False, "niet-woordtoken"
    if not original_word.islower() or not fix_word.islower():
        return False, "mogelijk eigennaam"
    if abs(len(fix_word) - len(original_word)) > 3:
        return False, "te grote lengtesprong"

    return True, "veilig"
