"""Text-to-Speech via ElevenLabs API."""

from pathlib import Path
from elevenlabs import ElevenLabs


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

    size_kb = out.stat().st_size / 1024
    print(f"Audio opgeslagen: {out} ({size_kb:.0f} KB)")
    return out
