"""FastAPI server voor de nieuws-naar-podcast pipeline."""

import logging
import os
import re
import uuid
import tempfile
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# Logging configureren — LOG_LEVEL via env var instelbaar (default: INFO)
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    force=True,
)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from src.database import (
    EpisodeStatus,
    create_episode,
    delete_episode,
    delete_episodes_older_than,
    get_episode,
    init_db,
    list_episodes,
    update_episode,
)
from src.extract import from_pdf, from_text, from_url, from_url_metadata
from src.episode_image import process_episode_image
from src.feed import generate_feed
from src.notify import send as notify
from src.scriptgen import generate_script
from src.transcript import generate_transcript
from src.tts import generate_audio

# Load .env lokaal; op Railway staan env vars in het platform
_env_file = Path(__file__).parent / "secret_files" / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

# --- Config ---

AUDIO_DIR = Path(os.getenv("AUDIO_DIR", "./output"))
EPISODE_IMAGE_DIR = Path(os.getenv("EPISODE_IMAGE_DIR", str(AUDIO_DIR / "episode-images")))
TRANSCRIPT_DIR = Path(os.getenv("TRANSCRIPT_DIR", str(AUDIO_DIR / "transcripts")))
TRANSCRIPT_MODE = os.getenv("TRANSCRIPT_MODE", "none")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
TRANSCRIPT_OPENAI_API_KEY = os.getenv("TRANSCRIPT_OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")

logger.info("Config geladen: BASE_URL=%s, AUDIO_DIR=%s", BASE_URL, AUDIO_DIR)


# --- Startup / Shutdown ---

RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "14"))
NOTIFY_ON_DEPLOY = os.getenv("NOTIFY_ON_DEPLOY", "true").lower() in {"1", "true", "yes", "on"}


def _delete_audio_file(filename: str | None):
    """Verwijder een audiobestand van disk als het bestaat."""
    if filename:
        path = AUDIO_DIR / filename
        if path.exists():
            logger.debug("Audiobestand verwijderd: %s", path)
        path.unlink(missing_ok=True)


def _delete_transcript_file(audio_filename: str | None):
    """Verwijder transcriptbestand (VTT) gekoppeld aan audiobestand."""
    if not audio_filename:
        return
    stem = Path(audio_filename).stem
    path = TRANSCRIPT_DIR / f"{stem}.vtt"
    if path.exists():
        logger.debug("Transcriptbestand verwijderd: %s", path)
    path.unlink(missing_ok=True)


def _delete_episode_image_file(image_url: str | None):
    """Verwijder lokaal gehoste episode-image als die bestaat."""
    if not image_url:
        return
    path_part = urlparse(image_url).path or ""
    prefix = "/episode-images/"
    if not path_part.startswith(prefix):
        return
    filename = path_part.removeprefix(prefix)
    if "/" in filename or "\\" in filename or ".." in filename:
        return
    path = EPISODE_IMAGE_DIR / filename
    if path.exists():
        logger.debug("Episode-image verwijderd: %s", path)
    path.unlink(missing_ok=True)


def _materialize_episode_image(article: dict):
    """Zet remote image_url om naar lokaal gehoste vierkante JPEG voor Apple Podcasts."""
    image_url = article.get("image_url")
    if not image_url:
        return
    try:
        local_path = process_episode_image(image_url, EPISODE_IMAGE_DIR)
        article["image_url"] = f"{BASE_URL.rstrip('/')}/episode-images/{local_path.name}"
    except Exception as e:
        logger.warning("Episode-image verwerking mislukt (%s), gebruik originele image_url", e)


async def _cleanup_old_episodes():
    """Verwijder episodes ouder dan RETENTION_DAYS en hun audiobestanden."""
    episodes = await delete_episodes_older_than(days=RETENTION_DAYS)
    for ep in episodes:
        _delete_audio_file(ep.audio_filename)
        _delete_transcript_file(ep.audio_filename)
        _delete_episode_image_file(ep.image_url)
    if episodes:
        logger.info("Cleanup: %d episode(s) ouder dan %d dagen verwijderd", len(episodes), RETENTION_DAYS)
    else:
        logger.debug("Cleanup: geen oude episodes gevonden")


