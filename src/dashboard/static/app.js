// ===== STATE =====
let activeSSE = null;
let isDemoMode = false;
// Stream IDs removed via the UI. Buffered SSE events for these IDs are
// ignored so "Remove" can't be undone by a stale broadcast.
const removedStreamIds = new Set();

// Multi-select filters (Set of IDs); empty set = nothing selected
const selectedStreamIds = new Set();
const selectedCommodityIds = new Set();

// Stream data: { streamId: { name, url, type, transcript, signals[], stopped } }
const streams = {};

// Default saved streams (loaded on first visit, then user edits persist in localStorage)
// Categories shown in the Saved Streams modal. Items without a category
// default to "Live streams" for backward compatibility with user-added entries.
const SAVED_CATEGORIES = [
  { id: "live", label: "Live streams" },
  { id: "historical", label: "Historical videos (multi-commodity)" },
  { id: "file", label: "Audio samples (local files)" },
  { id: "custom", label: "Your streams" },
];

const DEFAULT_SAVED_STREAMS = [
  // --- Live streams (24/7 channels) ---
  { name: "Bloomberg Business News", url: "https://www.youtube.com/watch?v=iEpJwprxDdk", category: "live" },
  { name: "Bloomberg Originals", url: "https://www.youtube.com/watch?v=DxmDPrfinXY", category: "live" },
  { name: "Yahoo Finance 24/7", url: "https://www.youtube.com/watch?v=KQp-e_XQnDE", category: "live" },
  { name: "CNBC Marathon", url: "https://www.youtube.com/watch?v=9NyxcX3rhQs", category: "live" },
  { name: "Bloomberg TV (channel)", url: "https://www.youtube.com/@markets/live", category: "live" },
  { name: "CNBC (channel)", url: "https://www.youtube.com/@CNBC/live", category: "live" },
  { name: "Reuters (channel)", url: "https://www.youtube.com/@Reuters/live", category: "live" },
  { name: "Kitco News (channel)", url: "https://www.youtube.com/@KitcoNEWS/live", category: "live" },

  // --- Historical videos (multi-commodity, front-loaded) ---
  // All entries have multiple commodities mentioned within the FIRST 2 MINUTES,
  // so credits aren't burned waiting for the speaker to get to the point.
  // CNBC TV18 daily briefings are news-format: the commodities are announced
  // in the very first sentence.

  // Ultra-short briefings (< 2 min) — the entire video is a multi-commodity scan
  { name: "CNBC TV18: Oil + Copper record highs (1:27)", category: "historical",
    url: "https://www.youtube.com/watch?v=X_A08N9GO9g" },
  { name: "CNBC TV18: Gold $4k + Copper 3-mo high (1:26)", category: "historical",
    url: "https://www.youtube.com/watch?v=Ao6bO2CXm0E" },
  { name: "CNBC TV18: Oil firm, Copper + Gold slip (1:31) — 3 commodities", category: "historical",
    url: "https://www.youtube.com/watch?v=tziI68GYIj4" },
  { name: "CNBC TV18: Copper record, Crude -2%, Gold gains (1:34) — 3 commodities", category: "historical",
    url: "https://www.youtube.com/watch?v=9F30Dsb74l0" },
  { name: "CNBC TV18: Crude steady, Gold 2-mo low (1:36)", category: "historical",
    url: "https://www.youtube.com/watch?v=McyesJLRhGw" },

  // Short (5–10 min) — multi-commodity, news/outlook format
  { name: "Commodities rally: Gold + Oil (5:03)", category: "historical",
    url: "https://www.youtube.com/watch?v=eOmzQJn92rA" },
  { name: "Gold + Silver + Copper 2026 outlook (6:18) — 3 commodities", category: "historical",
    url: "https://www.youtube.com/watch?v=Xmc83f-JOfU" },
  { name: "Oil + Gold + Silver + Copper trade setups (8:15) — 4 commodities", category: "historical",
    url: "https://www.youtube.com/watch?v=pU9Y3U0az9E" },

  // Medium (10–15 min) — multi-commodity analysis with front-loaded summary
  { name: "CNBC TV18 Big C: Oils + Metals outlook (10:56)", category: "historical",
    url: "https://www.youtube.com/watch?v=rS4KlK3BUh0" },
  { name: "CNBC TV18: Gold + Silver Commodity Champions (11:16)", category: "historical",
    url: "https://www.youtube.com/watch?v=FIGIJ__rIUI" },
  { name: "CNBC TV18: Gold + Silver + Copper + Crude (13:45) — 4 commodities", category: "historical",
    url: "https://www.youtube.com/watch?v=o0OMr9yerf4" },

  // --- Local audio files (offline demo) ---
  { name: "Sample: OPEC analysis (file)", url: "audio_samples/real/opec_raw.wav", category: "file" },
  { name: "Sample: Fed & Gold (file)", url: "audio_samples/real/fed_raw.wav", category: "file" },
];

function loadSavedStreams() {
  let stored = [];
  try {
    const raw = localStorage.getItem("csm_saved_streams");
    if (raw) stored = JSON.parse(raw);
  } catch (e) { void e; }
  // The `historical` category is curated by the app — we wipe stored entries
  // in that category on every load so curation updates (e.g. replacing a
  // slow-start video with a front-loaded one) always propagate. User-added
  // entries (category "custom") and their live/file overrides are preserved.
  const filteredStored = stored.filter(s => s.category !== "historical");
  const storedUrls = new Set(filteredStored.map(s => s.url));
  const merged = [...filteredStored];
  for (const def of DEFAULT_SAVED_STREAMS) {
    if (!storedUrls.has(def.url)) merged.push(def);
  }
  return merged.map(s => ({ ...s, category: s.category || "custom" }));
}

function persistSavedStreams(list) {
  try { localStorage.setItem("csm_saved_streams", JSON.stringify(list)); } catch (e) { void e; }
}

let savedStreams = loadSavedStreams();

// Commodity data: { commodityId: { display_name, short_name, events[] } }
const DEFAULT_COMMODITIES = {
  crude_oil_wti: { display_name: "WTI Crude Oil", short_name: "WTI" },
  crude_oil_brent: { display_name: "Brent Crude Oil", short_name: "Brent" },
  natural_gas: { display_name: "Natural Gas", short_name: "Nat Gas" },
  gold: { display_name: "Gold", short_name: "Gold" },
  silver: { display_name: "Silver", short_name: "Silver" },
  wheat: { display_name: "Wheat", short_name: "Wheat" },
  corn: { display_name: "Corn", short_name: "Corn" },
  copper: { display_name: "Copper", short_name: "Copper" },
};
const commodities = {};
// Seed with defaults synchronously so UI works even if /api/commodities 404s
for (const [id, c] of Object.entries(DEFAULT_COMMODITIES)) {
  commodities[id] = { display_name: c.display_name, short_name: c.short_name, events: [] };
  selectedCommodityIds.add(id);
}

async function loadCommodities() {
  // Refresh from backend registry (adds custom commodities; keeps defaults)
  const list = await fetchJSON("/api/commodities");
  if (!Array.isArray(list)) return;
  for (const c of list) {
    if (!commodities[c.name]) {
      commodities[c.name] = {
        display_name: c.display_name,
        short_name: c.display_name.length > 12 ? c.display_name.split(" ")[0] : c.display_name,
        events: [],
      };
      selectedCommodityIds.add(c.name);
    }
  }
}

// ===== INIT =====
async function rehydrateApiKeyFromStorage() {
  // If user saved a key in a previous session, push it back into the running
  // pipeline so server-restart doesn't force the onboarding flow again.
  const anthKey = localStorage.getItem("csm_api_key") || "";
  const openKey = localStorage.getItem("csm_openai_api_key") || "";
  const storedProvider = localStorage.getItem("csm_llm_provider");
  const provider = storedProvider === "openai" ? "openai" : "anthropic";
  const key = provider === "openai" ? openKey : anthKey;
  if (!key) return false;
  try {
    const res = await fetch("/api/settings/api-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key, provider }),
    });
    const data = await res.json();
    return !!(data && data.ok && data.active);
  } catch (e) {
    return false;
  }
}

async function init() {
  await loadCommodities();

  // Rehydrate first: if localStorage has a key, push to server before we read /api/config
  const rehydrated = await rehydrateApiKeyFromStorage();
  const config = await fetchJSON("/api/config");

  const hasKey = rehydrated || config.has_api_key;
  if (!hasKey && !config.input_source) {
    // Genuinely first-time user (no key anywhere, no source): show onboarding + demo offer
    showOnboarding();
    return;
  }

  // Skip onboarding — go straight to the app
  const source = config.input_source || "Pipeline";
  if (config.input_source) {
    addStream(source, source, config.mock_mode ? "mock" : "live");
  }
  showApp("streams");
  connect("/api/events");
  // Hydrate state from any already-running pipeline (active + recent segments)
  await hydrateSegments();
  if (config.mock_mode) setStatus("Mock Mode", "status-demo");
  else if (hasKey) setStatus("Ready", "status-ok");
}

async function hydrateSegments() {
  try {
    const [active, recent] = await Promise.all([
      fetch("/api/segments/active").then(r => r.json()),
      fetch("/api/segments/recent?limit=30").then(r => r.json()),
    ]);
    (active || []).forEach(seg => {
      if (!streams[seg.stream_id]) addStream(seg.stream_id, seg.stream_id, "live");
      streams[seg.stream_id].active_segments[seg.primary_commodity] = seg;
    });
    (recent || []).forEach(seg => {
      if (!streams[seg.stream_id]) addStream(seg.stream_id, seg.stream_id, "live");
      streams[seg.stream_id].closed_segments.push(seg);
      if (commodities[seg.primary_commodity]) {
        commodities[seg.primary_commodity]._closed_segments =
          commodities[seg.primary_commodity]._closed_segments || [];
        commodities[seg.primary_commodity]._closed_segments.push(seg);
      }
    });
    renderStreamFilters();
    if (!document.getElementById("view-streams").classList.contains("hidden")) renderStreams();
  } catch (e) {
    console.warn("[hydrate] segments failed:", e);
  }
}

async function fetchJSON(url) {
  try { const r = await fetch(url); return await r.json(); } catch (e) { return {}; }
}

function escapeHtml(t) {
  if (!t) return "";
  const d = document.createElement("div"); d.textContent = t; return d.innerHTML;
}

function setStatus(text, cls) {
  const el = document.getElementById("nav-status");
  el.textContent = text; el.className = cls;
}

// ===== NAVIGATION =====
function showOnboarding() {
  if (activeSSE) { activeSSE.close(); activeSSE = null; }
  document.getElementById("onboarding").classList.remove("hidden");
  document.getElementById("app").classList.add("hidden");
}

