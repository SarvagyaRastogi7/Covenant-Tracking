"""HTTP API: upload an Excel workbook and run deterministic or shared-state CrewAI flow."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from covenanttrackingphase1.main import run_agents_from_bytes, run_deterministic_from_bytes

app = FastAPI(title="Covenant tracking", version="0.1.0")

_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Covenant analysis</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg: #0f1419;
      --bg-elevated: #1a222d;
      --surface: #222c38;
      --border: #334155;
      --text: #f1f5f9;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --accent-dim: rgba(56, 189, 248, 0.15);
      --success: #34d399;
      --error: #f87171;
      --radius: 14px;
      --font: "DM Sans", ui-sans-serif, system-ui, sans-serif;
      --mono: "JetBrains Mono", ui-monospace, monospace;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: var(--font);
      color: var(--text);
      background: radial-gradient(1200px 600px at 10% -10%, rgba(56, 189, 248, 0.12), transparent),
                  radial-gradient(800px 400px at 100% 0%, rgba(52, 211, 153, 0.06), transparent),
                  var(--bg);
      line-height: 1.55;
    }
    .wrap {
      max-width: min(52rem, calc(100vw - 2rem));
      margin: 0 auto;
      padding: clamp(1.5rem, 4vw, 2.75rem) 1rem 3.5rem;
    }
    h1 {
      font-size: clamp(1.65rem, 4vw, 2rem);
      font-weight: 700;
      letter-spacing: -0.03em;
      margin: 0 0 0.65rem;
      line-height: 1.2;
    }
    .lede {
      color: var(--muted);
      font-size: 1.02rem;
      margin: 0 0 1.75rem;
      max-width: 52ch;
    }
    .card {
      background: linear-gradient(165deg, var(--bg-elevated) 0%, var(--surface) 100%);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.35rem 1.35rem 1.5rem;
      box-shadow: 0 24px 48px -12px rgba(0, 0, 0, 0.45);
    }
    .drop {
      border: 1.5px dashed rgba(148, 163, 184, 0.45);
      border-radius: 12px;
      min-height: 9.5rem;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1.25rem 1.25rem;
      text-align: center;
      transition: border-color 0.2s, background 0.2s;
      cursor: pointer;
      position: relative;
    }
    .drop:hover, .drop:focus-within {
      border-color: var(--accent);
      background: rgba(56, 189, 248, 0.06);
    }
    .drop-inner {
      pointer-events: none;
      position: relative;
      z-index: 1;
      max-width: 26rem;
    }
    .drop strong { display: block; font-size: 0.98rem; margin-bottom: 0.35rem; font-weight: 600; }
    .drop span { font-size: 0.84rem; color: var(--muted); line-height: 1.45; }
    .drop input[type="file"] {
      position: absolute;
      inset: 0;
      opacity: 0;
      cursor: pointer;
      width: 100%;
      height: 100%;
      z-index: 2;
      font-size: 0;
    }
    .file-name {
      margin-top: 0.75rem;
      font-size: 0.82rem;
      color: var(--muted);
      min-height: 1.25rem;
      word-break: break-all;
    }
    .file-name.has-file { color: var(--text); font-weight: 500; }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem 1rem;
      margin-top: 1.2rem;
      align-items: flex-start;
    }
    button[type="submit"] {
      font-family: var(--font);
      font-weight: 600;
      font-size: 0.95rem;
      color: var(--bg);
      background: linear-gradient(180deg, #7dd3fc 0%, var(--accent) 100%);
      border: none;
      padding: 0.65rem 1.35rem;
      border-radius: 10px;
      cursor: pointer;
      box-shadow: 0 4px 14px -2px rgba(56, 189, 248, 0.45);
      transition: transform 0.15s, box-shadow 0.15s;
    }
    button[type="submit"]:hover:not(:disabled) {
      transform: translateY(-1px);
      box-shadow: 0 8px 20px -4px rgba(56, 189, 248, 0.5);
    }
    button[type="submit"]:disabled {
      opacity: 0.55;
      cursor: not-allowed;
      transform: none;
    }
    .hint {
      font-size: 0.8rem;
      color: var(--muted);
      flex: 1 1 12rem;
      line-height: 1.45;
      padding-top: 0.15rem;
    }
    .agent-opt {
      flex: 1 1 100%;
      margin-top: 0.35rem;
      padding: 0.65rem 0.75rem;
      background: rgba(56, 189, 248, 0.06);
      border: 1px solid rgba(56, 189, 248, 0.22);
      border-radius: 10px;
      font-size: 0.88rem;
      color: var(--muted);
      display: flex;
      align-items: flex-start;
      gap: 0.55rem;
      cursor: pointer;
      user-select: none;
    }
    .agent-opt input {
      margin-top: 0.2rem;
      accent-color: var(--accent);
      cursor: pointer;
    }
    .agent-opt strong { color: var(--text); font-weight: 600; }
    .summary-agent-title {
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--accent);
      margin: 0 0 0.4rem;
    }
    .out-wrap {
      margin-top: 1.85rem;
      background: linear-gradient(165deg, var(--bg-elevated) 0%, var(--surface) 100%);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.15rem 1.25rem 1.25rem;
      box-shadow: 0 18px 40px -14px rgba(0, 0, 0, 0.4);
    }
    .out-head {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.45rem 0.6rem;
      margin-bottom: 0.85rem;
      padding-bottom: 0.65rem;
      border-bottom: 1px solid rgba(51, 65, 85, 0.6);
    }
    .out-label {
      font-size: 0.78rem;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--muted);
      margin-right: 0.15rem;
    }
    .pill {
      font-size: 0.72rem;
      font-weight: 600;
      padding: 0.2rem 0.55rem;
      border-radius: 6px;
      display: none;
    }
    .pill.on { display: inline-block; }
    .pill.ok { background: rgba(52, 211, 153, 0.2); color: var(--success); }
    .pill.err { background: rgba(248, 113, 113, 0.18); color: var(--error); }
    .pill.run { background: var(--accent-dim); color: var(--accent); }
    .summary {
      margin-bottom: 1rem;
      padding: 1rem 1.1rem;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #0c1014;
    }
    .summary[hidden] { display: none !important; }
    .summary-ok { border-color: rgba(52, 211, 153, 0.35); }
    .summary-err { border-color: rgba(248, 113, 113, 0.4); }
    .summary-top {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.6rem 0.85rem;
      margin-bottom: 0.85rem;
    }
    .decision-tag {
      font-size: 0.75rem;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      padding: 0.35rem 0.65rem;
      border-radius: 8px;
    }
    .decision-tag.compliant {
      background: rgba(52, 211, 153, 0.2);
      color: var(--success);
    }
    .decision-tag.breach {
      background: rgba(248, 113, 113, 0.22);
      color: var(--error);
    }
    .summary-meta {
      font-size: 0.88rem;
      color: var(--muted);
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr));
      gap: 0.65rem 1.25rem;
      margin: 0;
    }
    .summary-grid dt {
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--muted);
      margin: 0;
    }
    .summary-grid dd {
      margin: 0.15rem 0 0;
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--text);
    }
    .summary-action {
      margin: 0.9rem 0 0;
      padding-top: 0.85rem;
      border-top: 1px solid rgba(51, 65, 85, 0.6);
      font-size: 0.9rem;
      color: var(--muted);
    }
    .summary-action strong { color: var(--text); font-weight: 600; }
    .summary-action ul {
      margin: 0.55rem 0 0.1rem 1rem;
      padding: 0;
    }
    .summary-action li {
      margin: 0.25rem 0;
    }
    .metrics-wrap {
      margin-top: 0.9rem;
      padding-top: 0.85rem;
      border-top: 1px solid rgba(51, 65, 85, 0.6);
    }
    .metrics-title {
      margin: 0 0 0.55rem;
      font-size: 0.9rem;
      font-weight: 600;
      color: var(--text);
    }
    .metrics-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.83rem;
      color: var(--muted);
    }
    .metrics-table th,
    .metrics-table td {
      padding: 0.46rem 0.4rem;
      border-bottom: 1px solid rgba(51, 65, 85, 0.5);
      text-align: left;
      vertical-align: middle;
    }
    .metrics-table th {
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--muted);
      font-weight: 600;
    }
    .metrics-table td.metric-name {
      color: var(--text);
      font-weight: 600;
    }
    .decision-pill {
      display: inline-block;
      font-size: 0.68rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      padding: 0.16rem 0.5rem;
      border-radius: 6px;
      white-space: nowrap;
    }
    .decision-pill.compliant {
      color: var(--success);
      background: rgba(52, 211, 153, 0.2);
    }
    .decision-pill.breach {
      color: var(--error);
      background: rgba(248, 113, 113, 0.2);
    }
    .decision-pill.not_evaluated {
      color: var(--muted);
      background: rgba(148, 163, 184, 0.14);
    }
    .summary-err .summary-err-title {
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--error);
      margin: 0 0 0.35rem;
    }
    .summary-err .summary-err-msg { font-size: 0.88rem; color: var(--muted); margin: 0; line-height: 1.5; }
    .json-details {
      margin: 0;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #0c1014;
      overflow: hidden;
    }
    .json-details > summary {
      font-family: var(--font);
      font-size: 0.82rem;
      font-weight: 600;
      padding: 0.65rem 0.9rem;
      cursor: pointer;
      list-style: none;
      color: var(--muted);
      user-select: none;
    }
    .json-details > summary::-webkit-details-marker { display: none; }
    .json-details > summary::after {
      content: "▸";
      float: right;
      opacity: 0.6;
      transition: transform 0.15s;
    }
    .json-details[open] > summary::after { transform: rotate(90deg); }
    .json-details > summary:hover { color: var(--text); background: rgba(255,255,255,0.03); }
    .json-details pre#out {
      border: none;
      border-radius: 0;
      border-top: 1px solid var(--border);
    }
    pre#out {
      margin: 0;
      font-family: var(--mono);
      font-size: 0.78rem;
      line-height: 1.5;
      background: #0c1014;
      padding: 0.85rem 1rem;
      overflow: auto;
      max-height: min(45vh, 380px);
      color: #cbd5e1;
      white-space: pre-wrap;
      word-break: break-word;
    }
    footer {
      margin-top: 2rem;
      font-size: 0.8rem;
      color: var(--muted);
      text-align: center;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Upload your Financial Document(s):</h1>
    <p class="lede">Input data accepted - Excel Files and PDFs</p>
    <div class="card">
      <form id="f">
        <label class="drop" id="dropLabel">
          <input type="file" name="file" id="fileIn" accept=".xlsx,.pdf,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" required />
          <div class="drop-inner">
            <strong>Choose or drag a spreadsheet</strong>
            <span>Financial_Statement/Covenant_Config or Field/Value layout · accepts .xlsx or labeled .pdf</span>
          </div>
        </label>
        <div class="file-name" id="fileMeta">No file selected</div>
        <div class="actions">
          <button type="submit" id="submitBtn">Run analysis</button>
          <span class="hint"></span>
          <label class="agent-opt">
            <input type="checkbox" id="useAgents" name="use_agents" value="1" />
            <span><strong>Agentic orchestration</strong> — CrewAI agents run in sequence, while payloads move through shared state by <code>run_id</code> (no LLM payload rewrite).</span>
          </label>
        </div>
      </form>
    </div>
    <div class="out-wrap">
      <div class="out-head">
        <span class="out-label">Result</span>
        <span class="pill" id="statusPill" role="status"></span>
      </div>
      <div id="summary" class="summary" hidden></div>
      <details class="json-details" id="jsonDetails" open>
        <summary>Raw JSON</summary>
        <pre id="out">Select a workbook and click “Run analysis” to see the report.</pre>
      </details>
    </div>
  </div>
  <script>
    const form = document.getElementById('f');
    const out = document.getElementById('out');
    const summaryEl = document.getElementById('summary');
    const jsonDetails = document.getElementById('jsonDetails');
    const fileIn = document.getElementById('fileIn');
    const fileMeta = document.getElementById('fileMeta');
    const submitBtn = document.getElementById('submitBtn');
    const pill = document.getElementById('statusPill');

    function escapeHtml(s) {
      return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    function setPill(kind, text) {
      pill.className = 'pill on ' + (kind || '');
      pill.textContent = text || '';
      if (!text) pill.className = 'pill';
    }

    function renderSummary(data) {
      summaryEl.innerHTML = '';
      if (!data || typeof data !== 'object') {
        summaryEl.hidden = true;
        return;
      }
      if (data.status === 'error') {
        summaryEl.hidden = false;
        summaryEl.className = 'summary summary-err';
        const extra = data.missing_financial_fields || data.missing_config_fields;
        let detail = data.message || '';
        if (extra && Array.isArray(extra) && extra.length) {
          detail += (detail ? ' ' : '') + '(' + extra.join(', ') + ')';
        }
        if (!detail) detail = 'See raw JSON for details.';
        summaryEl.innerHTML =
          '<p class="summary-err-title">Could not process this file</p>' +
          '<p class="summary-err-msg">' + escapeHtml(detail) + '</p>';
        return;
      }
      if (data.mode === 'agentic') {
        if (data.final_task_json && data.final_task_json.report_type === 'COVENANT_DECISION_REPORT') {
          renderSummary(data.final_task_json);
          return;
        }
        summaryEl.hidden = false;
        summaryEl.className = 'summary summary-ok';
        const tasks = data.tasks_output || [];
        const chain = tasks.map(function (t) { return t.name || t.agent || 'task'; }).join(' → ');
        summaryEl.innerHTML =
          '<p class="summary-agent-title">Agentic workflow finished</p>' +
          '<p class="summary-err-msg">' + tasks.length + ' task(s)' +
          (chain ? ': ' + escapeHtml(chain) : '') +
          '. Full outputs are in <strong>Raw JSON</strong> below.</p>';
        return;
      }
      if (data.report_type === 'COVENANT_DECISION_REPORT') {
        summaryEl.hidden = false;
        summaryEl.className = 'summary summary-ok';
        const isBreach = data.decision === 'BREACH';
        const tagClass = isBreach ? 'breach' : 'compliant';
        const trace = data.calculation_trace || {};
        const cmp = trace.comparison != null ? String(trace.comparison) : '';
        const allMetrics = Array.isArray(data.all_metrics) ? data.all_metrics : [];
        const llmReport = data.llm_report && typeof data.llm_report === 'object' ? data.llm_report : null;
        const metricsHtml = allMetrics.length
          ? ('<div class="metrics-wrap">' +
            '<p class="metrics-title">All Metrics</p>' +
            '<table class="metrics-table">' +
            '<thead><tr><th>Metric</th><th>Actual</th><th>Threshold</th><th>Decision</th></tr></thead>' +
            '<tbody>' +
            allMetrics.map(function (m) {
              const metric = escapeHtml(String(m.metric || ''));
              const actual = m.actual != null ? escapeHtml(String(m.actual)) : '—';
              const threshold = m.threshold != null
                ? escapeHtml(String(m.threshold_operator || '')) + ' ' + escapeHtml(String(m.threshold))
                : '—';
              const rawDecision = String(m.decision || 'NOT_EVALUATED');
              const badgeClass = rawDecision.toLowerCase();
              const decisionBadge = '<span class="decision-pill ' + escapeHtml(badgeClass) + '">' +
                escapeHtml(rawDecision.replaceAll('_', ' ')) + '</span>';
              const reason = m.reason ? '<br/><span>' + escapeHtml(String(m.reason)) + '</span>' : '';
              return '<tr>' +
                '<td class="metric-name">' + metric + '</td>' +
                '<td>' + actual + '</td>' +
                '<td>' + threshold + '</td>' +
                '<td>' + decisionBadge + reason + '</td>' +
                '</tr>';
            }).join('') +
            '</tbody></table></div>')
          : '';
        const llmHtml = llmReport
          ? ('<div class="summary-action"><strong>Analysis Report</strong>' +
            (llmReport.summary ? '<p style="margin:0.55rem 0 0.25rem;">' + escapeHtml(String(llmReport.summary)) + '</p>' : '') +
            (Array.isArray(llmReport.resolution_points) && llmReport.resolution_points.length
              ? ('<ul>' + llmReport.resolution_points.map(function (pt) {
                  return '<li>' + escapeHtml(String(pt)) + '</li>';
                }).join('') + '</ul>')
              : '') +
            '</div>')
          : '';
        summaryEl.innerHTML =
          '<div class="summary-top">' +
          '<span class="decision-tag ' + tagClass + '">' + escapeHtml(data.decision || '') + '</span>' +
          '<span class="summary-meta">' +
          escapeHtml(String(data.borrower_id || '')) +
          ' · ' + escapeHtml(String(data.facility_id || '')) +
          ' · ' + escapeHtml(String(data.period || '')) +
          '</span></div>' +
          metricsHtml +
          llmHtml +
          (!llmHtml && cmp ? '<p class="summary-action"><strong>Comparison:</strong> ' + escapeHtml(cmp) + '</p>' : '') +
          (data.recommended_action
            ? '<p class="summary-action"><strong>Recommended:</strong> ' + escapeHtml(String(data.recommended_action)) + '</p>'
            : '');
        return;
      }
      summaryEl.hidden = true;
    }

    fileIn.addEventListener('change', () => {
      const f = fileIn.files && fileIn.files[0];
      if (f) {
        fileMeta.textContent = f.name + ' · ' + (f.size / 1024).toFixed(1) + ' KB';
        fileMeta.classList.add('has-file');
      } else {
        fileMeta.textContent = 'No file selected';
        fileMeta.classList.remove('has-file');
      }
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const useAgents = document.getElementById('useAgents').checked;
      setPill('run', useAgents ? 'Running flow…' : 'Analyzing…');
      summaryEl.hidden = true;
      summaryEl.innerHTML = '';
      out.textContent = useAgents ? 'Running agentic flow (CrewAI + shared state)…' : 'Running validation and DSCR…';
      jsonDetails.open = true;
      submitBtn.disabled = true;
      const fd = new FormData(form);
      const q = useAgents ? '?use_agents=true' : '';
      try {
        const res = await fetch('/api/analyze' + q, { method: 'POST', body: fd });
        const text = await res.text();
        let data;
        try { data = JSON.parse(text); } catch (_) { data = null; }
        if (data && typeof data === 'object') {
          out.textContent = JSON.stringify(data, null, 2);
          renderSummary(data);
          if (data.status === 'error') {
            setPill('err', data.mode === 'agentic' ? 'Flow error' : 'Issue with file');
            jsonDetails.open = true;
          } else if (data.mode === 'agentic') {
            setPill('ok', 'Flow finished');
            jsonDetails.open = true;
          } else {
            setPill('ok', 'Report ready');
            if (data.report_type === 'COVENANT_DECISION_REPORT') jsonDetails.open = false;
            else jsonDetails.open = true;
          }
        } else {
          out.textContent = text;
          summaryEl.hidden = true;
          setPill(res.ok ? 'ok' : 'err', res.ok ? 'Done' : 'HTTP ' + res.status);
        }
      } catch (err) {
        out.textContent = String(err);
        summaryEl.hidden = true;
        setPill('err', 'Request failed');
      }
      submitBtn.disabled = false;
    });
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX_HTML


@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    use_agents: bool = Query(
        False,
        description="If true, run CrewAI agents with shared-state payload handoffs by run_id.",
    ),
) -> JSONResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file name")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    suffix = Path(file.filename).suffix or ".xlsx"
    if use_agents:
        result = run_agents_from_bytes(raw, suffix=suffix)
    else:
        result = run_deterministic_from_bytes(raw, suffix=suffix)
    status_code = 422 if result.get("status") == "error" else 200
    return JSONResponse(status_code=status_code, content=result)


def serve() -> None:
    import uvicorn

    host = os.environ.get("COVENANT_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("COVENANT_WEB_PORT", "8000"))
    uvicorn.run("covenanttrackingphase1.web:app", host=host, port=port, reload=False)
