"""Text-to-Speech via ElevenLabs API."""

import logging
from pathlib import Path

from elevenlabs import ElevenLabs

logger = logging.getLogger(__name__)

OUTRO_PATH = Path(__file__).parent.parent / "static" / "outro.mp3"


def generate_audio(
    script: str,
    output_path: str,
    api_key: str,
    voice_id: str,
    model_id: str = "eleven_multilingual_v2",
) -> Path:
    """Zet een podcastscript om naar een mp3-bestand.

    Args:
        script: Het podcastscript als tekst
        output_path: Pad waar de mp3 opgeslagen wordt
        api_key: ElevenLabs API-key
        voice_id: ElevenLabs voice ID
        model_id: ElevenLabs model (default: eleven_multilingual_v2)

    Returns:
        Path naar het gegenereerde mp3-bestand
    """
    logger.info("TTS gestart: model=%s, voice=%s, script=%d chars", model_id, voice_id, len(script))
    client = ElevenLabs(api_key=api_key)

    audio_iterator = client.text_to_speech.convert(
        voice_id=voice_id,
        text=script,
        model_id=model_id,
        output_format="mp3_44100_128",
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    bytes_written = 0
    with open(out, "wb") as f:
        for chunk in audio_iterator:
            f.write(chunk)
            bytes_written += len(chunk)
    logger.debug("TTS audio ontvangen: %d bytes naar %s", bytes_written, out)

    # Voeg outro-geluid toe aan het einde
    _append_outro(out)

    size_kb = out.stat().st_size / 1024
    logger.info("Audio opgeslagen: %s (%.0f KB)", out, size_kb)
    return out


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
