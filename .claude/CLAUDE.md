# News Podcast Agent

## Project overview
A personal news-to-podcast pipeline that converts news articles into podcast episodes using Claude (script generation) and ElevenLabs (TTS). Deployed on Railway (free plan, no persistent volume).

## Architecture
- **Server**: FastAPI (`server.py`) with SQLAlchemy + PostgreSQL
- **Script generation**: Claude Haiku 4.5 (`src/scriptgen.py`) with LanguageTool post-processing for Dutch grammar
- **TTS**: ElevenLabs multilingual v2 → Google Cloud TTS WaveNet fallback (`src/tts.py`) with outro sound appended via pydub/ffmpeg
- **Feed**: Apple Podcasts-compatible RSS (`src/feed.py`)
- **Extraction**: trafilatura for URLs, pdfplumber for PDFs (`src/extract.py`)
- **Notifications**: Push via ntfy.sh (`src/notify.py`) — success + failure alerts to phone
- **Setup**: `/setup` page with Apple Shortcut instructions + desktop bookmarklet (`static/setup.html`)

## Deployment
- **Platform**: Railway (free plan)
- **URL**: https://ideal-sparkle-production.up.railway.app
- **No persistent volume**: MP3s are lost on redeploy. Orphaned DB records are cleaned up on startup.
- **Builder**: Nixpacks (ffmpeg installed via `nixpacks.toml`)
- **Auto-deploy**: GitHub → Railway on push to main

## Key decisions
- Two separate iOS Shortcuts instead of one combined (iOS can't type-check Shortcut Input without conversion errors)
- LanguageTool public API for grammar checking (no Java dependency, free tier sufficient for personal use)
- Cleanup on startup instead of cron (sufficient for personal project, Railway restarts on each deploy)
- CORS enabled for bookmarklet cross-origin requests (endpoints protected by API key)
- ElevenLabs → Google Cloud TTS fallback chain (graceful degradation when ElevenLabs quota is exceeded)
- Ntfy.sh for push notifications (no account needed, topic-based, optional via NTFY_TOPIC env var)
- Google Cloud credentials stored as base64-encoded env var (GOOGLE_TTS_CREDENTIALS_B64) for containerized deployment
- Secrets consolidated in `secret_files/.env` (gitignored), Railway uses platform env vars

## iOS Shortcuts
- **"Naar Podcast"**: Accepts URLs from any app. NRC app shares "Title URL" as one string — server-side regex extracts the URL.
- **"Naar Podcast (Safari)"**: Accepts Safari web pages only. Uses Safari Reader for paywall bypass (NRC, NYT). User must be logged in via Safari.
- NYT app requires "Tekst" input type enabled to show in share sheet. Paywalled NYT content always requires the Safari route.

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