async def _cleanup_orphaned_episodes():
    """Verwijder database-records waarvan het audiobestand ontbreekt (bijv. na deploy zonder volume)."""
    episodes = await list_episodes(limit=200)
    orphaned = [ep for ep in episodes if ep.audio_filename and not (AUDIO_DIR / ep.audio_filename).exists()]
    for ep in orphaned:
        logger.debug("Orphaned episode verwijderd: %s (%s)", ep.title, ep.id)
        _delete_transcript_file(ep.audio_filename)
        _delete_episode_image_file(ep.image_url)
        await delete_episode(ep.id)
    if orphaned:
        logger.info("Cleanup: %d episode(s) zonder audiobestand verwijderd", len(orphaned))
    else:
        logger.debug("Cleanup: geen orphaned episodes gevonden")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Server start — audio_dir=%s, retention=%d dagen", AUDIO_DIR, RETENTION_DAYS)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    EPISODE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    await init_db()
    # Ruim op bij elke (her)start
    await _cleanup_old_episodes()
    await _cleanup_orphaned_episodes()
    logger.info("Server klaar voor requests")
    if NOTIFY_ON_DEPLOY:
        commit = os.getenv("RAILWAY_GIT_COMMIT_SHA", "")[:7]
        release = os.getenv("RAILWAY_RELEASE_ID", "")
        deploy_ref = commit or release or "onbekend"
        notify(
            title="Deployment voltooid",
            message=f"Server klaar op {BASE_URL} (deploy: {deploy_ref})",
            tags="rocket,server",
        )
    yield
    logger.info("Server stopt")


