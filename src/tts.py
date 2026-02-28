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

# --- Per-taal voice configuratie ---

# ElevenLabs voice IDs per taal (multilingual v2 model spreekt alle talen)
_ELEVENLABS_VOICE_IDS = {
    "nl": os.getenv("ELEVENLABS_VOICE_ID", ""),
    "en": os.getenv("ELEVENLABS_VOICE_ID_EN", ""),
    "en-GB": os.getenv("ELEVENLABS_VOICE_ID_EN_GB", ""),
    "de": os.getenv("ELEVENLABS_VOICE_ID_DE", ""),
}

# Gemini Flash TTS voices en taalcodes
_GEMINI_VOICES = {
    "nl": os.getenv("GOOGLE_TTS_GEMINI_VOICE", "Kore"),
    "en": os.getenv("GOOGLE_TTS_GEMINI_VOICE_EN", "Kore"),
    "en-GB": os.getenv("GOOGLE_TTS_GEMINI_VOICE_EN_GB", "Kore"),
    "de": os.getenv("GOOGLE_TTS_GEMINI_VOICE_DE", "Kore"),
}
_GEMINI_LANG_CODES = {
    "nl": "nl-NL",
    "en": "en-US",
    "en-GB": "en-GB",
    "de": "de-DE",
}

# WaveNet voices (voice-naam bevat de taalcode)
_WAVENET_VOICES = {
    "nl": os.getenv("GOOGLE_TTS_WAVENET_VOICE", "nl-NL-Wavenet-F"),
    "en": os.getenv("GOOGLE_TTS_WAVENET_VOICE_EN", "en-US-Wavenet-D"),
    "en-GB": os.getenv("GOOGLE_TTS_WAVENET_VOICE_EN_GB", "en-GB-Wavenet-B"),
    "de": os.getenv("GOOGLE_TTS_WAVENET_VOICE_DE", "de-DE-Wavenet-C"),
}

# Style prompts per taal voor Gemini TTS
_STYLE_PROMPTS = {
    "nl": os.getenv(
        "GOOGLE_TTS_STYLE_PROMPT",
        "Lees voor in een neutrale, rustige nieuwsleestoon. "
        "Beperk expressie en emotionele variatie. "
        "Gebruik gelijkmatig tempo met korte, natuurlijke pauzes tussen alinea's.",
    ),
    "en": os.getenv(
        "GOOGLE_TTS_STYLE_PROMPT_EN",
        "Read in a neutral, calm newsreader style. "
        "Keep expression restrained and avoid dramatic emphasis. "
        "Use steady pacing with short, natural pauses between paragraphs.",
    ),
    "en-GB": os.getenv(
        "GOOGLE_TTS_STYLE_PROMPT_EN_GB",
        "Read in a neutral, calm newsreader style. "
        "Keep expression restrained and avoid dramatic emphasis. "
        "Use steady pacing with short, natural pauses between paragraphs.",
    ),
    "de": os.getenv(
        "GOOGLE_TTS_STYLE_PROMPT_DE",
        "Lies in einem neutralen, ruhigen Nachrichtenton vor. "
        "Halte die Ausdrucksstärke zurück und vermeide dramatische Betonung. "
        "Verwende ein gleichmäßiges Tempo mit kurzen, natürlichen Pausen zwischen Absätzen.",
    ),
}

# Chunk-limieten (bytes) — Google TTS API-limieten per request
_GEMINI_CHUNK_LIMIT = 3800  # Gemini: 4000 bytes max, met marge
_WAVENET_CHUNK_LIMIT = 4800  # WaveNet: 5000 bytes max, met marge


