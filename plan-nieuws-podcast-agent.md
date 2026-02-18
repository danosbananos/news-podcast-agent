# Plan: Nieuws-naar-Podcast Agent

## Wat het doet

Je leest een nieuwsartikel op je iPhone of desktop. Je deelt de URL. Binnen 1-2 minuten verschijnt er een nieuwe aflevering in Apple Podcasts — een natuurlijk klinkend podcastscript, ingesproken door ElevenLabs.

---

## Architectuur

```
┌──────────────────────┐
│  iPhone (Safari)     │──Shortcut────▶┐  (Reader-modus haalt tekst
│                      │               │   achter paywall op)
│  iPhone (NRC/NYT app)│──Shortcut────▶┤  (kopieer tekst of deel URL)
│                      │               │
│  Desktop (Chrome)    │──Bookmarklet─▶┤  (extraheert article-tekst
│                      │               │   uit ingelogde browser)
│  PDF fallback        │──Upload──────▶┤  (voor edge cases)
└──────────────────────┘               │
                                       ▼
                             ┌─────────────────────┐
                             │   FastAPI Server     │
                             │   (altijd aan)       │
                             │                      │
                             │  1. Ontvang input    │
                             │     (tekst/URL/PDF)  │
                             │  2. Extraheer tekst  │
                             │  3. Claude Haiku     │
                             │     → podcastscript  │
                             │  4. ElevenLabs API   │
                             │     → mp3            │
                             │  5. Update RSS feed  │
                             └──────────┬──────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │  Publieke RSS feed   │
                              │  (XML + mp3-hosting) │
                              └──────────┬──────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │   Apple Podcasts     │
                              │   (abonnement op     │
                              │    jouw RSS feed)    │
                              └─────────────────────┘
```

---

## Componenten

### 1. Server (FastAPI + Python)

De kern van het systeem. Een lichtgewicht Python-webserver die:

- Een POST-endpoint biedt (`/submit`) dat drie typen input accepteert:
  - **Tekst + metadata** (primair) — vanuit bookmarklet of Shortcut
  - **Alleen URL** — voor niet-paywalled artikelen
  - **PDF-upload** — als fallback voor paywall-situaties
- Een GET-endpoint biedt (`/feed.xml`) dat de RSS-feed serveert
- Statische mp3-bestanden serveert vanuit een persistent volume (`/audio/<bestandsnaam>.mp3`)

**Waarom FastAPI:** async, snel, minimaal, perfecte fit voor dit soort microservices.

### 2. Tekstextractie (meerdere bronnen)

De server verwerkt input in volgorde van voorkeur:

**A. Direct meegestuurde tekst (primair)**
De bookmarklet (desktop) en Apple Shortcut (iPhone) extraheren de artikeltekst aan de clientkant — waar jij ingelogd bent. Dit omzeilt paywalls volledig. De server ontvangt platte tekst en hoeft niets te scrapen.

**B. URL scrapen met Trafilatura (fallback voor open artikelen)**
Voor niet-paywalled artikelen kan de server de tekst zelf ophalen. Trafilatura is de beste Python-library hiervoor: het haalt de hoofdtekst eruit en negeert navigatie, advertenties en sidebars. Het extraheert ook metadata zoals titel, auteur en publicatiedatum.

**C. PDF-upload (fallback voor edge cases)**
Als de tekst niet via de bookmarklet/Shortcut lukt, kun je een PDF "printen" vanuit de browser en uploaden. De server extraheert tekst met `pdfplumber`.

De verwerkingslogica:

```
Ontvang request
  ├── Bevat 'text' veld?     → Gebruik die tekst direct
  ├── Bevat PDF-upload?       → Extraheer tekst uit PDF
  └── Bevat alleen 'url'?    → Probeer te scrapen met Trafilatura
                                 ├── Succes? → Gebruik tekst
                                 └── Paywall/fout? → Stuur melding:
                                      "Artikel niet bereikbaar,
                                       stuur tekst of PDF mee"
```

### 3. Scriptgenerator (Claude API — Haiku)

Herschrijft het artikel naar een podcastscript. Dit is de stap die het verschil maakt tussen een voorgelezen artikel en iets dat aanvoelt als een podcast. Het script bevat:

- Een korte intro ("Welkom bij je dagelijkse nieuwspodcast. Vandaag...")
- De kern van het artikel, herschreven voor gesproken taal (kortere zinnen, actieve vorm, duidelijke overgangen)
- Uitspraakhints voor namen, afkortingen, cijfers
- Een korte afsluiting

