# Backlog — Nieuws Podcast Agent

## 1. Scriptvalidatie via prompt-verbetering + grammaticacontrole
**Status:** Done
**Prioriteit:** Hoog | **Effort:** Laag

### Probleem
Haiku produceert soms Engelse woorden, verkeerde lidwoorden (de/het), of onnatuurlijke formuleringen in het podcastscript.

### Oplossing
Verscherp de system prompt in `src/scriptgen.py` in plaats van een apart validatiemodel of duurder model:
- Expliciete instructie: "Gebruik geen Engelse woorden tenzij het eigennamen of gangbare leenwoorden zijn"
- Expliciete instructie: "Controleer correct lidwoordgebruik (de/het)"
- Instructie voor natuurlijke spreektaal: korte zinnen, geen ambtelijk taalgebruik
- Interpunctie-sturing voor TTS: gedachtestreepjes, ellipsen, retorische vragen
- Alinea-structuur: 3-5 zinnen per alinea, gescheiden door witregels (zorgt voor pauzes in TTS én splitspunten voor chunking)
- Klemtoon via woordvolgorde: kernwoord aan begin of einde van de zin plaatsen

### Escalatiepad
Als prompt-aanpassingen onvoldoende zijn, upgrade naar Sonnet (`claude-sonnet-4-20250514`). Eén betere call is goedkoper dan twee aparte calls (generatie + validatie).

---

## 2. Gevarieerde intro's per artikel
**Status:** Done
**Prioriteit:** Hoog | **Effort:** Laag

### Probleem
Elke episode begint met dezelfde soort introductie, wat repetitief klinkt bij meerdere episodes achter elkaar.

### Oplossing
Pas de system prompt in `src/scriptgen.py` aan (kan samen met punt 1):
- Begin direct met het noemen van het artikel en de bron (bijv. "Uit de NRC van vandaag:", "The New York Times meldt dat...", "Op NOS.nl verscheen vandaag...")
- Varieer de openingsstijl op basis van het type bron en het onderwerp
- Geen vaste template-zin als opening — elke episode moet anders klinken
- De bron en eventuele datum moeten in de eerste zin verwerkt worden, niet als losse opsomming

### Relatie met punt 1
Beide punten vereisen aanpassingen aan dezelfde system prompt. Implementeer ze samen.

---

## 3. Audio-outro met vast geluid
**Status:** Done
**Prioriteit:** Medium | **Effort:** Laag

### Probleem
Episodes eindigen abrupt zonder markering.

### Oplossing
Voeg een vast audiobestand (korte gong/swoosh, ~1-2 seconden) toe aan het einde van elke gegenereerde episode:
- Plaats een `outro.mp3` in `static/`
- Na TTS-generatie: concateneer de podcast-audio + korte stilte (~1s) + outro-geluid
- Gebruik `pydub` of `ffmpeg` voor het samenvoegen

### Open vragen
- Welk geluid? Zoek een rechtenvrij geluid of genereer er een.

---

## 4. NYT-app: gift article links + Safari-route
**Status:** Done
**Prioriteit:** n.v.t.

### Diagnose
NYT retourneert `403 Forbidden` bij server-side requests met trafilatura's standaard-headers (bot-detectie). NRC retourneert `200 OK` met volledige HTML (paywall is client-side JavaScript).

### Oplossing
Browser-achtige HTTP headers (met name `Accept` en `User-Agent`) toegevoegd als fallback in `src/extract.py`. Hierdoor werken NYT **gift article links** (met `unlocked_article_code` parameter) via de URL-only Shortcut.

### Beperkingen
- Reguliere NYT-artikelen (zonder gift link) blijven geblokkeerd — de server-side paywall vereist authenticatie.
- Voor niet-gift NYT-artikelen: gebruik de Safari-route ("Naar Podcast (Safari)") waar je ingelogd bent.

---

## 5. Taaldetectie: Engels en Duits in oorspronkelijke taal voorlezen
**Status:** Done
**Prioriteit:** Medium | **Effort:** Medium

