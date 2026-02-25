"""Text-to-Speech via ElevenLabs API."""

from pathlib import Path
from elevenlabs import ElevenLabs

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
    client = ElevenLabs(api_key=api_key)

    audio_iterator = client.text_to_speech.convert(
        voice_id=voice_id,
        text=script,
        model_id=model_id,
        output_format="mp3_44100_128",
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "wb") as f:
        for chunk in audio_iterator:
            f.write(chunk)

    # Voeg outro-geluid toe aan het einde
    _append_outro(out)

    size_kb = out.stat().st_size / 1024
    print(f"Audio opgeslagen: {out} ({size_kb:.0f} KB)")
    return out


def _append_outro(audio_path: Path):
    """Voeg het outro-geluid toe aan het einde van een mp3-bestand."""
    if not OUTRO_PATH.exists():
        print("Waarschuwing: outro.mp3 niet gevonden, outro overgeslagen.")
        return

    try:
        from pydub import AudioSegment
        podcast = AudioSegment.from_mp3(audio_path)
        outro = AudioSegment.from_mp3(OUTRO_PATH)
        combined = podcast + outro
        combined.export(audio_path, format="mp3", bitrate="128k")
    except Exception as e:
        print(f"Waarschuwing: outro toevoegen mislukt ({e}), episode zonder outro opgeslagen.")
