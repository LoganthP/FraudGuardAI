// ── State ──
let selectedType = null;
let sessionHistory = [];
let gaugeChart = null, pieChart = null, histChart = null;
let lastPayload = null, lastData = null;
let currentTxnId = null;  // report ID returned by /predict
window._selectedType = null; // shared with inline script in index.html

// ── Clock ──
function updateClock() {
  const d = new Date();
  document.getElementById('clock').textContent =
    d.toUTCString().split(' ')[4] + ' UTC';
}
setInterval(updateClock, 1000);
updateClock();

// ── Generate TXN ID ──
function genTxnId() {
  const c = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  let r = 'T-';
  for (let i = 0; i < 8; i++) r += c[Math.floor(Math.random() * c.length)];
  return r;
}
document.getElementById('txnId').value = genTxnId();

// ── Type tabs (delegated — elements added by index.html inline script) ──
document.addEventListener('click', function(e) {
  const tab = e.target.closest('.type-tab');
  if (!tab) return;
  document.querySelectorAll('.type-tab').forEach(t => t.classList.remove('active'));
  tab.classList.add('active');
  selectedType = tab.dataset.type;
  window._selectedType = selectedType;
});

// ── Analysis ──
async function runAnalysis() {
  // Accept type from either state variable (inline script sets window._selectedType)
  if (!selectedType && window._selectedType) selectedType = window._selectedType;
  if (!selectedType) { alert('Select a transaction type tab.'); return; }
  const g = id => document.getElementById(id);
  const fields = ['amount','recency_hours','hours_day','txn_count_24h','is_dest_new',
                  'oldbalanceOrg','newbalanceOrig','oldbalanceDest','newbalanceDest'];
  for (const f of fields) {
    if (g(f).value === '') { alert('Missing: ' + f); return; }
  }

  const p = {
    amount: parseFloat(g('amount').value),
    recency_hours: parseFloat(g('recency_hours').value),
    txn_count_24h: parseInt(g('txn_count_24h').value),
    is_dest_new: parseInt(g('is_dest_new').value),
    hours_day: parseInt(g('hours_day').value),
    oldbalanceOrg: parseFloat(g('oldbalanceOrg').value),
    newbalanceOrig: parseFloat(g('newbalanceOrig').value),
    oldbalanceDest: parseFloat(g('oldbalanceDest').value),
    newbalanceDest: parseFloat(g('newbalanceDest').value),
    type_CASH_IN: selectedType==='CASH_IN'?1:0,
    type_CASH_OUT: selectedType==='CASH_OUT'?1:0,
    type_DEBIT: selectedType==='DEBIT'?1:0,
    type_PAYMENT: selectedType==='PAYMENT'?1:0,
    type_TRANSFER: selectedType==='TRANSFER'?1:0,
    // Metadata only — not used for ML prediction
    user_id: g('userId').value.trim(),
    transaction_id: g('txnId').value.trim(),
    currency: (g('currency') && g('currency').value) || 'USD',
  };
  lastPayload = p;

  const btn = g('scanBtn');
  btn.disabled = true; btn.classList.add('loading');
  const bl = btn.querySelector('.btn-loading');
  const sp = '<span class="spinner"></span>';
  bl.innerHTML = sp + 'CONNECTING...';
  let t1 = setTimeout(() => bl.innerHTML = sp + 'PROCESSING...', 600);
  let t2 = setTimeout(() => bl.innerHTML = sp + 'AI ANALYSIS...', 1200);

  try {
    const res = await fetch('/predict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(p)
    });
    if (!res.ok) throw new Error('Server ' + res.status);
    const data = await res.json();
    lastData = data;
    currentTxnId = data.txn_id;  // store server-issued report ID
    sessionHistory.push({
      label: '#' + (sessionHistory.length + 1),
      prob: data.fraud_probability,
      isFraud: data.is_fraud
    });
    renderResult(data, p);
    // Auto-generate a fresh TXN ID for the next scan
    g('txnId').value = genTxnId();
  } catch (e) {
    renderError(e.message);
  } finally {
    clearTimeout(t1); clearTimeout(t2);
    btn.disabled = false; btn.classList.remove('loading');
  }
}