### Probleem
Engelstalige en Duitstalige artikelen worden nu voorgelezen met een Nederlandse stem en in het Nederlands herschreven. Dit verliest nuance en klinkt onnatuurlijk bij artikelen die beter in de oorspronkelijke taal blijven.

### Gewenst gedrag
- **Nederlands artikel** → Nederlands script, Nederlandse stem (huidige flow)
- **Engels artikel** → Engels script, Engelse stem
- **Duits artikel** → Duits script, Duitse stem
- Het volledige script blijft in de oorspronkelijke taal (geen Nederlandstalige intro bij niet-Nederlandse artikelen)

### Oplossing

**Stap 1: Taaldetectie (`src/extract.py`)**
- Detecteer de taal van de geëxtraheerde tekst
- Optie A: Gebruik `langdetect` of `lingua-py` (lichtgewicht, pip-installeerbaar)
- Optie B: Laat Claude de taal bepalen als onderdeel van de scriptgeneratie (geen extra dependency, maar kost tokens)
- Optie C: Baseer op het domein (nytimes.com → Engels, spiegel.de → Duits) — simpelst maar niet waterdicht
- Sla de gedetecteerde taal op in het `article` dict als `language` (bijv. "nl", "en", "de")

**Stap 2: Scriptgeneratie (`src/scriptgen.py`)**
- Eén Engelstalige system prompt voor alle talen (Engels werkt het best als instructietaal voor Claude)
- Voeg de doeltaal toe als parameter: "Write the script in {language}"
- Voor niet-Nederlandse artikelen: schrijf het volledige script in `{language}` (inclusief intro)
- Voor Nederlandse artikelen: huidige gedrag (alles Nederlands)
- Geen aparte prompt-varianten per taal nodig

**Stap 3: TTS voice-selectie (`src/tts.py`)**
- Kies stem en taal op basis van `article["language"]`:
  - `nl` → huidige stemmen (ElevenLabs NL, Gemini nl-NL, WaveNet nl-NL)
  - `en` → Engelse stemmen (ElevenLabs EN voice, Gemini en-US, WaveNet en-US)
  - `de` → Duitse stemmen (ElevenLabs DE voice, Gemini de-DE, WaveNet de-DE)
- Nieuwe env vars voor extra stemmen:
  - `ELEVENLABS_VOICE_ID_EN`, `ELEVENLABS_VOICE_ID_DE`
  - `GOOGLE_TTS_GEMINI_VOICE_EN`, `GOOGLE_TTS_GEMINI_VOICE_DE`
  - `GOOGLE_TTS_WAVENET_VOICE_EN` (bijv. `en-US-Wavenet-D`), `GOOGLE_TTS_WAVENET_VOICE_DE` (bijv. `de-DE-Wavenet-C`)

### Bestanden
| File | Actie |
|---|---|
| `src/extract.py` | Taaldetectie toevoegen, `language` veld in article dict |
| `src/scriptgen.py` | Taal-afhankelijke prompt |
| `src/tts.py` | Taal-afhankelijke voice-selectie |
| `requirements.txt` | Eventueel `langdetect` of `lingua-py` toevoegen |

### Beslissingen
- Taaldetectie via `langdetect` (lichtgewicht, betrouwbaar, geen API-call)
- Geen Nederlandstalige intro bij niet-Nederlandse artikelen; volledig script blijft in brontaal
- Eén Engelstalige prompt met taal-parameter (geen aparte prompts per taal)

### Open vragen
- Welke Engelse/Duitse stemmen kiezen per TTS-provider?

---

## 6. Tweestemmigheid voor interviews
**Status:** Todo
**Prioriteit:** Laag | **Effort:** Hoog

### Probleem
Interviews worden nu voorgelezen als monoloog, wat onnatuurlijk klinkt.

### Oplossing
Gebruik twee stemmen (host + gast) voor interview-artikelen:

**Scriptgeneratie:**
- LLM formatteert het script met sprekersaanduidingen: `[HOST]: ...` en `[GAST]: ...`
- Detectie of een artikel een interview is: laat het LLM dit bepalen op basis van de tekst, of laat de gebruiker het aangeven via een parameter

**TTS-pipeline (`src/tts.py`):**
- Parse het script op sprekersaanduidingen
- Genereer audio per segment met de juiste voice
- Concateneer alle segmenten tot één MP3

**Benodigdheden:**
- Tweede voice configureren per provider
- Aangepaste system prompt voor interview-scripts
- Segment-parser in de TTS-pipeline

### Open vragen
- Automatische interview-detectie vs. handmatige keuze door gebruiker?
- Welke tweede stem? (Ander geslacht/karakter voor duidelijk onderscheid)

---

## 7. Per-episode artwork in RSS feed
**Status:** Done
**Prioriteit:** Medium | **Effort:** Medium

### Probleem
Alle episodes tonen dezelfde feed-artwork in Apple Podcasts. Visueel onderscheid per aflevering ontbreekt.

### Oplossing
Per episode een eigen thumbnail tonen via `<itunes:image>` op item-niveau in de RSS feed.

**Afbeeldingsbronnen (fallback-keten):**
1. `doc.image` uit trafilatura (hoofdafbeelding van het artikel)
2. `og:image` uit HTML meta tags
3. Clearbit logo van het brondomein (`https://logo.clearbit.com/{domain}`)

**Verwerking (`src/episode_image.py`):**
- Download remote image, converteer naar vierkante JPEG (1400x1400, center crop via Pillow)
- Sla lokaal op in `EPISODE_IMAGE_DIR` en serveer via `/episode-images/{filename}`
- Apple Podcasts vereist vierkante artwork — rechthoekige og:images worden gecenter-cropped

