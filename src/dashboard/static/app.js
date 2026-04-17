// ===== STATE =====
let chunksCount = 0, signalsCount = 0, reconnectDelay = 1000;
let currentSource = null, isDemoMode = false;

const ALL_COMMODITIES = [
  "crude_oil_wti", "crude_oil_brent", "natural_gas", "gold",
  "silver", "wheat", "corn", "copper"
];
const COMMODITY_NAMES = {
  crude_oil_wti: "WTI", crude_oil_brent: "Brent", natural_gas: "Nat Gas",
  gold: "Gold", silver: "Silver", wheat: "Wheat", corn: "Corn", copper: "Copper"
};

// ===== INIT =====
async function init() {
  const config = await fetchJSON("/api/config");
  if (!config.has_api_key && !config.input_source) {
    showOnboarding();
  } else {
    showDashboard();
    connect("/api/events");
  }
}

async function fetchJSON(url) {
  try { const r = await fetch(url); return await r.json(); }
  catch { return {}; }
}

function escapeHtml(text) {
  const d = document.createElement("div"); d.textContent = text; return d.innerHTML;
}

// ===== ONBOARDING =====
function showOnboarding() {
  document.getElementById("onboarding").classList.remove("hidden");
  document.getElementById("dashboard").classList.add("hidden");
  loadStreams();
}

function showDashboard() {
  document.getElementById("onboarding").classList.add("hidden");
  document.getElementById("dashboard").classList.remove("hidden");
  initHeatmap();
  loadPrices();
}

async function loadStreams() {
  const streams = await fetchJSON("/api/streams");
  const picker = document.getElementById("stream-picker");
  if (!picker || !streams.length) return;
  picker.innerHTML = "";
  for (const s of streams) {
    const div = document.createElement("div");
    div.className = "stream-option";
    div.innerHTML = `<span class="name">${escapeHtml(s.name)}</span>
      <span class="type-badge ${s.type}">${s.type}</span>
      <div class="desc">${escapeHtml(s.description)}</div>`;
    div.onclick = () => {
      document.querySelectorAll(".stream-option").forEach(el => el.classList.remove("selected"));
      div.classList.add("selected");
      currentSource = s;
    };
    picker.appendChild(div);
  }
}

function saveApiKey() {
  const key = document.getElementById("api-key-input").value.trim();
  if (!key) return alert("Please enter an API key");
  // In a real app this would POST to server. For demo, show dashboard.
  alert("API key would be saved server-side. For now, set ANTHROPIC_API_KEY in .env and restart.");
}

function startDemo() {
  isDemoMode = true;
  showDashboard();
  const status = document.getElementById("stat-status");
  status.textContent = "Demo Mode";
  status.className = "status-demo";
  connect("/api/demo");
}

