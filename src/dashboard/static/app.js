const signalsList = document.getElementById("signals-list");
const transcriptText = document.getElementById("transcript-text");
const statChunks = document.getElementById("stat-chunks");
const statSignals = document.getElementById("stat-signals");
const statCost = document.getElementById("stat-cost");
const statStatus = document.getElementById("stat-status");

let chunksCount = 0;
let signalsCount = 0;
let reconnectDelay = 1000;

function connect() {
  const source = new EventSource("/api/events");

  source.onopen = () => {
    statStatus.textContent = "Connected";
    statStatus.className = "status-connected";
    reconnectDelay = 1000; // reset on success
  };

  source.onerror = () => {
    statStatus.textContent = "Reconnecting...";
    statStatus.className = "status-error";
    source.close();
    // Exponential backoff reconnection (max 30s)
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  };

  source.addEventListener("signal", (e) => {
    const event = JSON.parse(e.data);
    const scoring = event.scoring;
    if (!scoring) return;

    chunksCount++;
    statChunks.textContent = `Chunks: ${chunksCount}`;

    for (const signal of scoring.signals) {
      signalsCount++;
      statSignals.textContent = `Signals: ${signalsCount}`;
      addSignalCard(signal, event.timestamp);
    }
  });

  source.addEventListener("extraction", (e) => {
    const event = JSON.parse(e.data);
    const extraction = event.extraction;
    if (!extraction) return;
    addExtraction(extraction);
  });

  source.addEventListener("transcript", (e) => {
    const event = JSON.parse(e.data);
    const transcript = event.transcript;
    if (!transcript) return;
    addTranscript(transcript);
  });

  source.addEventListener("keepalive", () => {});
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function addSignalCard(signal, timestamp) {
  const card = document.createElement("div");
  card.className = `signal-card ${signal.direction}`;

  const time = new Date(timestamp).toLocaleTimeString();
  const confPct = Math.round(signal.confidence * 100);

  card.innerHTML = `
    <div class="signal-header">
      <span class="signal-commodity">${escapeHtml(signal.display_name)}</span>
      <span class="signal-direction ${signal.direction}">${escapeHtml(signal.direction)}</span>
    </div>
    <div class="signal-meta">
      <span>${time}</span>
      <span>Confidence: ${confPct}%
        <span class="confidence-bar">
          <span class="confidence-fill" style="width:${confPct}%"></span>
        </span>
      </span>
      <span>${escapeHtml(signal.timeframe.replace("_", " "))}</span>
    </div>
    <div class="signal-rationale">${escapeHtml(signal.rationale)}</div>
  `;

  signalsList.prepend(card);

  while (signalsList.children.length > 50) {
    signalsList.removeChild(signalsList.lastChild);
  }
}

function addExtraction(extraction) {
  // Show extraction info in transcript area as context
  if (extraction.commodities.length === 0 && extraction.people.length === 0) return;
  const div = document.createElement("div");
  div.className = "transcript-chunk";
  const parts = [];
  if (extraction.commodities.length) {
    parts.push("Commodities: " + extraction.commodities.map(c => c.display_name).join(", "));
  }
  if (extraction.people.length) {
    parts.push("People: " + extraction.people.map(p => p.name).join(", "));
  }
  if (extraction.indicators.length) {
    parts.push("Indicators: " + extraction.indicators.map(i => i.display_name).join(", "));
  }
  div.innerHTML = `<div class="transcript-time">Entities [${extraction.chunk_id}]</div><div>${escapeHtml(parts.join(" | "))}</div>`;
  transcriptText.prepend(div);
}

function addTranscript(transcript) {
  const div = document.createElement("div");
  div.className = "transcript-chunk";
  div.innerHTML = `
    <div class="transcript-time">Chunk ${escapeHtml(transcript.chunk_id)} [${escapeHtml(transcript.language)}]</div>
    <div>${escapeHtml(transcript.full_text)}</div>
  `;
  transcriptText.prepend(div);

  while (transcriptText.children.length > 30) {
    transcriptText.removeChild(transcriptText.lastChild);
  }
}

async function pollStats() {
  try {
    const res = await fetch("/api/stats");
    const stats = await res.json();
    statCost.textContent = `Cost: $${stats.total_cost_usd.toFixed(4)}`;
  } catch {}
}

setInterval(pollStats, 10000);
connect();
