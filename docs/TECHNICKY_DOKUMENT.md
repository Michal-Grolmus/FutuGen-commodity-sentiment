# Technický dokument — Commodity Sentiment Monitor

**AI Engineer · Artefakt č. 3.** Real-time extrakce řeči z live streamů + scoring dopadu na ceny komodit.

## 1. Architektura

Třívrstvá asynchronní pipeline s back-pressure přes `asyncio.Queue`: **Ingestion** (yt-dlp + ffmpeg/PyAV auto-detekce) → **STT** (faster-whisper, lokálně CPU int8) → **Analysis** (LLM extract → LLM score + Yahoo RAG) → **Dashboard** (FastAPI + SSE) + JSONL signal log + delayed backtest. Extractor/scorer swapovatelné runtime bez restartu.

## 2. Klíčová rozhodnutí

- **faster-whisper lokálně** místo Whisper API — nulový variabilní náklad, offline, word-level timestampy; `small` WER 5–7 %.
- **2-stage LLM** (`extract → score`) — scorer vidí jen výřez + RAG: –50–70 % tokens, prázdná extrakce = 0 scoring volání.
- **Dual-provider** (Claude Haiku 4.5 + gpt-4o-mini) — runtime switch v Settings UI, adapter ~30 LOC.
- **PyAV + ffmpeg dual-backend** — bez ffmpeg fallback na `av`, Docker –80 MB.
- **Yahoo RAG** (cache 60 s) v scoringu → LLM kalibruje confidence podle trendu.
- **SSE** místo WebSocket — one-way broadcast, nativní auto-reconnect.

## 3. Model + prompty

Default **Claude Haiku 4.5**, fallback **gpt-4o-mini** (na 50-chunk Bloomberg/CNBC benchmarku Haiku +3 p.p. extraction / +2 p.p. scoring F1 za 2× cenu). **Extraction:** striktní JSON schema, kategorie commodities/people/indicators, 4 few-shot (prostý, ambigní, negativní „gold medal”, multi-entity), prázdno u chunků bez explicitního claimu. **Scoring:** extrakce + RAG + playbook („Fed hike → bearish gold”, „OPEC cut → bullish oil”), confidence >0.80 jen s konkrétní událostí/číslem/datem, timeframe (news = short, strukturální = medium), povinná citace `source_text`.

## 4. Náklady

10 min Yahoo Finance Live: Whisper $0; gpt-4o-mini extract+score **$0.045** = $0.27/h = $6.33/24h. Claude ≈ 2×. **Rozpočet $10 = ~37 h OpenAI / ~18 h Claude.**

## 5. Evaluace

**Walk-forward backtest, 387 událostí 2018–2024** (train <2022 / cal 2022 / test ≥2023). Baselines (bootstrap 95 % CI): random 28.8 %, always-bullish 47.5 % [39.6, 55.4], keyword 25.9 %. **LLM musí překonat 47.5 % na d=7.** P(správně d7 | správně d1) ≈ 33 % → half-life ~3 dny; adaptive horizon per event-type **+6.5 %** nad fixed-d7. MFE/MAE 1.55. Framework: McNemar, Platt kalibrace, reliability SVG, PnL/Sharpe, bez look-ahead.

**Limit:** ground-truth jsou Yahoo daily close, ne intraday → nelze měřit okamžitou reakci. Produkční validace = 3měsíční pilot + intraday ceny (Polygon.io $30–199/měs.) + 300+ signálů, milníky M1 uptime + 1000 signálů, M2 kalibrace, M3 A/B na intraday returns.

## 6. Co zlepšit v produkci

- **Škálování:** multi-stream (aktuálně 1/pipeline, redesign ~1 den), Whisper GPU `large-v3` (WER –3 p.p., throughput 10–20×), LLM worker pool, TimescaleDB pro log.
- **Monitoring:** Prometheus `/metrics` (latence, llm_errors, cost_burn, queue_depth), alerting, JSON logy s `chunk_id`, SLO 99.5 % uptime + p99 <15 s.
- **Kvalita signálu** (28/38 neutrálních „gold” na 10min Yahoo segmentu): noise gate před LLM (skip chunků bez keyword/čísla/action verb), rolling dedup, event-type taxonomy + UI filtr, Platt kalibrace.
- **Robustnost:** SIGTERM drain, exponential backoff s jitter, circuit breaker na LLM (3 fails → 60 s pauza scoringu, transkripty běží), persistent queue pro replay, versioned prompt hash.
- **Bezpečnost — CSRF/auth** (`src/dashboard/server.py:253-258`): `allow_origins=["*"]` bez auth → libovolná stránka může volat `POST /api/settings/api-key` (přepsat klíč, ztráta důvěrnosti transcriptu), `/pipeline/start`, `DELETE /commodities/{name}`. Fix: zúžit CORS na `127.0.0.1:8000` + `SameSite=Strict` token nebo povinná `X-Requested-With`.
- **Bezpečnost — LFI** (`src/pipeline.py:155-160`): cokoli mimo `http(s)/rtmp(s)/hls://` padne do `FileIngestor` → `id_rsa` jako `.wav` se načte. Fix: whitelist schémat + adresářů (`audio_samples/`).
- **Bezpečnost — XSS** (`src/dashboard/static/app.js:886-887`): `escapeHtml` neescapuje apostrof, backend povolí `'` v URL → breakout z JS stringu v `onclick`, exfiltrace API klíče z `localStorage`. Fix: `addEventListener` místo `onclick`.
- **Bezpečnost — SSRF** (`src/ingestion/stream_ingestor.py:314-319`): IP neomezena → cloud metadata `169.254.169.254` a RFC1918 projdou. Fix: resolvovat hostname, blokovat link-local/loopback/RFC1918.
- **Bezpečnost — menší:** žádný rate-limit, klíč v `localStorage`, `yt-dlp`/`ffmpeg` CVE. **V pořádku:** bind `127.0.0.1`, `create_subprocess_exec`, `SecurityHeadersMiddleware`, striktní validace Settings API. **Verdikt:** demo OK; pro interní síť opravit CSRF, LFI, XSS.

------------------------------------------------------------------------

*Plný kód, 96 pytest testů (ruff/mypy strict), evaluační report — GitHub repo.*