**Model:** Claude Haiku (claude-haiku-4-5-20251001) — snel, goedkoop (~€0,01-0,03 per artikel), en meer dan goed genoeg voor deze taak.

### 4. Text-to-Speech (ElevenLabs API)

Zet het podcastscript om naar een mp3. ElevenLabs biedt de meest natuurlijk klinkende stemmen, inclusief goede Nederlandse stemmen.

**Model:** `eleven_multilingual_v2` (of v3 zodra beschikbaar)
**Stem:** kies een stem uit de ElevenLabs voice library die past bij een nieuwspodcast-stijl. Je kunt ook een custom voice clonen als je dat wilt.

### 5. Mp3-opslag (Railway Volume)

Railway's filesystem is ephemeral — bestanden overleven geen redeploy. Daarom worden mp3-bestanden opgeslagen op een **Railway persistent volume**, gemount op bijv. `/data/audio`. Dit volume blijft bestaan onafhankelijk van deploys. Voor het verwachte volume (~100-150 mp3's van 1-3 MB per maand) is dit ruim voldoende.

### 6. RSS Feed Generator

Een simpele XML-generator die een geldige podcast-RSS feed bijhoudt. Elke keer dat er een nieuw artikel verwerkt is, wordt er een `<item>` toegevoegd aan de feed met:

- Titel van het artikel
- Publicatiedatum
- Link naar de mp3
- Korte beschrijving

Apple Podcasts pollt deze feed periodiek (standaard elk uur). Je kunt ook een handmatige refresh triggeren in de Podcasts-app.

### 7. Share-integraties (paywall-proof)

**iPhone — Apple Shortcut:**
Een Shortcut die verschijnt in het Share Sheet van Safari en nieuwsapps. De Shortcut:
- Vanuit Safari: gebruikt "Get Article from Web Page" (Reader-modus) om de tekst te extraheren — werkt met jouw ingelogde sessie, dus ook achter paywalls bij NRC en NYT
- Vanuit apps: pakt de gedeelde URL en opent deze kort in Safari Reader, of accepteert gekopieerde tekst van het klembord
- Stuurt de tekst + URL + titel als POST-request naar jouw server
- Toont een bevestiging ("Artikel wordt verwerkt!")

**Desktop — Slimme bookmarklet:**
Een bookmarklet die de artikeltekst uit de pagina haalt terwijl jij ingelogd bent:
```javascript
javascript:void(fetch('https://jouw-app.up.railway.app/submit',{
  method:'POST',
  headers:{'Content-Type':'application/json',
            'Authorization':'Bearer JOUW_KEY'},
  body:JSON.stringify({
    url:location.href,
    title:document.title,
    text:document.querySelector('article')?.innerText
  })
}).then(r=>r.json()).then(d=>alert(d.message)))
```
Dit werkt voor NRC en NYT omdat beide sites hun artikeltekst in een `<article>`-tag plaatsen. De extractie gebeurt in jouw browser met jouw sessie.

**PDF-upload (fallback):**
Voor edge cases waar bovenstaande niet werkt: print het artikel als PDF en upload via een simpel webformulier op `https://jouw-app.up.railway.app/upload`.

---

## Hosting

De server moet altijd bereikbaar zijn, want:
- Je wilt op elk moment een URL kunnen insturen
- Apple Podcasts moet de RSS feed en mp3's kunnen ophalen

### Platform: Railway

Railway is een container-platform dat deploy via `git push`. Het is ideaal voor dit project omdat:
- Geen serverbeheer nodig (geen SSH, geen OS-updates)
- Automatisch HTTPS op een `*.up.railway.app`-domein
- Ingebouwde PostgreSQL als managed service
- Persistent volumes voor mp3-opslag
- Deploys via GitHub-integratie
- Je draait al een ander project op Railway, dus geen extra abonnementskosten — de $5/maand Hobby-plan is per account, niet per project

### Domein + HTTPS

Railway geeft automatisch een publiek HTTPS-adres. Optioneel kun je een eigen domein koppelen (bijv. via Cloudflare, ~€10/jaar), maar voor persoonlijk gebruik volstaat het Railway-domein.

---

## Kosten (geschat, per maand)

Uitgaande van 3-5 artikelen per dag:

