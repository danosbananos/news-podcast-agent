"""Tekstextractie uit URL, platte tekst of PDF."""

import re
from urllib.parse import urlparse

import trafilatura
import pdfplumber
from pathlib import Path


def _extract_html_title(html: str) -> str:
    """Haal de <title> tag uit HTML als fallback."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        # Strip site suffix like " - NOS"
        title = match.group(1).strip()
        title = re.split(r"\s*[|\-–—]\s*(?=[^|]*$)", title)[0].strip()
        return title
    return ""


def _domain_to_source(url: str) -> str:
    """Haal een leesbare bronnaam uit het domein (nos.nl → NOS)."""
    hostname = urlparse(url).hostname or ""
    # Verwijder www. en TLD
    name = hostname.removeprefix("www.").split(".")[0]
    return name.upper() if len(name) <= 4 else name.capitalize()


def from_url(url: str) -> dict:
    """Haal artikeltekst op via URL (werkt alleen voor niet-paywalled artikelen)."""
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise ValueError(f"Kon pagina niet ophalen: {url}")

    # Extraheer tekst + metadata via bare_extraction (retourneert Document object)
    doc = trafilatura.bare_extraction(
        downloaded,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )

    text = doc.text if doc else ""
    if not text or len(text.strip()) < 100:
        raise ValueError(
            "Geen bruikbare tekst gevonden. Artikel mogelijk achter paywall — "
            "stuur de tekst mee via bookmarklet/Shortcut, of upload als PDF."
        )

    # Gebruik trafilatura-metadata, met fallbacks voor title en source
    title = (doc.title if doc else None) or _extract_html_title(downloaded) or ""
    source = (doc.sitename if doc else None) or _domain_to_source(url)

    return {
        "text": text,
        "title": title,
        "author": (doc.author if doc else None) or "",
        "source": source,
        "date": (doc.date if doc else None) or "",
    }


def from_pdf(pdf_path: str) -> dict:
    """Extraheer tekst uit een PDF-bestand."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF niet gevonden: {pdf_path}")

    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                pages.append(page_text)

    text = "\n\n".join(pages)
    if len(text.strip()) < 100:
        raise ValueError("Kon geen bruikbare tekst uit de PDF extraheren.")

    return {"text": text, "title": path.stem}


def from_text(text: str, title: str = "", source: str = "") -> dict:
    """Wikkel platte tekst in het standaardformaat."""
    if len(text.strip()) < 50:
        raise ValueError("Tekst is te kort om een podcastscript van te maken.")
    return {"text": text, "title": title, "source": source}
