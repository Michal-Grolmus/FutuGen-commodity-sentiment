# Technický dokument — Commodity Sentiment Monitor

**Kandidát:** AI Engineer · **Projekt:** Real-time extrakce řeči z live streamu + scoring dopadu na ceny komodit
**Artefakt č. 3** podle zadání (Architektonická rozhodnutí, trade-offs, návrhy pro produkci).

---

## 1. Architektura v kostce

Třívrstvá asynchronní pipeline, spojená přes `asyncio.Queue`:

```
[Live stream / audio file]
      ↓  (Ingestion — yt-dlp + ffmpeg/PyAV)
   Audio chunks (10 s WAV @ 16 kHz mono)
      ↓  (STT — faster-whisper, lokálně, int8/CPU)
   Transkript + timestampy na úrovni slov
      ↓  (Extraction — LLM #1: komodity, osoby, ekonomické indikátory)
   Strukturovaná extrakce (JSON)
      ↓  (Scoring — LLM #2 + RAG z Yahoo Finance: aktuální cena)
   CommoditySignal {commodity, direction, confidence, rationale, timeframe}
      ↓
   Dashboard (FastAPI + SSE) + perzistentní log (JSONL)
```

Každá vrstva běží jako samostatný `async` loop; queues zajišťují back-pressure a umožňují nezávislé škálování. Transkriber je singleton (Whisper model loader je drahý); extractor/scorer mohou být swapnuty za běhu (`pipeline.set_api_key`).

---

## 2. Klíčová architektonická rozhodnutí a trade-offs

| Rozhodnutí | Alternativa | Proč takhle |
|---|---|---|
| **faster-whisper lokálně (CPU, int8)** | OpenAI Whisper API | Nulový běhový náklad, offline schopnost, latence 0.2–0.4× real-time na `small` modelu. API by přidala 20–50 ms latence a cca $0.006/min. |
| **LLM `extract → score` ve dvou krocích** | Jeden monolitický prompt | Menší token usage (extraction vrací strukturu, scoring dostává jen relevantní entity). Oddělená odpovědnost = snazší debug a promptové A/B. |
| **Dual-provider LLM (Anthropic + OpenAI)** | Jen Anthropic Claude | Zákaznická flexibilita — dashboard UI umožňuje přepnout provider za běhu bez restartu. Defaultní modely `claude-haiku-4.5` a `gpt-4o-mini` jsou oba levné a rychlé (Haiku-tier). |
| **PyAV + ffmpeg dual-backend pro stream ingestion** | Jen ffmpeg subprocess | PyAV (pip, libavformat) eliminuje potřebu ffmpeg binárky v PATH → `docker compose up` funguje bez `apt-get install ffmpeg` a lokální Windows dev nepotřebuje externí instalaci. ffmpeg se automaticky použije, když je na PATH (mírně rychlejší). |
| **RAG z Yahoo Finance při scoringu** | Bez kontextu | Scorer dostane aktuální cenu + 24h změnu. LLM tak může kalibrovat confidence podle toho, zda *"bullish signál"* není v konfliktu s již probíhajícím +5% pohybem. |
| **Persistentní JSONL signal log + delayed backtesting** | Jen real-time eventy | Append-only formát je jednoduchý, odolný vůči crashům, lidsky čitelný. Timeframe-aware delay (24 h / 7 d) umožňuje re-evaluaci bez hindsightu. |
| **FastAPI + SSE** | WebSocket / polling | SSE je jednosměrný broadcast, přesně vyhovující use-case. Bez WebSocket složitosti, funguje přes proxy/CDN. |

---

## 3. Nákladová analýza

**OpenAI `gpt-4o-mini`** (měřeno na reálném streamu Yahoo Finance Live, chunk = 10 s):

- **10 min streamu ≈ $0.0445** (60 chunks × ~$0.00074 per chunk, extract + score dohromady)
- **1 hod ≈ $0.27**
- **24/7 měsíc ≈ $194** (bez quality gate; s filtrací nízkokvalitních chunků lze snížit o 60–70 %)

**Anthropic `claude-haiku-4.5`:** cca 2× dražší (input $0.80/MTok, output $4/MTok), ale kvalita extrakce lepší na české/ambigní případy. Pro rozpočet $10 to znamená cca 22 min Claude nebo 45 min OpenAI aktivního streamu.