function showApp(view) {
  document.getElementById("onboarding").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  showView(view || "streams");
}

function showView(view) {
  document.getElementById("view-streams").classList.toggle("hidden", view !== "streams");
  document.getElementById("view-commodities").classList.toggle("hidden", view !== "commodities");
  document.getElementById("view-evaluation").classList.toggle("hidden", view !== "evaluation");
  document.getElementById("view-settings").classList.toggle("hidden", view !== "settings");
  document.getElementById("nav-streams").classList.toggle("active", view === "streams");
  document.getElementById("nav-commodities").classList.toggle("active", view === "commodities");
  const evalNav = document.getElementById("nav-evaluation");
  if (evalNav) evalNav.classList.toggle("active", view === "evaluation");
  document.getElementById("nav-settings").classList.toggle("active", view === "settings");

  if (view === "commodities") {
    renderCommodityFilters();
    renderLatestEvents();
    renderCommodities();
  }
  if (view === "streams") {
    renderStreamFilters();
    renderStreams();
  }
  if (view === "evaluation") {
    refreshEvaluation();
  }
  if (view === "settings") {
    renderSettingsView();
  }
}

// ===== ONBOARDING =====
function onOnboardingProviderChange() {
  const sel = document.getElementById("api-provider-select");
  const input = document.getElementById("api-key-input");
  if (!sel || !input) return;
  input.placeholder = sel.value === "openai" ? "sk-..." : "sk-ant-...";
}

async function saveApiKey() {
  const key = document.getElementById("api-key-input").value.trim();
  if (!key) return;
  const sel = document.getElementById("api-provider-select");
  const provider = sel ? sel.value : "anthropic";
  const meta = PROVIDER_META[provider] || PROVIDER_META.anthropic;
  localStorage.setItem("csm_llm_provider", provider);
  localStorage.setItem(meta.storageKey, key);

  try {
    const res = await fetch("/api/settings/api-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key, provider }),
    });
    const data = await res.json();
    if (data.ok && data.active) {
      // Key accepted by the running pipeline — advance to the app + open SSE
      await loadCommodities();
      showApp("streams");
      connect("/api/events");
      setStatus("Ready", "status-ok");
    } else if (data.ok && !data.active) {
      // Server acknowledged but pipeline is not active (no source yet or empty key)
      await loadCommodities();
      showApp("streams");
      connect("/api/events");
      setStatus("Ready (add a stream to start analysis)", "status-ok");
    } else if (data.error) {
      alert(`Key saved locally, but the server returned: ${data.error}\n\n` +
            `You can also set ${meta.envVar} in .env and restart.`);
    }
  } catch (e) {
    alert("Failed to reach the server: " + e.message +
          "\nKey is saved locally; try refreshing the page.");
  }
}

async function startDemo() {
  await loadCommodities();
  isDemoMode = true;
  showApp("streams");
  setStatus("Demo Mode", "status-demo");
  connect("/api/demo");
}

// ===== SETTINGS MODAL =====
async function showSettingsModal() {
  document.getElementById("settings-modal").classList.remove("hidden");
  // Clear any leftover status from a previous save
  const statusEl = document.getElementById("setting-save-status");
  if (statusEl) {
    statusEl.textContent = "";
    statusEl.className = "setting-save-status";
    statusEl.title = "";
  }
  // Seed from localStorage immediately so there's no visual flicker while
  // we fetch the authoritative server state below.
  const stored = JSON.parse(localStorage.getItem("csm_settings") || "{}");
  const chunkInput = document.getElementById("setting-chunk");
  const chunkDisplay = document.getElementById("setting-chunk-val");
  const modelSelect = document.getElementById("setting-model");
  const langSelect = document.getElementById("setting-lang");
  chunkInput.value = stored.chunk || 10;
  chunkDisplay.textContent = (stored.chunk || 10) + "s";
  modelSelect.value = stored.model || "small";
  langSelect.value = stored.lang !== undefined ? stored.lang : "en";
  // Overlay live server state (truth wins over localStorage — keeps the modal
  // in sync with whatever was hot-swapped via /api/settings/pipeline).
  try {
    const res = await fetch("/api/config");
    if (res.ok) {
      const cfg = await res.json();
      if (cfg.chunk_duration_s != null) {
        chunkInput.value = cfg.chunk_duration_s;
        chunkDisplay.textContent = cfg.chunk_duration_s + "s";
      }
      if (cfg.whisper_model) modelSelect.value = cfg.whisper_model;
      if (cfg.whisper_language !== undefined) langSelect.value = cfg.whisper_language;
    }
  } catch (_err) {
    // Ignore — localStorage fallback is already applied.
  }
}

function closeSettingsModal() {
  document.getElementById("settings-modal").classList.add("hidden");
}

async function applyPipelineSettings() {
  const chunkEl = document.getElementById("setting-chunk");
  const modelEl = document.getElementById("setting-model");
  const langEl = document.getElementById("setting-lang");
  const btn = document.getElementById("setting-save-btn");
  const statusEl = document.getElementById("setting-save-status");
  const chunk = parseInt(chunkEl.value, 10);
  const model = modelEl.value;
  const lang = langEl.value;  // "" = auto-detect

  // Persist locally so the UI restores them on reload
  localStorage.setItem("csm_settings", JSON.stringify({ chunk, model, lang }));

  // Disable button + show pending state — model reload can take a few seconds
  btn.disabled = true;
  const originalText = btn.textContent;
  btn.textContent = "Applying\u2026";
  statusEl.className = "setting-save-status pending";
  statusEl.textContent = "Applying to pipeline\u2026";

  try {
    const res = await fetch("/api/settings/pipeline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chunk_duration_s: chunk,
        whisper_model: model,
        whisper_language: lang,
      }),
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      statusEl.className = "setting-save-status error";
      statusEl.textContent = `\u2717 ${data.error || "Apply failed"}`;
      return;
    }
    const applied = (data.applied || []).length;
    const pending = data.pending || [];
    const notes = data.notes || [];
    const parts = [`\u2713 Applied (${applied})`];
    if (pending.length) parts.push(`pending: ${pending.join(", ")}`);
    statusEl.className = "setting-save-status success";
    statusEl.textContent = parts.join(" \u00b7 ");
    if (notes.length) statusEl.title = notes.join(" | ");
    // Auto-close the modal after a short pause so user sees the confirmation
    setTimeout(() => {
      closeSettingsModal();
      statusEl.textContent = "";
      statusEl.className = "setting-save-status";
      statusEl.title = "";
    }, 1800);
  } catch (err) {
    statusEl.className = "setting-save-status error";
    statusEl.textContent = `\u2717 Network error: ${err && err.message ? err.message : err}`;
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

// ===== SETTINGS VIEW (API key management, provider-aware) =====
// localStorage keys:
//   csm_llm_provider     — "anthropic" | "openai"
//   csm_api_key          — Anthropic key (legacy name, kept for backward compat)
//   csm_openai_api_key   — OpenAI key
const PROVIDER_META = {
  anthropic: {
    label: "Anthropic (Claude)",
    placeholder: "sk-ant-...",
    storageKey: "csm_api_key",
    consoleUrl: "https://console.anthropic.com/settings/keys",
    linkText: "Get an Anthropic API key \u2192",
    envVar: "ANTHROPIC_API_KEY",
  },
  openai: {
    label: "OpenAI (GPT)",
    placeholder: "sk-...",
    storageKey: "csm_openai_api_key",
    consoleUrl: "https://platform.openai.com/api-keys",
    linkText: "Get an OpenAI API key \u2192",
    envVar: "OPENAI_API_KEY",
  },
};

function getCurrentProvider() {
  const stored = localStorage.getItem("csm_llm_provider");
  return stored === "openai" ? "openai" : "anthropic";
}

function renderSettingsView() {
  const provider = getCurrentProvider();
  const meta = PROVIDER_META[provider];
  const select = document.getElementById("settings-provider");
  const input = document.getElementById("settings-api-key");
  const status = document.getElementById("api-key-status");
  const link = document.getElementById("settings-provider-link");

  if (select) select.value = provider;
  if (input) input.placeholder = meta.placeholder;
  if (link) {
    link.href = meta.consoleUrl;
    link.textContent = meta.linkText;
  }

  const key = localStorage.getItem(meta.storageKey) || "";
  if (key) {
    status.className = "has-key";
    status.textContent = `\u2713 ${meta.label} key saved (${key.substring(0, 8)}...${key.slice(-4)}). Active in the running pipeline.`;
    input.value = key;
  } else {
    status.className = "no-key";
    status.textContent = `No ${meta.label} key saved. Without it, signals require --mock mode.`;
    input.value = "";
  }
}

function onProviderChange() {
  const select = document.getElementById("settings-provider");
  if (!select) return;
  localStorage.setItem("csm_llm_provider", select.value);
  renderSettingsView();
}

async function saveSettingsApiKey() {
  const provider = getCurrentProvider();
  const meta = PROVIDER_META[provider];
  const key = document.getElementById("settings-api-key").value.trim();
  if (!key) return alert("Enter an API key first.");
  localStorage.setItem(meta.storageKey, key);
  localStorage.setItem("csm_llm_provider", provider);

  // Live-update the running pipeline
  try {
    const res = await fetch("/api/settings/api-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key, provider }),
    });
    const data = await res.json();
    const status = document.getElementById("api-key-status");
    if (data.ok && data.active) {
      status.className = "has-key";
      status.textContent = `\u2713 ${meta.label} key saved and activated. Next transcribed chunks will use ${meta.label}.`;
    } else if (data.error) {
      status.className = "no-key";
      status.innerHTML = `\u26a0 ${escapeHtml(data.error)} Key saved locally. To use it, restart the pipeline with <code>${meta.envVar}=${escapeHtml(key.substring(0, 10))}...</code>`;
    }
  } catch (e) {
    alert("Failed to update runtime: " + e.message);
  }
}

async function removeSettingsApiKey() {
  const provider = getCurrentProvider();
  const meta = PROVIDER_META[provider];
  if (!confirm(`Remove ${meta.label} key from browser and deactivate in pipeline?`)) return;
  localStorage.removeItem(meta.storageKey);
  try {
    await fetch("/api/settings/api-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: "", provider }),
    });
  } catch (e) { void e; }
  renderSettingsView();

  // If NO provider has a key anymore, return to onboarding so the user sees
  // the demo offer again. If the other provider still has a key, stay in app.
  const otherKey = provider === "openai"
    ? localStorage.getItem("csm_api_key")
    : localStorage.getItem("csm_openai_api_key");
  if (!otherKey) {
    showOnboarding();
  }
}

