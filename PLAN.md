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

## 5. Tweestemmigheid voor interviews
**Status:** Todo
**Prioriteit:** Laag | **Effort:** Hoog

### Probleem
Interviews worden nu voorgelezen als monoloog, wat onnatuurlijk klinkt.

### Oplossing
Gebruik twee ElevenLabs-stemmen (host + gast) voor interview-artikelen:

**Scriptgeneratie:**
- LLM formatteert het script met sprekersaanduidingen: `[HOST]: ...` en `[GAST]: ...`
- Detectie of een artikel een interview is: laat het LLM dit bepalen op basis van de tekst, of laat de gebruiker het aangeven via een parameter

**TTS-pipeline (`src/tts.py`):**
- Parse het script op sprekersaanduidingen
- Genereer audio per segment met de juiste `voice_id`
- Concateneer alle segmenten tot één MP3

**Benodigdheden:**
- Tweede ElevenLabs `voice_id` configureren (`ELEVENLABS_VOICE_ID_GUEST`)
- Aangepaste system prompt voor interview-scripts
- Segment-parser in de TTS-pipeline

### Open vragen
- Automatische interview-detectie vs. handmatige keuze door gebruiker?
- Welke tweede stem? (Ander geslacht/karakter voor duidelijk onderscheid)

---

## 6. Engelse stem bij Engelstalig artikel
**Status:** Todo
**Prioriteit:** Laag | **Effort:** Medium

Automatisch de juiste TTS-stem en taal kiezen op basis van de taal van het artikel. Moet nog uitgewerkt worden.

---

## 7. Share-integraties (Shortcuts, bookmarklet, setup-pagina)
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

## 8. Push-notificaties via ntfy
**Status:** Done
**Prioriteit:** Medium | **Effort:** Laag

### Oplossing
Push-notificaties naar telefoon via ntfy.sh bij succes en falen van episode-verwerking.
- `src/notify.py` — ntfy helper module
- Geconfigureerd via `NTFY_TOPIC` env var (optioneel — zonder wordt het overgeslagen)
- Error messages worden gesanitized: alleen exception type + eerste regel, max 200 chars

---

## 9. Google Cloud TTS als fallback
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