"""Transcriptgeneratie (VTT) met meerdere modi."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


def generate_transcript(
    *,
    script: str,
    audio_path: Path,
    output_dir: Path,
    language: str = "nl",
    duration_seconds: int | None = None,
    mode: str = "none",
    openai_api_key: str = "",
) -> Path | None:
    """Genereer een VTT transcriptbestand voor een episode."""
    mode = (mode or "none").strip().lower()
    if mode == "none":
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"{audio_path.stem}.vtt"

    try:
        if mode == "heuristic":
            segments = _segments_heuristic(script, duration_seconds)
        elif mode == "whisper_api":
            segments = _segments_whisper_api(audio_path, language=language, api_key=openai_api_key)
            if not segments:
                logger.warning("Whisper API gaf geen segmenten terug; fallback naar heuristic transcript")
                segments = _segments_heuristic(script, duration_seconds)
        else:
            logger.warning("Onbekende TRANSCRIPT_MODE '%s'; transcript overgeslagen", mode)
            return None

        _write_vtt(segments, out)
        logger.info("Transcript opgeslagen: %s (mode=%s, segments=%d)", out, mode, len(segments))
        return out
    except Exception as e:
        logger.warning("Transcriptgeneratie mislukt (mode=%s): %s", mode, e)
        return None


def _segments_heuristic(script: str, duration_seconds: int | None) -> list[tuple[float, float, str]]:
    """Heuristische timing op basis van zinnen en woordverdeling."""
    clean = re.sub(r"\s+", " ", (script or "").strip())
    if not clean:
        return []

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean) if s.strip()]
    if not sentences:
        sentences = [clean]

    words_total = max(len(clean.split()), 1)
    target = float(duration_seconds or max(int(words_total / 150 * 60), 10))

    segments: list[tuple[float, float, str]] = []
    t = 0.0
    for sentence in sentences:
        w = max(len(sentence.split()), 1)
        seg = max(0.8, target * (w / words_total))
        start = t
        end = min(target, t + seg)
        segments.append((start, end, sentence))
        t = end

    # Zorg dat laatste segment exact eindigt op target (mooier voor spelers).
    if segments:
        s, _, txt = segments[-1]
        segments[-1] = (s, max(s + 0.2, target), txt)
    return segments


def _segments_whisper_api(audio_path: Path, *, language: str, api_key: str) -> list[tuple[float, float, str]]:
    """Vraag getimede segmenten op via OpenAI Audio Transcriptions API."""
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY/TRANSCRIPT_OPENAI_API_KEY ontbreekt")
    if not audio_path.exists():
        raise FileNotFoundError(f"Audiobestand niet gevonden: {audio_path}")

    lang = (language or "nl").split("-")[0]
    with open(audio_path, "rb") as f:
        files = {"file": (audio_path.name, f, "audio/mpeg")}
        data = {
            "model": "whisper-1",
            "response_format": "verbose_json",
            "language": lang,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        response = httpx.post(
            "https://api.openai.com/v1/audio/transcriptions",
            data=data,
            files=files,
            headers=headers,
            timeout=180.0,
        )
        response.raise_for_status()
        payload = response.json()

    segments_raw = payload.get("segments", []) or []
    segments: list[tuple[float, float, str]] = []
    for seg in segments_raw:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start + 1.0))
        if end <= start:
            end = start + 0.5
        segments.append((start, end, text))
    return segments


def _write_vtt(segments: list[tuple[float, float, str]], out: Path) -> None:
    """Schrijf VTT-bestand."""
    lines = ["WEBVTT", ""]
    for start, end, text in segments:
        lines.append(f"{_fmt_vtt_ts(start)} --> {_fmt_vtt_ts(end)}")
        lines.append(text)
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")


def _fmt_vtt_ts(seconds: float) -> str:
    """Formateer seconden naar VTT timestamp HH:MM:SS.mmm."""
    ms_total = max(0, int(round(seconds * 1000)))
    h, rem = divmod(ms_total, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
