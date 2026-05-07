/* Day 4. Cashflow Bridge. Front-end JS.
   Handles upload, sample picking, results rendering, scenario engine,
   inline SVG balance chart, downloads. CSRF double-submit cookie.
*/

(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const els = {
    runBtn: $("#run-btn"),
    fileInput: $("#file-input"),
    dropCard: $("#drop-card"),
    bundledCard: $("#bundled-card"),
    srcUpload: $("#src-upload"),
    srcBundled: $("#src-bundled"),
    apiKey: $("#api-key"),
    skipAi: $("#skip-ai"),
    modelSelect: $("#model-select"),
    results: $("#results"),
    weeksTable: $("#weeks-table"),
    totalsTable: $("#totals-table"),
    linesTable: $("#lines-table"),
    balanceSvg: $("#balance-svg"),
    seriesLegend: $("#series-legend"),
    commentary: $("#commentary-card"),
    commentaryBody: $("#commentary-body"),
    scenarioInput: $("#scenario-input"),
    scenarioBtn: $("#run-scenario"),
    suggestions: $$(".chip"),
    samples: $$(".sample"),
    dlRow: $("#dl-row"),
    toast: $("#toast"),
    themeToggle: $("#theme-toggle"),
    cl30d: $("#cl-30d"),
    clTotal: $("#cl-total"),
    clRuns: $("#cl-runs"),
    clearLog: $("#clear-log"),
    heroOpening: $("#hero-opening"),
    heroClosing: $("#hero-closing"),
    heroMin: $("#hero-min"),
    heroRunway: $("#hero-runway"),
    heroCost: $("#hero-cost"),
    kpiFoot: $("#kpi-foot"),
  };

  const state = {
    lastResult: null,
    lastScenario: null,
    runId: null,
    lastSampleId: null,   // remembered so Run button + Ctrl+Enter can replay it
  };

  // ---- CSRF cookie helpers ----------------------------------------
  function getCookie(name) {
    const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }
  const CSRF = () => getCookie("csrf_token");

  // ---- GBP / pct format -------------------------------------------
  const fmtGbp = (v) => {
    if (v === null || v === undefined || Number.isNaN(v)) return "-";
    const sign = v < 0 ? "-" : "";
    const abs = Math.abs(v);
    return sign + "£" + abs.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  const fmtPct = (v) => (v === null || v === undefined ? "-" : (v * 100).toFixed(1) + "%");
  const fmtCount = (v) => (v === null || v === undefined ? "-" : String(v));

  // ---- Toast ------------------------------------------------------
  function toast(msg, kind) {
    els.toast.textContent = msg;
    els.toast.className = "toast " + (kind || "");
    els.toast.classList.remove("hidden");
    setTimeout(() => els.toast.classList.add("hidden"), 4500);
  }

  // ---- Theme toggle -----------------------------------------------
  // The Liquidity Ledger ships in two flavours: 'paper' (default cream
  // broadsheet) and 'ink' (dark, for evening reading).
  function applyTheme(t) {
    if (t === "ink") {
      document.documentElement.setAttribute("data-theme", "ink");
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
    if (t) localStorage.setItem("day04.theme", t);
  }
  applyTheme(localStorage.getItem("day04.theme") || "paper");
  if (els.themeToggle) {
    els.themeToggle.addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme");
      applyTheme(cur === "ink" ? "paper" : "ink");
    });
  }

  // ---- Source toggle ----------------------------------------------
  function showUpload() {
    els.srcUpload.classList.add("seg-on");
    els.srcBundled.classList.remove("seg-on");
    els.dropCard.classList.remove("hidden");
    els.bundledCard.classList.add("hidden");
  }
  function showBundled() {
    els.srcBundled.classList.add("seg-on");
    els.srcUpload.classList.remove("seg-on");
    els.bundledCard.classList.remove("hidden");
    els.dropCard.classList.add("hidden");
  }
  els.srcUpload.addEventListener("click", showUpload);
  els.srcBundled.addEventListener("click", showBundled);

  // ---- Upload triggers --------------------------------------------
  els.dropCard.addEventListener("click", () => els.fileInput.click());
  els.dropCard.addEventListener("dragover", (e) => {
    e.preventDefault();
    els.dropCard.style.borderColor = "var(--teal)";
  });
  els.dropCard.addEventListener("dragleave", () => {
    els.dropCard.style.borderColor = "";
  });
  els.dropCard.addEventListener("drop", (e) => {
    e.preventDefault();
    els.dropCard.style.borderColor = "";
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f && /\.xlsx$/i.test(f.name)) {
      els.fileInput.files = e.dataTransfer.files;
      runAnalyse();
    } else {
      toast("Drop an .xlsx file.", "warn");
    }
  });
  els.fileInput.addEventListener("change", () => {
    if (els.fileInput.files.length > 0) runAnalyse();
  });

  // ---- Samples ----------------------------------------------------
  // Clicking a sample auto-runs the analysis AND remembers the sample
  // so the Run button / Ctrl+Enter can replay it without a fresh click.
  // Picking a file upload clears the sample memory.
  function selectSample(sampleId) {
    state.lastSampleId = sampleId;
    els.samples.forEach((b) => {
      b.classList.toggle("is-selected", b.dataset.sampleId === sampleId);
    });
    if (els.fileInput.value) els.fileInput.value = "";
  }

  els.samples.forEach((btn) => {
    btn.addEventListener("click", () => {
      const sid = btn.dataset.sampleId;
      selectSample(sid);
      runAnalyse({ sampleId: sid });
    });
  });

  // When the user picks a real file, drop the sample memory so we don't
  // accidentally replay the sample on the next Run click.
  els.fileInput.addEventListener("change", () => {
    if (els.fileInput.files.length > 0) {
      state.lastSampleId = null;
      els.samples.forEach((b) => b.classList.remove("is-selected"));
    }
  });

  // ---- Run button + Ctrl+Enter ------------------------------------
  function triggerRun() {
    if (els.fileInput.files.length > 0) {
      runAnalyse();
    } else if (state.lastSampleId) {
      runAnalyse({ sampleId: state.lastSampleId });
    } else {
      toast("Pick a workbook or a sample first.", "warn");
    }
  }

  els.runBtn.addEventListener("click", triggerRun);
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key === "Enter") {
      if (document.activeElement === els.scenarioInput) {
        runScenario();
      } else {
        triggerRun();
      }
    }
  });

  // ---- Scenario ----------------------------------------------------
  els.scenarioBtn.addEventListener("click", runScenario);
  els.scenarioInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") runScenario();
  });
  els.suggestions.forEach((chip) => {
    chip.addEventListener("click", () => {
      els.scenarioInput.value = chip.dataset.suggest;
      runScenario();
    });
  });

  // ---- Cost log strip ----------------------------------------------
  els.clearLog.addEventListener("click", async () => {
    if (!confirm("Clear the cost log? This wipes the running totals on disk.")) return;
    const r = await fetch("/api/cost-log/clear", { method: "POST", headers: { "X-CSRF-Token": CSRF() } });
    if (r.ok) loadCostLog();
  });

  async function loadCostLog() {
    try {
      const r = await fetch("/api/runs");
      if (!r.ok) return;
      const data = await r.json();
      const s = data.summary || {};
      els.cl30d.textContent = "$" + (s.cost_usd_30d || 0).toFixed(4);
      els.clTotal.textContent = "$" + (s.cost_usd_total || 0).toFixed(4);
      els.clRuns.textContent = String(s.runs || 0);
    } catch (e) { /* ignore */ }
  }
  loadCostLog();

  // ---- Run analyse ------------------------------------------------
  async function runAnalyse(opts) {
    opts = opts || {};
    const fd = new FormData();
    if (opts.sampleId) {
      fd.append("use_samples", "true");
      fd.append("sample_id", opts.sampleId);
    } else if (els.fileInput.files.length > 0) {
      fd.append("file", els.fileInput.files[0]);
    } else {
      toast("Pick a workbook or sample first.", "warn");
      return;
    }
    fd.append("skip_ai", els.skipAi.checked ? "true" : "false");
    if (els.apiKey.value) fd.append("api_key", els.apiKey.value);
    if (els.modelSelect.value) fd.append("model", els.modelSelect.value);

    setBusy(true);
    try {
      const r = await fetch("/api/analyse", {
        method: "POST",
        headers: { "X-CSRF-Token": CSRF() },
        body: fd,
      });
      const data = await r.json();
      if (!r.ok) {
        toast(data.error || "Analysis failed.", "warn");
        return;
      }
      state.lastResult = data;
      state.runId = data.run_id;
      state.lastScenario = null;
      render(data);
      // Pull the page down to the analysis so the user sees it.
      requestAnimationFrame(() => {
        els.results.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      toast("Analysis ready. See below.", "ok");
    } catch (e) {
      toast("Network error: " + e.message, "warn");
    } finally {
      setBusy(false);
      loadCostLog();
    }
  }

  async function runScenario() {
    if (!state.runId) {
      toast("Run an analysis first.", "warn");
      return;
    }
    const prompt = els.scenarioInput.value.trim();
    if (!prompt) { toast("Type a scenario question.", "warn"); return; }

    const fd = new FormData();
    fd.append("run_id", state.runId);
    fd.append("prompt", prompt);
    fd.append("skip_ai", els.skipAi.checked ? "true" : "false");
    if (els.apiKey.value) fd.append("api_key", els.apiKey.value);
    if (els.modelSelect.value) fd.append("model", els.modelSelect.value);

    setBusy(true);
    try {
      const r = await fetch("/api/scenario", {
        method: "POST",
        headers: { "X-CSRF-Token": CSRF() },
        body: fd,
      });
      const data = await r.json();
      if (!r.ok) {
        toast(data.error || "Scenario failed.", "warn");
        return;
      }
      state.lastScenario = data;
      renderScenario(data);
      requestAnimationFrame(() => {
        const card = $("#commentary-card");
        if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      toast("Scenario applied.", "ok");
    } catch (e) {
      toast("Network error: " + e.message, "warn");
    } finally {
      setBusy(false);
      loadCostLog();
    }
  }

  function setBusy(b) {
    els.runBtn.disabled = b;
    els.scenarioBtn.disabled = b;
    els.runBtn.textContent = b ? "Analysing..." : "Analyse forecast";
  }

  // ---- Rendering ---------------------------------------------------
  function render(data) {
    els.results.classList.remove("hidden");
    const h = data.headline;
    const md = data.metadata || {};
    els.heroOpening.textContent = fmtGbp(h.opening_balance);
    els.heroClosing.textContent = fmtGbp(h.closing_balance);
    els.heroMin.textContent = fmtGbp(h.min_balance);
    els.heroRunway.textContent = h.runway_weeks === null ? "Beyond horizon" : "W" + h.runway_weeks;
    els.heroCost.textContent = "$" + (data.cost_usd || 0).toFixed(4);
    if (els.kpiFoot) {
      const start = md.start_date ? `, 13 wks from ${md.start_date}` : "";
      els.kpiFoot.textContent = `${md.company || "Forecast"}${start}`;
    }
    const banner = $("#results-banner-meta");
    if (banner) {
      const runwayStr = h.runway_weeks === null ? "no breach in 13 weeks" : `runway W${h.runway_weeks}`;
      banner.textContent = `${md.company || "Forecast"} . closing ${fmtGbp(h.closing_balance)} . ${runwayStr}`;
    }

    drawBalanceSvg(data.weeks.map((w) => w.closing), null, h.buffer_used);
    renderWeeksTable(data.weeks);
    renderTotalsTable(data.type_totals);
    renderLinesTable(data.lines);
    renderDownloads(data);
    renderBaseCommentary(data.commentary);
  }

  function renderBaseCommentary(c) {
    if (!c || c.skipped) {
      els.commentary.classList.add("hidden");
      return;
    }
    els.commentary.classList.remove("hidden");
    const labelEl = $("#commentary-byline-label");
    const metaEl = $("#commentary-byline-meta");
    if (labelEl) labelEl.textContent = "The controller writes";

    if (c.error) {
      if (metaEl) metaEl.textContent = "AI commentary unavailable";
      els.commentaryBody.innerHTML =
        `<div class="meta">The base run could not be narrated.</div>` +
        `<div class="summary">${escapeHtml(c.headline || c.error)}</div>`;
      return;
    }

    if (metaEl) {
      const cost = (c.cost_usd || 0).toFixed(4);
      metaEl.textContent = `cost $${cost} . ${c.input_tokens || 0} in / ${c.output_tokens || 0} out . ${c.model || "deepseek-chat"}`;
    }

    const html = [];
    if (c.headline) html.push(`<h3>${escapeHtml(c.headline)}</h3>`);
    if (c.summary) html.push(`<div class="summary">${escapeHtml(c.summary)}</div>`);
    if (c.actions && c.actions.length) {
      html.push(`<div class="driver-block"><h4>Drivers and actions</h4><ul>`);
      c.actions.forEach((a) => html.push(`<li>${escapeHtml(a)}</li>`));
      html.push(`</ul></div>`);
    }
    els.commentaryBody.innerHTML = html.join("");
  }

  function renderScenario(data) {
    state.lastResult = data.scenario;
    state.lastResult.run_id = state.runId;  // preserve so scenario can re-run
    const scenarioHeadline = data.scenario.headline;
    const baseClosings = data.base.weeks.map((w) => w.closing);
    const sceneClosings = data.scenario.weeks.map((w) => w.closing);

    els.heroOpening.textContent = fmtGbp(scenarioHeadline.opening_balance);
    els.heroClosing.textContent = fmtGbp(scenarioHeadline.closing_balance);
    els.heroMin.textContent = fmtGbp(scenarioHeadline.min_balance);
    els.heroRunway.textContent = scenarioHeadline.runway_weeks === null
      ? "Beyond horizon" : "W" + scenarioHeadline.runway_weeks;
    els.heroCost.textContent = "$" + (data.commentary.cost_usd || 0).toFixed(4);
    if (els.kpiFoot) els.kpiFoot.textContent = "After scenario . click below to revise";

    drawBalanceSvg(sceneClosings, baseClosings, scenarioHeadline.buffer_used);
    renderWeeksTable(data.scenario.weeks);
    renderTotalsTable(data.scenario.type_totals);
    renderLinesTable(data.scenario.lines);
    renderCommentary(data);

    if (data.xlsx_filename) {
      // Refresh download row to point at scenario xlsx.
      const merged = Object.assign({}, data.scenario, {
        xlsx_filename: data.xlsx_filename,
        weekly_csv_filename: state.lastResult.weekly_csv_filename,
        lines_csv_filename: state.lastResult.lines_csv_filename,
      });
      renderDownloads(merged);
    }
  }

  function renderCommentary(scenarioData) {
    const c = scenarioData.commentary || {};
    els.commentary.classList.remove("hidden");
    const bylineLabel = $("#commentary-byline-label");
    const bylineMeta = $("#commentary-byline-meta");
    if (bylineLabel) bylineLabel.textContent = "The controller on this scenario";

    if (c.error) {
      if (bylineMeta) bylineMeta.textContent = "AI unavailable";
      const html = [
        `<div class="meta">The scenario engine could not be reached.</div>`,
        `<div class="summary">${escapeHtml(c.headline || c.error)}</div>`,
      ];
      els.commentaryBody.innerHTML = html.join("");
      return;
    }

    const costStr = (c.cost_usd || 0).toFixed(4);
    const tokensStr = `${c.input_tokens || 0} in / ${c.output_tokens || 0} out`;
    if (bylineMeta) {
      bylineMeta.textContent = `cost $${costStr} . ${tokensStr} . ${c.model || "deepseek-chat"}`;
    }

    const html = [];
    if (c.headline) html.push(`<h3>${escapeHtml(c.headline)}</h3>`);
    if (c.interpretation) {
      html.push(`<p class="meta">Reading: ${escapeHtml(c.interpretation)}</p>`);
    }
    if (c.summary) html.push(`<div class="summary">${escapeHtml(c.summary)}</div>`);
    if (c.actions && c.actions.length) {
      html.push(`<div class="driver-block"><h4>Suggested actions</h4><ul>`);
      c.actions.forEach((a) => html.push(`<li>${escapeHtml(a)}</li>`));
      html.push(`</ul></div>`);
    }
    els.commentaryBody.innerHTML = html.join("");
  }

  function renderWeeksTable(weeks) {
    const cols = ["week", "iso_week_label", "receipts", "outflow", "net", "closing", "rag"];
    let html = "<table><thead><tr>";
    cols.forEach((c) => {
      html += `<th class="${c === "week" || c === "iso_week_label" || c === "rag" ? "text" : ""}">${c}</th>`;
    });
    html += "</tr></thead><tbody>";
    weeks.forEach((w) => {
      html += "<tr>";
      html += `<td class="text">W${w.week}</td>`;
      html += `<td class="text">${escapeHtml(w.iso_week_label)}</td>`;
      html += `<td>${fmtGbp(w.receipts)}</td>`;
      html += `<td>${fmtGbp(w.outflow)}</td>`;
      html += `<td>${fmtGbp(w.net)}</td>`;
      html += `<td>${fmtGbp(w.closing)}</td>`;
      html += `<td class="text"><span class="rag-pill rag-${w.rag}">${w.rag}</span></td>`;
      html += "</tr>";
    });
    html += "</tbody></table>";
    els.weeksTable.innerHTML = html;
  }

  function renderTotalsTable(totals) {
    let html = "<table><thead><tr><th class='text'>type</th><th>total</th></tr></thead><tbody>";
    Object.entries(totals).forEach(([k, v]) => {
      html += `<tr><td class="text">${escapeHtml(k)}</td><td>${fmtGbp(v)}</td></tr>`;
    });
    html += "</tbody></table>";
    els.totalsTable.innerHTML = html;
  }

  function renderLinesTable(lines) {
    let html = "<table><thead><tr>";
    html += `<th class="text">name</th><th class="text">type</th><th class="text">category</th>`;
    for (let w = 1; w <= 13; w++) html += `<th>W${w}</th>`;
    html += `<th>total</th></tr></thead><tbody>`;
    lines.forEach((line) => {
      html += "<tr>";
      html += `<td class="text">${escapeHtml(line.name)}</td>`;
      html += `<td class="text">${escapeHtml(line.type)}</td>`;
      html += `<td class="text">${escapeHtml(line.category || "")}</td>`;
      line.amounts.forEach((v) => { html += `<td>${fmtGbp(v)}</td>`; });
      html += `<td>${fmtGbp(line.total)}</td>`;
      html += "</tr>";
    });
    html += "</tbody></table>";
    els.linesTable.innerHTML = html;
  }

  function renderDownloads(data) {
    const rows = [];
    if (data.xlsx_filename) {
      rows.push(`<a class="dl-btn" href="/api/download/${encodeURIComponent(data.xlsx_filename)}" download>Excel <span class="dl-tag">.xlsx</span></a>`);
    }
    if (data.weekly_csv_filename) {
      rows.push(`<a class="dl-btn" href="/api/download/${encodeURIComponent(data.weekly_csv_filename)}" download>Weekly CSV <span class="dl-tag">.csv</span></a>`);
    }
    if (data.lines_csv_filename) {
      rows.push(`<a class="dl-btn" href="/api/download/${encodeURIComponent(data.lines_csv_filename)}" download>Lines CSV <span class="dl-tag">.csv</span></a>`);
    }
    els.dlRow.innerHTML = rows.join("");
  }

  // ---- SVG balance line --------------------------------------------
  // Editorial palette: ink black for the main series, faded mute for the
  // base run, mustard for the buffer line, burgundy for breach.
  function drawBalanceSvg(closing, baseSeries, buffer) {
    // Pull live theme colours from CSS so dark mode swaps too.
    const css = getComputedStyle(document.documentElement);
    const cInk      = css.getPropertyValue("--ink").trim() || "#1A1815";
    const cMute     = css.getPropertyValue("--ink-mute").trim() || "#4F4A42";
    const cRule     = css.getPropertyValue("--rule-2").trim() || "#A8A19A";
    const cMustard  = css.getPropertyValue("--mustard").trim() || "#B8860B";
    const cBurgundy = css.getPropertyValue("--burgundy").trim() || "#8B2635";
    const cGreen    = css.getPropertyValue("--green").trim() || "#2C5F2D";

    const W = 920, H = 280, pad = 32;
    const allVals = [...closing];
    if (baseSeries) allVals.push(...baseSeries);
    if (buffer && buffer > 0) allVals.push(buffer);
    allVals.push(0);
    let minV = Math.min.apply(null, allVals);
    let maxV = Math.max.apply(null, allVals);
    if (maxV === minV) { maxV += 1; minV -= 1; }
    const span = maxV - minV;
    const n = closing.length;
    const innerW = W - 2 * pad;
    const innerH = H - 2 * pad;

    const x = (i) => pad + (i / Math.max(n - 1, 1)) * innerW;
    const y = (v) => pad + (1 - (v - minV) / span) * innerH;

    const lineToPath = (vals) => {
      if (!vals || !vals.length) return "";
      return "M " + vals.map((v, i) => `${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" L ");
    };

    const parts = [];
    parts.push(`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`);
    parts.push(`<rect width="${W}" height="${H}" fill="transparent"/>`);

    // Faint horizontal rules (broadsheet feel)
    for (let r = 1; r <= 4; r++) {
      const yy = pad + (r / 5) * innerH;
      parts.push(`<line x1="${pad}" y1="${yy.toFixed(1)}" x2="${W - pad}" y2="${yy.toFixed(1)}" stroke="${cRule}" stroke-width="0.4" stroke-dasharray="1 4"/>`);
    }
    // Frame
    parts.push(`<rect x="${pad}" y="${pad}" width="${innerW}" height="${innerH}" fill="none" stroke="${cInk}" stroke-width="0.8"/>`);

    // Zero line
    if (minV <= 0 && maxV >= 0) {
      const zy = y(0);
      parts.push(`<line x1="${pad}" y1="${zy.toFixed(1)}" x2="${W - pad}" y2="${zy.toFixed(1)}" stroke="${cMute}" stroke-width="0.8" stroke-dasharray="3 3"/>`);
      parts.push(`<text x="${pad - 6}" y="${(zy + 3).toFixed(1)}" font-size="9" font-family="Courier New, monospace" fill="${cMute}" text-anchor="end" font-style="italic">0</text>`);
    }
    // Buffer line
    if (buffer && buffer > 0 && buffer >= minV && buffer <= maxV) {
      const by = y(buffer);
      parts.push(`<line x1="${pad}" y1="${by.toFixed(1)}" x2="${W - pad}" y2="${by.toFixed(1)}" stroke="${cMustard}" stroke-width="0.8" stroke-dasharray="2 4"/>`);
    }
    // Base series (faded, behind)
    if (baseSeries) {
      parts.push(`<path d="${lineToPath(baseSeries)}" fill="none" stroke="${cMute}" stroke-width="1.4" stroke-dasharray="3 3" opacity="0.6"/>`);
      baseSeries.forEach((v, i) => {
        parts.push(`<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2" fill="${cMute}"/>`);
      });
    }
    // Main series (ink black, solid)
    parts.push(`<path d="${lineToPath(closing)}" fill="none" stroke="${cInk}" stroke-width="2"/>`);
    closing.forEach((v, i) => {
      const colour = v < 0 ? cBurgundy : cInk;
      parts.push(`<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3.5" fill="${colour}" stroke="${cInk}" stroke-width="0.6"/>`);
    });
    // X axis labels
    for (let i = 0; i < n; i++) {
      parts.push(`<text x="${x(i).toFixed(1)}" y="${(H - 10).toFixed(1)}" font-size="10" font-family="Courier New, monospace" fill="${cMute}" text-anchor="middle">W${i + 1}</text>`);
    }
    parts.push("</svg>");
    els.balanceSvg.innerHTML = parts.join("");

    const legend = [
      `<span><span class="swatch" style="background:${cInk}"></span>Closing balance</span>`,
    ];
    if (baseSeries) legend.push(`<span><span class="swatch" style="background:${cMute}"></span>Base run</span>`);
    if (buffer && buffer > 0) legend.push(`<span><span class="swatch" style="background:${cMustard}"></span>Buffer £${buffer.toLocaleString("en-GB", { maximumFractionDigits: 0 })}</span>`);
    legend.push(`<span><span class="swatch" style="background:${cBurgundy}"></span>Below zero</span>`);
    els.seriesLegend.innerHTML = legend.join("");
  }

  function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }
})();
