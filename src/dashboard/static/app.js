// ===== STATE =====
let activeSSE = null;
let isDemoMode = false;

// Multi-select filters (Set of IDs); empty set = nothing selected
const selectedStreamIds = new Set();
const selectedCommodityIds = new Set();

// Stream data: { streamId: { name, url, type, transcript, signals[], stopped } }
const streams = {};

// Default saved streams (loaded on first visit, then user edits persist in localStorage)
const DEFAULT_SAVED_STREAMS = [
  { name: "Bloomberg Business News", url: "https://www.youtube.com/watch?v=iEpJwprxDdk" },
  { name: "Bloomberg Originals", url: "https://www.youtube.com/watch?v=DxmDPrfinXY" },
  { name: "Yahoo Finance 24/7", url: "https://www.youtube.com/watch?v=KQp-e_XQnDE" },
  { name: "CNBC Marathon", url: "https://www.youtube.com/watch?v=9NyxcX3rhQs" },
  { name: "Bloomberg TV (channel)", url: "https://www.youtube.com/@markets/live" },
  { name: "CNBC (channel)", url: "https://www.youtube.com/@CNBC/live" },
  { name: "Reuters (channel)", url: "https://www.youtube.com/@Reuters/live" },
  { name: "Kitco News (channel)", url: "https://www.youtube.com/@KitcoNEWS/live" },
  { name: "Sample: OPEC analysis (file)", url: "audio_samples/real/opec_raw.wav" },
  { name: "Sample: Fed & Gold (file)", url: "audio_samples/real/fed_raw.wav" },
];

function loadSavedStreams() {
  try {
    const stored = localStorage.getItem("csm_saved_streams");
    if (stored) return JSON.parse(stored);
  } catch {}
  return [...DEFAULT_SAVED_STREAMS];
}

