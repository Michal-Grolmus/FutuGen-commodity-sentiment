// ===== STATE =====
let activeSSE = null;
let isDemoMode = false;

// Stream data: { streamId: { name, url, type, transcript, signals[] } }
const streams = {};

// Commodity data: { commodityId: { display_name, events[] } }
const commodities = {
  crude_oil_wti: { display_name: "WTI Crude Oil", events: [] },
  crude_oil_brent: { display_name: "Brent Crude Oil", events: [] },
  natural_gas: { display_name: "Natural Gas", events: [] },
  gold: { display_name: "Gold", events: [] },
  silver: { display_name: "Silver", events: [] },
  wheat: { display_name: "Wheat", events: [] },
  corn: { display_name: "Corn", events: [] },
  copper: { display_name: "Copper", events: [] },
};

// ===== INIT =====
async function init() {
  const config = await fetchJSON("/api/config");
  if (!config.has_api_key && !config.input_source) {
    showOnboarding();
  } else {
    const source = config.input_source || "Pipeline";
    addStream("default", source, config.mock_mode ? "mock" : "live");
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
  loadStreamPicker();
}

function showApp(view) {
  document.getElementById("onboarding").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  showView(view || "streams");
  renderCommodities();
}

function showView(view) {
  document.getElementById("view-streams").classList.toggle("hidden", view !== "streams");
  document.getElementById("view-commodities").classList.toggle("hidden", view !== "commodities");
  document.getElementById("nav-streams").classList.toggle("active", view === "streams");
  document.getElementById("nav-commodities").classList.toggle("active", view === "commodities");
  if (view === "commodities") renderCommodities();
  if (view === "streams") renderStreams();
}

// ===== ONBOARDING =====
async function loadStreamPicker() {
  const list = await fetchJSON("/api/streams");
  const picker = document.getElementById("stream-picker");
  if (!picker) return;
  picker.innerHTML = "";
  for (const s of list) {
    const div = document.createElement("div");
    div.className = "stream-option";
    div.innerHTML = `<span class="name">${escapeHtml(s.name)}</span><span class="type-badge ${s.type}">${s.type}</span><div class="desc">${escapeHtml(s.description)}</div>`;
    div.onclick = () => {
      addStream(s.name, s.url, s.type);
      showApp("streams");
      // For file sources, we'd need to restart pipeline — show info
      if (s.type === "file") {
        alert(`To analyze this file, restart with:\npython -m src.main --mock -f ${s.url}`);
      }
    };
    picker.appendChild(div);
  }
}

function saveApiKey() {
  const key = document.getElementById("api-key-input").value.trim();
  if (!key) return;
  alert("Set in .env:\nANTHROPIC_API_KEY=" + key.substring(0, 12) + "...\nThen restart the server.");
}

function startDemo() {
  isDemoMode = true;
  addStream("demo", "Demo Replay (12 scenarios)", "demo");
  showApp("streams");
  setStatus("Demo Mode", "status-demo");
  connect("/api/demo");
}

// ===== STREAM MANAGEMENT =====
function addStream(id, url, type) {
  if (!streams[id]) {
    streams[id] = { name: id, url, type, transcript: "", signals: [] };
  }
}

function renderStreams() {
  const container = document.getElementById("streams-list");
  const noStreams = document.getElementById("no-streams");
  const keys = Object.keys(streams);
  noStreams.classList.toggle("hidden", keys.length > 0);
  container.innerHTML = "";

  for (const [id, s] of Object.entries(streams)) {
    const visibleSignals = s.signals.slice(-3);
    const totalSignals = s.signals.length;
    const card = document.createElement("div");
    card.className = "stream-card";
    card.id = `stream-${id}`;

    let signalsHtml = visibleSignals.map(sig => renderSignalItem(sig)).join("");
    let expandHtml = totalSignals > 3
      ? `<div class="stream-signals-header" onclick="toggleStreamSignals('${id}')">Show all ${totalSignals} signals ▸</div><div id="stream-all-${id}" class="hidden">${s.signals.map(sig => renderSignalItem(sig)).join("")}</div>`
      : "";

    card.innerHTML = `
      <div class="stream-card-header">
        <span class="stream-name">${escapeHtml(s.name)}</span>
        <span class="stream-status">${escapeHtml(s.type)}</span>
      </div>
      <div class="stream-transcript" id="transcript-${id}">${escapeHtml(s.transcript) || '<span style="color:#484f58">Waiting for transcript...</span>'}</div>
      <div class="stream-signals">
        ${signalsHtml}
        ${expandHtml}
      </div>`;
    container.appendChild(card);
  }
}

function toggleStreamSignals(id) {
  const el = document.getElementById(`stream-all-${id}`);
  if (el) el.classList.toggle("hidden");
}

// ===== COMMODITY VIEW =====
function renderCommodities() {
  const grid = document.getElementById("commodities-grid");
  if (!grid) return;
  grid.innerHTML = "";

  for (const [id, c] of Object.entries(commodities)) {
    const latest = c.events.length > 0 ? c.events[c.events.length - 1] : null;
    const badgeClass = latest ? latest.direction : "none";
    const badgeText = latest ? `${latest.direction} ${Math.round(latest.confidence * 100)}%` : "No data";
    const visible = c.events.slice(-3);
    const total = c.events.length;

    const card = document.createElement("div");
    card.className = "commodity-card";

    let eventsHtml = visible.map(e => renderSignalItem(e)).join("");
    let expandHtml = total > 3
      ? `<div class="stream-signals-header" onclick="toggleCommodityEvents('${id}')">Show all ${total} events ▸</div><div id="commodity-all-${id}" class="hidden">${c.events.map(e => renderSignalItem(e)).join("")}</div>`
      : "";

    card.innerHTML = `
      <div class="commodity-card-header" onclick="toggleCommodityEvents('${id}_main')">
        <div>
          <span class="commodity-title">${escapeHtml(c.display_name)}</span>
          <span class="commodity-count">${total} event${total !== 1 ? "s" : ""}</span>
        </div>
        <span class="commodity-badge ${badgeClass}">${badgeText}</span>
      </div>
      <div class="commodity-events${total > 0 ? " open" : ""}" id="commodity-${id}_main">
        ${eventsHtml || '<div style="color:#484f58;font-size:0.8rem;padding:0.5rem 0">No events detected yet</div>'}
        ${expandHtml}
      </div>`;
    grid.appendChild(card);
  }
}

function toggleCommodityEvents(id) {
  const el = document.getElementById(`commodity-${id}`);
  if (el) el.classList.toggle("open");
  const allEl = document.getElementById(`commodity-all-${id}`);
  if (allEl) allEl.classList.toggle("hidden");
}

// ===== SHARED SIGNAL RENDERER =====
function renderSignalItem(sig) {
  const time = sig._time || new Date().toLocaleTimeString();
  return `<div class="signal-item">
    <span class="signal-dir ${sig.direction}">${sig.direction}</span>
    <div class="signal-info">
      <div class="signal-name">${escapeHtml(sig.display_name || sig.commodity)}</div>
      <div class="signal-rationale">${escapeHtml(sig.rationale)}</div>
    </div>
    <div class="signal-meta">${time}<br>${(sig.timeframe || "").replace("_", " ")}</div>
    <div class="signal-conf">${Math.round((sig.confidence || 0) * 100)}%</div>
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
    // Update the first stream's transcript
    const streamId = Object.keys(streams)[0];
    if (streamId && streams[streamId]) {
      streams[streamId].transcript = t.full_text;
      const el = document.getElementById(`transcript-${streamId}`);
      if (el) el.textContent = t.full_text;
    }
  });

  source.addEventListener("signal", (e) => {
    const event = JSON.parse(e.data);
    const scoring = event.scoring;
    if (!scoring) return;

    const streamId = Object.keys(streams)[0];
    for (const sig of scoring.signals) {
      sig._time = new Date().toLocaleTimeString();

      // Add to stream
      if (streamId && streams[streamId]) {
        streams[streamId].signals.push(sig);
      }

      // Add to commodity
      const cid = sig.commodity;
      if (commodities[cid]) {
        commodities[cid].events.push(sig);
      }
    }

    // Re-render active view
    if (!document.getElementById("view-streams").classList.contains("hidden")) renderStreams();
    if (!document.getElementById("view-commodities").classList.contains("hidden")) renderCommodities();
  });

  source.addEventListener("keepalive", () => {});
}

// ===== START =====
init();