**Whisper** běží lokálně → nulový variabilní náklad. CPU `small` model dá ~0.3× RT na běžném notebooku.

---

## 4. Provozní závislosti (co je potřeba od zákazníka)

Pipeline je **funkčně hotová, ale její reálná hodnota závisí na vstupech, které musí dodat zákazník před nasazením:**

1. **Seznam live streamů k monitoringu** — kurátor musí nominovat zdroje, které jsou pro jeho obchodní rozhodování relevantní (Bloomberg TV, CNBC, konkrétní OPEC/Fed briefingy, specializované analytické pořady). Z jejich charakteru (jazyk, rychlost řeči, poměr komoditního obsahu vs. noise) plyne kalibrace chunk_duration, Whisper modelu a prompt templatů.
2. **Preferovaný LLM provider** — zákazník může mít vlastní enterprise kontrakt s OpenAI / Anthropic / Azure OpenAI / Google Vertex. Dashboard aktuálně podporuje **Anthropic a OpenAI**; pokud zákazník používá jiný provider (Groq, Mistral, Gemini, lokální LLaMA přes vLLM), přidá se třetí větev do `src/analysis/llm.py` helperu (~30 řádků) a rozšíří provider-selector v Settings UI. **Dodání API klíče** probíhá přes dashboard Settings (uloženo v localStorage prohlížeče + pushnuto na backend přes `POST /api/settings/api-key`) nebo přes `.env` pro deployment scenarios.
3. **Seznam sledovaných komodit** — výchozí registrace pokrývá 8 základních (WTI, Brent, Nat Gas, Gold, Silver, Wheat, Corn, Copper). Pokud zákazník sleduje například soft commodities (coffee, cocoa) nebo metals (platina, palladium, nickel), přidá je přes `POST /api/commodities` nebo UI v Commodities view — runtime registry, žádný code change.
4. **Slack webhook (volitelně)** — pro push notifikace signálů s confidence > 0.8.

Bez bodů 1+2 je to demo; s nimi production-ready PoC pro danou doménu.

---

## 5. Evaluace — co se dá a nedá měřit

### Co funguje

- **Clean-signal benchmark** (12 kurátorovaných úryvků s ground truth): 100 % direction accuracy. Je to však cherry-picked set, nikoli realistická metrika.
- **Retrospective backtest na 387 historických událostech** (2018–2024, walk-forward split, train/cal/test): na baselineách (random, always-bullish, keyword) cca 25–48 % accuracy proti aktuálnímu pohybu trhu. LLM musí tento baseline překročit, jinak nepřidává hodnotu.
- **Horizon analysis**: signál má typicky half-life ~3 dny (P(správně na d7 | správně na d1) ≈ 33 %). Per-event-type adaptive horizon dává +6.5 % uplift nad fixed-d7 evaluací.

### Co je fundamentálně omezené

**Historická data nebyla sbírána z přesného časového razítka konkrétního proslovu.** Pro každý seedovaný event je:
- Datum = **den** události (ne hodina / minuta, kdy headline dorazila na tape)
- Cena = Yahoo Finance **closing price** v ten den (ne intraday snapshot k okamžiku oznámení)

Důsledek: nelze měřit **okamžitou reakci trhu** na konkrétní větu ze streamu. Pokud OPEC oznámí cut v 10:30 UTC a trh na to reaguje +2 % během 15 min, naše evaluace to zachytí jen jako *close-to-close return* daného obchodního dne — smíchaný s ostatním intraday noise. Produkční validace modelu vyžaduje:

1. **Dlouhodobý paralelní log vlastních transkripcí** s přesnými timestampy (sekundy)
2. **Intraday ceny** (minutové rozlišení, zdroj: Polygon.io, Alpha Vantage premium, Databento — ~$30–300/měs.)
3. **Pairing transcript timestamp → price snapshot** → výpočet return na horizontech 1 min / 5 min / 15 min / 1 h
4. Toto **běžet 2–3 měsíce** pro statisticky smysluplný vzorek (300+ nezávislých signálů)

Teprve potom lze stanovit, zda systém obchodně přidává hodnotu nad baseline a zda confidence je kalibrovaná.

### Důsledek pro sales-pitch

