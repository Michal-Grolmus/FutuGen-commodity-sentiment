# Podrobny navod na testovani aplikace Commodity Sentiment Monitor

## Co aplikace dela (zjednodusene)

Aplikace funguje jako automaticky "posluchac" zivych streamu (napr. Bloomberg TV, CNBC, OPEC tiskovky). Kdyz nekdo v TV rekne neco o rope, zlatu, nebo psenic, aplikace to zachyti, prepisedo textu, analyzuje a rekne: "Toto je bullish signal pro ropu s 85% jistotou, protoze OPEC snizil produkci."

### Pipeline v 5 krocich:

```
1. AUDIO VSTUP     Vezme zvuk ze streamu nebo souboru
        |
2. PREPIS (STT)    Whisper prepise zvuk na text (lokalne, zdarma)
        |
3. EXTRAKCE        Claude AI najde v textu komodity, lidi, udalosti
        |
4. SCORING         Claude AI ohodnoti dopad na ceny (bullish/bearish/neutral)
        |
5. DASHBOARD       Vysledky se zobrazi na webove strance v realnem case
```

---

## Predpoklady

- Windows 10/11 s Python 3.11+
- Pripojeni k internetu (pro stazeni Whisper modelu a volani Claude API)
- Anthropic API klic (pro analyzu; bez nej funguje jen prepis)

---

## Krok 1: Instalace

Otevri terminal (PowerShell nebo cmd) a spust:

```bash
cd D:\OTHERS\WORK\FutuGen

# Vytvor virtualni prostredi (doporuceno)
python -m venv .venv
.venv\Scripts\activate

# Nainstaluj zavislosti
pip install -e ".[dev]"
```

Toto nainstaluje vsechny knihovny: Whisper, FastAPI, Anthropic SDK atd.

---

## Krok 2: Overeni instalace (testy)

```bash
pytest tests/ -v
```

Ocekavany vysledek: **27 passed** (vsechny testy zelene).

Pokud neco selze, zkontroluj:
- Python verze: `python --version` (musi byt 3.11+)
- Pip install probehl bez chyb

---

## Krok 3: Test prepisu (BEZ API klice)

Tento test nevyzaduje zadny API klic — pouziva jen lokalni Whisper model.

```bash
set INPUT_FILE=audio_samples/sample_01_opec.wav
python -m src.main
```

Co se stane:
1. Aplikace nacte audio soubor `sample_01_opec.wav` (simulovana OPEC tiskova konference)
2. Whisper model se stahne z internetu (~150 MB pri prvnim spusteni)
3. Audio se rozdeli na 10-sekundove chunky
4. Kazdy chunk se prepise na text
5. Dashboard bezi na `http://127.0.0.1:8000`

Ocekavany vystup v terminalu:
```
Loading Whisper model: base (device=cpu, compute=int8)
Whisper model loaded.
Pipeline starting...
Chunk xxx transcribed in 1.2s (0.1x real-time): OPEC has just announced...
```

Otevri prohlizec na **http://127.0.0.1:8000** — uvidis dashboard s prepisy, ale bez signalu (protoze chybi API klic).

Ukonci: stiskni **Ctrl+C**.

---

## Krok 4: Test s Anthropic API (plny pipeline)

### 4a: Nastav API klic

Vytvor soubor `.env` v korenove slozce projektu:

```bash
copy .env.example .env
```

Uprav `.env` — nastav svuj API klic:
```
ANTHROPIC_API_KEY=sk-ant-tvuj-skutecny-klic
INPUT_FILE=audio_samples/sample_01_opec.wav
```

### 4b: Spust plny pipeline

```bash
python -m src.main
```

Tentokrat ocekavej navic:
1. Po prepisu se text posle do Claude API
2. Claude identifikuje komodity (crude_oil_wti, crude_oil_brent)
3. Claude ohodnoti dopad (bullish, confidence 0.85)
4. Signal se zobrazi na dashboardu

Ocekavany vystup v terminalu:
```
Extraction xxx: 2 commodities, 1 people, 1 indicators (0.8s)
Signal xxx: crude_oil_wti bullish (conf=0.85) — OPEC production cuts reduce supply...
```

Na dashboardu (`http://127.0.0.1:8000`) uvidis:
- **Live Signals** sekce: zelena karta "WTI Crude Oil — BULLISH" s confidence barem
- **Latest Transcript** sekce: prepis z audia

### 4c: Otestuj vice samplu

Spust postupne s ruznymi soubory:

```bash
# Test 1: OPEC riz produkce (ocekavani: bullish oil)
set INPUT_FILE=audio_samples/sample_01_opec.wav
python -m src.main

# Test 2: Fed zvyseni sazeb (ocekavani: bearish gold)
set INPUT_FILE=audio_samples/sample_02_fed_hike.wav
python -m src.main

# Test 3: Sucho na Stredozapade USA (ocekavani: bullish wheat, corn)
set INPUT_FILE=audio_samples/sample_04_drought.wav
python -m src.main

# Test 4: Sankce na Rusko (ocekavani: bullish natural gas, oil)
set INPUT_FILE=audio_samples/sample_05_sanctions.wav
python -m src.main

# Test 5: Napeti na Blizkem vychode (ocekavani: bullish oil)
set INPUT_FILE=audio_samples/sample_09_mideast.wav
python -m src.main

# Test 6: Neutralni komentovani (ocekavani: neutral nebo zadne signaly)
set INPUT_FILE=audio_samples/sample_10_neutral.wav
python -m src.main
```

---

## Krok 5: Test s realnym YouTube videem

Aby jsi otestoval/a na realnych datech, pouzij nahrane video z YouTube:

### Varianta A: Stazeni YouTube videa jako audio

```bash
# Nainstaluj yt-dlp pokud jeste neni
pip install yt-dlp

# Stahni audio z realneho videa o komoditach
# Priklad: Bloomberg OPEC coverage
yt-dlp -x --audio-format wav -o "audio_samples/real_bloomberg.%(ext)s" "https://www.youtube.com/watch?v=REAL_VIDEO_ID"
```

Pozn: Nahrad `REAL_VIDEO_ID` ID videa. Vyhledej na YouTube: "Bloomberg OPEC oil announcement 2025" nebo "CNBC gold price analysis".

Pak spust:
```bash
set INPUT_FILE=audio_samples/real_bloomberg.wav
python -m src.main
```

### Varianta B: Zivy stream (pokud je dostupny)

```bash
set STREAM_URL=https://www.youtube.com/watch?v=LIVE_STREAM_ID
python -m src.main
```

Tento rezim bude kontinualne zpracovavat audio ze ziveho vysilan.

---

## Krok 6: Spusteni evaluace

Evaluace projde vsech 12 testovacich ukryvku a spocita presnost:

```bash
python -m evaluation.run_eval
```

Ocekavany vystup:
```
Loaded 12 test excerpts.
Processing: opec_01 — OPEC announces production cut...
  [CORRECT] Direction: expected=bullish, predicted=bullish | Commodity recall: 100%
Processing: fed_01 — Federal Reserve raises interest rates...
  [CORRECT] Direction: expected=bearish, predicted=bearish | Commodity recall: 100%
...
=== RESULTS ===
Direction accuracy: 83.3%
Avg commodity recall: 91.7%
Total API cost: $0.04
Report saved: evaluation/results/evaluation_report.md
```

Report se ulozi do `evaluation/results/evaluation_report.md`.

---

## Krok 7: Overeni weboveho dashboardu

Pri bezicim pipeline otevri `http://127.0.0.1:8000` v prohlizeci.

### Co na dashboardu vidis:

**Hlavicka:**
- Chunks: pocet zpracovanych audio bloku
- Signals: pocet detekovanych signalu
- Cost: celkove naklady na API volani
- Status: Connected (zelene) = SSE stream funguje

**Live Signals (leva cast):**
- Kazdy signal je karta s barvou:
  - **Zelena** = bullish (cena pravdepodobne nahoru)
  - **Cervena** = bearish (cena pravdepodobne dolu)
  - **Zluta** = neutral (nejasne)
- Kazda karta ukazuje: komoditu, smer, confidence %, casovy horizont, zduvodneni

**Latest Transcript (prava cast):**
- Prepisy z audia v realnem case
- Entity extrakcni informace (komodity, osoby, indikatory)

---

## Krok 8: Overeni v Docker kontejneru

```bash
# Nastav .env soubor (viz krok 4a)
docker compose up --build
```

Aplikace pobezi na `http://localhost:8000` (v Dockeru na 0.0.0.0).

---

## Reseni problemu

| Problem | Reseni |
|---------|--------|
| `ModuleNotFoundError` | Spust `pip install -e ".[dev]"` znovu |
| Whisper model se nestahuje | Zkontroluj pripojeni k internetu |
| Dashboard neukazuje signaly | Over, ze ANTHROPIC_API_KEY je nastaven v `.env` |
| "No input source configured" | Nastav `INPUT_FILE` nebo `STREAM_URL` v `.env` |
| Testy selhavaji | Zkontroluj Python >= 3.11, spust `pip install -e ".[dev]"` |
| Docker build selze | Over, ze Docker Desktop bezi |

---

## Kolik to stoji?

| Co | Cena |
|----|------|
| Jeden 10s chunk (extrakce + scoring) | ~$0.003 |
| 30 min demo | ~$0.50 |
| Evaluace (12 samplu) | ~$0.04 |
| Celkovy odhad vcetne vyvoje | ~$2 |

Budget $10 je dostatecny na desitky hodin bezprerusitoho zpracovani.