app = FastAPI(
    title="Nieuws-naar-Podcast API",
    description="Zet nieuwsartikelen om naar podcastafleveringen",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS: nodig voor de bookmarklet die vanaf andere domeinen (nrc.nl, nytimes.com, etc.) fetch doet
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


# --- Auth ---

async def verify_api_key(request: Request):
    """Controleer de Bearer token op beveiligde endpoints."""
    if not API_KEY:
        logger.debug("Auth overgeslagen — geen API_KEY geconfigureerd")
        return  # Geen key ingesteld = geen auth (alleen voor development)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != API_KEY:
        logger.warning("Ongeldige API-key poging van %s op %s", request.client.host if request.client else "?", request.url.path)
        raise HTTPException(status_code=401, detail="Ongeldige of ontbrekende API-key")


# --- Request/Response models ---

class SubmitRequest(BaseModel):
    url: Optional[str] = None
    text: Optional[str] = None
    title: Optional[str] = ""
    source: Optional[str] = ""


class SubmitResponse(BaseModel):
    status: str
    episode_id: str
    message: str


class EpisodeResponse(BaseModel):
    id: str
    title: str
    source: Optional[str]
    source_url: Optional[str]
    status: str
    audio_url: Optional[str]
    created_at: str
    error_message: Optional[str]


# --- Achtergrondverwerking ---

async def process_article(episode_id: uuid.UUID, article: dict):
    """Verwerk een artikel: genereer script → audio → update database."""
    title = article.get("title", "?")
    logger.info("Verwerking gestart: episode=%s titel='%s'", episode_id, title)
    try:
        # Stap 1: Podcastscript genereren
        logger.info("Stap 1/4: Script genereren voor '%s'", title)
        script = generate_script(article, api_key=ANTHROPIC_API_KEY)
        logger.info("Script gegenereerd: %d karakters, %d woorden", len(script), len(script.split()))

        await update_episode(episode_id, script=script)

        # Stap 2: Audio genereren
        logger.info("Stap 2/4: Audio genereren voor '%s'", title)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = (article.get("title", "podcast") or "podcast")[:50]
        import unicodedata
        slug = unicodedata.normalize("NFKD", slug).encode("ascii", "ignore").decode("ascii")
        slug = "".join(c if c.isalnum() or c in "-_ " else "" for c in slug).strip()
        slug = slug.replace(" ", "_") or "podcast"
        filename = f"{timestamp}_{slug}.mp3"
        output_path = AUDIO_DIR / filename

        language = article.get("language", "nl")
        generate_audio(
            script=script,
            output_path=str(output_path),
            api_key=ELEVENLABS_API_KEY,
            language=language,
        )

        # Stap 3: Duur schatten (~150 woorden per minuut bij TTS)
        word_count = len(script.split())
        duration_seconds = int(word_count / 150 * 60)
        logger.info("Stap 3/4: Transcript genereren (mode=%s) voor '%s'", TRANSCRIPT_MODE, title)
        transcript_path = generate_transcript(
            script=script,
            audio_path=output_path,
            output_dir=TRANSCRIPT_DIR,
            language=language,
            duration_seconds=duration_seconds,
            mode=TRANSCRIPT_MODE,
            openai_api_key=TRANSCRIPT_OPENAI_API_KEY,
        )
        if transcript_path:
            logger.info("Transcript gekoppeld aan episode: %s", transcript_path.name)
        else:
            logger.info("Geen transcript gekoppeld (mode=%s)", TRANSCRIPT_MODE)

        logger.info("Stap 4/4: Episode afronden — duur=%ds, bestand=%s", duration_seconds, filename)

        await update_episode(
            episode_id,
            audio_filename=filename,
            duration_seconds=duration_seconds,
            status=EpisodeStatus.completed,
        )
        logger.info("Verwerking voltooid: episode=%s titel='%s'", episode_id, title)
        notify(
            title=f"Podcast klaar: {title}",
            message=f"Duur: {duration_seconds // 60}m{duration_seconds % 60:02d}s",
            tags="white_check_mark,podcast",
        )

    except Exception as e:
        logger.error("Verwerking mislukt: episode=%s titel='%s' fout=%s", episode_id, title, e, exc_info=True)
        # Sanitize: alleen het type en de eerste regel bewaren, geen stack traces
        # of interne paden naar de client/ntfy sturen
        safe_msg = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
        await update_episode(
            episode_id,
            status=EpisodeStatus.failed,
            error_message=safe_msg,
        )
        notify(
            title=f"Podcast mislukt: {title}",
            message=safe_msg,
            priority="high",
            tags="warning,podcast",
        )


# --- Endpoints ---

@app.post("/submit", response_model=SubmitResponse, dependencies=[Depends(verify_api_key)])
async def submit_article(req: SubmitRequest, background_tasks: BackgroundTasks):
    """Stuur een artikel in voor verwerking."""
    logger.info("POST /submit — url=%s, text=%s chars, title='%s'", req.url, len(req.text) if req.text else 0, req.title)

    # Validatie: minstens text of url moet aanwezig zijn
    if not req.text and not req.url:
        logger.warning("Submit afgewezen: geen text of url meegegeven")
        raise HTTPException(
            status_code=400,
            detail="Geef minstens 'text' of 'url' mee.",
        )

    # URL opschonen: apps zoals NRC delen soms "Titel https://..." als één string
    if req.url:
        url_match = re.search(r'https?://\S+', req.url)
        if url_match:
            cleaned_url = url_match.group(0)
            if cleaned_url != req.url:
                logger.debug("URL opgeschoond: '%s' → '%s'", req.url, cleaned_url)
            req.url = cleaned_url

    # Tekstextractie
    try:
        if req.text:
            logger.debug("Extractie via meegegeven tekst (%d chars)", len(req.text))
            article = from_text(req.text, title=req.title or "", source=req.source or "")
        else:
            logger.debug("Extractie via URL: %s", req.url)
            article = from_url(req.url)
    except ValueError as e:
        logger.warning("Extractie mislukt: %s", e)
        raise HTTPException(status_code=422, detail=str(e))

    # Override metadata met request-waarden als die meegegeven zijn
    if req.title:
        article["title"] = req.title
    if req.source:
        article["source"] = req.source

    # Bij text+url: verrijk metadata uit URL (vooral image_url) zonder tekst te overschrijven.
    if req.text and req.url:
        try:
            metadata = from_url_metadata(req.url)
            if metadata.get("image_url"):
                article["image_url"] = metadata["image_url"]
            if not article.get("source") and metadata.get("source"):
                article["source"] = metadata["source"]
            if not article.get("title") and metadata.get("title"):
                article["title"] = metadata["title"]
            if not article.get("date") and metadata.get("date"):
                article["date"] = metadata["date"]
        except ValueError as e:
            logger.info("URL metadata-verrijking overgeslagen: %s", e)

    _materialize_episode_image(article)

    # Database record aanmaken
    episode = await create_episode(
        article_text=article["text"],
        title=article.get("title", "Zonder titel"),
        source=article.get("source"),
        source_url=req.url,
        image_url=article.get("image_url"),
    )
    logger.info("Episode aangemaakt: id=%s, titel='%s', bron=%s", episode.id, article.get("title"), article.get("source"))

    # Verwerking op de achtergrond starten
    background_tasks.add_task(process_article, episode.id, article)

    return SubmitResponse(
        status="processing",
        episode_id=str(episode.id),
        message=f"Artikel '{article.get('title', 'Zonder titel')}' wordt verwerkt!",
    )


@app.post("/upload", response_model=SubmitResponse, dependencies=[Depends(verify_api_key)])
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: Optional[str] = None,
    source: Optional[str] = None,
):
    """Upload een PDF voor verwerking."""
    logger.info("POST /upload — bestand='%s', title='%s'", file.filename, title)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        logger.warning("Upload afgewezen: geen PDF — '%s'", file.filename)
        raise HTTPException(status_code=400, detail="Alleen PDF-bestanden worden geaccepteerd.")

    # Sla PDF tijdelijk op
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    logger.debug("PDF opgeslagen als temp: %s (%d bytes)", tmp_path, len(content))

    try:
        article = from_pdf(tmp_path)
    except ValueError as e:
        logger.warning("PDF extractie mislukt: %s", e)
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if title:
        article["title"] = title
    if source:
        article["source"] = source

    _materialize_episode_image(article)

    episode = await create_episode(
        article_text=article["text"],
        title=article.get("title", "Zonder titel"),
        source=source,
        image_url=article.get("image_url"),
    )
    logger.info("Episode aangemaakt vanuit PDF: id=%s, titel='%s'", episode.id, article.get("title"))

    background_tasks.add_task(process_article, episode.id, article)

    return SubmitResponse(
        status="processing",
        episode_id=str(episode.id),
        message=f"PDF '{file.filename}' wordt verwerkt!",
    )