// ===== SOURCE MODAL =====
async function showSignalSource(streamId, sigRef) {
  // sigRef is a JSON-encoded signal object (passed from button onclick)
  let sig;
  try { sig = JSON.parse(decodeURIComponent(sigRef)); } catch (e) { return; }

  const stream = streams[streamId] || { name: streamId, url: "", type: "unknown" };
  const body = document.getElementById("source-modal-body");

  // Build modal content
  const urlHtml = stream.url && (stream.url.startsWith("http") || stream.url.startsWith("rtmp"))
    ? `<a href="${escapeHtml(stream.url)}" target="_blank" class="link">${escapeHtml(stream.url)}</a>`
    : escapeHtml(stream.url || "—");

  body.innerHTML = `
    <div class="source-field">
      <div class="source-field-label">Stream</div>
      <div class="source-field-value"><strong>${escapeHtml(stream.name)}</strong><br>${urlHtml}</div>
    </div>
    <div class="source-field">
      <div class="source-field-label">Signal</div>
      <div class="source-field-value">
        <strong>${escapeHtml(sig.display_name)}</strong> —
        <span class="signal-dir ${sig.direction}">${sig.direction}</span>
        at ${Math.round((sig.confidence || 0) * 100)}% confidence, ${(sig.timeframe || "").replace("_", " ")}
      </div>
    </div>
    <div class="source-field">
      <div class="source-field-label">Rationale</div>
      <div class="source-field-value">${escapeHtml(sig.rationale)}</div>
    </div>
    <div class="source-field">
      <div class="source-field-label">Detected at</div>
      <div class="source-field-value">${sig._time || "—"} · chunk <code>${escapeHtml(sig.chunk_id || "n/a")}</code></div>
    </div>
    <div class="source-field">
      <div class="source-field-label">Source text (chunk transcript)</div>
      <div class="source-transcript">${escapeHtml(sig.source_text || stream.transcript || "(not available)")}</div>
    </div>
    <div class="source-field">
      <div class="source-field-label">Historical comparison — current market price</div>
      <div id="source-price" class="source-field-value">Loading...</div>
    </div>
    ${sig.speaker ? `<div class="source-field"><div class="source-field-label">Speaker</div><div class="source-field-value">${escapeHtml(sig.speaker)}</div></div>` : ""}
  `;

  document.getElementById("source-modal").classList.remove("hidden");

  // Fetch current price for historical comparison
  const priceEl = document.getElementById("source-price");
  const data = await fetchJSON(`/api/prices/${sig.commodity}`);
  if (data && data.current_price != null) {
    const change = data.change_24h || 0;
    const dir = change >= 0 ? "up" : "down";
    const sign = change >= 0 ? "+" : "";
    const alignMsg = sig.direction === "bullish" && change > 0 ? "✓ Price moved in predicted direction" :
                     sig.direction === "bearish" && change < 0 ? "✓ Price moved in predicted direction" :
                     sig.direction === "neutral" ? "—" : "⚠ Price moved against prediction";
    priceEl.innerHTML = `
      <div class="source-price-row">
        <div><div class="source-field-label">Current</div><div class="price-value">$${data.current_price.toFixed(2)}</div></div>
        <div><div class="source-field-label">24h change</div><div class="price-value price-change ${dir}">${sign}${change.toFixed(2)}</div></div>
      </div>
      <div style="margin-top:0.5rem;font-size:0.8rem;color:#c9d1d9">${alignMsg}</div>
    `;
  } else {
    priceEl.textContent = "Price data unavailable for this commodity.";
  }
}

function closeSourceModal() {
  document.getElementById("source-modal").classList.add("hidden");
}

// ===== SAVED STREAMS MODAL =====
function showSavedStreamsModal() {
  document.getElementById("saved-streams-modal").classList.remove("hidden");
  renderSavedStreams();
}

function closeSavedStreamsModal() {
  document.getElementById("saved-streams-modal").classList.add("hidden");
}

function renderSavedStreams() {
  const list = document.getElementById("saved-streams-list");
  if (!list) return;
  if (savedStreams.length === 0) {
    list.innerHTML = '<div style="color:#8b949e;padding:0.75rem 0;font-size:0.85rem">No saved streams. Add one below.</div>';
    return;
  }
  list.innerHTML = "";

  // Group streams by category, preserving original index for correct callbacks
  const groups = new Map();
  for (const cat of SAVED_CATEGORIES) groups.set(cat.id, []);
  savedStreams.forEach((s, i) => {
    const cat = s.category && groups.has(s.category) ? s.category : "custom";
    groups.get(cat).push({ s, i });
  });

  for (const cat of SAVED_CATEGORIES) {
    const entries = groups.get(cat.id);
    if (!entries || entries.length === 0) continue;
    const header = document.createElement("div");
    header.className = "saved-section-header";
    header.textContent = cat.label;
    list.appendChild(header);
    for (const { s, i } of entries) {
      // "active" = pipeline is currently transcribing this URL (not just
      // a leftover stream card from a previous session). A merely paused
      // or finished stream still appears in `streams` — we don't count it.
      const isActive = Object.values(streams).some(
        a => a.url === s.url && !a.stopped,
      );
      const item = document.createElement("div");
      item.className = "saved-stream-item";
      item.innerHTML = `
        <span class="saved-badge ${isActive ? "active" : "inactive"}">${isActive ? "active" : "inactive"}</span>
        <div style="flex:1;min-width:0">
          <div class="saved-name">${escapeHtml(s.name)}</div>
          <div class="saved-url">${escapeHtml(s.url)}</div>
        </div>
        <button class="btn-sm" onclick="addFromSaved(${i})" title="${isActive ? 'Already running' : 'Start processing this URL'}">${isActive ? 'Running' : 'Start'}</button>
        <button class="btn-remove" onclick="deleteSavedStream(${i})">Remove</button>`;
      list.appendChild(item);
    }
  }
}

function addSavedStream() {
  const name = document.getElementById("new-saved-name").value.trim();
  const url = document.getElementById("new-saved-url").value.trim();
  if (!name || !url) return alert("Name and URL are required.");
  savedStreams.push({ name, url, category: "custom" });
  persistSavedStreams(savedStreams);
  document.getElementById("new-saved-name").value = "";
  document.getElementById("new-saved-url").value = "";
  renderSavedStreams();
}

function deleteSavedStream(index) {
  if (!confirm(`Remove "${savedStreams[index].name}" from saved streams?`)) return;
  savedStreams.splice(index, 1);
  persistSavedStreams(savedStreams);
  renderSavedStreams();
}

async function addFromSaved(index) {
  console.log("[addFromSaved] click", { index, entry: savedStreams[index] });
  const s = savedStreams[index];
  if (!s) {
    alert("Could not find saved stream at index " + index + ". Try reopening the modal.");
    return;
  }
  const type = s.url.startsWith("http") ? "live" : "file";
  addStream(s.name, s.url, type);
  renderSavedStreams();
  renderStreamFilters();
  renderStreams();
  closeSavedStreamsModal();  // close modal so user can see the stream card + status change
  await startPipelineWithSource(s.url);
}

async function startAllSavedStreams() {
  const toStart = [];
  for (const s of savedStreams) {
    const already = Object.values(streams).some(a => a.url === s.url);
    if (!already) {
      const type = s.url.startsWith("http") ? "live" : "file";
      addStream(s.name, s.url, type);
      toStart.push(s.url);
    }
  }
  renderStreamFilters();
  renderStreams();
  if (toStart.length === 0) {
    alert("All saved streams are already active.");
    return;
  }
  // Multi-source backend: kick off every URL. Each gets its own ingest task
  // that feeds the shared transcribe/analyze/broadcast workers.
  await Promise.all(toStart.map(url => startPipelineWithSource(url)));
}

function showAddStreamDialog() {
  document.getElementById("add-stream-url").value = "";
  document.getElementById("add-stream-name").value = "";
  document.getElementById("add-stream-modal").classList.remove("hidden");
  setTimeout(() => document.getElementById("add-stream-url").focus(), 50);
}

function closeAddStreamModal() {
  document.getElementById("add-stream-modal").classList.add("hidden");
}

async function submitAddStream() {
  const url = document.getElementById("add-stream-url").value.trim();
  const nameInput = document.getElementById("add-stream-name").value.trim();
  if (!url) return alert("URL is required.");
  const name = nameInput || url.substring(0, 50);
  const type = url.startsWith("http") || url.startsWith("rtmp") ? "live" : "file";
  addStream(name, url, type);
  renderStreamFilters();
  renderStreams();
  closeAddStreamModal();
  await startPipelineWithSource(url);
}

