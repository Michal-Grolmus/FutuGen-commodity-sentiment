// ===== STATE =====
let activeSSE = null;
let isDemoMode = false;

// Multi-select filters (Set of IDs); empty set = nothing selected
const selectedStreamIds = new Set();
const selectedCommodityIds = new Set();

// Stream data: { streamId: { name, url, type, transcript, signals[], stopped } }
const streams = {};

// Commodity data: { commodityId: { display_name, short_name, events[] } }
// Loaded from /api/commodities at init
const commodities = {};

async function loadCommodities() {
  const list = await fetchJSON("/api/commodities");
  if (!Array.isArray(list)) return;
  for (const c of list) {
    if (!commodities[c.name]) {
      commodities[c.name] = {
        display_name: c.display_name,
        short_name: c.display_name.length > 12 ? c.display_name.split(" ")[0] : c.display_name,
        events: [],
      };
      selectedCommodityIds.add(c.name);  // auto-select new commodities
    }
  }
  // Remove commodities that no longer exist in backend
  const validNames = new Set(list.map(c => c.name));
  for (const id of Object.keys(commodities)) {
    if (!validNames.has(id)) {
      delete commodities[id];
      selectedCommodityIds.delete(id);
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

  if (view === "commodities") {
    renderCommodityFilters();
    renderLatestEvents();
    renderCommodities();
  }
  if (view === "streams") {
    renderStreamFilters();
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

async function startDemo() {
  await loadCommodities();
  isDemoMode = true;
  showApp("streams");
  setStatus("Demo Mode", "status-demo");
  connect("/api/demo");
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
    let expand = total > 3
      ? `<span class="expand-link" onclick="toggleStreamSignals('${escapeHtml(id)}')">Show all ${total} signals &darr;</span><div id="stream-all-${escapeHtml(id)}" class="hidden">${s.signals.slice().reverse().map(sig => renderSignalItem(sig)).join("")}</div>`
      : "";

    const card = document.createElement("div");
    card.className = "stream-card";
    card.id = `stream-card-${id}`;
    const urlHref = s.url && (s.url.startsWith("http") || s.url.startsWith("rtmp")) ? s.url : null;
    const urlHtml = urlHref
      ? `<a class="stream-url" href="${escapeHtml(urlHref)}" target="_blank" rel="noopener">${escapeHtml(s.url)}</a>`
      : `<span class="stream-url">${escapeHtml(s.url || "")}</span>`;
    const stopBtnLabel = s.stopped ? "Resume Transcript" : "Stop Transcript";
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
      <div class="stream-transcript" id="transcript-${escapeHtml(id)}">${escapeHtml(s.transcript) || '<span style="color:#8b949e">Waiting for transcript...</span>'}</div>
      <div class="stream-signals">${signalsHtml || '<span style="color:#8b949e;font-size:0.8rem">No signals yet</span>'}${expand}</div>`;
    container.appendChild(card);
  }
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
  const name = prompt("Commodity ID (snake_case, e.g. 'lithium'):");
  if (!name) return;
  const display = prompt("Display name (e.g. 'Lithium'):");
  if (!display) return;
  const keywords = prompt("Keywords for detection (comma-separated, e.g. 'lithium, battery metal, ev battery'):") || "";
  const ticker = prompt("Yahoo Finance ticker (optional, e.g. 'LIT' for lithium ETF):") || "";
  saveCommodity(name, display, keywords, ticker);
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
    alert(`Added "${data.display_name}". LLM prompts and mock analyzer will now detect this commodity.`);
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
    let expand = total > 3
      ? `<span class="expand-link" onclick="toggleCommodity('${id}')">Show all ${total} events &darr;</span><div id="commodity-all-${id}" class="hidden">${c.events.slice().reverse().map(e => renderSignalItem(e)).join("")}</div>`
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

    const ts = Date.now();
    for (const sig of scoring.signals) {
      sig._time = new Date().toLocaleTimeString();
      sig._timestamp = ts;

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

// ===== START =====
init();
