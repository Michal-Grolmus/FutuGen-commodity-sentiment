// ===== STATE =====
let activeSSE = null;
let isDemoMode = false;
let selectedStreamId = null;     // for stream sub-nav filter
let selectedCommodityId = null;  // for commodity sub-nav filter

// Stream data: { streamId: { name, url, type, transcript, signals[] } }
const streams = {};

// Commodity data: { commodityId: { display_name, events[] } }
const COMMODITY_NAMES_FULL = {
  crude_oil_wti: "WTI Crude Oil", crude_oil_brent: "Brent Crude Oil",
  natural_gas: "Natural Gas", gold: "Gold", silver: "Silver",
  wheat: "Wheat", corn: "Corn", copper: "Copper",
};
const COMMODITY_SHORT = {
  crude_oil_wti: "WTI", crude_oil_brent: "Brent", natural_gas: "Nat Gas",
  gold: "Gold", silver: "Silver", wheat: "Wheat", corn: "Corn", copper: "Copper",
};
const commodities = {};
for (const [id, name] of Object.entries(COMMODITY_NAMES_FULL)) {
  commodities[id] = { display_name: name, events: [] };
}

// ===== INIT =====
async function init() {
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
  loadStreamPicker();
}

function showApp(view) {
  document.getElementById("onboarding").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  showView(view || "streams");
}

function showView(view) {
  document.getElementById("view-streams").classList.toggle("hidden", view !== "streams");
  document.getElementById("view-commodities").classList.toggle("hidden", view !== "commodities");
  document.getElementById("nav-streams").classList.toggle("active", view === "streams");
  document.getElementById("nav-commodities").classList.toggle("active", view === "commodities");
  document.getElementById("sub-nav-streams").classList.toggle("hidden", view !== "streams");
  document.getElementById("sub-nav-commodities").classList.toggle("hidden", view !== "commodities");

  if (view === "commodities") {
    renderCommoditySubNav();
    renderLatestEvents();
    renderCommodities();
  }
  if (view === "streams") {
    renderStreamSubNav();
    renderStreams();
  }
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
      if (s.type === "file") {
        alert(`To analyze this file, restart with:\npython -m src.main --mock -f ${s.url}`);
      } else if (s.type === "live") {
        alert(`To analyze this live stream, restart with:\npython -m src.main --mock -s "${s.url}"`);
      }
    };
    picker.appendChild(div);
  }
}

function addCustomStream() {
  const url = document.getElementById("custom-url").value.trim();
  if (!url) return;
  addStream(url, url, "custom");
  showApp("streams");
  alert(`To analyze this stream, restart with:\npython -m src.main --mock -s "${url}"`);
}

function saveApiKey() {
  const key = document.getElementById("api-key-input").value.trim();
  if (!key) return;
  alert("Set in .env:\nANTHROPIC_API_KEY=" + key.substring(0, 12) + "...\nThen restart the server.");
}

function startDemo() {
  isDemoMode = true;
  showApp("streams");
  setStatus("Demo Mode", "status-demo");
  connect("/api/demo");
}

// ===== STREAM MANAGEMENT =====
function addStream(id, url, type) {
  if (!streams[id]) {
    streams[id] = { name: id, url, type, transcript: "", signals: [] };
  }
  if (!selectedStreamId) selectedStreamId = id;
}

function renderStreamSubNav() {
  const nav = document.getElementById("sub-nav-streams");
  const ids = Object.keys(streams);
  if (ids.length === 0) {
    nav.innerHTML = '<span style="color:#c9d1d9;font-size:0.78rem">No streams yet</span>';
    return;
  }
  nav.innerHTML = `<button class="sub-nav-btn ${selectedStreamId === '__all__' ? 'active' : ''}" onclick="selectStream('__all__')">All <span class="count">${ids.length}</span></button>`;
  for (const id of ids) {
    const s = streams[id];
    const cls = selectedStreamId === id ? "active" : "";
    nav.innerHTML += `<button class="sub-nav-btn ${cls}" onclick="selectStream('${escapeHtml(id)}')">${escapeHtml(s.name)} <span class="count">${s.signals.length}</span></button>`;
  }
}

function selectStream(id) {
  selectedStreamId = id;
  renderStreamSubNav();
  renderStreams();
}

