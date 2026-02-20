"""FastAPI server voor de nieuws-naar-podcast pipeline."""

import os
import uuid
import tempfile
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from src.database import (
    EpisodeStatus,
    create_episode,
    get_episode,
    init_db,
    list_episodes,
    update_episode,
)
from src.extract import from_pdf, from_text, from_url
from src.feed import generate_feed
from src.scriptgen import generate_script
from src.tts import generate_audio

# Load secrets.env lokaal; op Railway staan env vars in het platform
_env_file = Path(__file__).parent / "secrets.env"
if _env_file.exists():
    load_dotenv(_env_file)

# --- Config ---

AUDIO_DIR = Path(os.getenv("AUDIO_DIR", "./output"))
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")


# --- Startup / Shutdown ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    await init_db()
    yield


app = FastAPI(
    title="Nieuws-naar-Podcast API",
    description="Zet nieuwsartikelen om naar podcastafleveringen",
    version="0.2.0",
    lifespan=lifespan,
)


# --- Auth ---

async def verify_api_key(request: Request):
    """Controleer de Bearer token op beveiligde endpoints."""
    if not API_KEY:
        return  # Geen key ingesteld = geen auth (alleen voor development)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != API_KEY:
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
    try:
        # Stap 1: Podcastscript genereren
        script = generate_script(article, api_key=ANTHROPIC_API_KEY)

        await update_episode(episode_id, script=script)

        # Stap 2: Audio genereren
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = (article.get("title", "podcast") or "podcast")[:50]
        import unicodedata
        slug = unicodedata.normalize("NFKD", slug).encode("ascii", "ignore").decode("ascii")
        slug = "".join(c if c.isalnum() or c in "-_ " else "" for c in slug).strip()
        slug = slug.replace(" ", "_") or "podcast"
        filename = f"{timestamp}_{slug}.mp3"
        output_path = AUDIO_DIR / filename

        generate_audio(
            script=script,
            output_path=str(output_path),
            api_key=ELEVENLABS_API_KEY,
            voice_id=ELEVENLABS_VOICE_ID,
        )

        # Stap 3: Duur schatten (~150 woorden per minuut bij TTS)
        word_count = len(script.split())
        duration_seconds = int(word_count / 150 * 60)

        await update_episode(
            episode_id,
            audio_filename=filename,
            duration_seconds=duration_seconds,
            status=EpisodeStatus.completed,
        )

    except Exception as e:
        traceback.print_exc()
        await update_episode(
            episode_id,
            status=EpisodeStatus.failed,
            error_message=str(e),
        )


# --- Endpoints ---

@app.post("/submit", response_model=SubmitResponse, dependencies=[Depends(verify_api_key)])
async def submit_article(req: SubmitRequest, background_tasks: BackgroundTasks):
    """Stuur een artikel in voor verwerking."""
    # Validatie: minstens text of url moet aanwezig zijn
    if not req.text and not req.url:
        raise HTTPException(
            status_code=400,
            detail="Geef minstens 'text' of 'url' mee.",
        )

    # Tekstextractie
    try:
        if req.text:
            article = from_text(req.text, title=req.title or "", source=req.source or "")
        else:
            article = from_url(req.url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Override metadata met request-waarden als die meegegeven zijn
    if req.title:
        article["title"] = req.title
    if req.source:
        article["source"] = req.source

    # Database record aanmaken
    episode = await create_episode(
        article_text=article["text"],
        title=article.get("title", "Zonder titel"),
        source=article.get("source"),
        source_url=req.url,
    )

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
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Alleen PDF-bestanden worden geaccepteerd.")

    # Sla PDF tijdelijk op
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        article = from_pdf(tmp_path)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if title:
        article["title"] = title
    if source:
        article["source"] = source

    episode = await create_episode(
        article_text=article["text"],
        title=article.get("title", "Zonder titel"),
        source=source,
    )

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
    xml = generate_feed(episodes, base_url=BASE_URL)
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


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