async function startPipelineWithSource(source) {
  // If we're still on the demo SSE, switch to the live events endpoint so
  // chunks from the newly-added source actually reach the UI. (Demo mode
  // only replays 3 fixed streams; custom ones need the real pipeline.)
  if (isDemoMode) {
    isDemoMode = false;
    connect("/api/events");
  } else if (!activeSSE) {
    // Safety net: without an open SSE, events produced by the pipeline never
    // reach the UI and the user sees "Waiting for transcript..." forever.
    connect("/api/events");
  }
  setStatus("Starting pipeline (10\u201330s for live streams)\u2026", "status-connecting");
  try {
    const res = await fetch("/api/pipeline/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    });
    const data = await res.json();
    console.log("[pipeline/start]", data);
    if (data.ok) {
      // Multi-source backend: ok=true for both "launched" and "already active"
      setStatus("Processing", "status-ok");
      return;
    }
    if (data.error) {
      alert("Could not start pipeline: " + data.error);
    } else if (data.reason) {
      // Validation issue (e.g. empty source)
      alert("Could not start: " + data.reason);
    }
  } catch (e) {
    alert("Failed to contact server: " + e.message);
  }
}

// ===== STREAM MANAGEMENT =====
// Stream data shape:
//   { name, url, type, stopped,
//     chunks: [{chunk_id, ts, text, signals: [CommoditySignal, ...]}, ...]  // in order
//     active_segments: { primary_commodity: Segment, ... },  // keyed by primary
//     closed_segments: [Segment, ...]  // last 30, newest last
//     _chunks_expanded: bool  // UI state — are older chunks unfolded?
//   }
const CHUNKS_VISIBLE_DEFAULT = 3;
const CLOSED_SEGMENTS_KEEP = 30;

function addStream(id, url, type) {
  removedStreamIds.delete(id);
  if (!streams[id]) {
    streams[id] = {
      name: id, url, type,
      stopped: false,
      chunks: [],
      active_segments: {},
      closed_segments: [],
      _chunks_expanded: false,
    };
    selectedStreamIds.add(id);
  }
}

function renderStreamFilters() {
  const panel = document.getElementById("filters-streams-buttons");
  const ids = Object.keys(streams);
  if (ids.length === 0) {
    panel.innerHTML = '<span style="color:#8b949e;font-size:0.78rem">No streams yet</span>';
    return;
  }
  const allSelected = ids.every(id => selectedStreamIds.has(id));
  const toggleLabel = allSelected ? "Deselect All" : "Select All";
  const toggleAction = allSelected ? "deselectAllStreams()" : "selectAllStreams()";
  let html = `<button class="filter-btn toggle-all" onclick="${toggleAction}">${toggleLabel}</button>`;
  for (const id of ids) {
    const s = streams[id];
    const cls = selectedStreamIds.has(id) ? "active" : "";
    // Count total signals across all chunks (new data model after phase 2 refactor)
    const signalCount = (s.chunks || []).reduce(
      (sum, c) => sum + ((c.signals && c.signals.length) || 0), 0,
    );
    html += `<button class="filter-btn ${cls}" onclick="toggleStream('${escapeHtml(id)}')">${escapeHtml(s.name)} <span class="count">${signalCount}</span></button>`;
  }
  panel.innerHTML = html;
}

function toggleStream(id) {
  if (selectedStreamIds.has(id)) selectedStreamIds.delete(id);
  else selectedStreamIds.add(id);
  renderStreamFilters();
  renderStreams();
}

function selectAllStreams() {
  for (const id of Object.keys(streams)) selectedStreamIds.add(id);
  renderStreamFilters();
  renderStreams();
}

function deselectAllStreams() {
  selectedStreamIds.clear();
  renderStreamFilters();
  renderStreams();
}

function renderStreams() {
  const container = document.getElementById("streams-list");
  const noStreams = document.getElementById("no-streams");
  const keys = Object.keys(streams);
  noStreams.classList.toggle("hidden", keys.length > 0);
  container.innerHTML = "";

  const toRender = keys.filter(id => selectedStreamIds.has(id));
  if (keys.length > 0 && toRender.length === 0) {
    container.innerHTML = '<div class="empty-state">No streams selected. Click <strong>Select All</strong> or individual streams in the top menu.</div>';
    return;
  }

  for (const id of toRender) {
    const s = streams[id];
    const card = document.createElement("div");
    card.className = "stream-card";
    card.id = `stream-card-${id}`;
    const urlHref = s.url && (s.url.startsWith("http") || s.url.startsWith("rtmp")) ? s.url : null;
    const urlHtml = urlHref
      ? `<a class="stream-url" href="${escapeHtml(urlHref)}" target="_blank" rel="noopener">${escapeHtml(s.url)}</a>`
      : `<span class="stream-url">${escapeHtml(s.url || "")}</span>`;
    const stopBtnLabel = s.stopped ? "Start Transcription" : "Pause Transcription";
    const statusLabel = s.stopped ? "stopped" : s.type;
    const statusColor = s.stopped ? "color:#f0b400" : "";

    card.innerHTML = `
      <div class="stream-card-header">
        <div class="stream-identity">
          <div class="stream-name">${escapeHtml(s.name)}</div>
          ${urlHtml}
        </div>
        <div class="stream-actions">
          <span class="stream-status" style="${statusColor}">${escapeHtml(statusLabel)}</span>
          <button class="btn-stop" onclick="toggleStopStream('${escapeHtml(id)}')" title="Toggle transcript processing">${stopBtnLabel}</button>
          <button class="btn-remove" onclick="removeStream('${escapeHtml(id)}')" title="Remove this stream">Remove</button>
        </div>
      </div>
      <div class="stream-chunks-container" id="chunks-container-${escapeHtml(id)}">
        ${renderStreamChunks(id, s)}
      </div>
      <div class="stream-segments-container" id="segments-container-${escapeHtml(id)}">
        ${renderStreamActiveSegments(id, s)}
      </div>`;
    container.appendChild(card);
  }
}

function renderStreamChunks(id, s) {
  const total = s.chunks.length;
  if (total === 0) {
    return `<div class="chunks-empty">${waitingTranscriptMessage(s)}</div>`;
  }
  const visible = s.chunks.slice(-CHUNKS_VISIBLE_DEFAULT);  // last N, oldest first
  const older = s.chunks.slice(0, Math.max(0, total - CHUNKS_VISIBLE_DEFAULT));
  const olderCount = older.length;

  const olderBlock = olderCount > 0
    ? `<div class="chunks-older ${s._chunks_expanded ? '' : 'hidden'}" id="chunks-older-${escapeHtml(id)}">
         ${older.map(c => renderChunkRow(c, id)).join("")}
       </div>
       <div class="chunks-toggle" onclick="toggleChunksExpand('${escapeHtml(id)}')">
         ${s._chunks_expanded ? '&uarr; Hide' : 'Show'} ${olderCount} older chunk${olderCount !== 1 ? 's' : ''} ${s._chunks_expanded ? '' : '&darr;'}
       </div>`
    : '';

  return olderBlock + `
    <div class="chunks-visible">
      ${visible.map(c => renderChunkRow(c, id)).join("")}
    </div>`;
}

function renderChunkRow(chunk, streamId) {
  const ts = chunk.ts || "";
  const hasEvent = chunk.signals && chunk.signals.length > 0;
  const dominantDir = hasEvent ? topDirection(chunk.signals) : null;
  const markerClass = hasEvent ? `chunk-marker chunk-marker-${dominantDir}` : 'chunk-marker-none';
  const sigSummary = hasEvent
    ? chunk.signals.map(s => `${s.commodity} ${s.direction} ${Math.round((s.confidence || 0) * 100)}%`).join(' · ')
    : '';

  // People + indicators come from the `extraction` SSE event, attached in
  // the extraction listener. They're meta-context for the chunk, not signals
  // per se — shown inline but smaller, with full details in a hover tooltip.
  const people = (chunk.people || []);
  const indicators = (chunk.indicators || []);
  let entitiesLine = '';
  if (people.length || indicators.length) {
    const peopleBrief = people.map(p => escapeHtml(p.name)).join(', ');
    const indicatorsBrief = indicators
      .map(i => escapeHtml(i.display_name || i.name)).join(', ');
    const peopleTitle = people
      .map(p => `${p.name}${p.role ? ' — ' + p.role : ''}: ${p.context || ''}`)
      .join('\n');
    const indicatorsTitle = indicators
      .map(i => `${i.display_name || i.name}: ${i.context || ''}`)
      .join('\n');
    const tooltip = [
      people.length ? `People:\n${peopleTitle}` : '',
      indicators.length ? `Indicators:\n${indicatorsTitle}` : '',
    ].filter(Boolean).join('\n\n');
    entitiesLine = `<div class="chunk-entities" title="${escapeHtml(tooltip)}">` +
      (people.length ? `<span class="chunk-ent-people">👤 ${peopleBrief}</span>` : '') +
      (indicators.length ? `<span class="chunk-ent-indicators">📊 ${indicatorsBrief}</span>` : '') +
      `</div>`;
  }

  return `
    <div class="chunk-row ${hasEvent ? 'chunk-has-event' : ''}">
      <div class="${markerClass}"></div>
      <div class="chunk-body">
        <div class="chunk-ts">${escapeHtml(ts)}</div>
        <div class="chunk-text">${escapeHtml(chunk.text || '')}</div>
        ${hasEvent ? `<div class="chunk-event-badge">${escapeHtml(sigSummary)}</div>` : ''}
        ${entitiesLine}
      </div>
    </div>`;
}

function topDirection(signals) {
  // Highest-confidence signal wins; ties go to bullish > bearish > neutral
  if (!signals || signals.length === 0) return 'neutral';
  const top = signals.reduce((best, s) =>
    (best === null || (s.confidence || 0) > (best.confidence || 0)) ? s : best, null);
  return top && top.direction ? top.direction : 'neutral';
}

function renderStreamActiveSegments(id, s) {
  const active = Object.values(s.active_segments || {});
  const recentClosed = (s.closed_segments || []).slice(-5).reverse();

  if (active.length === 0 && recentClosed.length === 0) {
    const msg = isDemoMode
      ? "Demo replays only chunks + signals — segments require a live pipeline with an LLM."
      : "No segments yet — waiting for first commodity signal.";
    return `<div class="segment-active-empty">${msg}</div>`;
  }

  let html = '';
  if (active.length > 0) {
    html += '<div class="segment-section-label">Active</div>';
    html += active.map(seg => renderActiveSegmentCard(seg)).join('');
  }
  if (recentClosed.length > 0) {
    html += `<div class="segment-section-label">Recently closed (${recentClosed.length})</div>`;
    html += recentClosed.map(seg => renderActiveSegmentCard(seg)).join('');
  }
  return html;
}

function renderActiveSegmentCard(seg) {
  const dir = seg.direction || 'neutral';
  const conf = Math.round((seg.confidence || 0) * 100);
  const commodityName = commodities[seg.primary_commodity]?.display_name || seg.primary_commodity;
  const secondaries = (seg.secondary_commodities || []).length > 0
    ? `<span class="seg-secondary">also: ${seg.secondary_commodities.map(c => escapeHtml(c)).join(', ')}</span>`
    : '';
  const arc = seg.sentiment_arc ? `<div class="seg-arc">${escapeHtml(seg.sentiment_arc)}</div>` : '';
  return `
    <div class="segment-card segment-active segment-${dir}">
      <div class="segment-header">
        <span class="segment-pulse"></span>
        <span class="segment-title">${escapeHtml(commodityName)}</span>
        <span class="segment-dir segment-dir-${dir}">${dir}</span>
        <span class="segment-conf">${conf}%</span>
        <span class="segment-chunks">${(seg.chunk_ids || []).length} chunks</span>
        ${secondaries}
      </div>
      <div class="segment-summary">${escapeHtml(seg.summary || 'Analyzing…')}</div>
      ${arc}
      ${seg.rationale ? `<div class="segment-rationale">${escapeHtml(seg.rationale)}</div>` : ''}
    </div>`;
}

function toggleChunksExpand(id) {
  if (!streams[id]) return;
  streams[id]._chunks_expanded = !streams[id]._chunks_expanded;
  const container = document.getElementById(`chunks-container-${id}`);
  if (container) container.innerHTML = renderStreamChunks(id, streams[id]);
}

// Demo-backed stream names (match demo endpoint stream_map values)
const DEMO_STREAM_NAMES = new Set(["Bloomberg Live", "CNBC Markets", "Yahoo Finance"]);

function waitingTranscriptMessage(s) {
  // Demo mode replays pre-recorded events for 3 fixed streams. A custom
  // stream added during demo mode needs the live SSE to see its chunks —
  // transcription itself is free (local Whisper), only the commodity
  // scoring step needs an LLM API key.
  if (isDemoMode && !DEMO_STREAM_NAMES.has(s.name)) {
    return `<span style="color:#f0b400">Demo is replaying fixed streams \u2014 custom streams route through the live pipeline.</span>
      <span style="color:#c9d1d9"><a href="#" onclick="exitDemoAndConnectLive();return false;" class="link">Exit demo &amp; start transcription</a>
      (Whisper runs locally, free; commodity signals need an <a href="#" onclick="showView('settings');return false;" class="link">API key</a>).</span>`;
  }
  return '<span style="color:#8b949e">Waiting for transcript\u2026</span>';
}

// Exit demo mode and connect to the live /api/events stream so the custom
// stream just added starts producing chunks in the UI.
function exitDemoAndConnectLive() {
  isDemoMode = false;
  setStatus("Connecting to live pipeline\u2026", "status-connecting");
  connect("/api/events");
  // Re-render so the waiting message updates on every stream card
  renderStreams();
}

async function toggleStopStream(id) {
  if (!streams[id]) return;
  const wasStopped = streams[id].stopped;
  streams[id].stopped = !wasStopped;
  renderStreams();
  if (!wasStopped) {
    // Was running → pause (stop backend pipeline)
    try {
      await fetch("/api/pipeline/stop", { method: "POST" });
      setStatus("Paused", "status-connecting");
    } catch (e) {
      console.warn("stop failed", e);
    }
  } else {
    // Was paused → resume (restart pipeline on the same source)
    await startPipelineWithSource(streams[id].url);
  }
}

function toggleStreamSignals(id) {
  const el = document.getElementById(`stream-all-${id}`);
  if (el) el.classList.toggle("hidden");
}

async function removeStream(id) {
  if (!streams[id]) return;
  if (!confirm(`Remove stream "${streams[id].name}"? Transcript and signals will be cleared.`)) return;
  const url = streams[id].url;
  delete streams[id];
  selectedStreamIds.delete(id);
  removedStreamIds.add(id);  // block buffered SSE events from re-creating this card
  renderStreamFilters();
  renderStreams();
  // Stop just this specific source on the backend — other streams keep
  // running. The server supports per-source removal when the payload has
  // a "source" URL; omit it to stop everything.
  try {
    const res = await fetch("/api/pipeline/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: url }),
    });
    const data = await res.json();
    console.log("[pipeline/stop]", data);
    if (data.scope === "source" && data.was_running) {
      setStatus(`Stopped "${streams[id]?.name || url}"`, "status-connecting");
    } else if (data.was_running) {
      setStatus(`Stopped (was processing ${url})`, "status-connecting");
    } else {
      setStatus("Ready", "status-ok");
    }
  } catch (e) {
    console.warn("stop failed", e);
  }
}

