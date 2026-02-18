#!/usr/bin/env python3
"""
Nieuws-naar-Podcast — Fase 1: Proof of Concept

Gebruik:
    # Vanuit een URL (werkt alleen voor niet-paywalled artikelen):
    python main.py --url "https://example.com/artikel"

    # Vanuit platte tekst:
    python main.py --text "Hier de volledige artikeltekst..." --title "Titel" --source "NRC"

    # Vanuit een PDF:
    python main.py --pdf pad/naar/artikel.pdf

    # Tekst via stdin (handig voor piping):
    cat artikel.txt | python main.py --stdin --title "Titel"
"""

import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from src.extract import from_url, from_pdf, from_text
from src.scriptgen import generate_script
from src.tts import generate_audio


def main():
    load_dotenv(Path(__file__).parent / "secrets.env")

    parser = argparse.ArgumentParser(
        description="Zet een nieuwsartikel om naar een podcastaflevering."
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--url", help="URL van het artikel")
    input_group.add_argument("--text", help="Platte artikeltekst")
    input_group.add_argument("--pdf", help="Pad naar een PDF-bestand")
    input_group.add_argument(
        "--stdin", action="store_true", help="Lees tekst van stdin"
    )

    parser.add_argument("--title", default="", help="Titel van het artikel")
    parser.add_argument("--source", default="", help="Bron (bijv. NRC, NYT)")
    parser.add_argument(
        "--output", "-o", default=None, help="Output mp3-pad (default: output/<timestamp>.mp3)"
    )
    parser.add_argument(
        "--script-only",
        action="store_true",
        help="Toon alleen het gegenereerde script, geen audio",
    )

    args = parser.parse_args()

    # --- Check API keys ---
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    elevenlabs_key = os.getenv("ELEVENLABS_API_KEY")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID")

    if not anthropic_key:
        print("Fout: ANTHROPIC_API_KEY niet gevonden. Zet deze in secrets.env of als omgevingsvariabele.")
        sys.exit(1)

    if not args.script_only:
        if not elevenlabs_key:
            print("Fout: ELEVENLABS_API_KEY niet gevonden. Zet deze in secrets.env of als omgevingsvariabele.")
            sys.exit(1)
        if not voice_id:
            print("Fout: ELEVENLABS_VOICE_ID niet gevonden. Zet deze in secrets.env of als omgevingsvariabele.")
            print("Tip: ga naar https://elevenlabs.io/voice-library en kies een stem.")
            print("     Het voice ID vind je in de URL of via de API.")
            sys.exit(1)

    # --- Stap 1: Tekstextractie ---
    print("📄 Tekst extraheren...")
    try:
        if args.url:
            article = from_url(args.url)
            print(f"   Bron: {article.get('source', 'onbekend')}")
            print(f"   Titel: {article.get('title', 'onbekend')}")
        elif args.pdf:
            article = from_pdf(args.pdf)
            print(f"   PDF: {args.pdf}")
        elif args.stdin:
            text = sys.stdin.read()
            article = from_text(text, title=args.title, source=args.source)
        else:
            article = from_text(args.text, title=args.title, source=args.source)

        # Override metadata met CLI-argumenten als die meegegeven zijn
        if args.title:
            article["title"] = args.title
        if args.source:
            article["source"] = args.source

        print(f"   Tekstlengte: {len(article['text'])} karakters")
    except (ValueError, FileNotFoundError) as e:
        print(f"Fout bij extractie: {e}")
        sys.exit(1)

    # --- Stap 2: Podcastscript genereren ---
    print("\n🎙️  Podcastscript genereren (Claude Haiku)...")
    try:
        script = generate_script(article, api_key=anthropic_key)
        print(f"   Scriptlengte: {len(script)} karakters")
        print(f"\n--- Script ---\n{script}\n--- Einde script ---\n")
    except Exception as e:
        print(f"Fout bij scriptgeneratie: {e}")
        sys.exit(1)

    if args.script_only:
        return

    # --- Stap 3: Text-to-Speech ---
    print("🔊 Audio genereren (ElevenLabs)...")
    if args.output:
        output_path = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = (article.get("title", "podcast") or "podcast")[:50]
        # Maak bestandsnaam veilig
        slug = "".join(c if c.isalnum() or c in "-_ " else "" for c in slug).strip()
        slug = slug.replace(" ", "_") or "podcast"
        output_path = f"output/{timestamp}_{slug}.mp3"

    try:
        path = generate_audio(
            script=script,
            output_path=output_path,
            api_key=elevenlabs_key,
            voice_id=voice_id,
        )
        print(f"\n✅ Klaar! Aflevering opgeslagen: {path}")
    except Exception as e:
        print(f"Fout bij audiogeneratie: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
