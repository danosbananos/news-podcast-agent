"""Podcastscript genereren met Claude Haiku."""

import anthropic

SYSTEM_PROMPT = """\
Je bent een redacteur voor een persoonlijke nieuwspodcast in het Nederlands.
Herschrijf het volgende nieuwsartikel naar een podcastscript.

Regels:
- Begin met een korte intro die de bron en datum noemt als die beschikbaar zijn. \
Als bron of datum ontbreekt, sla die dan gewoon over in de intro.
- Herschrijf de tekst voor gesproken taal: korte zinnen, actieve vorm, \
geen jargon zonder uitleg
- Schrijf getallen voluit (15 miljoen, niet 15.000.000)
- Schrijf afkortingen voluit bij eerste gebruik \
(NATO wordt "de NAVO, de Noord-Atlantische Verdragsorganisatie")
- Gebruik natuurlijke overgangen tussen alinea's
- Sluit af met een korte samenvatting in één zin
- Houd de lengte onder de 2 minuten leestijd \
(maximaal ~1.500 karakters) om API-kosten beheersbaar te houden
- Geef ALLEEN het uitgesproken script terug als platte tekst
- Gebruik GEEN markdown, geen kopjes, geen opsommingstekens, geen scheidingslijnen
- Gebruik GEEN placeholders zoals [bron] of [datum] — als informatie ontbreekt, laat het weg"""


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