@app.get("/feed.xml")
async def get_feed():
    """Serveer de podcast RSS feed (publiek, geen auth)."""
    episodes = await list_episodes(limit=50)
    logger.debug("Feed gegenereerd met %d episodes", len(episodes))
    xml = generate_feed(episodes, base_url=BASE_URL)
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


@app.get("/static/{filename}")
async def get_static(filename: str):
    """Serveer statische bestanden (cover art etc.)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Ongeldige bestandsnaam")
    path = Path(__file__).parent / "static" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Bestand niet gevonden")
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".html": "text/html", ".css": "text/css", ".js": "application/javascript"}
    media_type = media_types.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@app.get("/setup", response_class=HTMLResponse)
async def setup_page():
    """Setup-pagina met Shortcut instructies en bookmarklet (publiek, geen auth)."""
    path = Path(__file__).parent / "static" / "setup.html"
    return HTMLResponse(content=path.read_text(encoding="utf-8"))


@app.get("/audio/{filename}")
async def get_audio(filename: str):
    """Serveer een mp3-bestand (publiek, geen auth)."""
    # Voorkom path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Ongeldige bestandsnaam")

    path = AUDIO_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audiobestand niet gevonden")

    return FileResponse(path, media_type="audio/mpeg", filename=filename)


@app.get("/episode-images/{filename}")
async def get_episode_image(filename: str):
    """Serveer lokaal opgeslagen episode-artwork."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Ongeldige bestandsnaam")

    path = EPISODE_IMAGE_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Afbeelding niet gevonden")

    return FileResponse(path, media_type="image/jpeg", filename=filename)


@app.get("/transcripts/{filename}")
async def get_transcript(filename: str):
    """Serveer transcriptbestand (VTT)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Ongeldige bestandsnaam")

    path = TRANSCRIPT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Transcript niet gevonden")

    return FileResponse(path, media_type="text/vtt; charset=utf-8", filename=filename)


@app.get("/episodes", response_model=list[EpisodeResponse])
async def get_episodes():
    """Lijst van alle afleveringen (voor debugging/dashboard)."""
    episodes = await list_episodes(limit=50)
    return [_episode_to_response(ep) for ep in episodes]


@app.get("/episodes/{episode_id}", response_model=EpisodeResponse)
async def get_episode_detail(episode_id: str):
    """Details van één aflevering."""
    try:
        ep_uuid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ongeldig episode ID")

    episode = await get_episode(ep_uuid)
    if not episode:
        raise HTTPException(status_code=404, detail="Aflevering niet gevonden")

    return _episode_to_response(episode)


@app.delete("/episodes/{episode_id}", dependencies=[Depends(verify_api_key)])
async def delete_episode_endpoint(episode_id: str):
    """Verwijder een aflevering en het bijbehorende audiobestand."""
    try:
        ep_uuid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ongeldig episode ID")

    episode = await delete_episode(ep_uuid)
    if not episode:
        raise HTTPException(status_code=404, detail="Aflevering niet gevonden")

    _delete_audio_file(episode.audio_filename)
    _delete_transcript_file(episode.audio_filename)
    _delete_episode_image_file(episode.image_url)
    logger.info("Episode verwijderd: id=%s, titel='%s'", episode_id, episode.title)
    return {"status": "deleted", "title": episode.title}


def _episode_to_response(ep) -> EpisodeResponse:
    audio_url = None
    if ep.audio_filename:
        audio_url = f"{BASE_URL}/audio/{ep.audio_filename}"

    return EpisodeResponse(
        id=str(ep.id),
        title=ep.title,
        source=ep.source,
        source_url=ep.source_url,
        status=ep.status.value if isinstance(ep.status, EpisodeStatus) else ep.status,
        audio_url=audio_url,
        created_at=ep.created_at.isoformat() if ep.created_at else "",
        error_message=ep.error_message,
    )