// ===== SSE CONNECTION =====
function connect(endpoint) {
  const source = new EventSource(endpoint);
  const status = document.getElementById("stat-status");

  source.onopen = () => {
    if (!isDemoMode) { status.textContent = "Connected"; status.className = "status-connected"; }
    reconnectDelay = 1000;
  };

  source.onerror = () => {
    if (isDemoMode) { status.textContent = "Demo Complete"; return; }
    status.textContent = "Reconnecting..."; status.className = "status-error";
    source.close();
    setTimeout(() => connect(endpoint), reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  };

  source.addEventListener("signal", (e) => {
    const event = JSON.parse(e.data);
    const scoring = event.scoring;
    if (!scoring) return;
    chunksCount++;
    document.getElementById("stat-chunks").textContent = `Chunks: ${chunksCount}`;
    for (const signal of scoring.signals) {
      signalsCount++;
      document.getElementById("stat-signals").textContent = `Signals: ${signalsCount}`;
      addSignalCard(signal, event.timestamp);
      updateHeatmapCell(signal);
    }
  });

  source.addEventListener("transcript", (e) => {
    const event = JSON.parse(e.data);
    if (event.transcript) addTranscript(event.transcript);
  });

  source.addEventListener("extraction", (e) => {
    const event = JSON.parse(e.data);
    if (event.extraction) addExtraction(event.extraction);
  });

  source.addEventListener("keepalive", () => {});
}

// ===== SIGNAL CARDS =====
function addSignalCard(signal, timestamp) {
  const list = document.getElementById("signals-list");
  const card = document.createElement("div");
  card.className = `signal-card ${signal.direction}`;
  const time = timestamp ? new Date(timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
  const confPct = Math.round(signal.confidence * 100);
  card.innerHTML = `
    <div class="signal-header">
      <span class="signal-commodity">${escapeHtml(signal.display_name)}</span>
      <span class="signal-direction ${signal.direction}">${escapeHtml(signal.direction)}</span>
    </div>
    <div class="signal-meta">
      <span>${time}</span>
      <span>Conf: ${confPct}% <span class="confidence-bar"><span class="confidence-fill" style="width:${confPct}%"></span></span></span>
      <span>${escapeHtml((signal.timeframe || "").replace("_", " "))}</span>
    </div>
    <div class="signal-rationale">${escapeHtml(signal.rationale)}</div>`;
  list.prepend(card);
  while (list.children.length > 40) list.removeChild(list.lastChild);
}

// ===== TRANSCRIPT =====
function addTranscript(t) {
  const el = document.getElementById("transcript-text");
  const div = document.createElement("div");
  div.className = "transcript-chunk";
  div.innerHTML = `<div class="transcript-time">${escapeHtml(t.chunk_id)} [${escapeHtml(t.language)}]</div>
    <div>${escapeHtml(t.full_text)}</div>`;
  el.prepend(div);
  while (el.children.length > 20) el.removeChild(el.lastChild);
}

function addExtraction(ext) {
  if (!ext.commodities || ext.commodities.length === 0) return;
  const el = document.getElementById("transcript-text");
  const parts = [];
  if (ext.commodities.length) parts.push("Commodities: " + ext.commodities.map(c => c.display_name).join(", "));
  if (ext.people && ext.people.length) parts.push("People: " + ext.people.map(p => p.name).join(", "));
  const div = document.createElement("div");
  div.className = "transcript-chunk";
  div.innerHTML = `<div class="transcript-time">Entities [${escapeHtml(ext.chunk_id)}]</div>
    <div>${escapeHtml(parts.join(" | "))}</div>`;
  el.prepend(div);
}

// ===== HEATMAP =====
function initHeatmap() {
  const hm = document.getElementById("heatmap");
  if (!hm) return;
  hm.innerHTML = "";
  for (const c of ALL_COMMODITIES) {
    const cell = document.createElement("div");
    cell.className = "heatmap-cell empty";
    cell.id = `hm-${c}`;
    cell.innerHTML = `<div class="name">${COMMODITY_NAMES[c]}</div><div class="conf">--</div>`;
    hm.appendChild(cell);
  }
}

function updateHeatmapCell(signal) {
  const cell = document.getElementById(`hm-${signal.commodity}`);
  if (!cell) return;
  const conf = Math.round(signal.confidence * 100);
  const dir = signal.direction;
  let cls = "empty";
  if (dir === "bullish") cls = signal.confidence > 0.7 ? "bullish-strong" : "bullish-weak";
  else if (dir === "bearish") cls = signal.confidence > 0.7 ? "bearish-strong" : "bearish-weak";
  else cls = "neutral";
  cell.className = `heatmap-cell ${cls}`;
  cell.querySelector(".conf").textContent = `${conf}%`;
}

// ===== PRICES =====
async function loadPrices() {
  const grid = document.getElementById("prices-grid");
  if (!grid) return;
  grid.innerHTML = "<div style='color:#8b949e;font-size:0.8rem;grid-column:1/-1'>Loading prices...</div>";

  const prices = await fetchJSON("/api/prices");
  if (!prices || !Object.keys(prices).length) {
    grid.innerHTML = "<div style='color:#484f58;font-size:0.8rem;grid-column:1/-1'>Price data unavailable</div>";
    return;
  }
  grid.innerHTML = "";
  for (const [commodity, data] of Object.entries(prices)) {
    const card = document.createElement("div");
    card.className = "price-card";
    const changeDir = (data.change_24h || 0) >= 0 ? "up" : "down";
    const changeSign = changeDir === "up" ? "+" : "";
    const changeVal = data.change_24h != null ? `${changeSign}${data.change_24h.toFixed(2)}` : "--";
    card.innerHTML = `
      <div class="commodity-name">${escapeHtml(data.display_name)}</div>
      <div class="price-value">$${data.price.toFixed(2)}</div>
      <div class="price-change ${changeDir}">${changeVal} (24h)</div>
      <svg id="spark-${commodity}" viewBox="0 0 100 30" preserveAspectRatio="none"></svg>`;
    grid.appendChild(card);
    loadSparkline(commodity, changeDir);
  }
}

async function loadSparkline(commodity, direction) {
  const data = await fetchJSON(`/api/prices/${commodity}`);
  const svg = document.getElementById(`spark-${commodity}`);
  if (!svg || !data.history || data.history.length < 2) return;
  const prices = data.history.map(h => h.close);
  const min = Math.min(...prices), max = Math.max(...prices);
  const range = max - min || 1;
  const points = prices.map((p, i) =>
    `${(i / (prices.length - 1)) * 100},${30 - ((p - min) / range) * 28}`
  ).join(" ");
  svg.innerHTML = `<polyline class="sparkline ${direction}" points="${points}"/>`;
}

// ===== LATENCY MONITOR =====
async function pollStats() {
  const stats = await fetchJSON("/api/stats");
  if (stats.total_cost_usd != null)
    document.getElementById("stat-cost").textContent = `Cost: $${stats.total_cost_usd.toFixed(4)}`;
  if (stats.avg_stt_latency_ms != null)
    document.getElementById("lat-stt").textContent = `STT: ${Math.round(stats.avg_stt_latency_ms)}ms`;
  if (stats.avg_extraction_latency_ms != null)
    document.getElementById("lat-extract").textContent = `Extract: ${Math.round(stats.avg_extraction_latency_ms)}ms`;
  if (stats.avg_scoring_latency_ms != null)
    document.getElementById("lat-score").textContent = `Score: ${Math.round(stats.avg_scoring_latency_ms)}ms`;
  const chunks = stats.chunks_processed || 0;
  if (chunks > 0)
    document.getElementById("lat-throughput").textContent = `Throughput: ~${chunks}/session`;
}

setInterval(pollStats, 5000);

// ===== START =====
init();
