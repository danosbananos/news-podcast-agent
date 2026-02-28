# News Podcast Agent

## Project overview
A personal news-to-podcast pipeline that converts news articles into podcast episodes using Claude (script generation) and ElevenLabs (TTS). Deployed on Railway (free plan, no persistent volume).

## Architecture
- **Server**: FastAPI (`server.py`) with SQLAlchemy + PostgreSQL
- **Script generation**: Claude Haiku 4.5 (`src/scriptgen.py`) — English system prompt with language parameter. LanguageTool post-processing for grammar (nl, en-US, en-GB, de-DE). Prompt optimized for TTS: punctuation-driven pacing, paragraph structure, word-order emphasis.
- **Language detection**: `langdetect` in `src/extract.py` — detects nl/en/en-GB/de. UK English refined via `.uk` TLD and known British `.com` domains.
- **TTS**: ElevenLabs → Gemini Flash TTS (with style prompt) → WaveNet fallback (`src/tts.py`) with chunking + outro via pydub/ffmpeg. Per-language voice selection across all providers.
- **Feed**: Apple Podcasts-compatible RSS (`src/feed.py`) with per-episode artwork (`<itunes:image>`) and Podcasting 2.0 transcripts (`<podcast:transcript>`)
- **Episode images**: `src/episode_image.py` — downloads og:image, crops to 1400x1400 square JPEG, served locally. Fallback to Clearbit logo.
- **Transcripts**: `src/transcript.py` — VTT generation via heuristic timing or OpenAI Whisper API. Configurable via `TRANSCRIPT_MODE` env var.
- **Extraction**: trafilatura for URLs, pdfplumber for PDFs (`src/extract.py`). Extracts og:image for episode artwork.
- **Notifications**: Push via ntfy.sh (`src/notify.py`) — success, failure, and deploy alerts to phone
- **Setup**: `/setup` page with Apple Shortcut instructions + desktop bookmarklet (`static/setup.html`)

## Deployment
- **Platform**: Railway (free plan)
- **URL**: https://ideal-sparkle-production.up.railway.app
- **No persistent volume**: MP3s, episode images, and transcripts are lost on redeploy. Orphaned DB records are cleaned up on startup.
- **Builder**: Nixpacks (ffmpeg installed via `nixpacks.toml`)
- **Auto-deploy**: GitHub → Railway on push to main

## Key decisions
- Two separate iOS Shortcuts instead of one combined (iOS can't type-check Shortcut Input without conversion errors)
- LanguageTool public API for grammar checking with safety limits (max 20 corrections, single-token only, no proper nouns/acronyms)
- Cleanup on startup instead of cron (sufficient for personal project, Railway restarts on each deploy)
- CORS enabled for bookmarklet cross-origin requests (endpoints protected by API key)
- Three-tier TTS fallback: ElevenLabs → Gemini Flash TTS (style prompt) → WaveNet (graceful degradation)
- Per-language voice selection via env vars (fallback to default voice if not configured)
- Google TTS providers use chunking to handle scripts longer than 4000/5000 byte API limit
- Ntfy.sh for push notifications (no account needed, topic-based, optional via NTFY_TOPIC env var) — includes deploy notifications
- Google Cloud credentials stored as base64-encoded env var (GOOGLE_TTS_CREDENTIALS_B64) for containerized deployment
- Secrets consolidated in `secret_files/.env` (gitignored), Railway uses platform env vars
- Episode images hosted locally as square JPEGs (Pillow crop/resize) — external og:images are unreliable for Apple Podcasts
- langdetect with deterministic seed (0) for consistent language detection
- English system prompt for all languages (Claude performs best with English instructions)
- No Dutch intro for non-Dutch articles; scripts stay fully in source language
- HEAD support enabled on feed/audio/image/transcript routes for crawler compatibility
- UK English refinement is conservative but includes explicit British `.com` domains (e.g. `theguardian.com`)

## Considered and rejected options
- Rejected: only mark en-GB on strict UK URL signals; too strict for expected UK sources (e.g. The Guardian).
- Rejected: keep using remote og:image URLs only; local hosted square artwork proved more reliable for podcast clients.
- Rejected as required path: forcing Apple Podcasts Connect for this personal setup; accepted trade-off is reduced/inconsistent Apple client features on private RSS.

## iOS Shortcuts
- **"Naar Podcast"**: Accepts URLs from any app. NRC app shares "Title URL" as one string — server-side regex extracts the URL.
- **"Naar Podcast (Safari)"**: Accepts Safari web pages only. Uses Safari Reader for paywall bypass (NRC, NYT). User must be logged in via Safari.
- NYT app requires "Tekst" input type enabled to show in share sheet. Paywalled NYT content always requires the Safari route.

## Known Apple Podcasts limitations (private RSS)
- With private RSS feeds (added via URL, not catalog distribution), Apple Podcasts may not reliably show episode-level artwork.
- Apple transcripts are not shown for private RSS-only flows; transcript support primarily works when distributed through Apple Podcasts catalog/Connect.

## Apple Shortcuts terminology (Dutch vs English)
Dutch terms vary between iPhone and Mac:
- Opdrachten = Shortcuts
- Als / Anders / Einde als = If / Otherwise / End If
- Invoer opdracht = Shortcut Input
- Haal artikel op via Safari Reader = Get Article using Safari Reader
- Stel variabele in = Set Variable
- Haal inhoud van URL op = Get Contents of URL
- Haal woordenboekwaarde op = Get Dictionary Value
- Toon waarschuwing (Mac) / Toon melding (iPhone) = Show Alert / Show Notification
- Ontvang ... van Deelpaneel = Receive ... from Share Sheet
- Haal URL's op uit = Get URLs from Input

## Forbidden paths
- **NEVER** read, open, or access files in `secret_files/` or any `.env` / `secrets.env` files. These contain credentials and secrets that must not appear in conversation or tool output.

## Backlog
See `PLAN.md` for the full backlog with specs.