// ===== COMMODITY VIEW =====
function renderCommodityFilters() {
  const panel = document.getElementById("filters-commodities-buttons");
  const ids = Object.keys(commodities);
  const allSelected = ids.every(id => selectedCommodityIds.has(id));
  const toggleLabel = allSelected ? "Deselect All" : "Select All";
  const toggleAction = allSelected ? "deselectAllCommodities()" : "selectAllCommodities()";
  let html = `<button class="filter-btn toggle-all" onclick="${toggleAction}">${toggleLabel}</button>`;
  for (const [id, c] of Object.entries(commodities)) {
    const cls = selectedCommodityIds.has(id) ? "active" : "";
    html += `<button class="filter-btn ${cls}" onclick="toggleCommodityFilter('${id}')">${escapeHtml(c.short_name)} <span class="count">${c.events.length}</span></button>`;
  }
  panel.innerHTML = html;
}

async function removeCommodity(id) {
  if (!commodities[id]) return;
  if (!confirm(`Remove commodity "${commodities[id].display_name}"? Events will be cleared and new signals for this commodity will be ignored.`)) return;
  try {
    await fetch(`/api/commodities/${encodeURIComponent(id)}`, { method: "DELETE" });
  } catch (e) { void e; }
  delete commodities[id];
  selectedCommodityIds.delete(id);
  renderCommodityFilters();
  renderLatestEvents();
  renderCommodities();
}

function showAddCommodityDialog() {
  document.getElementById("add-commodity-id").value = "";
  document.getElementById("add-commodity-name").value = "";
  document.getElementById("add-commodity-keywords").value = "";
  document.getElementById("add-commodity-ticker").value = "";
  document.getElementById("add-commodity-modal").classList.remove("hidden");
  setTimeout(() => document.getElementById("add-commodity-id").focus(), 50);
}

function closeAddCommodityModal() {
  document.getElementById("add-commodity-modal").classList.add("hidden");
}

function submitAddCommodity() {
  const id = document.getElementById("add-commodity-id").value.trim();
  const display = document.getElementById("add-commodity-name").value.trim();
  const keywords = document.getElementById("add-commodity-keywords").value.trim();
  const ticker = document.getElementById("add-commodity-ticker").value.trim();
  if (!id || !display) return alert("ID and display name are required.");
  saveCommodity(id, display, keywords, ticker);
}

async function saveCommodity(name, display, keywords, ticker) {
  const payload = {
    name: name.trim().toLowerCase().replace(/\s+/g, "_"),
    display_name: display.trim(),
    keywords: keywords,
    yahoo_ticker: ticker.trim(),
  };
  try {
    const res = await fetch("/api/commodities", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.error) { alert("Error: " + data.error); return; }
    await loadCommodities();
    renderCommodityFilters();
    renderCommodities();
    closeAddCommodityModal();
  } catch (e) {
    alert("Failed to add commodity: " + e.message);
  }
}

function toggleCommodityFilter(id) {
  if (selectedCommodityIds.has(id)) selectedCommodityIds.delete(id);
  else selectedCommodityIds.add(id);
  renderCommodityFilters();
  renderLatestEvents();
  renderCommodities();
}

function selectAllCommodities() {
  for (const id of Object.keys(commodities)) selectedCommodityIds.add(id);
  renderCommodityFilters();
  renderLatestEvents();
  renderCommodities();
}

function deselectAllCommodities() {
  selectedCommodityIds.clear();
  renderCommodityFilters();
  renderLatestEvents();
  renderCommodities();
}

function renderLatestEvents() {
  const grid = document.getElementById("latest-events-grid");
  if (!grid) return;

  // Collect latest event per SELECTED commodity, pick 3 with most recent timestamp
  const allEvents = [];
  for (const [id, c] of Object.entries(commodities)) {
    if (!selectedCommodityIds.has(id)) continue;
    if (c.events.length > 0) {
      const latest = c.events[c.events.length - 1];
      allEvents.push({ ...latest, _cid: id, _time: latest._time || "just now" });
    }
  }
  allEvents.sort((a, b) => (b._timestamp || 0) - (a._timestamp || 0));
  const top3 = allEvents.slice(0, 3);

  if (top3.length === 0) {
    grid.innerHTML = '<div style="grid-column:1/-1;color:#8b949e;font-size:0.85rem;padding:1rem 0">No events yet — start demo or wait for pipeline signals</div>';
    return;
  }

  grid.innerHTML = "";
  for (const ev of top3) {
    const card = document.createElement("div");
    card.className = `latest-card ${ev.direction}`;
    card.innerHTML = `
      <div class="name">${escapeHtml(ev.display_name)}</div>
      <div class="dir-row">
        <span class="dir ${ev.direction}">${ev.direction}</span>
        <span class="time">${ev._time}</span>
      </div>
      <div class="rationale">${escapeHtml(ev.rationale)}</div>
      <div class="conf">Confidence: ${Math.round(ev.confidence * 100)}% &middot; ${(ev.timeframe || "").replace("_", " ")}</div>`;
    grid.appendChild(card);
  }
}

function renderCommodities() {
  const grid = document.getElementById("commodities-grid");
  if (!grid) return;
  grid.innerHTML = "";

  const toRender = Object.keys(commodities).filter(id => selectedCommodityIds.has(id));
  if (toRender.length === 0) {
    grid.innerHTML = '<div class="empty-state">No commodities selected. Click <strong>Select All</strong> or individual commodities in the top menu.</div>';
    return;
  }

  for (const id of toRender) {
    const c = commodities[id];
    // Collect all segments (closed + active) where this commodity is primary
    const closedSegments = (c._closed_segments || []).slice();
    const activeSegments = [];
    for (const s of Object.values(streams)) {
      for (const seg of Object.values(s.active_segments || {})) {
        if (seg.primary_commodity === id) activeSegments.push(seg);
      }
    }
    // Active segments first (newest on top), then closed newest-first
    const allSegments = [...activeSegments].concat(closedSegments.slice().reverse());
    const totalSegments = allSegments.length;
    const totalChunkEvents = c.events.length;

    const card = document.createElement("div");
    card.className = "commodity-card";
    card.id = `commodity-card-${id}`;

    let segmentsHtml;
    if (totalSegments === 0) {
      // Fallback: no segments yet — show raw events (backward compatible demo path)
      const visible = c.events.slice(-3).reverse();
      segmentsHtml = visible.map(e => renderSignalItem(e)).join("")
        || '<div style="color:#8b949e;font-size:0.82rem;padding:0.5rem 0">No events or segments detected yet</div>';
    } else {
      // Show first 3 segments by default, rest under expand
      const top = allSegments.slice(0, 3);
      const hidden = allSegments.slice(3);
      segmentsHtml = top.map(seg => renderCommoditySegmentCard(seg, id)).join("");
      if (hidden.length > 0) {
        segmentsHtml += `
          <span class="expand-link" onclick="toggleCommodity('${id}')">Show ${hidden.length} older segment${hidden.length !== 1 ? 's' : ''} &darr;</span>
          <div id="commodity-all-${id}" class="hidden">
            ${hidden.map(seg => renderCommoditySegmentCard(seg, id)).join("")}
          </div>`;
      }
    }

    card.innerHTML = `
      <div class="commodity-card-header">
        <div onclick="toggleCommodity('${id}_main')" style="flex:1;cursor:pointer">
          <span class="commodity-title">${escapeHtml(c.display_name)}</span>
          <span class="commodity-count">${totalSegments} segment${totalSegments !== 1 ? 's' : ''} &middot; ${totalChunkEvents} chunk event${totalChunkEvents !== 1 ? 's' : ''}</span>
        </div>
        <button class="btn-remove" onclick="removeCommodity('${id}')" title="Stop tracking this commodity">Remove</button>
      </div>
      <div class="commodity-events${totalSegments > 0 ? " open" : ""}" id="commodity-${id}_main">
        ${segmentsHtml}
      </div>`;
    grid.appendChild(card);
  }
}

