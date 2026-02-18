"""Tekstextractie uit URL, platte tekst of PDF."""

import trafilatura
import pdfplumber
from pathlib import Path


def from_url(url: str) -> dict:
    """Haal artikeltekst op via URL (werkt alleen voor niet-paywalled artikelen)."""
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise ValueError(f"Kon pagina niet ophalen: {url}")

    text = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text or len(text.strip()) < 100:
        raise ValueError(
            "Geen bruikbare tekst gevonden. Artikel mogelijk achter paywall — "
            "stuur de tekst mee via bookmarklet/Shortcut, of upload als PDF."
        )

    metadata = trafilatura.extract(
        downloaded,
        include_comments=False,
        output_format="json",
        only_with_metadata=False,
    )

    # Trafilatura's JSON output is een string; parse titel/auteur er handmatig uit
    import json
    meta = {}
    if metadata:
        try:
            parsed = json.loads(metadata)
            meta["title"] = parsed.get("title", "")
            meta["author"] = parsed.get("author", "")
            meta["source"] = parsed.get("sitename", "")
            meta["date"] = parsed.get("date", "")
        except json.JSONDecodeError:
            pass

    return {"text": text, **meta}


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
