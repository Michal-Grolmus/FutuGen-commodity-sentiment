// ===== STATE =====
let chunksCount = 0, signalsCount = 0, reconnectDelay = 1000;
let currentSource = null, isDemoMode = false;
let activeSSE = null;  // track active EventSource to prevent loops
let sentimentCounts = { bullish: 0, bearish: 0, neutral: 0 };

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
  if (!text) return "";
  const d = document.createElement("div"); d.textContent = text; return d.innerHTML;
}

// ===== ONBOARDING =====
function showOnboarding() {
  // Close any active SSE
  if (activeSSE) { activeSSE.close(); activeSSE = null; }
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
  if (!key) return;
  alert(
    "To use a live API key:\n\n" +
    "1. Create a .env file in the project root\n" +
    "2. Add: ANTHROPIC_API_KEY=" + key.substring(0, 10) + "...\n" +
    "3. Restart the server\n\n" +
    "For now, click 'Start Demo' to see the system in action."
  );
}

function startDemo() {
  isDemoMode = true;
  // Reset state
  chunksCount = 0; signalsCount = 0;
  sentimentCounts = { bullish: 0, bearish: 0, neutral: 0 };
  showDashboard();
  document.getElementById("signals-list").innerHTML = "";
  document.getElementById("transcript-text").innerHTML = "";
  const status = document.getElementById("stat-status");
  status.textContent = "Demo Mode";
  status.className = "status-demo";
  connect("/api/demo");
}

// ===== SSE CONNECTION =====
function connect(endpoint) {
  if (activeSSE) activeSSE.close();
  const source = new EventSource(endpoint);
  activeSSE = source;
  const status = document.getElementById("stat-status");

  source.onopen = () => {
    if (!isDemoMode) { status.textContent = "Connected"; status.className = "status-connected"; }
    reconnectDelay = 1000;
  };

  source.onerror = () => {
    if (isDemoMode) {
      status.textContent = "Demo Complete";
      status.className = "status-demo";
      source.close();
      activeSSE = null;
      return;
    }
    status.textContent = "Reconnecting..."; status.className = "status-error";
    source.close(); activeSSE = null;
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
      addSignalCard(signal);
      updateHeatmapCell(signal);
      updateSentiment(signal.direction);
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
function addSignalCard(signal) {
  const list = document.getElementById("signals-list");
  const card = document.createElement("div");
  card.className = `signal-card ${signal.direction}`;
  const time = new Date().toLocaleTimeString();
  const confPct = Math.round(signal.confidence * 100);
  card.innerHTML = `
    <div class="signal-header">
      <span class="signal-commodity">${escapeHtml(signal.display_name)}</span>
      <span class="signal-direction ${signal.direction}">${signal.direction.toUpperCase()}</span>
    </div>
    <div class="signal-meta">
      <span>${time}</span>
      <span>Conf: ${confPct}%
        <span class="confidence-bar"><span class="confidence-fill" style="width:${confPct}%"></span></span>
      </span>
      <span>${(signal.timeframe || "").replace("_", " ")}</span>
    </div>
    <div class="signal-rationale">${escapeHtml(signal.rationale)}</div>`;
  list.prepend(card);
  while (list.children.length > 30) list.removeChild(list.lastChild);
}

// ===== SENTIMENT SUMMARY =====
function updateSentiment(direction) {
  sentimentCounts[direction] = (sentimentCounts[direction] || 0) + 1;
  const total = sentimentCounts.bullish + sentimentCounts.bearish + sentimentCounts.neutral;
  if (total === 0) return;
  const bPct = (sentimentCounts.bullish / total * 100);
  const nPct = (sentimentCounts.neutral / total * 100);
  const ePct = (sentimentCounts.bearish / total * 100);
  const bEl = document.getElementById("sent-bullish");
  const nEl = document.getElementById("sent-neutral");
  const eEl = document.getElementById("sent-bearish");
  bEl.style.width = bPct + "%";
  nEl.style.width = nPct + "%";
  eEl.style.width = ePct + "%";
  bEl.querySelector("span").textContent = bPct >= 15 ? `Bullish ${Math.round(bPct)}%` : "";
  nEl.querySelector("span").textContent = nPct >= 15 ? `Neutral ${Math.round(nPct)}%` : "";
  eEl.querySelector("span").textContent = ePct >= 15 ? `Bearish ${Math.round(ePct)}%` : "";
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
  const stt = stats.avg_stt_latency_ms;
  const ext = stats.avg_extraction_latency_ms;
  const scr = stats.avg_scoring_latency_ms;
  if (stt) document.getElementById("lat-stt").textContent = `STT: ${Math.round(stt)}ms`;
  if (ext) document.getElementById("lat-extract").textContent = `Extract: ${Math.round(ext)}ms`;
  if (scr) document.getElementById("lat-score").textContent = `Score: ${Math.round(scr)}ms`;
  const chunks = stats.chunks_processed || 0;
  if (chunks > 0)
    document.getElementById("lat-throughput").textContent = `${chunks} chunks processed`;
}

setInterval(pollStats, 5000);

// ===== START =====
init();