function renderCommoditySegmentCard(seg, commodityId) {
  const dir = seg.direction || 'neutral';
  const conf = Math.round((seg.confidence || 0) * 100);
  const isActive = !seg.is_closed;
  const segState = isActive ? 'active' : 'closed';

  const startTs = seg.start_time ? new Date(seg.start_time).toLocaleTimeString() : '';
  const endTs = seg.end_time ? new Date(seg.end_time).toLocaleTimeString() : 'ongoing';
  const durationChunks = (seg.chunk_ids || []).length;
  const streamLabel = seg.stream_id ? (streams[seg.stream_id]?.name || seg.stream_id) : '';

  // Show top 3 sub-signals (highest confidence, filtered by this commodity)
  const chunkIds = new Set(seg.chunk_ids || []);
  const relatedSignals = [];
  // Walk closed + active streams to find chunk-level signals tied to this segment
  for (const s of Object.values(streams)) {
    for (const c of s.chunks) {
      if (!chunkIds.has(c.chunk_id)) continue;
      for (const sig of c.signals || []) {
        if (sig.commodity === commodityId) relatedSignals.push({ ...sig, _chunk_ts: c.ts });
      }
    }
  }
  relatedSignals.sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
  const topSubs = relatedSignals.slice(0, 3);
  const olderSubs = relatedSignals.slice(3);

  const arcHtml = seg.sentiment_arc
    ? `<div class="seg-arc">${escapeHtml(seg.sentiment_arc)}</div>` : '';
  const closedBadge = !isActive
    ? `<span class="seg-badge-closed" title="closed: ${escapeHtml(seg.close_reason || '')}">closed</span>`
    : `<span class="segment-pulse" title="active"></span>`;

  const subsignalsHtml = topSubs.length > 0
    ? `<div class="seg-subsignals">
         ${topSubs.map(sig => renderSubsignalRow(sig)).join("")}
         ${olderSubs.length > 0 ? `
           <span class="expand-link" onclick="toggleSegmentSubs('${seg.segment_id}')">Show ${olderSubs.length} more sub-signal${olderSubs.length !== 1 ? 's' : ''} &darr;</span>
           <div class="seg-subs-hidden hidden" id="seg-subs-${seg.segment_id}">
             ${olderSubs.map(sig => renderSubsignalRow(sig)).join("")}
           </div>` : ''}
       </div>`
    : '';

  return `
    <div class="segment-card segment-${segState} segment-${dir}">
      <div class="segment-header">
        ${closedBadge}
        <span class="segment-title">${escapeHtml(seg.summary || 'Segment')}</span>
        <span class="segment-dir segment-dir-${dir}">${dir}</span>
        <span class="segment-conf">${conf}%</span>
      </div>
      <div class="segment-meta">
        ${escapeHtml(streamLabel)} · ${startTs} → ${endTs} · ${durationChunks} chunks
      </div>
      ${arcHtml}
      ${seg.rationale ? `<div class="segment-rationale">${escapeHtml(seg.rationale)}</div>` : ''}
      ${subsignalsHtml}
    </div>`;
}

function renderSubsignalRow(sig) {
  const conf = Math.round((sig.confidence || 0) * 100);
  return `
    <div class="subsignal-row">
      <span class="subsignal-dir subsignal-dir-${sig.direction}">${sig.direction}</span>
      <span class="subsignal-conf">${conf}%</span>
      <span class="subsignal-rationale">${escapeHtml((sig.rationale || '').slice(0, 120))}</span>
      <span class="subsignal-ts">${escapeHtml(sig._chunk_ts || '')}</span>
    </div>`;
}

function toggleSegmentSubs(segId) {
  const el = document.getElementById(`seg-subs-${segId}`);
  if (el) el.classList.toggle("hidden");
}

function toggleCommodity(id) {
  const el = document.getElementById(`commodity-${id}`);
  if (el) el.classList.toggle("open");
  const allEl = document.getElementById(`commodity-all-${id}`);
  if (allEl) allEl.classList.toggle("hidden");
}

// ===== SHARED RENDERER =====
function renderSignalItem(sig) {
  const time = sig._time || "just now";
  const streamId = sig._stream_id || Object.keys(streams)[0] || "";
  const encoded = encodeURIComponent(JSON.stringify(sig));
  return `<div class="signal-item">
    <span class="signal-dir ${sig.direction}">${sig.direction}</span>
    <div class="signal-info">
      <div class="signal-name">${escapeHtml(sig.display_name || sig.commodity)}</div>
      <div class="signal-rationale">${escapeHtml(sig.rationale)}</div>
    </div>
    <div class="signal-meta">${time}<br>${(sig.timeframe || "").replace("_", " ")}</div>
    <div class="signal-conf">${Math.round((sig.confidence || 0) * 100)}%</div>
    <button class="btn-source" onclick="showSignalSource('${escapeHtml(streamId)}', '${encoded}')" title="Show source details">Source</button>
  </div>`;
}

// ===== SSE =====
// Backend broadcasts events with `stream_id = URL` (the raw source).
// Frontend keys `streams` by the user-friendly name (e.g. "CNBC TV18: ...").
// resolveStreamId finds the existing key by URL match before falling back
// to creating a new entry — fixes "stream shown twice, once by name once by URL".
function resolveStreamId(sseStreamId) {
  if (!sseStreamId) return sseStreamId;
  if (streams[sseStreamId]) return sseStreamId;  // exact key match (demo mode)
  for (const [key, s] of Object.entries(streams)) {
    if (s.url === sseStreamId) return key;
  }
  return sseStreamId;
}

function connect(endpoint) {
  if (activeSSE) activeSSE.close();
  console.log("[SSE] connecting to", endpoint);
  const source = new EventSource(endpoint);
  activeSSE = source;

  source.onopen = () => {
    console.log("[SSE] open");
    if (!isDemoMode) setStatus("Connected", "status-connected");
  };

  source.onerror = (e) => {
    console.warn("[SSE] error/closed", e);
    if (isDemoMode) { setStatus("Demo Complete", "status-demo"); source.close(); activeSSE = null; return; }
    setStatus("Reconnecting...", "status-connecting");
    source.close(); activeSSE = null;
    setTimeout(() => connect(endpoint), 3000);
  };

  source.addEventListener("transcript", (e) => {
    const event = JSON.parse(e.data);
    const t = event.transcript;
    if (!t) return;
    const streamId = resolveStreamId(event.stream_id) || Object.keys(streams)[0];
    if (removedStreamIds.has(streamId)) return;
    if (!streams[streamId]) addStream(streamId, streamId, "demo");
    if (streams[streamId].stopped) return;

    // Append new chunk to the rolling buffer. Signals attach later via the
    // signal event (usually arrives within a second of transcript).
    const s = streams[streamId];
    // If this chunk_id already exists (re-processing), skip
    if (s.chunks.some(c => c.chunk_id === t.chunk_id)) return;
    s.chunks.push({
      chunk_id: t.chunk_id,
      ts: new Date().toLocaleTimeString(),
      text: t.full_text || "",
      signals: [],  // filled when the signal event arrives
    });
    // Keep last ~5 min (~30 chunks @ 10s)
    if (s.chunks.length > 30) s.chunks = s.chunks.slice(-30);

    renderStreamFilters();
    if (!document.getElementById("view-streams").classList.contains("hidden")) {
      const container = document.getElementById(`chunks-container-${streamId}`);
      if (container) container.innerHTML = renderStreamChunks(streamId, s);
      else renderStreams();
    }
  });

  // Extraction carries people + indicators (commodities go via the signal event).
  // We attach them to the matching chunk so the UI can surface them.
  source.addEventListener("extraction", (e) => {
    const event = JSON.parse(e.data);
    const ex = event.extraction;
    if (!ex) return;
    const streamId = resolveStreamId(event.stream_id) || Object.keys(streams)[0];
    if (removedStreamIds.has(streamId)) return;
    const s = streams[streamId];
    if (!s) return;
    const chunk = s.chunks.find(c => c.chunk_id === ex.chunk_id);
    if (!chunk) return;
    chunk.people = ex.people || [];
    chunk.indicators = ex.indicators || [];
    // Re-render just this stream's chunks panel
    if (!document.getElementById("view-streams").classList.contains("hidden")) {
      const container = document.getElementById(`chunks-container-${streamId}`);
      if (container) container.innerHTML = renderStreamChunks(streamId, s);
    }
  });

  source.addEventListener("signal", (e) => {
    const event = JSON.parse(e.data);
    const scoring = event.scoring;
    if (!scoring) return;
    const streamId = resolveStreamId(event.stream_id) || Object.keys(streams)[0];
    if (removedStreamIds.has(streamId)) return;
    if (!streams[streamId]) addStream(streamId, streamId, "demo");
    if (streams[streamId].stopped) return;

    const ts = Date.now();
    for (const sig of scoring.signals) {
      sig._time = new Date().toLocaleTimeString();
      sig._timestamp = ts;
      sig._stream_id = streamId;
      sig.chunk_id = scoring.chunk_id;

      if (commodities[sig.commodity]) {
        commodities[sig.commodity].events.push(sig);
      }
    }

    // Attach signals to their chunk if it exists (it should, from transcript event)
    const s = streams[streamId];
    const chunk = s.chunks.find(c => c.chunk_id === scoring.chunk_id);
    if (chunk) {
      chunk.signals = chunk.signals.concat(scoring.signals);
    }

    renderStreamFilters();
    renderCommodityFilters();

    if (!document.getElementById("view-streams").classList.contains("hidden")) {
      const container = document.getElementById(`chunks-container-${streamId}`);
      if (container) container.innerHTML = renderStreamChunks(streamId, s);
      else renderStreams();
    }
    if (!document.getElementById("view-commodities").classList.contains("hidden")) {
      renderLatestEvents();
      renderCommodities();
    }
  });

  // ----- SEGMENT EVENTS (hierarchical super-events) -----
  const handleSegmentEvent = (kind) => (e) => {
    const event = JSON.parse(e.data);
    const seg = event.segment;
    if (!seg) return;
    const streamId = resolveStreamId(event.stream_id || seg.stream_id);
    if (removedStreamIds.has(streamId)) return;
    if (!streams[streamId]) addStream(streamId, streamId, "demo");
    const s = streams[streamId];

    if (kind === "close") {
      // Remove from active, add to closed history
      delete s.active_segments[seg.primary_commodity];
      s.closed_segments.push(seg);
      if (s.closed_segments.length > CLOSED_SEGMENTS_KEEP) {
        s.closed_segments = s.closed_segments.slice(-CLOSED_SEGMENTS_KEEP);
      }
      // Also attach to commodity view's segment history
      if (commodities[seg.primary_commodity]) {
        commodities[seg.primary_commodity]._closed_segments =
          commodities[seg.primary_commodity]._closed_segments || [];
        commodities[seg.primary_commodity]._closed_segments.push(seg);
      }
    } else {
      // open / update
      s.active_segments[seg.primary_commodity] = seg;
    }

    if (!document.getElementById("view-streams").classList.contains("hidden")) {
      const container = document.getElementById(`segments-container-${streamId}`);
      if (container) container.innerHTML = renderStreamActiveSegments(streamId, s);
    }
    if (!document.getElementById("view-commodities").classList.contains("hidden")) {
      renderLatestEvents();
      renderCommodities();
    }
  };
  source.addEventListener("segment.open", handleSegmentEvent("open"));
  source.addEventListener("segment.update", handleSegmentEvent("update"));
  source.addEventListener("segment.close", handleSegmentEvent("close"));

  source.addEventListener("keepalive", () => {});
}