Honest framing: *"Systém spolehlivě extrahuje komoditní entity a generuje směrové signály s rationale. Kalibrace confidence a čistá return-based přesnost vyžadují 2–3 měsíce produkčního logování před definitivní výpovědí."* Nabídnout pilot v tomto délce s měřitelnými milníky.

---

## 6. Co zlepšit před produkčním nasazením

### Škálovatelnost
- **Multi-stream**: aktuálně 1 stream/pipeline. Redesign na N paralelních ingestor tasks s label-routed queues (~1 den práce).
- **Whisper GPU**: `large-v3` na T4/A10 sníží WER o ~3 p.p. při 10–20× vyšším throughput (~$0.10/h GPU runtime).
- **Worker pool pro LLM**: aktuálně sekvenční scoring per chunk. Při více streamech paralelizovat přes `asyncio.gather` s rate limit token-bucketem.

### SLA + monitoring
- **Prometheus metrics** endpoint (`/metrics`): `stt_latency_ms`, `extraction_latency_ms`, `llm_errors_total`, `signals_emitted_total`, `stream_reconnects_total`, `api_cost_usd_total`.
- **Alerting**: PagerDuty/Opsgenie na `stream_down_seconds > 60`, `llm_error_rate > 5% / 5min`, `api_cost_burn_rate > $1/h`.
- **Log aggregation**: structured JSON logs do Loki/Datadog. Korelace chunk_id napříč vrstvami.
- **Health check + readiness**: `/health` existuje; přidat `/ready` který ověří Whisper loadness + LLM connectivity.

### Bezpečnost
- **API key storage**: aktuálně browser localStorage + in-memory backend. Pro produkci: secrets manager (AWS Secrets Manager / HashiCorp Vault), rotace klíčů, audit log kdo přepnul provider.
- **Rate limiting** na `/api/settings/api-key` (aktuálně neomezeně — someone může zkoušet hádat).
- **CORS**: dashboard má `allow_origins=["*"]`. Pro produkci whitelist zákaznických originů.
- **Stream URL allowlist**: `StreamIngestor._validate_url` povoluje http/https/rtmp/hls; přidat denylist pro interní IP ranges (SSRF protection).
- **Signal log sanitizace**: aktuálně ukládáme `source_text` jako plain text. Pokud by stream obsahoval PII (jména, zájmena), pro GDPR-regulované customer: redaction přes entity PII detection.

### Kvalita signálu
- **Noise gate před LLM**: chunks bez commodity keyword / price number / action verb přeskočit → ušetří 60–70 % API volání a odstraní šum (viz pozorování: 28 neutrálních signálů ze segmentu o ETF composition).
- **Rolling dedup** v broadcast loopu: stejná komodita + stejný směr + podobné rationale v <5 min → update existing místo create new.
- **Event-type taxonomy**: rozlišit `news_event` / `analyst_forecast` / `narrative` / `commentary` / `mention`. Default UI filtr: show first two, hide last two.
- **Confidence kalibrace**: fit Platt scaling na production logu po 2 měsících provozu → remapovat raw LLM confidence na empirickou přesnost.

### Provozní robustnost
- **Graceful shutdown**: SIGTERM handler počká na drain queues (max 30 s) → žádné ztracené chunks při rolling restart.
- **Stream reconnect backoff**: aktuálně fixed 5 s s max 360 retries. Lepší: exponential backoff s jitter, max 5 min.
- **Circuit breaker na LLM**: při 3 po sobě failujících voláních na 60 s pausovat extraction/scoring, broadcast jen transcripty.
- **Persistent queue**: při pádu backend teď ztratíme in-flight chunks. SQLite/Redis-backed queue umožní replay.

---

## 7. Závěr

Pipeline je **end-to-end funkční, Dockerizovaná, otestovaná** (96 jednotkových testů, ruff clean). Evaluace je **metodicky čistá** (walk-forward split, baselines, bootstrap CI, horizon analysis), ale **validita produkčních metrik vyžaduje 2–3 měsíce intraday logu** z konkrétních zákaznických streamů.

Největší hodnota projektu není v konkrétním číslu accuracy, ale v **čitelném produkčním frameworku** (auditovatelný prompt, strukturovaný JSONL log, runtime-swapovatelný LLM provider, dual-backend audio), na kterém může provozní tým iterovat dle reálných dat zákazníka.