function renderStreams() {
  const container = document.getElementById("streams-list");
  const noStreams = document.getElementById("no-streams");
  const keys = Object.keys(streams);
  noStreams.classList.toggle("hidden", keys.length > 0);
  container.innerHTML = "";

  const toRender = (selectedStreamId === "__all__" || !selectedStreamId)
    ? keys
    : keys.filter(id => id === selectedStreamId);

  for (const id of toRender) {
    const s = streams[id];
    const visible = s.signals.slice(-3).reverse();
    const total = s.signals.length;

    let signalsHtml = visible.map(sig => renderSignalItem(sig)).join("");
    let expand = total > 3
      ? `<span class="expand-link" onclick="toggleStreamSignals('${escapeHtml(id)}')">Show all ${total} signals &darr;</span><div id="stream-all-${escapeHtml(id)}" class="hidden">${s.signals.slice().reverse().map(sig => renderSignalItem(sig)).join("")}</div>`
      : "";

    const card = document.createElement("div");
    card.className = "stream-card";
    card.innerHTML = `
      <div class="stream-card-header">
        <span class="stream-name">${escapeHtml(s.name)}</span>
        <span class="stream-status">${escapeHtml(s.type)}</span>
      </div>
      <div class="stream-transcript" id="transcript-${escapeHtml(id)}">${escapeHtml(s.transcript) || '<span style="color:#8b949e">Waiting for transcript...</span>'}</div>
      <div class="stream-signals">${signalsHtml || '<span style="color:#8b949e;font-size:0.8rem">No signals yet</span>'}${expand}</div>`;
    container.appendChild(card);
  }
}

function toggleStreamSignals(id) {
  const el = document.getElementById(`stream-all-${id}`);
  if (el) el.classList.toggle("hidden");
}

// ===== COMMODITY VIEW =====
function renderCommoditySubNav() {
  const nav = document.getElementById("sub-nav-commodities");
  nav.innerHTML = `<button class="sub-nav-btn ${selectedCommodityId === null ? 'active' : ''}" onclick="selectCommodity(null)">All</button>`;
  for (const [id, c] of Object.entries(commodities)) {
    const cls = selectedCommodityId === id ? "active" : "";
    nav.innerHTML += `<button class="sub-nav-btn ${cls}" onclick="selectCommodity('${id}')">${escapeHtml(COMMODITY_SHORT[id])} <span class="count">${c.events.length}</span></button>`;
  }
}

function selectCommodity(id) {
  selectedCommodityId = id;
  renderCommoditySubNav();
  renderCommodities();
}

function renderLatestEvents() {
  const grid = document.getElementById("latest-events-grid");
  if (!grid) return;

  // Collect all events from all commodities, pick 3 with most recent timestamp
  const allEvents = [];
  for (const [id, c] of Object.entries(commodities)) {
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

  const toRender = selectedCommodityId === null
    ? Object.keys(commodities)
    : [selectedCommodityId];

  for (const id of toRender) {
    const c = commodities[id];
    const visible = c.events.slice(-3).reverse();
    const total = c.events.length;

    const card = document.createElement("div");
    card.className = "commodity-card";

    let eventsHtml = visible.map(e => renderSignalItem(e)).join("");
    let expand = total > 3
      ? `<span class="expand-link" onclick="toggleCommodity('${id}')">Show all ${total} events &darr;</span><div id="commodity-all-${id}" class="hidden">${c.events.slice().reverse().map(e => renderSignalItem(e)).join("")}</div>`
      : "";

    card.innerHTML = `
      <div class="commodity-card-header" onclick="toggleCommodity('${id}_main')">
        <div>
          <span class="commodity-title">${escapeHtml(c.display_name)}</span>
          <span class="commodity-count">${total} event${total !== 1 ? "s" : ""}</span>
        </div>
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
    const streamId = event.stream_id || Object.keys(streams)[0];
    if (!streams[streamId]) addStream(streamId, streamId, "demo");
    streams[streamId].transcript = t.full_text;
    renderStreamSubNav();
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

    const ts = Date.now();
    for (const sig of scoring.signals) {
      sig._time = new Date().toLocaleTimeString();
      sig._timestamp = ts;

      streams[streamId].signals.push(sig);
      if (commodities[sig.commodity]) {
        commodities[sig.commodity].events.push(sig);
      }
    }

    renderStreamSubNav();
    renderCommoditySubNav();

    if (!document.getElementById("view-streams").classList.contains("hidden")) renderStreams();
    if (!document.getElementById("view-commodities").classList.contains("hidden")) {
      renderLatestEvents();
      renderCommodities();
    }
  });

  source.addEventListener("keepalive", () => {});
}

// ===== START =====
init();