// ===== STATS POLLING =====
async function pollStats() {
  const stats = await fetchJSON("/api/stats");
  if (!stats) return;
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  set("stat-stt", stats.avg_stt_latency_ms ? `${Math.round(stats.avg_stt_latency_ms)}ms` : "--");
  set("stat-extract", stats.avg_extraction_latency_ms ? `${Math.round(stats.avg_extraction_latency_ms)}ms` : "--");
  set("stat-score", stats.avg_scoring_latency_ms ? `${Math.round(stats.avg_scoring_latency_ms)}ms` : "--");
  set("stat-chunks-val", stats.chunks_processed || 0);
  set("stat-signals-val", stats.total_signals || 0);
  set("stat-cost-val", `$${(stats.total_cost_usd || 0).toFixed(4)}`);

  // Point the "actual →" link at the right provider's usage page
  const link = document.getElementById("stat-cost-link");
  if (link) {
    const provider = (typeof getCurrentProvider === "function") ? getCurrentProvider() : "anthropic";
    link.href = provider === "openai"
      ? "https://platform.openai.com/usage"
      : "https://console.anthropic.com/settings/usage";
    link.title = `Open ${provider === "openai" ? "OpenAI" : "Anthropic"} usage dashboard (actual billed cost)`;
  }
}
setInterval(pollStats, 3000);

async function pollBacktest() {
  const stats = await fetchJSON("/api/backtest/stats");
  if (!stats) return;
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

  const renderPanel = (prefix, data) => {
    if (!data || !data.by_timeframe) return;
    const short = data.by_timeframe.short_term || {};
    const med = data.by_timeframe.medium_term || {};
    const shortEvald = (short.total || 0) - (short.pending || 0);
    const medEvald = (med.total || 0) - (med.pending || 0);
    set(`${prefix}-short`, `${short.correct || 0} / ${shortEvald}`);
    set(`${prefix}-medium`, `${med.correct || 0} / ${medEvald}`);
    set(`${prefix}-overall`, data.accuracy !== null ? `${Math.round(data.accuracy * 100)}%` : "--");
  };

  renderPanel("btl", stats.live);
  if (stats.live) set("btl-pending", stats.live.pending || 0);
  renderPanel("btr", stats.retrospective);
  if (stats.retrospective) set("btr-total", stats.retrospective.total || 0);
}
setInterval(pollBacktest, 10000);
pollBacktest();

// ===== EVALUATION VIEW =====
async function refreshEvaluation() {
  const containers = {
    dataset: document.getElementById("eval-dataset-content"),
    headline: document.getElementById("eval-headline-content"),
    reliability: document.getElementById("eval-reliability-content"),
    comparisons: document.getElementById("eval-comparisons-content"),
    horizon: document.getElementById("eval-horizon-content"),
    commodity: document.getElementById("eval-commodity-content"),
    pnl: document.getElementById("eval-pnl-content"),
  };

  const horizonAnalysisEl = document.getElementById("eval-horizon-analysis-content");
  let data;
  try {
    const res = await fetch("/api/backtest/professional");
    data = await res.json();
  } catch (e) {
    Object.values(containers).forEach(el => { if (el) el.textContent = "Failed to load: " + e.message; });
    if (horizonAnalysisEl) horizonAnalysisEl.textContent = "Failed to load: " + e.message;
    return;
  }

  if (data.error) {
    const msg = `<p class="no-key">${escapeHtml(data.error)}</p>` +
                `<pre style="white-space:pre-wrap;font-size:0.8rem;background:#0d1117;padding:0.5rem;border-radius:4px">` +
                `python -m evaluation.fetch_prices\npython -m evaluation.walk_forward --split calibration\npython -m evaluation.walk_forward --split test\npython -m evaluation.run_professional_backtest</pre>`;
    if (containers.dataset) containers.dataset.innerHTML = msg;
    ["headline", "reliability", "comparisons", "horizon", "commodity", "pnl"].forEach(k => {
      if (containers[k]) containers[k].innerHTML = "<p class='hint'>Not available until backtest is run.</p>";
    });
    if (horizonAnalysisEl) horizonAnalysisEl.innerHTML = "<p class='hint'>Not available until backtest is run.</p>";
    return;
  }

  renderEvalDataset(containers.dataset, data);
  renderEvalHeadline(containers.headline, data);
  renderEvalReliability(containers.reliability, data);
  renderEvalComparisons(containers.comparisons, data);
  renderEvalHorizon(containers.horizon, data);
  renderEvalCommodity(containers.commodity, data);
  renderEvalPnl(containers.pnl, data);
  renderEvalHorizonAnalysis(horizonAnalysisEl, data);

  // Segment reality score (separate endpoint)
  const segStatsEl = document.getElementById("eval-segment-stats-content");
  if (segStatsEl) {
    try {
      const segStats = await fetch("/api/segments/stats").then(r => r.json());
      renderSegmentStats(segStatsEl, segStats);
    } catch (e) {
      segStatsEl.innerHTML = "<p class='hint'>Failed to load segment stats.</p>";
    }
  }
}

function renderSegmentStats(el, stats) {
  const total = stats.total_segments || 0;
  if (total === 0) {
    el.innerHTML = "<p class='hint'>No closed segments yet. Run a live stream for a few minutes to see segments here.</p>";
    return;
  }

  const byCom = stats.by_commodity || {};
  const byStream = stats.by_stream || {};
  const horizons = ["h1m", "h5m", "h15m", "h1h"];

  const commodityRows = Object.entries(byCom)
    .sort((a, b) => b[1].total - a[1].total)
    .map(([name, row]) => {
      const cells = horizons.map(h => {
        const acc = (row.accuracy || {})[h];
        return acc != null ? `${(acc * 100).toFixed(1)}%` : "&mdash;";
      });
      return `<tr><td>${escapeHtml(name)}</td><td>${row.total}</td><td>${row.with_reality}</td>${cells.map(c => `<td>${c}</td>`).join("")}</tr>`;
    }).join("");

  const streamRows = Object.entries(byStream)
    .sort((a, b) => b[1].total - a[1].total)
    .map(([name, row]) => {
      const cells = horizons.map(h => {
        const acc = (row.accuracy || {})[h];
        return acc != null ? `${(acc * 100).toFixed(1)}%` : "&mdash;";
      });
      const short = name.length > 50 ? name.slice(0, 47) + "..." : name;
      return `<tr><td title="${escapeHtml(name)}">${escapeHtml(short)}</td><td>${row.total}</td><td>${row.with_reality}</td>${cells.map(c => `<td>${c}</td>`).join("")}</tr>`;
    }).join("");

  el.innerHTML = `
    <p><strong>${total}</strong> segments logged. Accuracy = segment's predicted direction matched actual price movement by the horizon (|pct change| &lt; 0.5% counts as neutral).</p>

    <h4 style="margin-top:1rem">Per commodity</h4>
    <table class="eval-table">
      <thead><tr><th>Commodity</th><th>Segments</th><th>With reality</th><th>+1m</th><th>+5m</th><th>+15m</th><th>+1h</th></tr></thead>
      <tbody>${commodityRows}</tbody>
    </table>

    <h4 style="margin-top:1rem">Per stream</h4>
    <table class="eval-table">
      <thead><tr><th>Stream</th><th>Segments</th><th>With reality</th><th>+1m</th><th>+5m</th><th>+15m</th><th>+1h</th></tr></thead>
      <tbody>${streamRows}</tbody>
    </table>
    <p class="hint" style="font-size:0.72rem;margin-top:0.5rem">1-minute bars from Yahoo Finance for last 7 days. For older segments, falls back to daily close. For production-grade intraday validation, upgrade to Polygon.io / Alpha Vantage Premium.</p>`;
}