| Component | Kosten |
|---|---|
| Claude API (Haiku, ~100-150 artikelen/maand) | ~€1,50 - €3,00 |
| ElevenLabs API (Starter plan, 30.000 chars/maand) | $5/maand (~€4,50) |
| Railway Hobby plan (gedeeld met bestaand project) | €0 extra (al betaald) |
| Railway resource usage (CPU/RAM, geschat) | ~€1 - €2/maand |
| Domein (optioneel) | ~€0,80/maand |
| **Totaal** | **~€7 - €10/maand** |

> **Opmerking:** de Railway Hobby-abonnementskosten ($5/maand) betaal je al voor je bestaande project. De $5 aan usage credits wordt gedeeld over al je projecten. Pas als het totaalverbruik boven de $5 uitkomt, betaal je het meerdere. Deze podcast-agent is lichtgewicht (idle server, piekjes bij artikel-verwerking), dus het extra verbruik is minimaal.

### ElevenLabs API-plan nader bekeken

Een gemiddeld nieuwsartikel als podcastscript ≈ 3.000-5.000 karakters. Bij 100 artikelen/maand is dat 300.000-500.000 karakters. Het **Starter-plan** ($5/maand, 30.000 chars) is dan te krap. Realistischer:

- **Creator-plan** ($22/maand, 100.000 chars) — voldoende voor ~20-30 artikelen/maand
- **Pro-plan** ($99/maand, 500.000 chars) — voldoende voor ~100+ artikelen/maand
- **Alternatief:** gebruik het gratis tier (10.000 chars/maand, ~2-3 artikelen) om te testen

> **Tip:** je kunt het script ook inkorten. In plaats van het hele artikel voor te lezen, kun je Claude een samenvatting van ~1.000-1.500 karakters laten maken. Dan red je 20-30 artikelen/maand met het Starter-plan.

---

## Beveiliging

Omdat de server publiek bereikbaar is, zijn er een paar maatregelen nodig:

- **API-key op het `/submit` endpoint** — een simpele bearer token die je in de Shortcut en bookmarklet opneemt, zodat niet iedereen artikelen kan insturen
- **Rate limiting** — maximaal bijv. 20 requests per uur
- **Input-validatie** — alleen geldige URLs accepteren
- **HTTPS** — verplicht voor Apple Podcasts én voor het beschermen van je API-key in transit

---

## Fasering

### Fase 1 — Proof of Concept (1 dag)

Doel: een werkend Python-script dat lokaal draait.

- [ ] Tekstextractie: URL scrapen (Trafilatura), platte tekst, en PDF-input
- [ ] Claude Haiku API-call: artikel → podcastscript
- [ ] ElevenLabs API-call: script → mp3
- [ ] Mp3 afspelen en beoordelen

Resultaat: je kunt een URL, tekst, of PDF invoeren en krijgt een mp3 terug.

### Fase 2 — Server + RSS (1-2 dagen)

Doel: een draaiende server met podcast-feed.

- [ ] FastAPI-server met `/submit` en `/feed.xml` endpoints
- [ ] PostgreSQL-database (Railway) voor het bijhouden van verwerkte artikelen
- [ ] RSS XML-generator (conform Apple Podcast specificaties)
- [ ] Mp3-opslag op persistent volume en hosting via FastAPI
- [ ] Feed testen met een podcast-validator (bijv. Podbase of Cast Feed Validator)
- [ ] Abonneren in Apple Podcasts

Resultaat: je kunt via een API-call een artikel insturen en het verschijnt in Apple Podcasts.

### Fase 3 — Share-integraties (halve dag)

Doel: moeiteloos artikelen insturen, inclusief achter paywalls.

- [ ] Apple Shortcut bouwen met Reader-modus (pakt tekst achter paywall)
- [ ] Shortcut testen met NRC en NYT (ingelogd in Safari)
- [ ] Slimme bookmarklet maken die `article`-tekst meestuurt
- [ ] Bookmarklet testen op NRC.nl en NYTimes.com
- [ ] PDF-upload pagina op de server (simpel webformulier)
- [ ] Bevestigingsnotificatie na succesvolle verwerking

Resultaat: twee tikken op je iPhone, en het artikel wordt een podcast.

### Fase 4 — Deploy + Polish (1 dag)

Doel: stabiel draaien in productie.

- [ ] Railway project aanmaken met GitHub-repo
- [ ] PostgreSQL service toevoegen aan het Railway project
- [ ] Persistent volume aanmaken en mounten voor mp3-opslag
- [ ] Environment variables instellen (API-keys, database URL)
- [ ] Deploy via `git push` en controleren of alles draait
- [ ] API-key beveiliging
- [ ] Foutafhandeling (wat als scraping faalt? wat als de URL geen artikel is?)
- [ ] Logging en monitoring
- [ ] Automatisch opruimen van oude mp3's (bijv. ouder dan 30 dagen)