function persistSavedStreams(list) {
  try { localStorage.setItem("csm_saved_streams", JSON.stringify(list)); } catch {}
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
async function init() {
  await loadCommodities();
  const config = await fetchJSON("/api/config");
  if (!config.has_api_key && !config.input_source) {
    showOnboarding();
  } else {
    const source = config.input_source || "Pipeline";
    addStream(source, source, config.mock_mode ? "mock" : "live");
    showApp("streams");
    connect("/api/events");
    if (config.mock_mode) setStatus("Mock Mode", "status-demo");
  }
}

async function fetchJSON(url) {
  try { const r = await fetch(url); return await r.json(); } catch { return {}; }
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
      // Key accepted by the running pipeline — advance to the app
      await loadCommodities();
      showApp("streams");
      setStatus("Ready", "status-ok");
    } else if (data.ok && !data.active) {
      // Server acknowledged but pipeline is not active (no source yet or empty key)
      await loadCommodities();
      showApp("streams");
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
function showSettingsModal() {
  document.getElementById("settings-modal").classList.remove("hidden");
  // Pre-fill with stored or default values
  const stored = JSON.parse(localStorage.getItem("csm_settings") || "{}");
  document.getElementById("setting-chunk").value = stored.chunk || 10;
  document.getElementById("setting-chunk-val").textContent = (stored.chunk || 10) + "s";
  document.getElementById("setting-model").value = stored.model || "small";
  document.getElementById("setting-lang").value = stored.lang !== undefined ? stored.lang : "en";
}

function closeSettingsModal() {
  document.getElementById("settings-modal").classList.add("hidden");
}

function showRestartCommand() {
  const chunk = document.getElementById("setting-chunk").value;
  const model = document.getElementById("setting-model").value;
  const lang = document.getElementById("setting-lang").value;
  localStorage.setItem("csm_settings", JSON.stringify({ chunk, model, lang }));

  const langPart = lang ? ` WHISPER_LANGUAGE=${lang}` : " WHISPER_LANGUAGE=";
  const cmd = `WHISPER_MODEL_SIZE=${model} CHUNK_DURATION_S=${chunk}${langPart} python -m src.main --mock -f audio_samples/real/opec_raw.wav`;

  alert(
    "To apply these settings, restart the server:\n\n" +
    "Linux/Mac:\n" + cmd + "\n\n" +
    "Windows (PowerShell):\n" +
    `$env:WHISPER_MODEL_SIZE='${model}'; $env:CHUNK_DURATION_S=${chunk}; $env:WHISPER_LANGUAGE='${lang}'; python -m src.main --mock -f audio_samples/real/opec_raw.wav\n\n` +
    "Or edit .env and restart."
  );
  closeSettingsModal();
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
  } catch {}
  renderSettingsView();
}

// ===== SOURCE MODAL =====
async function showSignalSource(streamId, sigRef) {
  // sigRef is a JSON-encoded signal object (passed from button onclick)
  let sig;
  try { sig = JSON.parse(decodeURIComponent(sigRef)); } catch { return; }

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
  for (let i = 0; i < savedStreams.length; i++) {
    const s = savedStreams[i];
    const isActive = Object.values(streams).some(a => a.url === s.url);
    const item = document.createElement("div");
    item.className = "saved-stream-item";
    item.innerHTML = `
      <span class="saved-badge ${isActive ? "active" : "inactive"}">${isActive ? "active" : "inactive"}</span>
      <div style="flex:1;min-width:0">
        <div class="saved-name">${escapeHtml(s.name)}</div>
        <div class="saved-url">${escapeHtml(s.url)}</div>
      </div>
      <button class="btn-sm" onclick="addFromSaved(${i})" ${isActive ? "disabled" : ""}>Start</button>
      <button class="btn-remove" onclick="deleteSavedStream(${i})">Remove</button>`;
    list.appendChild(item);
  }
}

function addSavedStream() {
  const name = document.getElementById("new-saved-name").value.trim();
  const url = document.getElementById("new-saved-url").value.trim();
  if (!name || !url) return alert("Name and URL are required.");
  savedStreams.push({ name, url });
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

function addFromSaved(index) {
  const s = savedStreams[index];
  const type = s.url.startsWith("http") ? "live" : "file";
  addStream(s.name, s.url, type);
  renderSavedStreams();
  renderStreamFilters();
  renderStreams();
}

function startAllSavedStreams() {
  let added = 0;
  for (const s of savedStreams) {
    const already = Object.values(streams).some(a => a.url === s.url);
    if (!already) {
      const type = s.url.startsWith("http") ? "live" : "file";
      addStream(s.name, s.url, type);
      added++;
    }
  }
  renderStreamFilters();
  renderStreams();
  if (added === 0) {
    alert("All saved streams are already active.");
  } else {
    alert(`Added ${added} stream${added !== 1 ? "s" : ""}. To actually transcribe, restart server with one of them as --stream-url or --input-file.`);
  }
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

function submitAddStream() {
  const url = document.getElementById("add-stream-url").value.trim();
  const nameInput = document.getElementById("add-stream-name").value.trim();
  if (!url) return alert("URL is required.");
  const name = nameInput || url.substring(0, 50);
  const type = url.startsWith("http") || url.startsWith("rtmp") ? "live" : "file";
  addStream(name, url, type);
  renderStreamFilters();
  renderStreams();
  closeAddStreamModal();
}

// ===== STREAM MANAGEMENT =====
function addStream(id, url, type) {
  if (!streams[id]) {
    streams[id] = { name: id, url, type, transcript: "", signals: [] };
    selectedStreamIds.add(id);  // auto-select new streams
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
    html += `<button class="filter-btn ${cls}" onclick="toggleStream('${escapeHtml(id)}')">${escapeHtml(s.name)} <span class="count">${s.signals.length}</span></button>`;
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
    const visible = s.signals.slice(-3).reverse();
    const total = s.signals.length;

    let signalsHtml = visible.map(sig => renderSignalItem(sig)).join("");
    // "Show all" should only list the OLDER entries not already visible (visible shows last 3)
    const olderSignals = s.signals.slice(0, Math.max(0, total - 3)).reverse();
    const hidden = olderSignals.length;
    let expand = hidden > 0
      ? `<span class="expand-link" onclick="toggleStreamSignals('${escapeHtml(id)}')">Show ${hidden} older signal${hidden !== 1 ? "s" : ""} &darr;</span><div id="stream-all-${escapeHtml(id)}" class="hidden">${olderSignals.map(sig => renderSignalItem(sig)).join("")}</div>`
      : "";

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
      <div class="stream-transcript" id="transcript-${escapeHtml(id)}">${escapeHtml(s.transcript) || waitingTranscriptMessage(s)}</div>
      <div class="stream-signals">${signalsHtml || '<span style="color:#8b949e;font-size:0.8rem">No signals yet</span>'}${expand}</div>`;
    container.appendChild(card);
  }
}

// Demo-backed stream names (match demo endpoint stream_map values)
const DEMO_STREAM_NAMES = new Set(["Bloomberg Live", "CNBC Markets", "Yahoo Finance"]);

function waitingTranscriptMessage(s) {
  // If we're in demo mode and this stream won't receive demo events, tell user how to activate
  if (isDemoMode && !DEMO_STREAM_NAMES.has(s.name)) {
    return `<span style="color:#f0b400">Demo mode doesn't transcribe custom streams.</span>
      <span style="color:#c9d1d9">To start real transcription, <a href="#" onclick="showView('settings');return false;" class="link">add an API key in Settings</a> and restart the pipeline with this URL.</span>`;
  }
  return '<span style="color:#8b949e">Waiting for transcript...</span>';
}

function toggleStopStream(id) {
  if (!streams[id]) return;
  streams[id].stopped = !streams[id].stopped;
  renderStreams();
}

function toggleStreamSignals(id) {
  const el = document.getElementById(`stream-all-${id}`);
  if (el) el.classList.toggle("hidden");
}

function removeStream(id) {
  if (!streams[id]) return;
  if (!confirm(`Remove stream "${streams[id].name}"? Transcript and signals will be cleared.`)) return;
  delete streams[id];
  selectedStreamIds.delete(id);
  renderStreamFilters();
  renderStreams();
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
  } catch {}
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
    const visible = c.events.slice(-3).reverse();
    const total = c.events.length;

    const card = document.createElement("div");
    card.className = "commodity-card";
    card.id = `commodity-card-${id}`;

    let eventsHtml = visible.map(e => renderSignalItem(e)).join("");
    // "Show all" should only list the OLDER entries not already visible
    const olderEvents = c.events.slice(0, Math.max(0, total - 3)).reverse();
    const hidden = olderEvents.length;
    let expand = hidden > 0
      ? `<span class="expand-link" onclick="toggleCommodity('${id}')">Show ${hidden} older event${hidden !== 1 ? "s" : ""} &darr;</span><div id="commodity-all-${id}" class="hidden">${olderEvents.map(e => renderSignalItem(e)).join("")}</div>`
      : "";

    card.innerHTML = `
      <div class="commodity-card-header">
        <div onclick="toggleCommodity('${id}_main')" style="flex:1;cursor:pointer">
          <span class="commodity-title">${escapeHtml(c.display_name)}</span>
          <span class="commodity-count">${total} event${total !== 1 ? "s" : ""}</span>
        </div>
        <button class="btn-remove" onclick="removeCommodity('${id}')" title="Stop tracking this commodity">Remove</button>
      </div>
      <div class="commodity-events${total > 0 ? " open" : ""}" id="commodity-${id}_main">
        ${eventsHtml || '<div style="color:#8b949e;font-size:0.82rem;padding:0.5rem 0">No events detected yet</div>'}
        ${expand}
      </div>`;
    grid.appendChild(card);
  }
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
function connect(endpoint) {
  if (activeSSE) activeSSE.close();
  const source = new EventSource(endpoint);
  activeSSE = source;

  source.onopen = () => {
    if (!isDemoMode) setStatus("Connected", "status-connected");
  };

  source.onerror = () => {
    if (isDemoMode) { setStatus("Demo Complete", "status-demo"); source.close(); activeSSE = null; return; }
    setStatus("Reconnecting...", "status-connecting");
    source.close(); activeSSE = null;
    setTimeout(() => connect(endpoint), 3000);
  };

  source.addEventListener("transcript", (e) => {
    const event = JSON.parse(e.data);
    const t = event.transcript;
    if (!t) return;
    const streamId = event.stream_id || Object.keys(streams)[0];
    if (!streams[streamId]) addStream(streamId, streamId, "demo");
    if (streams[streamId].stopped) return;  // skip transcript update if stopped
    streams[streamId].transcript = t.full_text;
    renderStreamFilters();
    if (!document.getElementById("view-streams").classList.contains("hidden")) {
      const el = document.getElementById(`transcript-${streamId}`);
      if (el) el.textContent = t.full_text;
      else renderStreams();
    }
  });

  source.addEventListener("signal", (e) => {
    const event = JSON.parse(e.data);
    const scoring = event.scoring;
    if (!scoring) return;
    const streamId = event.stream_id || Object.keys(streams)[0];
    if (!streams[streamId]) addStream(streamId, streamId, "demo");
    if (streams[streamId].stopped) return;  // skip signals + commodity events when paused

    const ts = Date.now();
    for (const sig of scoring.signals) {
      sig._time = new Date().toLocaleTimeString();
      sig._timestamp = ts;
      sig._stream_id = streamId;
      sig.chunk_id = scoring.chunk_id;

      streams[streamId].signals.push(sig);
      if (commodities[sig.commodity]) {
        commodities[sig.commodity].events.push(sig);
      }
    }

    renderStreamFilters();
    renderCommodityFilters();

    if (!document.getElementById("view-streams").classList.contains("hidden")) renderStreams();
    if (!document.getElementById("view-commodities").classList.contains("hidden")) {
      renderLatestEvents();
      renderCommodities();
    }
  });

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