**Database:**
- `image_url` kolom op `episodes` tabel (VARCHAR 2000, nullable)
- Lichtgewicht migratie via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` bij startup

### Bestanden
| File | Actie |
|---|---|
| `src/extract.py` | og:image extractie, Clearbit logo fallback |
| `src/episode_image.py` | Download, crop, JPEG-conversie |
| `src/feed.py` | `<itunes:image>` per item |
| `src/database.py` | `image_url` kolom + migratie |
| `server.py` | `/episode-images/` endpoint, cleanup bij delete |

### Beperking
- Bij privé RSS-feeds (niet via Apple Podcasts Connect) toont Apple Podcasts episode-artwork niet altijd betrouwbaar

---

## 8. VTT transcript pipeline
**Status:** Done
**Prioriteit:** Laag | **Effort:** Medium

### Probleem
Geen transcripten beschikbaar voor afleveringen.

### Oplossing
WebVTT transcripten genereren en koppelen via Podcasting 2.0 `<podcast:transcript>` tag in de RSS feed.

**Modi (`TRANSCRIPT_MODE` env var):**
- `none` (default) — geen transcript
- `heuristic` — timing op basis van woordtelling en geschatte duur
- `whisper_api` — OpenAI Whisper API voor echte tijdstempels, met heuristic fallback

**Bestanden:**
- `src/transcript.py` — transcriptgeneratie
- `src/feed.py` — `<podcast:transcript>` tag
- `server.py` — `/transcripts/{filename}` endpoint

### Beperking
- Apple Podcasts toont transcripten alleen voor shows in de Apple-catalogus (via Podcasts Connect), niet voor privé RSS-feeds

---

## 9. Share-integraties (Shortcuts, bookmarklet, setup-pagina)
**Status:** Done
**Prioriteit:** Hoog | **Effort:** Medium

### Oplossing
- **Apple Shortcuts**: Twee opdrachten — "Naar Podcast" (URL-only, alle apps) en "Naar Podcast (Safari)" (paywall-route via Safari Reader)
- **Desktop bookmarklet**: JavaScript one-liner die artikeltekst + URL naar `/submit` POST
- **Setup-pagina** (`/setup`): Publieke HTML-pagina met stap-voor-stap instructies, configureerbare bookmarklet, en feed-URL
- Shortcuts bevatten If/Otherwise error-handling die de server-response toont bij fouten

### Bestanden
- `static/setup.html` — setup-pagina
- `server.py` — `/setup` endpoint

---

## 10. Push-notificaties via ntfy
**Status:** Done
**Prioriteit:** Medium | **Effort:** Laag

### Oplossing
Push-notificaties naar telefoon via ntfy.sh bij succes, falen, en deploys.
- `src/notify.py` — ntfy helper module
- Geconfigureerd via `NTFY_TOPIC` env var (optioneel — zonder wordt het overgeslagen)
- Error messages worden gesanitized: alleen exception type + eerste regel, max 200 chars
- Deploy-notificatie bij serverstart met commit SHA (`NOTIFY_ON_DEPLOY`, default: `true`)

---

## 11. Google Cloud TTS als fallback
**Status:** Done
**Prioriteit:** Hoog | **Effort:** Medium

### Probleem
ElevenLabs Starter-plan heeft een limiet van 30.000 characters/maand.

### Oplossing
Drielaagse fallback-keten in `src/tts.py`: ElevenLabs → Gemini Flash TTS → WaveNet.

**Gemini Flash TTS (eerste fallback):**
- Style prompt: configureerbaar via `GOOGLE_TTS_STYLE_PROMPT` (default: podcast-presentator toon)
- Voice: `Kore` (instelbaar via `GOOGLE_TTS_GEMINI_VOICE`)
- Veel natuurlijker dan WaveNet dankzij LLM-gestuurde intonatie
- Betaald ($0.50/$10 per 1M tokens in/out), maar $300 startcredits

**WaveNet (tweede fallback):**
- Voice: `nl-NL-Wavenet-F` (instelbaar via `GOOGLE_TTS_WAVENET_VOICE`)
- 1M chars/maand gratis — betrouwbare gratis vangneet

**Chunking:**
- Google TTS API's hebben limieten per request (4000/5000 bytes)
- Scripts worden opgesplitst op alineagrenzen, audio per chunk gegenereerd en samengevoegd via pydub
- Credentials via `GOOGLE_TTS_CREDENTIALS_B64` (base64-encoded service account JSON)

---

## 12. Procesbesluiten (overwogen en verworpen opties)
**Status:** Vastgelegd

### Gekozen
- **Episode-art lokaal hosten** (vierkante JPEGs) in plaats van alleen externe `og:image`-URLs; dit is betrouwbaarder voor podcast-clients.
- **`HEAD` ondersteunen op feed/assets** (`/feed.xml`, `/audio/*`, `/episode-images/*`, `/transcripts/*`) voor crawler-compatibiliteit.
- **Conservatieve UK-domeinverfijning met expliciete uitzonderingen** (zoals `theguardian.com`), zodat herkenning van Brits Engels stabiel blijft.
- **Transcripten als VTT + RSS-linking** als technische basis, met `heuristic` of `whisper_api`.

### Verworpen of bijgesteld
- **Niet gekozen:** “alleen en-GB bij duidelijke UK URL-signalen”.  
  Reden: te streng; gewenste bronnen zoals The Guardian moeten standaard als en-GB kunnen vallen.
- **Niet gekozen:** Nederlandstalige intro voor niet-Nederlandse artikelen.  
  Reden: onnatuurlijk en inconsistent met brontaalweergave.
- **Niet gekozen als blokkade:** langdetect non-determinisme als apart risicoproject.  
  Reden: lage impact voor dit project; seed is gezet, verdere uitwerking niet geprioriteerd.
- **Niet gekozen voor privégebruik:** publicatie via Apple Podcasts Connect als vereiste route.  
  Reden: doel is privé RSS-gebruik; wel geaccepteerd dat Apple-features (transcripten, episode-art) in de app dan beperkt/inconsistent kunnen zijn.

### Geaccepteerde beperkingen
- Bij privé RSS-feeds in Apple Podcasts zijn transcripten niet zichtbaar en episode-artwork kan inconsistent zijn, ook als de feed technisch correct is.