def generate_audio(
    script: str,
    output_path: str,
    api_key: str,
    voice_id: str,
    model_id: str = "eleven_multilingual_v2",
    language: str = "nl",
) -> Path:
    """Zet een podcastscript om naar een mp3-bestand.

    Fallback-keten: ElevenLabs → Gemini Flash TTS → Google WaveNet.
    Kiest automatisch de juiste stem op basis van de taal.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Bepaal de taal-specifieke voice ID voor ElevenLabs
    el_voice = _ELEVENLABS_VOICE_IDS.get(language) or voice_id

    # 1. ElevenLabs (primair)
    if api_key and el_voice:
        try:
            _generate_elevenlabs(script, out, api_key, el_voice, model_id)
            _append_outro(out)
            size_kb = out.stat().st_size / 1024
            logger.info("Audio opgeslagen (ElevenLabs): %s (%.0f KB, taal=%s)", out, size_kb, language)
            return out
        except Exception as e:
            logger.warning("ElevenLabs mislukt: %s — probeer Gemini TTS", e)

    # 2. Gemini Flash TTS (eerste fallback)
    if GOOGLE_TTS_CREDENTIALS_B64:
        try:
            _generate_gemini_tts(script, out, language)
            _append_outro(out)
            size_kb = out.stat().st_size / 1024
            logger.info("Audio opgeslagen (Gemini Flash TTS): %s (%.0f KB, taal=%s)", out, size_kb, language)
            return out
        except Exception as e:
            logger.warning("Gemini TTS mislukt: %s — probeer WaveNet", e)

        # 3. WaveNet (tweede fallback)
        try:
            _generate_wavenet(script, out, language)
            _append_outro(out)
            size_kb = out.stat().st_size / 1024
            logger.info("Audio opgeslagen (WaveNet): %s (%.0f KB, taal=%s)", out, size_kb, language)
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


def _generate_gemini_tts(script: str, out: Path, language: str = "nl"):
    """Genereer audio via Gemini Flash TTS met style prompt."""
    from google.cloud import texttospeech
    from google.oauth2 import service_account

    gemini_voice = _GEMINI_VOICES.get(language, _GEMINI_VOICES["nl"])
    gemini_lang = _GEMINI_LANG_CODES.get(language, "nl-NL")
    style_prompt = _STYLE_PROMPTS.get(language, _STYLE_PROMPTS["nl"])

    logger.info(
        "TTS gestart (Gemini Flash): voice=%s, lang=%s, script=%d chars",
        gemini_voice, gemini_lang, len(script),
    )

    client = _get_google_client(texttospeech, service_account)

    chunks = _split_into_chunks(script, _GEMINI_CHUNK_LIMIT)
    logger.info("Script opgesplitst in %d chunks voor Gemini TTS", len(chunks))

    audio_segments = []
    for i, chunk_text in enumerate(chunks):
        logger.debug("Gemini TTS chunk %d/%d: %d chars", i + 1, len(chunks), len(chunk_text))
        synthesis_input = texttospeech.SynthesisInput(
            text=chunk_text,
            prompt=style_prompt,
        )
        voice = texttospeech.VoiceSelectionParams(
            language_code=gemini_lang,
            name=gemini_voice,
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


def _generate_wavenet(script: str, out: Path, language: str = "nl"):
    """Genereer audio via Google Cloud WaveNet."""
    from google.cloud import texttospeech
    from google.oauth2 import service_account

    wavenet_voice = _WAVENET_VOICES.get(language, _WAVENET_VOICES["nl"])
    language_code = "-".join(wavenet_voice.split("-")[:2])

    logger.info("TTS gestart (WaveNet): voice=%s, script=%d chars", wavenet_voice, len(script))

    client = _get_google_client(texttospeech, service_account)

    chunks = _split_into_chunks(script, _WAVENET_CHUNK_LIMIT)
    logger.info("Script opgesplitst in %d chunks voor WaveNet", len(chunks))

    audio_segments = []
    for i, chunk_text in enumerate(chunks):
        logger.debug("WaveNet chunk %d/%d: %d chars", i + 1, len(chunks), len(chunk_text))
        synthesis_input = texttospeech.SynthesisInput(text=chunk_text)
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=wavenet_voice,
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
