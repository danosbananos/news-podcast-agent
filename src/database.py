"""Database models en CRUD voor podcast-afleveringen (PostgreSQL + SQLAlchemy async)."""

import enum
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Enum, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


# --- Enum ---

class EpisodeStatus(str, enum.Enum):
    processing = "processing"
    completed = "completed"
    failed = "failed"


# --- Model ---

class Base(DeclarativeBase):
    pass


class Episode(Base):
    __tablename__ = "episodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(500), nullable=False, default="Zonder titel")
    source = Column(String(200), nullable=True)
    source_url = Column(String(2000), nullable=True)
    article_text = Column(Text, nullable=False)
    script = Column(Text, nullable=True)
    audio_filename = Column(String(500), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    status = Column(
        Enum(EpisodeStatus, name="episode_status"),
        nullable=False,
        default=EpisodeStatus.processing,
    )
    error_message = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


# --- Engine & Session ---

_engine = None
_session_factory = None


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise ValueError("DATABASE_URL environment variable is niet ingesteld.")
    # Railway geeft soms postgres:// i.p.v. postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif not url.startswith("postgresql+asyncpg://"):
        url = f"postgresql+asyncpg://{url}"
    return url


def get_engine():
    global _engine
    if _engine is None:
        url = get_database_url()
        connect_args = {}
        # Railway's interne Postgres draait zonder SSL; asyncpg probeert
        # standaard SSL-negotiatie wat een timeout veroorzaakt.
        # Intern verkeer blijft binnen Railway's private netwerk.
        if ".railway.internal" in os.getenv("DATABASE_URL", ""):
            connect_args["ssl"] = False
            logger.debug("SSL uitgeschakeld voor Railway intern verkeer")
        _engine = create_async_engine(url, echo=False, connect_args=connect_args)
        logger.debug("Database engine aangemaakt")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def init_db():
    """Maak tabellen aan als ze niet bestaan. Retry voor Railway's private netwerk startup."""
    import asyncio
    engine = get_engine()
    last_error = None
    logger.info("Database initialisatie gestart")
    for attempt in range(5):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tabellen aangemaakt/geverifieerd")
            return
        except Exception as e:
            last_error = e
            wait = 2 ** attempt
            logger.warning("DB verbinding mislukt (poging %d/5), retry in %ds: %s", attempt + 1, wait, e)
            await asyncio.sleep(wait)
    logger.error("Database initialisatie mislukt na 5 pogingen")
    raise last_error


# --- CRUD ---

async def create_episode(
    article_text: str,
    title: str = "Zonder titel",
    source: Optional[str] = None,
    source_url: Optional[str] = None,
) -> Episode:
    """Maak een nieuw episode-record aan met status 'processing'."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        episode = Episode(
            title=title,
            source=source,
            source_url=source_url,
            article_text=article_text,
            status=EpisodeStatus.processing,
        )
        session.add(episode)
        await session.commit()
        await session.refresh(episode)
        logger.debug("Episode aangemaakt: id=%s, titel='%s', tekst=%d chars", episode.id, title, len(article_text))
        return episode


async def update_episode(
    episode_id: uuid.UUID,
    **kwargs,
) -> Optional[Episode]:
    """Update een episode met willekeurige velden."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        episode = await session.get(Episode, episode_id)
        if not episode:
            logger.warning("Update mislukt — episode niet gevonden: %s", episode_id)
            return None
        for key, value in kwargs.items():
            if hasattr(episode, key):
                setattr(episode, key, value)
        await session.commit()
        await session.refresh(episode)
        logger.debug("Episode bijgewerkt: id=%s, velden=%s", episode_id, list(kwargs.keys()))
        return episode


async def get_episode(episode_id: uuid.UUID) -> Optional[Episode]:
    """Haal één episode op."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        return await session.get(Episode, episode_id)


async def delete_episode(episode_id: uuid.UUID) -> Optional[Episode]:
    """Verwijder een episode en geef het verwijderde object terug (voor bestandsopruiming)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        episode = await session.get(Episode, episode_id)
        if not episode:
            return None
        await session.delete(episode)
        await session.commit()
        return episode


async def delete_episodes_older_than(days: int = 14) -> list[Episode]:
    """Verwijder episodes ouder dan X dagen. Retourneert de verwijderde episodes."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    logger.debug("Zoek episodes ouder dan %s (cutoff: %s)", days, cutoff.isoformat())
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(Episode).where(Episode.created_at < cutoff)
        )
        episodes = list(result.scalars().all())
        for episode in episodes:
            await session.delete(episode)
        await session.commit()
        return episodes


async def list_episodes(limit: int = 50) -> list[Episode]:
    """Haal de laatste episodes op, nieuwste eerst."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(Episode)
            .where(Episode.status == EpisodeStatus.completed)
            .order_by(Episode.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