function renderEvalHorizonAnalysis(el, data) {
  if (!el) return;
  const ha = data.horizon_analysis;
  if (!ha) {
    el.innerHTML = "<p class='hint'>No horizon analysis data.</p>";
    return;
  }
  const source = ha.source || "unknown";
  const anyHit = ((ha.any_horizon || {}).any_hit || 0) * 100;
  const allHit = ((ha.all_horizons || {}).all_hit || 0) * 100;
  const adap = ha.adaptive_vs_fixed || {};
  const uplift = (adap.uplift || 0) * 100;
  const upliftStr = uplift >= 0 ? `+${uplift.toFixed(1)}%` : `${uplift.toFixed(1)}%`;
  const upliftColor = uplift > 2 ? "#3fb950" : (uplift < -2 ? "#f85149" : "#8b949e");

  const persist = ha.signal_persistence || {};
  const persistRows = [1, 3, 7, 14, 30].map(h => {
    const v = persist[`d${h}_given_d1`];
    return v != null ? `<tr><td>d${h}</td><td>${(v * 100).toFixed(1)}%</td></tr>` : `<tr><td>d${h}</td><td>&mdash;</td></tr>`;
  }).join("");

  const mm = ha.mae_mfe || {};
  const maeMfeHtml = mm.n ? `
    <table class="eval-table">
      <thead><tr><th>Metric</th><th>Value</th></tr></thead>
      <tbody>
        <tr><td>Avg MFE (best the average trade got to)</td><td>${(mm.avg_mfe_pct || 0).toFixed(2)}%</td></tr>
        <tr><td>Avg MAE (worst the average trade dropped to)</td><td>${(mm.avg_mae_pct || 0).toFixed(2)}%</td></tr>
        <tr><td>MFE / |MAE| ratio</td><td>${mm.ratio_mfe_mae != null ? mm.ratio_mfe_mae.toFixed(2) : "&mdash;"}</td></tr>
      </tbody>
    </table>` : "<p class='hint'>No MAE/MFE data.</p>";

  const opt = ha.optimal_horizon_per_type || {};
  const optRows = Object.entries(opt)
    .sort((a, b) => b[1].n_samples - a[1].n_samples)
    .map(([et, row]) => `<tr><td>${escapeHtml(et)}</td><td>d${row.best_horizon}</td><td>${(row.best_accuracy * 100).toFixed(1)}%</td><td>${row.n_samples}</td></tr>`)
    .join("");

  el.innerHTML = `
    <p class="hint"><strong>Source:</strong> ${escapeHtml(source)}</p>

    <h4 style="margin-top:1rem;margin-bottom:0.4rem">Upper / lower bounds</h4>
    <table class="eval-table">
      <tbody>
        <tr><td><strong>Any-horizon hit rate</strong> (correct at d1 OR d3 OR d7 OR d14 OR d30)</td><td><strong>${anyHit.toFixed(1)}%</strong></td></tr>
        <tr><td><strong>All-horizons hit rate</strong> (correct at every horizon &mdash; durable signal)</td><td><strong>${allHit.toFixed(1)}%</strong></td></tr>
        <tr><td colspan="2" class="hint">Gap between them = predictions whose direction was right but <em>timing-dependent</em>. Large gap &rarr; optimizing horizon can help.</td></tr>
      </tbody>
    </table>

    <h4 style="margin-top:1rem;margin-bottom:0.4rem">Adaptive horizon vs. fixed d=7</h4>
    <table class="eval-table">
      <tbody>
        <tr><td>Fixed d=7 accuracy</td><td>${((adap.fixed_d7_accuracy || 0) * 100).toFixed(1)}%</td></tr>
        <tr><td>Adaptive accuracy (per-type horizon learned on train+cal)</td><td>${((adap.adaptive_accuracy || 0) * 100).toFixed(1)}%</td></tr>
        <tr><td><strong>Uplift</strong></td><td><strong style="color:${upliftColor}">${upliftStr}</strong></td></tr>
      </tbody>
    </table>
    <p class="hint" style="font-size:0.72rem">Positive uplift &rarr; failing predictions at d=7 were often correct at another horizon matching their event type. Learned without look-ahead: horizons fitted on train+cal, applied to test.</p>

    <h4 style="margin-top:1rem;margin-bottom:0.4rem">Signal persistence P(correct at d_h | correct at d1)</h4>
    <table class="eval-table">
      <thead><tr><th>Horizon</th><th>Still correct</th></tr></thead>
      <tbody>${persistRows}</tbody>
    </table>
    <p class="hint" style="font-size:0.72rem">~1.0 = durable; 0.5 = signal already half reverted; &lt;0.5 = trade flipped against you.</p>

    <h4 style="margin-top:1rem;margin-bottom:0.4rem">Maximum Favorable / Adverse Excursion</h4>
    ${maeMfeHtml}

    <h4 style="margin-top:1rem;margin-bottom:0.4rem">Optimal horizon per event type (from train+cal)</h4>
    <table class="eval-table">
      <thead><tr><th>Event type</th><th>Best horizon</th><th>Accuracy</th><th>n</th></tr></thead>
      <tbody>${optRows}</tbody>
    </table>
  `;
}

function renderEvalDataset(el, data) {
  if (!el) return;
  const ds = data.dataset || {};
  const split = ds.split || {};
  const rows = ["train", "calibration", "test"].map(name => {
    const s = split[name] || {};
    if (!s.count) return `<tr><td>${name}</td><td>0</td><td>&mdash;</td></tr>`;
    return `<tr><td>${name}</td><td>${s.count}</td><td>${s.date_min} &rarr; ${s.date_max}</td></tr>`;
  }).join("");
  el.innerHTML = `
    <p>Total events: <strong>${ds.total || 0}</strong> across ${(ds.commodities || []).length} commodities (${(ds.commodities || []).join(", ")}).</p>
    <table class="eval-table">
      <thead><tr><th>Split</th><th>Count</th><th>Date range</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderEvalHeadline(el, data) {
  if (!el) return;
  const methods = data.methods || {};
  if (Object.keys(methods).length === 0) {
    el.innerHTML = "<p class='hint'>No methods evaluated yet.</p>";
    return;
  }
  const primaryKey = "d7";
  const rows = Object.entries(methods).map(([name, row]) => {
    const m = (row.metrics_test || {})[primaryKey] || {};
    const market = m.accuracy_vs_market || {};
    const label = m.accuracy_vs_label || {};
    const marketStr = market.point != null
      ? `${(market.point * 100).toFixed(1)}% <span class="hint">[${(market.ci95_low * 100).toFixed(1)}–${(market.ci95_high * 100).toFixed(1)}]</span>`
      : "&mdash;";
    const labelStr = label.point != null ? `${(label.point * 100).toFixed(1)}%` : "&mdash;";
    return `<tr><td>${escapeHtml(name)}</td><td>${marketStr}</td><td>${labelStr}</td></tr>`;
  }).join("");
  el.innerHTML = `
    <table class="eval-table">
      <thead><tr><th>Method</th><th>Accuracy vs. market (d=7) + 95% CI</th><th>vs. label</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderEvalReliability(el, data) {
  if (!el) return;
  if (!data.calibration) {
    el.innerHTML = "<p class='hint'>No LLM calibration data yet. Run walk_forward on calibration + test splits.</p>";
    return;
  }
  const cal = data.calibration;
  el.innerHTML = `
    <p>ECE before calibration: <strong>${cal.ece_before.toFixed(3)}</strong> &rarr; after (test split): <strong>${cal.ece_after_test.toFixed(3)}</strong>. Lower is better; 0 = perfectly calibrated.</p>
    <div style="display:flex;gap:1rem;flex-wrap:wrap">
      <div><div class="hint">Calibration split</div><img src="/api/backtest/reliability.svg?split=calibration" alt="Reliability calibration" style="max-width:100%;border-radius:6px"/></div>
      <div><div class="hint">Test split (post-calibration)</div><img src="/api/backtest/reliability.svg?split=test" alt="Reliability test" style="max-width:100%;border-radius:6px"/></div>
    </div>`;
}

function renderEvalComparisons(el, data) {
  if (!el) return;
  const comps = data.comparisons || {};
  if (Object.keys(comps).length === 0) {
    el.innerHTML = "<p class='hint'>LLM predictions not available yet.</p>";
    return;
  }
  const rows = Object.entries(comps).map(([label, c]) => {
    const verdict = (c.p_value < 0.05 && c.a_only_correct > c.b_only_correct)
      ? "<span style='color:#3fb950'>LLM wins</span>"
      : (c.p_value < 0.05 ? "<span style='color:#f85149'>Baseline wins</span>" : "<span class='hint'>tie</span>");
    return `<tr><td>${escapeHtml(label)}</td><td>${c.both_correct}</td><td>${c.a_only_correct}</td><td>${c.b_only_correct}</td><td>${c.both_wrong}</td><td>${c.p_value.toFixed(3)}</td><td>${verdict}</td></tr>`;
  }).join("");
  el.innerHTML = `
    <table class="eval-table">
      <thead><tr><th>Comparison</th><th>Both right</th><th>LLM only</th><th>Baseline only</th><th>Both wrong</th><th>p-value</th><th>Verdict</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderEvalHorizon(el, data) {
  if (!el) return;
  const methods = data.methods || {};
  if (Object.keys(methods).length === 0) {
    el.innerHTML = "<p class='hint'>No data.</p>";
    return;
  }
  const horizons = ["d1", "d3", "d7", "d14", "d30"];
  const rows = Object.entries(methods).map(([name, row]) => {
    const cells = horizons.map(h => {
      const m = (row.metrics_test || {})[h] || {};
      const p = (m.accuracy_vs_market || {}).point;
      return p != null ? `${(p * 100).toFixed(1)}%` : "&mdash;";
    });
    return `<tr><td>${escapeHtml(name)}</td>${cells.map(c => `<td>${c}</td>`).join("")}</tr>`;
  }).join("");
  el.innerHTML = `
    <table class="eval-table">
      <thead><tr><th>Method</th><th>d1</th><th>d3</th><th>d7</th><th>d14</th><th>d30</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderEvalCommodity(el, data) {
  if (!el) return;
  const pc = data.per_commodity || {};
  const llm = pc.llm || {};
  const kw = pc.keyword || {};
  const commodities = Array.from(new Set([...Object.keys(llm), ...Object.keys(kw)])).sort();
  if (commodities.length === 0) {
    el.innerHTML = "<p class='hint'>No commodity data.</p>";
    return;
  }
  const rows = commodities.map(c => {
    const l = llm[c] || {};
    const k = kw[c] || {};
    const lAcc = l.accuracy != null ? `${(l.accuracy * 100).toFixed(1)}%` : "&mdash;";
    const kAcc = k.accuracy != null ? `${(k.accuracy * 100).toFixed(1)}%` : "&mdash;";
    return `<tr><td>${escapeHtml(c)}</td><td>${l.count || 0}</td><td>${lAcc}</td><td>${kAcc}</td></tr>`;
  }).join("");
  el.innerHTML = `
    <table class="eval-table">
      <thead><tr><th>Commodity</th><th>LLM n</th><th>LLM acc</th><th>Keyword acc</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderEvalPnl(el, data) {
  if (!el) return;
  const pnl = data.pnl || [];
  const filtered = pnl.filter(p => p.confidence_threshold === 0.6);
  if (filtered.length === 0) {
    el.innerHTML = "<p class='hint'>No LLM P&L data yet.</p>";
    return;
  }
  const rows = filtered.map(r => {
    const sharpe = r.sharpe != null ? r.sharpe.toFixed(2) : "&mdash;";
    const wr = r.win_rate != null ? `${(r.win_rate * 100).toFixed(1)}%` : "&mdash;";
    const total = r.total_return.toFixed(3);
    const dd = r.max_drawdown.toFixed(3);
    return `<tr><td>d${r.horizon_days}</td><td>${r.trades}</td><td>${total}</td><td>${sharpe}</td><td>${dd}</td><td>${wr}</td></tr>`;
  }).join("");
  el.innerHTML = `
    <table class="eval-table">
      <thead><tr><th>Horizon</th><th>Trades</th><th>Total log-return</th><th>Sharpe</th><th>Max DD</th><th>Win rate</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ===== START =====
init();
