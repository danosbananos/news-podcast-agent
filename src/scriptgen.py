"""Podcastscript genereren met Claude Haiku + grammaticacontrole."""

import logging

import anthropic
import httpx

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Je bent een redacteur voor een persoonlijke nieuwspodcast in het Nederlands.
Herschrijf het volgende nieuwsartikel naar een podcastscript.

Stijl:
- Schrijf in correct, natuurlijk Nederlands. Geen ambtelijke of schrijftalige formuleringen.
- Gebruik GEEN Engelse woorden, tenzij het eigennamen zijn (bijv. "Supreme Court") \
of gangbare leenwoorden die in het Nederlands geen goed alternatief hebben (bijv. "app", "software").
- Let op correct lidwoordgebruik: "het artikel", "de krant", "het onderzoek", "de politie". \
Gebruik bij twijfel het meest gangbare lidwoord.
- Korte zinnen, actieve vorm. Geen jargon zonder uitleg.
- Gebruik interpunctie actief om ritme en intonatie te sturen:
  - Gedachtestreepjes (—) voor een korte ademhalingspauze of bijzin.
  - Ellipsen (...) voor een dramatische of nadenkende pauze.
  - Komma's en puntkomma's voor natuurlijke rustmomenten.
  - Retorische vragen voor betrokkenheid ("Maar waarom eigenlijk?").
- Wissel lange en korte zinnen af. Een korte zin na een lange trekt de aandacht.
- Stuur klemtoon via woordvolgorde: plaats het belangrijkste woord aan het einde of begin van de zin. \
"Het gaat om honderd miljard dollar" legt nadruk op het bedrag. \
"Honderd miljard dollar — dat is waar het om gaat" legt nadruk op de conclusie. \
Vermijd zinnen waar het kernwoord weggestopt zit in het midden.
- Schrijf getallen voluit (vijftien miljoen, niet 15.000.000).
- Schrijf afkortingen voluit bij eerste gebruik \
(NATO wordt "de NAVO, de Noord-Atlantische Verdragsorganisatie").
- Gebruik natuurlijke overgangen tussen alinea's.

Intro:
- Begin NIET elke keer met dezelfde openingszin. Varieer de intro.
- Verwerk de bron (NRC, NOS, New York Times, etc.) en het onderwerp in de eerste zin. \
Voorbeelden van gevarieerde openingen:
  "Uit de NRC: een verhaal over..."
  "De New York Times schrijft vandaag over..."
  "Op NOS.nl verscheen een artikel over..."
  "Een opvallend bericht uit de NRC vandaag..."
  "Volgens de New York Times..."
- Als er een datum beschikbaar is, verwerk die natuurlijk (bijv. "afgelopen dinsdag", "vandaag", "eerder deze week"). \
Noem de datum NIET als die ontbreekt.
- Als de bron ontbreekt, begin dan direct met het onderwerp.

Afsluiting:
- Sluit af met een korte samenvatting in één zin.

Lengte en format:
- Houd de lengte onder de 2 minuten leestijd (maximaal ~1.500 karakters).
- Verdeel het script in korte alinea's (3-5 zinnen per alinea), gescheiden door een witregel. \
Elke alinea behandelt één punt of aspect van het verhaal. De witregels zorgen voor natuurlijke pauzes bij het voorlezen.
- Geef ALLEEN het uitgesproken script terug als platte tekst.
- Gebruik GEEN markdown, geen kopjes, geen opsommingstekens, geen scheidingslijnen.
- Gebruik GEEN placeholders zoals [bron] of [datum] — als informatie ontbreekt, laat het weg.
- Verzin GEEN feiten, namen, of citaten die niet in het originele artikel staan."""


def generate_script(
    article: dict,
    api_key: str,
    model: str = "claude-haiku-4-5-20251001",
) -> str:
    """Genereer een podcastscript op basis van een artikeltekst.

    Args:
        article: dict met minimaal 'text', optioneel 'title', 'source', 'date'
        api_key: Anthropic API-key
        model: Claude-model om te gebruiken

    Returns:
        Podcastscript als string
    """
    logger.info("Scriptgeneratie gestart: model=%s, titel='%s'", model, article.get("title", "?"))
    client = anthropic.Anthropic(api_key=api_key)

    # Bouw de user-prompt op met beschikbare metadata
    parts = []
    if article.get("title"):
        parts.append(f"Titel: {article['title']}")
    if article.get("source"):
        parts.append(f"Bron: {article['source']}")
    if article.get("date"):
        parts.append(f"Datum: {article['date']}")
    parts.append(f"\nArtikel:\n{article['text']}")

    user_prompt = "\n".join(parts)
    logger.debug("Prompt opgebouwd: %d chars (artikel: %d chars)", len(user_prompt), len(article.get("text", "")))

    message = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": user_prompt}],
        system=SYSTEM_PROMPT,
    )

    script = message.content[0].text
    usage = message.usage
    logger.info(
        "Claude response ontvangen: script=%d chars, input_tokens=%d, output_tokens=%d",
        len(script), usage.input_tokens, usage.output_tokens,
    )

    # Grammaticacontrole via LanguageTool
    script = _fix_grammar(script)

    return script


def _fix_grammar(text: str) -> str:
    """Corrigeer grammaticafouten via de gratis LanguageTool API.

    Stuurt de tekst naar de publieke LanguageTool API voor Nederlandse
    grammaticacontrole. Past automatisch correcties toe (bijv. 'sprang' → 'sprong').
    Bij fouten wordt de originele tekst ongewijzigd teruggegeven.
    """
    logger.debug("Grammaticacontrole gestart (%d chars)", len(text))
    try:
        response = httpx.post(
            "https://api.languagetool.org/v2/check",
            data={
                "text": text,
                "language": "nl",
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

    # Pas correcties toe van achteren naar voren (zodat offsets kloppen)
    corrected = text
    applied = 0
    for match in sorted(matches, key=lambda m: m["offset"], reverse=True):
        replacements = match.get("replacements", [])
        if not replacements:
            continue
        offset = match["offset"]
        length = match["length"]
        fix = replacements[0]["value"]  # Eerste suggestie is meestal de beste
        original = corrected[offset:offset + length]
        corrected = corrected[:offset] + fix + corrected[offset + length:]
        logger.info("Grammatica: '%s' → '%s' (regel: %s)", original, fix, match.get("rule", {}).get("id", "?"))
        applied += 1

    logger.info("Grammaticacontrole voltooid: %d correcties toegepast", applied)
    return corrected
