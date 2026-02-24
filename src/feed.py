"""RSS feed generator voor Apple Podcasts-compatibele podcast feed."""

import os
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree, register_namespace, tostring

# iTunes namespace — registreer vóór het bouwen van elementen
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
register_namespace("itunes", ITUNES_NS)
register_namespace("content", "http://purl.org/rss/1.0/modules/content/")


def generate_feed(episodes: list, base_url: str) -> str:
    """Genereer een Apple Podcasts-compatibele RSS feed.

    Args:
        episodes: Lijst van Episode-objecten (database records) met status 'completed'
        base_url: Publieke URL van de server (bijv. https://jouw-app.up.railway.app)

    Returns:
        Volledige RSS XML als string
    """
    base_url = base_url.rstrip("/")

    # Feed-metadata uit environment variabelen
    podcast_title = os.getenv("PODCAST_TITLE", "Mijn Nieuwspodcast")
    podcast_description = os.getenv(
        "PODCAST_DESCRIPTION",
        "Nieuwsartikelen omgezet naar podcast met AI",
    )
    podcast_author = os.getenv("PODCAST_AUTHOR", "Nieuwspodcast")
    podcast_language = os.getenv("PODCAST_LANGUAGE", "nl")
    podcast_image = os.getenv("PODCAST_IMAGE_URL", "")

    # Root element (namespaces worden via register_namespace afgehandeld)
    rss = Element("rss", {"version": "2.0"})

    channel = SubElement(rss, "channel")

    # Channel-level metadata
    SubElement(channel, "title").text = podcast_title
    SubElement(channel, "description").text = podcast_description
    SubElement(channel, "language").text = podcast_language
    SubElement(channel, "link").text = base_url
    SubElement(channel, f"{{{ITUNES_NS}}}author").text = podcast_author
    SubElement(channel, f"{{{ITUNES_NS}}}summary").text = podcast_description
    SubElement(channel, f"{{{ITUNES_NS}}}explicit").text = "no"
    SubElement(channel, f"{{{ITUNES_NS}}}type").text = "episodic"

    # Podcast-categorie
    category = SubElement(channel, f"{{{ITUNES_NS}}}category")
    category.set("text", "News")

    # Podcast owner (vereist door Apple)
    owner = SubElement(channel, f"{{{ITUNES_NS}}}owner")
    SubElement(owner, f"{{{ITUNES_NS}}}name").text = podcast_author
    owner_email = os.getenv("PODCAST_OWNER_EMAIL", "")
    if owner_email:
        SubElement(owner, f"{{{ITUNES_NS}}}email").text = owner_email

    # Podcast afbeelding (optioneel maar aanbevolen)
    if podcast_image:
        img = SubElement(channel, f"{{{ITUNES_NS}}}image")
        img.set("href", podcast_image)
        image = SubElement(channel, "image")
        SubElement(image, "url").text = podcast_image
        SubElement(image, "title").text = podcast_title
        SubElement(image, "link").text = base_url

    # Episodes als items (alleen episodes met een bestaand audiobestand)
    for ep in episodes:
        if not ep.audio_filename or _get_file_size(ep.audio_filename) == 0:
            continue
        item = SubElement(channel, "item")

        SubElement(item, "title").text = ep.title or "Zonder titel"
        SubElement(item, "description").text = _make_description(ep)
        SubElement(item, f"{{{ITUNES_NS}}}summary").text = _make_description(ep)
        SubElement(item, f"{{{ITUNES_NS}}}author").text = podcast_author
        SubElement(item, f"{{{ITUNES_NS}}}explicit").text = "no"

        # GUID (uniek per aflevering)
        guid = SubElement(item, "guid", isPermaLink="false")
        guid.text = str(ep.id)

        # Publicatiedatum (RFC 2822)
        if ep.created_at:
            SubElement(item, "pubDate").text = format_datetime(ep.created_at)

        # Duur
        if ep.duration_seconds:
            minutes, seconds = divmod(ep.duration_seconds, 60)
            SubElement(item, f"{{{ITUNES_NS}}}duration").text = f"{minutes}:{seconds:02d}"

        # Audio enclosure
        if ep.audio_filename:
            audio_url = f"{base_url}/audio/{ep.audio_filename}"
            audio_size = _get_file_size(ep.audio_filename)
            SubElement(item, "enclosure", {
                "url": audio_url,
                "length": str(audio_size),
                "type": "audio/mpeg",
            })

    # Serialize naar string
    xml_bytes = tostring(rss, encoding="unicode", xml_declaration=False)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_bytes}'


def _make_description(episode) -> str:
    """Maak een korte beschrijving voor de feed-item."""
    parts = []
    if episode.source:
        parts.append(f"Bron: {episode.source}")
    if episode.source_url:
        parts.append(f"Origineel artikel: {episode.source_url}")
    if episode.script:
        # Eerste 200 karakters van het script als preview
        preview = episode.script[:200].rsplit(" ", 1)[0]
        if len(episode.script) > 200:
            preview += "..."
        parts.append(preview)
    return " | ".join(parts) if parts else "Nieuwspodcast aflevering"


def _get_file_size(audio_filename: str) -> int:
    """Haal de bestandsgrootte op van een mp3-bestand."""
    audio_dir = os.getenv("AUDIO_DIR", "./output")
    path = Path(audio_dir) / audio_filename
    if path.exists():
        return path.stat().st_size
    return 0
