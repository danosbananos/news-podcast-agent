"""Text-to-Speech met drielaagse fallback: ElevenLabs → Gemini Flash TTS → WaveNet."""

import base64
import io
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

OUTRO_PATH = Path(__file__).parent.parent / "static" / "outro.mp3"

# Google Cloud TTS configuratie
GOOGLE_TTS_CREDENTIALS_B64 = os.getenv("GOOGLE_TTS_CREDENTIALS_B64", "")
GOOGLE_TTS_WAVENET_VOICE = os.getenv("GOOGLE_TTS_WAVENET_VOICE", "nl-NL-Wavenet-F")
GOOGLE_TTS_GEMINI_VOICE = os.getenv("GOOGLE_TTS_GEMINI_VOICE", "Kore")
GOOGLE_TTS_GEMINI_LANG = os.getenv("GOOGLE_TTS_GEMINI_LANG", "nl-NL")
GOOGLE_TTS_STYLE_PROMPT = os.getenv(
    "GOOGLE_TTS_STYLE_PROMPT",
    "Lees voor als een professionele podcast-presentator. "
    "Rustige, betrokken toon. Varieer je intonatie en leg nadruk op belangrijke woorden. "
    "Neem korte pauzes tussen alinea's.",
)

# Chunk-limieten (bytes) — Google TTS API-limieten per request
_GEMINI_CHUNK_LIMIT = 3800  # Gemini: 4000 bytes max, met marge
_WAVENET_CHUNK_LIMIT = 4800  # WaveNet: 5000 bytes max, met marge


