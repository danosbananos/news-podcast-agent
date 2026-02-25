"""Podcastscript genereren met Claude Haiku."""

import anthropic

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

    message = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": user_prompt}],
        system=SYSTEM_PROMPT,
    )

    return message.content[0].text
