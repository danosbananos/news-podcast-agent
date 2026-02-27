"""Text-to-Speech met ElevenLabs (primair) en Google Cloud TTS (fallback)."""

import base64
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

OUTRO_PATH = Path(__file__).parent.parent / "static" / "outro.mp3"

# Google Cloud TTS configuratie
GOOGLE_TTS_VOICE = os.getenv("GOOGLE_TTS_VOICE", "nl-NL-Wavenet-F")
GOOGLE_TTS_CREDENTIALS_B64 = os.getenv("GOOGLE_TTS_CREDENTIALS_B64", "")


def generate_audio(
    script: str,
    output_path: str,
    api_key: str,
    voice_id: str,
    model_id: str = "eleven_multilingual_v2",
) -> Path:
    """Zet een podcastscript om naar een mp3-bestand.

    Probeert ElevenLabs eerst. Als dat faalt (rate limit, quota, API-fout),
    valt terug op Google Cloud TTS.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Probeer ElevenLabs
    if api_key and voice_id:
        try:
            _generate_elevenlabs(script, out, api_key, voice_id, model_id)
            _append_outro(out)
            size_kb = out.stat().st_size / 1024
            logger.info("Audio opgeslagen (ElevenLabs): %s (%.0f KB)", out, size_kb)
            return out
        except Exception as e:
            logger.warning("ElevenLabs mislukt: %s — probeer Google Cloud TTS", e)

    # Fallback: Google Cloud TTS
    if GOOGLE_TTS_CREDENTIALS_B64:
        try:
            _generate_google_tts(script, out)
            _append_outro(out)
            size_kb = out.stat().st_size / 1024
            logger.info("Audio opgeslagen (Google Cloud TTS): %s (%.0f KB)", out, size_kb)
            return out
        except Exception as e:
            logger.error("Google Cloud TTS ook mislukt: %s", e)
            raise RuntimeError(f"Alle TTS-providers gefaald. ElevenLabs en Google Cloud TTS beide mislukt. Laatste fout: {e}") from e

    # Geen fallback beschikbaar
    raise RuntimeError(
        "ElevenLabs mislukt en Google Cloud TTS niet geconfigureerd. "
        "Stel GOOGLE_TTS_CREDENTIALS_B64 in als fallback."
    )


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


def _generate_google_tts(script: str, out: Path):
    """Genereer audio via Google Cloud Text-to-Speech API."""
    from google.cloud import texttospeech
    from google.oauth2 import service_account

    logger.info("TTS gestart (Google Cloud): voice=%s, script=%d chars", GOOGLE_TTS_VOICE, len(script))

    # Decodeer service account credentials van base64 env var
    creds_json = base64.b64decode(GOOGLE_TTS_CREDENTIALS_B64)
    creds_info = json.loads(creds_json)
    credentials = service_account.Credentials.from_service_account_info(creds_info)

    client = texttospeech.TextToSpeechClient(credentials=credentials)

    # Bepaal taal op basis van voice name (nl-NL-Wavenet-F → nl-NL)
    language_code = "-".join(GOOGLE_TTS_VOICE.split("-")[:2])

    synthesis_input = texttospeech.SynthesisInput(text=script)
    voice = texttospeech.VoiceSelectionParams(
        language_code=language_code,
        name=GOOGLE_TTS_VOICE,
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

    with open(out, "wb") as f:
        f.write(response.audio_content)
    logger.debug("Google Cloud TTS audio ontvangen: %d bytes", len(response.audio_content))


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