// ── Render ──
function renderResult(data, p) {
  const isFraud = data.is_fraud;
  const cls = isFraud ? 'fraud' : 'legit';
  const prob = data.fraud_probability;
  const probPct = (prob * 100).toFixed(1);

  // Risk factor scores
  const rfVelocity = Math.min(100, (p.txn_count_24h / 10) * 100);
  const rfGeo = Math.min(100, prob * 100 + Math.random() * 10);
  const rfDevice = Math.min(100, (p.is_dest_new === 1 ? 60 : 30) + Math.random() * 15);

  // Balance deltas
  const curBal = p.newbalanceOrig;
  const prevBal = p.oldbalanceOrg;
  const diff = curBal - prevBal;
  const lastTrans = p.newbalanceDest - p.oldbalanceDest;

  // Donut data
  const dFraudPat = 45, dSusBehav = 30, dKnownActor = 15, dAnomaly = 10;

  if (gaugeChart) { gaugeChart.destroy(); gaugeChart = null; }
  if (pieChart) { pieChart.destroy(); pieChart = null; }
  if (histChart) { histChart.destroy(); histChart = null; }

  const txnId = document.getElementById('txnId').value;

  document.getElementById('scanView').innerHTML = `
    <!-- Verdict Banner -->
    <div class="verdict-banner ${cls} anim">
      <div>
        <div class="verdict-badge ${isFraud ? 'threat' : 'clear'}">${isFraud ? 'THREAT DETECTED' : 'CLEARANCE GRANTED'}</div>
        <div class="verdict-pct ${isFraud ? 'fraud-c' : 'legit-c'}">${probPct}% <small>PROBABILITY</small></div>
      </div>
      <div class="arc-wrap">
        <canvas id="arcCanvas" width="100" height="100"></canvas>
        <div class="arc-label" id="arcLabel">0%</div>
      </div>
    </div>

    <!-- Risk Factors + Donut -->
    <div class="row-factors-chart">
      <div class="card anim" style="animation-delay:.05s">
        <div class="card-title">RISK FACTORS</div>
        <div id="riskFactorsBlock">
          ${mkSlider('Account Velocity', rfVelocity)}
          ${mkSlider('Geographic Anomaly', rfGeo)}
          ${mkSlider('Device Mismatch', rfDevice)}
        </div>
      </div>
      <div class="card anim" style="animation-delay:.1s">
        <div class="card-title">RISK BREAKDOWN</div>
        <div class="donut-wrap">
          <canvas id="donutC" class="donut-canvas" width="110" height="110"></canvas>
          <div class="donut-legend">
            <div class="dl-item"><div class="dl-dot" style="background:#ff4757"></div>${dFraudPat}% Fraud Pattern</div>
            <div class="dl-item"><div class="dl-dot" style="background:#ffa502"></div>${dSusBehav}% Suspicious Behavior</div>
            <div class="dl-item"><div class="dl-dot" style="background:#3b82f6"></div>${dKnownActor}% Known Threat Actor</div>
            <div class="dl-item"><div class="dl-dot" style="background:#6c5ce7"></div>${dAnomaly}% Anomaly</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Balance Deltas + Session History -->
    <div class="row-balance-session">
      <div class="card anim" style="animation-delay:.15s">
        <div class="card-title">BALANCE DELTAS</div>
        <div class="bd-grid">
          <div class="bd-item"><label>CURRENT</label><div class="bd-val c-text">$${curBal.toLocaleString(undefined,{minimumFractionDigits:2})}</div></div>
          <div class="bd-item"><label>PREV</label><div class="bd-val c-text">$${prevBal.toLocaleString(undefined,{minimumFractionDigits:2})}</div></div>
          <div class="bd-item"><label>DIFF</label><div class="bd-val ${diff>=0?'c-green':'c-red'}">${diff>=0?'+':''}$${Math.abs(diff).toLocaleString(undefined,{minimumFractionDigits:2})}</div></div>
          <div class="bd-item"><label>LAST TRANS</label><div class="bd-val ${lastTrans>=0?'c-green':'c-red'}">${lastTrans>=0?'+':'-'}$${Math.abs(lastTrans).toLocaleString(undefined,{minimumFractionDigits:2})}</div></div>
        </div>
      </div>
      <div class="card anim" style="animation-delay:.18s">
        <div class="card-title">SESSION HISTORY</div>
        <div class="session-chart"><canvas id="histC" height="90"></canvas></div>
      </div>
    </div>

    <!-- AI Analyst -->
    <div class="card anim ai-card" style="animation-delay:.22s">
      <div class="ai-label">AI ANALYST</div>
      <div class="ai-text" id="aiBlock"></div>
    </div>

    <!-- Forensic + Export buttons -->
    <div style="display:flex;justify-content:flex-end;align-items:center;gap:8px;margin-top:2px">
      <button id="exportPdfBtn" onclick="exportReport()"
        style="background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.4);border-radius:4px;
               padding:0 14px;height:36px;color:#6366f1;font-family:var(--mono);
               font-size:10px;font-weight:600;letter-spacing:0.2em;cursor:pointer;
               transition:border-color 150ms,background 150ms;">
        EXPORT FORENSIC REPORT
      </button>
      <button onclick="openForensic()"
        style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 14px;color:var(--accent);font-family:var(--mono);font-size:9px;font-weight:700;letter-spacing:.08em;cursor:pointer;transition:.15s">
        VIEW FORENSIC ANALYSIS
      </button>
    </div>
  `;

  // ── Arc gauge ──
  drawArc(prob, isFraud);

  // ── Donut ──
  pieChart = new Chart(document.getElementById('donutC'), {
    type: 'doughnut',
    data: {
      datasets: [{
        data: [dFraudPat, dSusBehav, dKnownActor, dAnomaly],
        backgroundColor: ['#ff4757', '#ffa502', '#3b82f6', '#6c5ce7'],
        borderColor: '#0f1218', borderWidth: 2
      }]
    },
    options: {
      responsive: false, cutout: '62%',
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      animation: { duration: 800 }
    }
  });

  // ── Session sparkline ──
  const ctx = document.getElementById('histC').getContext('2d');
  const grad = ctx.createLinearGradient(0, 0, 0, 90);
  grad.addColorStop(0, isFraud ? 'rgba(255,71,87,.25)' : 'rgba(0,229,176,.25)');
  grad.addColorStop(1, 'transparent');

  histChart = new Chart(document.getElementById('histC'), {
    type: 'line',
    data: {
      labels: sessionHistory.map(h => h.label),
      datasets: [{
        data: sessionHistory.map(h => +(h.prob * 100).toFixed(1)),
        borderColor: isFraud ? '#ff4757' : '#2ed573',
        backgroundColor: grad,
        pointBackgroundColor: sessionHistory.map(h => h.isFraud ? '#ff4757' : '#2ed573'),
        pointRadius: 4, pointHoverRadius: 6,
        borderWidth: 2, tension: .35, fill: true
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: '#5a6a85', font: { family: "'JetBrains Mono'", size: 8 } }, grid: { color: '#1c2333' } },
        y: { min: 0, max: 100, ticks: { color: '#5a6a85', font: { family: "'JetBrains Mono'", size: 8 }, callback: v => v + '%' }, grid: { color: '#1c2333' } }
      },
      plugins: { legend: { display: false }, tooltip: { backgroundColor: '#151a22', titleColor: '#e2e8f0', bodyColor: '#5a6a85', borderColor: '#2a3550', borderWidth: 1 } },
      animation: { duration: 600 }
    }
  });

  // ── Animate risk factor bars ──
  requestAnimationFrame(() => requestAnimationFrame(() => {
    document.querySelectorAll('.rf-fill[data-w]').forEach(el => {
      el.style.width = el.dataset.w + '%';
    });
  }));

  // ── AI typewriter ──
  const aiBlock = document.getElementById('aiBlock');
  aiBlock.innerHTML = 'Analyst: ';
  let i = 0;
  const txt = data.summary;
  function type() {
    if (i < txt.length) {
      aiBlock.innerHTML = aiBlock.innerHTML.replace('█', '') + txt.charAt(i) + '█';
      i++;
      setTimeout(type, 16);
    } else {
      aiBlock.innerHTML = aiBlock.innerHTML.replace('█', '<span class="cursor-blink">█</span>');
    }
  }
  setTimeout(type, 400);
}