def generate_audio(
    script: str,
    output_path: str,
    api_key: str,
    voice_id: str,
    model_id: str = "eleven_multilingual_v2",
) -> Path:
    """Zet een podcastscript om naar een mp3-bestand.

    Fallback-keten: ElevenLabs → Gemini Flash TTS → Google WaveNet.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # 1. ElevenLabs (primair)
    if api_key and voice_id:
        try:
            _generate_elevenlabs(script, out, api_key, voice_id, model_id)
            _append_outro(out)
            size_kb = out.stat().st_size / 1024
            logger.info("Audio opgeslagen (ElevenLabs): %s (%.0f KB)", out, size_kb)
            return out
        except Exception as e:
            logger.warning("ElevenLabs mislukt: %s — probeer Gemini TTS", e)

    # 2. Gemini Flash TTS (eerste fallback)
    if GOOGLE_TTS_CREDENTIALS_B64:
        try:
            _generate_gemini_tts(script, out)
            _append_outro(out)
            size_kb = out.stat().st_size / 1024
            logger.info("Audio opgeslagen (Gemini Flash TTS): %s (%.0f KB)", out, size_kb)
            return out
        except Exception as e:
            logger.warning("Gemini TTS mislukt: %s — probeer WaveNet", e)

        # 3. WaveNet (tweede fallback)
        try:
            _generate_wavenet(script, out)
            _append_outro(out)
            size_kb = out.stat().st_size / 1024
            logger.info("Audio opgeslagen (WaveNet): %s (%.0f KB)", out, size_kb)
            return out
        except Exception as e:
            logger.error("WaveNet ook mislukt: %s", e)
            raise RuntimeError(
                f"Alle TTS-providers gefaald (ElevenLabs, Gemini, WaveNet). Laatste fout: {e}"
            ) from e

    raise RuntimeError(
        "ElevenLabs mislukt en Google Cloud TTS niet geconfigureerd. "
        "Stel GOOGLE_TTS_CREDENTIALS_B64 in als fallback."
    )


# --- Providers ---


def _generate_elevenlabs(script: str, out: Path, api_key: str, voice_id: str, model_id: str):
    """Genereer audio via ElevenLabs API."""
    from elevenlabs import ElevenLabs

    logger.info("TTS gestart (ElevenLabs): model=%s, voice=%s, script=%d chars", model_id, voice_id, len(script))
    client = ElevenLabs(api_key=api_key)

    audio_iterator = client.text_to_speech.convert(
        voice_id=voice_id,
        text=script,
        model_id=model_id,
        output_format="mp3_44100_128",
    )

    bytes_written = 0
    with open(out, "wb") as f:
        for chunk in audio_iterator:
            f.write(chunk)
            bytes_written += len(chunk)
    logger.debug("ElevenLabs audio ontvangen: %d bytes", bytes_written)


def _generate_gemini_tts(script: str, out: Path):
    """Genereer audio via Gemini Flash TTS met style prompt."""
    from google.cloud import texttospeech
    from google.oauth2 import service_account

    logger.info(
        "TTS gestart (Gemini Flash): voice=%s, lang=%s, script=%d chars",
        GOOGLE_TTS_GEMINI_VOICE, GOOGLE_TTS_GEMINI_LANG, len(script),
    )

    client = _get_google_client(texttospeech, service_account)

    chunks = _split_into_chunks(script, _GEMINI_CHUNK_LIMIT)
    logger.info("Script opgesplitst in %d chunks voor Gemini TTS", len(chunks))

    audio_segments = []
    for i, chunk_text in enumerate(chunks):
        logger.debug("Gemini TTS chunk %d/%d: %d chars", i + 1, len(chunks), len(chunk_text))
        synthesis_input = texttospeech.SynthesisInput(
            text=chunk_text,
            prompt=GOOGLE_TTS_STYLE_PROMPT,
        )
        voice = texttospeech.VoiceSelectionParams(
            language_code=GOOGLE_TTS_GEMINI_LANG,
            name=GOOGLE_TTS_GEMINI_VOICE,
            model_name="gemini-2.5-flash-tts",
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )
        audio_segments.append(response.audio_content)

    _concatenate_mp3_segments(audio_segments, out)
    logger.debug("Gemini TTS voltooid: %d chunks samengevoegd", len(chunks))


def _generate_wavenet(script: str, out: Path):
    """Genereer audio via Google Cloud WaveNet."""
    from google.cloud import texttospeech
    from google.oauth2 import service_account

    logger.info("TTS gestart (WaveNet): voice=%s, script=%d chars", GOOGLE_TTS_WAVENET_VOICE, len(script))

    client = _get_google_client(texttospeech, service_account)
    language_code = "-".join(GOOGLE_TTS_WAVENET_VOICE.split("-")[:2])

    chunks = _split_into_chunks(script, _WAVENET_CHUNK_LIMIT)
    logger.info("Script opgesplitst in %d chunks voor WaveNet", len(chunks))

    audio_segments = []
    for i, chunk_text in enumerate(chunks):
        logger.debug("WaveNet chunk %d/%d: %d chars", i + 1, len(chunks), len(chunk_text))
        synthesis_input = texttospeech.SynthesisInput(text=chunk_text)
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=GOOGLE_TTS_WAVENET_VOICE,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            sample_rate_hertz=44100,
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )
        audio_segments.append(response.audio_content)

    _concatenate_mp3_segments(audio_segments, out)
    logger.debug("WaveNet voltooid: %d chunks samengevoegd", len(chunks))


# --- Helpers ---


def _get_google_client(texttospeech, service_account):
    """Maak een Google Cloud TTS client met credentials uit env var."""
    creds_json = base64.b64decode(GOOGLE_TTS_CREDENTIALS_B64)
    creds_info = json.loads(creds_json)
    credentials = service_account.Credentials.from_service_account_info(creds_info)
    return texttospeech.TextToSpeechClient(credentials=credentials)


def _split_into_chunks(text: str, max_bytes: int) -> list[str]:
    """Splits tekst in chunks op alineagrenzen, binnen de byte-limiet.

    Probeert te splitsen op dubbele newlines (alinea's), dan enkele newlines,
    dan zinnen (punt + spatie). Houdt tekst bij elkaar waar mogelijk.
    """
    paragraphs = text.split("\n\n")
    chunks = []
    current = ""

    for para in paragraphs:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate.encode("utf-8")) <= max_bytes:
            current = candidate
        else:
            # Huidige chunk opslaan als die niet leeg is
            if current:
                chunks.append(current)
            # Als de paragraaf zelf te lang is, splits op zinnen
            if len(para.encode("utf-8")) > max_bytes:
                chunks.extend(_split_paragraph(para, max_bytes))
                current = ""
            else:
                current = para

    if current:
        chunks.append(current)

    return chunks


def _split_paragraph(text: str, max_bytes: int) -> list[str]:
    """Splits een lange paragraaf op zinsgrenzen."""
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current = ""

    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate.encode("utf-8")) <= max_bytes:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)

    return chunks


def _concatenate_mp3_segments(segments: list[bytes], out: Path):
    """Voeg meerdere MP3-segmenten samen tot één bestand."""
    if len(segments) == 1:
        with open(out, "wb") as f:
            f.write(segments[0])
        return

    from pydub import AudioSegment

    combined = AudioSegment.empty()
    for segment_bytes in segments:
        segment_audio = AudioSegment.from_mp3(io.BytesIO(segment_bytes))
        combined += segment_audio

    combined.export(out, format="mp3", bitrate="128k")


def _append_outro(audio_path: Path):
    """Voeg het outro-geluid toe aan het einde van een mp3-bestand."""
    if not OUTRO_PATH.exists():
        logger.warning("outro.mp3 niet gevonden op %s, outro overgeslagen", OUTRO_PATH)
        return

    try:
        from pydub import AudioSegment
        podcast = AudioSegment.from_mp3(audio_path)
        outro = AudioSegment.from_mp3(OUTRO_PATH)
        combined = podcast + outro
        combined.export(audio_path, format="mp3", bitrate="128k")
        logger.debug("Outro toegevoegd: podcast=%.1fs + outro=%.1fs", podcast.duration_seconds, outro.duration_seconds)
    except Exception as e:
        logger.warning("Outro toevoegen mislukt (%s), episode zonder outro opgeslagen", e)
