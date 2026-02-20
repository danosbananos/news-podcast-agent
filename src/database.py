"""Database models en CRUD voor podcast-afleveringen (PostgreSQL + SQLAlchemy async)."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Enum, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

import enum
import os


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
        _engine = create_async_engine(url, echo=False, connect_args=connect_args)
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
    for attempt in range(5):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            return
        except Exception as e:
            last_error = e
            wait = 2 ** attempt
            print(f"[db] Verbinding mislukt (poging {attempt + 1}/5), retry in {wait}s: {e}", flush=True)
            await asyncio.sleep(wait)
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
            return None
        for key, value in kwargs.items():
            if hasattr(episode, key):
                setattr(episode, key, value)
        await session.commit()
        await session.refresh(episode)
        return episode


async def get_episode(episode_id: uuid.UUID) -> Optional[Episode]:
    """Haal één episode op."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        return await session.get(Episode, episode_id)


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