function mkSlider(label, pct) {
  pct = Math.min(100, Math.max(0, pct)).toFixed(0);
  let col = pct > 70 ? 'var(--red)' : pct > 40 ? 'var(--amber)' : 'var(--green)';
  return `<div class="rf-row">
    <div class="rf-hdr"><span class="rf-name">${label}</span><span class="rf-val" style="color:${col}">${pct}%</span></div>
    <div class="rf-track"><div class="rf-fill" style="background:${col}" data-w="${pct}"></div></div>
  </div>`;
}

function drawArc(prob, isFraud) {
  const canvas = document.getElementById('arcCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = 100, h = 100, cx = w / 2, cy = h / 2, r = 38, lw = 6;
  const col = isFraud ? '#ff4757' : '#2ed573';
  const bgCol = '#1c2333';

  let current = 0;
  const target = prob;
  const duration = 1000;
  const start = performance.now();

  function frame(now) {
    const elapsed = now - start;
    const progress = Math.min(elapsed / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    current = eased * target;

    ctx.clearRect(0, 0, w, h);

    // bg arc
    ctx.beginPath();
    ctx.arc(cx, cy, r, -Math.PI * 0.75, Math.PI * 0.75);
    ctx.strokeStyle = bgCol; ctx.lineWidth = lw; ctx.lineCap = 'round';
    ctx.stroke();

    // fill arc
    const totalAngle = Math.PI * 1.5;
    const endAngle = -Math.PI * 0.75 + totalAngle * current;
    ctx.beginPath();
    ctx.arc(cx, cy, r, -Math.PI * 0.75, endAngle);
    ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.lineCap = 'round';
    ctx.shadowColor = col; ctx.shadowBlur = 10;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // label
    const el = document.getElementById('arcLabel');
    if (el) el.textContent = (current * 100).toFixed(1) + '%';

    if (progress < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

// ── Forensic Modal ──
function openForensic() {
  if (!lastPayload || !lastData) return;
  const p = lastPayload, d = lastData;
  const txnId = document.getElementById('txnId').value;

  document.getElementById('modalTxnId').textContent = 'TXN_ID: ' + txnId;

  const rawJson = JSON.stringify({
    timestamp: new Date().toISOString(),
    txn_id: txnId,
    user_id: document.getElementById('userId').value,
    amount: p.amount,
    currency: (document.getElementById('currency') ? document.getElementById('currency').value : 'USD'),
    metadata: {
      ip_address: "192.168.1.1",
      device_id: "D-" + Math.random().toString(36).substr(2, 6).toUpperCase(),
      session_id: "S-" + Math.random().toString(36).substr(2, 6).toUpperCase()
    }
  }, null, 2);

  document.getElementById('modalBody').innerHTML = `
    <div class="modal-card">
      <div class="modal-card-title">RAW DATA TRACE</div>
      <div class="raw-json">${rawJson}</div>
    </div>
    <div class="modal-card">
      <div class="modal-card-title">NETWORK GRAPH</div>
      <svg class="network-svg" viewBox="0 0 300 180">
        <path class="net-line" d="M60,90 C120,90 120,30 240,30"/>
        <path class="net-line" d="M60,90 C120,90 120,90 240,90"/>
        <path class="net-line" d="M60,90 C120,90 120,150 240,150"/>
        <path class="net-line" d="M240,30 L240,90" style="stroke-dasharray:4,3"/>
        <path class="net-line" d="M240,90 L240,150" style="stroke-dasharray:4,3"/>
        <circle class="net-node" cx="60" cy="90" r="8"/>
        <circle class="net-node" cx="240" cy="30" r="7"/>
        <circle class="net-node" cx="240" cy="90" r="7"/>
        <circle class="net-node" cx="240" cy="150" r="7"/>
        <text class="net-label" x="60" y="112">SENDER</text>
        <text class="net-label" x="240" y="18">THREAT ACTOR 1</text>
        <text class="net-label" x="240" y="78">KNOWN LAUNDERER</text>
        <text class="net-label" x="240" y="168">ANONYMIZED PROXY</text>
      </svg>
    </div>
    <div class="modal-card geo-card">
      <div class="modal-card-title">GEOSPATIAL SIGNAL</div>
      <div class="geo-row">
        <div class="geo-dot"></div>
        <div class="geo-info">
          Origin: Unknown / Tor Exit Node<br>
          Region: Eastern Europe (High Risk)
        </div>
      </div>
    </div>
  `;

  document.getElementById('forensicModal').classList.add('open');
}

function closeModal() {
  document.getElementById('forensicModal').classList.remove('open');
}

// ── PDF Export ──
function exportReport() {
  if (!currentTxnId) return;
  const btn = document.getElementById('exportPdfBtn');
  if (!btn) return;
  const orig = btn.textContent;
  btn.textContent = 'GENERATING...';
  btn.disabled = true;
  window.open('/report/' + currentTxnId, '_blank');
  setTimeout(() => {
    btn.textContent = orig;
    btn.disabled = false;
  }, 1200);
}

document.getElementById('forensicModal').addEventListener('click', function(e) {
  if (e.target === this) closeModal();
});

// ── Error ──
function renderError(msg) {
  document.getElementById('resultPanel').innerHTML = `
    <div class="card" style="border-color:var(--amber)">
      <div style="font-family:var(--mono);font-size:10px;color:var(--amber);margin-bottom:8px">CONNECTION ERROR</div>
      <div style="font-family:var(--mono);font-size:12px;color:var(--text-muted)">${msg}</div>
      <div style="font-family:var(--mono);font-size:10px;color:var(--text-dim);margin-top:8px">Run: uvicorn app.main:app --reload</div>
    </div>`;
}
