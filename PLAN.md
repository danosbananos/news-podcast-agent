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

## 4. NYT-app Shortcut debugging
**Status:** Todo
**Prioriteit:** Medium | **Effort:** Laag (diagnose)

### Probleem
Delen vanuit de NRC-app naar de "Naar Podcast" Shortcut werkt, maar vanuit de NYT-app niet (of niet betrouwbaar).

### Onderzoeksvragen
- Wat deelt de NYT-app precies via het Share Sheet? (URL, tekst, of een ander type?)
- Verschijnt de Shortcut niet in het deelmenu, of verschijnt hij wel maar faalt hij?
- Welke foutmelding verschijnt er?

### Mogelijke oplossingen
- Invoertype van Shortcut 1 aanpassen (bijv. ook "Tekst" accepteren)
- URL-extractie verbeteren voor het formaat dat NYT deelt
- Safari-route blijft altijd de fallback voor paywalled NYT-content

### Niet doen
Een native iPhone-app bouwen lost het paywall-probleem niet op en is disproportioneel veel werk voor dit probleem.

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
