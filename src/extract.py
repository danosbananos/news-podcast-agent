"""Tekstextractie uit URL, platte tekst of PDF."""

import logging
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pdfplumber
import trafilatura
from langdetect import detect, LangDetectException

logger = logging.getLogger(__name__)

# Browser-achtige headers voor sites met bot-detectie (bijv. NYT)
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                  "Version/17.0 Safari/605.1.15",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}


_SUPPORTED_LANGUAGES = {"nl", "en", "de"}

# Bekende Britse domeinen — als het domein hierin voorkomt, wordt "en" → "en-GB"
# Alles onder .uk wordt automatisch herkend; deze set is voor .com-domeinen
_UK_DOMAINS_COM = {
    "bbc.com",
    "theguardian.com",
    "thetimes.com",
    "ft.com",
    "economist.com",
    "reuters.com",
}


def _normalize_domain(value: str | None) -> str:
    """Normaliseer URL of domeinnaam naar een kaal domein zonder www."""
    if not value:
        return ""
    parsed = urlparse(value)
    hostname = parsed.hostname or value
    return hostname.removeprefix("www.").lower()


def _detect_language(text: str, url: str | None = None, source: str | None = None) -> str:
    """Detecteer de taal van een tekst. Retourneert taalcode ('nl', 'en', 'en-GB', 'de').

    Voor Engelstalige teksten van bekende UK-domeinen wordt 'en-GB' teruggegeven.
    Valt terug op 'nl' als de taal niet gedetecteerd kan worden of niet ondersteund is.
    """
    try:
        lang = detect(text)
        if lang not in _SUPPORTED_LANGUAGES:
            logger.info("Taal '%s' niet ondersteund, fallback naar 'nl'", lang)
            return "nl"
        # Verfijn Engels naar en-GB als het domein Brits is (via url of source)
        if lang == "en":
            domain = _normalize_domain(url) or _normalize_domain(source)
            if domain.endswith(".uk") or domain in _UK_DOMAINS_COM:
                logger.info("Taal gedetecteerd: en-GB (domein %s)", domain)
                return "en-GB"
        logger.info("Taal gedetecteerd: %s", lang)
        return lang
    except LangDetectException as e:
        logger.warning("Taaldetectie mislukt (%s), fallback naar 'nl'", e)
        return "nl"


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


def _fetch_with_browser_headers(url: str) -> str | None:
    """Fallback-fetch met browser-achtige headers voor sites met bot-detectie."""
    try:
        req = Request(url, headers=_BROWSER_HEADERS)
        with urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            logger.debug("Browser-fetch geslaagd: %d bytes van %s", len(html), url)
            return html
    except Exception as e:
        logger.warning("Browser-fetch ook mislukt voor %s: %s", url, e)
        return None


def from_url(url: str) -> dict:
    """Haal artikeltekst op via URL. Gebruikt browser-headers als fallback."""
    logger.info("URL extractie gestart: %s", url)
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        # Fallback: sommige sites (NYT) blokkeren trafilatura's headers
        logger.info("trafilatura.fetch_url mislukt, probeer browser-headers voor %s", url)
        downloaded = _fetch_with_browser_headers(url)
    if not downloaded:
        logger.error("Kon pagina niet ophalen (beide methoden mislukt): %s", url)
        raise ValueError(f"Kon pagina niet ophalen: {url}")

    logger.debug("HTML opgehaald: %d bytes van %s", len(downloaded), url)

    # Extraheer tekst + metadata via bare_extraction (retourneert Document object)
    doc = trafilatura.bare_extraction(
        downloaded,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )

    text = doc.text if doc else ""
    if not text or len(text.strip()) < 100:
        logger.warning("Onvoldoende tekst geëxtraheerd (%d chars) van %s — mogelijk paywall", len(text.strip()) if text else 0, url)
        raise ValueError(
            "Geen bruikbare tekst gevonden. Artikel mogelijk achter paywall — "
            "stuur de tekst mee via bookmarklet/Shortcut, of upload als PDF."
        )

    # Gebruik trafilatura-metadata, met fallbacks voor title en source
    title = (doc.title if doc else None) or _extract_html_title(downloaded) or ""
    source = (doc.sitename if doc else None) or _domain_to_source(url)

    language = _detect_language(text, url=url)
    logger.info("URL extractie voltooid: titel='%s', bron=%s, taal=%s, tekst=%d chars", title, source, language, len(text))

    return {
        "text": text,
        "title": title,
        "author": (doc.author if doc else None) or "",
        "source": source,
        "date": (doc.date if doc else None) or "",
        "language": language,
    }


def from_pdf(pdf_path: str) -> dict:
    """Extraheer tekst uit een PDF-bestand."""
    logger.info("PDF extractie gestart: %s", pdf_path)
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF niet gevonden: {pdf_path}")

    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                pages.append(page_text)
        logger.debug("PDF gelezen: %d pagina's, %d met tekst", len(pdf.pages), len(pages))

    text = "\n\n".join(pages)
    if len(text.strip()) < 100:
        logger.warning("Onvoldoende tekst uit PDF (%d chars): %s", len(text.strip()), pdf_path)
        raise ValueError("Kon geen bruikbare tekst uit de PDF extraheren.")

    language = _detect_language(text)
    logger.info("PDF extractie voltooid: %d pagina's, %d chars, taal=%s", len(pages), len(text), language)
    return {"text": text, "title": path.stem, "language": language}


def from_text(text: str, title: str = "", source: str = "") -> dict:
    """Wikkel platte tekst in het standaardformaat."""
    if len(text.strip()) < 50:
        logger.warning("Tekst te kort: %d chars (minimaal 50)", len(text.strip()))
        raise ValueError("Tekst is te kort om een podcastscript van te maken.")
    language = _detect_language(text, source=source)
    logger.info("Tekst-extractie: titel='%s', bron='%s', taal=%s, %d chars", title, source, language, len(text))
    return {"text": text, "title": title, "source": source, "language": language}