Resultaat: een betrouwbaar systeem dat je dagelijks kunt gebruiken.

### Fase 5 — Optionele uitbreidingen

- [ ] Meerdere stemmen (bijv. een andere stem voor tech-nieuws vs. politiek)
- [ ] Dagelijkse "ochtendpodcast" die automatisch de top-5 artikelen uit je RSS-reader verwerkt
- [ ] Queue-systeem zodat meerdere artikelen parallel verwerkt worden
- [ ] Notificatie (Pushover/Pushcut) wanneer een aflevering klaarstaat
- [ ] Web-dashboard om de queue en geschiedenis te bekijken

---

## Tech Stack Samenvatting

| Component | Technologie |
|---|---|
| Taal | Python 3.11+ |
| Web framework | FastAPI |
| Article scraping | Trafilatura |
| PDF-extractie | pdfplumber |
| Script generatie | Claude API (Haiku) |
| Text-to-Speech | ElevenLabs API (eleven_multilingual_v2) |
| Database | PostgreSQL (Railway managed) |
| Mp3-opslag | Railway persistent volume |
| RSS feed | Python xml.etree (of feedgen library) |
| Hosting | Railway (container platform) |
| HTTPS | Automatisch via Railway (*.up.railway.app) |
| iPhone share | Apple Shortcuts (met Reader-modus voor paywalls) |
| Desktop share | Bookmarklet (met article-extractie voor paywalls) |

---

## Promptontwerp (Claude Haiku)

Het systeem-prompt voor het genereren van het podcastscript is cruciaal. Een eerste versie:

```
Je bent een redacteur voor een persoonlijke nieuwspodcast in het Nederlands.
Herschrijf het volgende nieuwsartikel naar een podcastscript.

Regels:
- Begin met een korte intro: "Je luistert naar [titel onderwerp].
  Gepubliceerd door [bron] op [datum]."
- Herschrijf de tekst voor gesproken taal: korte zinnen, actieve vorm,
  geen jargon zonder uitleg
- Schrijf getallen voluit (15 miljoen, niet 15.000.000)
- Schrijf afkortingen voluit bij eerste gebruik
  (NATO wordt "de NAVO, de Noord-Atlantische Verdragsorganisatie")
- Gebruik natuurlijke overgangen tussen alinea's
- Sluit af met een korte samenvatting in één zin
- Houd de lengte onder de 2 minuten leestijd
  (maximaal ~1.500 karakters) om API-kosten beheersbaar te houden
- Geef ALLEEN het script terug, geen metadata of instructies
```

---

## Risico's en mitigatie

| Risico | Impact | Mitigatie |
|---|---|---|
| ElevenLabs API-kosten hoger dan verwacht | Maandelijks budget overschrijden | Scriptlengte limiet instellen; dagelijks budget in code afdwingen |
| Trafilatura kan sommige sites niet scrapen | Artikel niet beschikbaar | Fallback: bookmarklet/Shortcut stuurt tekst mee; PDF-upload als noodoplossing |
| Paywall blokkeert scraping (NRC, NYT) | Geen tekst beschikbaar | Primair: client-side extractie via bookmarklet/Shortcut; fallback: PDF |
| NRC/NYT wijzigt HTML-structuur | Bookmarklet haalt geen tekst op | `article`-selector is robuust; eventueel site-specifieke selectors toevoegen |
| Apple Podcasts ververst feed traag | Nieuwe afleveringen niet direct zichtbaar | Is normaal (kan tot 1 uur duren); handmatige refresh mogelijk |
| ElevenLabs API down | Geen audio | Retry-mechanisme met exponential backoff; optioneel Edge TTS als fallback |
| Server niet bereikbaar | Geen artikelen insturen | Railway heeft ingebouwde health checks en auto-restart; monitoring met uptime check |

---

## Eerste stap

Start met **Fase 1**: het proof of concept. Hiervoor heb je nodig:

1. **Claude API-key** — aanmaken op [console.anthropic.com](https://console.anthropic.com)
2. **ElevenLabs API-key** — aanmaken op [elevenlabs.io](https://elevenlabs.io) (gratis tier is genoeg om te testen)
3. **Python 3.11+** geïnstalleerd

Zodra je die hebt, kan ik de volledige code voor Fase 1 voor je schrijven.
