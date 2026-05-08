// OpenAlex-only institution-year-field candidate browser.

const PAGE = 100;
const state = {
  meta: null,
  taxonomy: { fields: {} },
  payload: null,
  rows: [],
  filtered: [],
  shown: 0,
};

const $ = (id) => document.getElementById(id);

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"})[c]);
}

function fmtPct(p) {
  if (p == null || Number.isNaN(Number(p))) return "-";
  return (100 * Number(p)).toFixed(1) + "%";
}

function fmtInt(x) {
  if (x == null || x === "") return "0";
  return Number(x).toLocaleString();
}

function fieldLabel(code) {
  if (code === "COMP_ENGG") return "Computer Science plus Engineering";
  return state.taxonomy.fields[code] || code || "field";
}

function authorUrl(authorId) {
  return authorId ? `https://openalex.org/${encodeURIComponent(authorId)}` : "#";
}

function fieldProb(a, code) {
  if (code === "COMP_ENGG") {
    return Number(a.fp?.COMP || 0) + Number(a.fp?.ENGG || 0);
  }
  return Number(a.fp?.[code] || 0);
}

function authorWorks(a) {
  return Number(a.w || 0);
}

function probChip(label, value) {
  if (!label) return "";
  return `<span class="prob-chip">${escapeHtml(label)} <strong>${fmtPct(value)}</strong></span>`;
}

function fieldsHtml(a, selectedField) {
  const top = (a.tf || []).map(([code, p]) => [fieldLabel(code), p]);
  const chips = top.length
    ? top.map(([label, p]) => probChip(label, p)).join("")
    : `<span class="table-sub">No career field probabilities in classifier sample.</span>`;
  return `
    <div class="chip-stack">${chips}</div>
    <div class="table-sub">selected ${escapeHtml(fieldLabel(selectedField))}: ${fmtPct(fieldProb(a, selectedField))}</div>
  `;
}

function metricsHtml(a) {
  return `
    <div class="metric-stack">
      <div><strong>${fmtInt(a.w)}</strong><span>OpenAlex works</span></div>
      <div><strong>${fmtInt(a.c)}</strong><span>citations</span></div>
      <div><strong>${fmtInt(a.h)}</strong><span>h-index</span></div>
      <div><strong>${fmtInt(a.sp)}</strong><span>publications in classifier sample</span></div>
    </div>
  `;
}

function evidenceHtml(a) {
  const raw = Number(a.raw || 0);
  const label = raw > 0 ? "observed raw affiliation" : "imputed affiliation";
  const cls = raw > 0 ? "status-good" : "status-muted";
  return `
    <span class="status-badge ${cls}">${label}</span>
    <div class="table-sub">${fmtInt(a.yp)} papers at selected university-year${raw > 0 ? `; ${fmtInt(raw)} raw rows` : ""}</div>
  `;
}

function selectedKey() {
  return `${$("university-select").value}-${$("year-select").value}`;
}

function yearMeta() {
  const key = selectedKey();
  return state.meta.school_years.find((d) => `${d.university_key}-${d.year}` === key);
}

function buildDropdowns() {
  $("university-select").innerHTML = state.meta.universities.map((u) =>
    `<option value="${escapeHtml(u.key)}">${escapeHtml(u.name)}</option>`
  ).join("");
  $("year-select").innerHTML = state.meta.years.map((y) =>
    `<option value="${escapeHtml(y)}">${escapeHtml(y)}</option>`
  ).join("");
  const fieldOptions = [
    `<option value="COMP_ENGG">Computer Science plus Engineering</option>`,
    ...state.meta.fields.map((code) =>
      `<option value="${escapeHtml(code)}">${escapeHtml(fieldLabel(code))}</option>`
    ),
  ];
  $("field-select").innerHTML = fieldOptions.join("");

  const defaults = state.meta.defaults;
  $("university-select").value = defaults.university_key;
  $("year-select").value = String(defaults.year);
  $("field-select").value = defaults.field;
  $("min-works").value = defaults.min_works;
  $("min-prob").value = Number(defaults.min_field_probability).toFixed(2);
  $("min-school-papers").value = defaults.min_school_papers;
}

async function loadSelectedYear() {
  const meta = yearMeta();
  if (!meta) {
    state.payload = null;
    state.rows = [];
    $("results").innerHTML = `<div class="empty">No candidate data for that institution-year.</div>`;
    return;
  }
  $("count-badge").textContent = "loading candidates...";
  $("results").innerHTML = `<div class="loader">Loading ${escapeHtml(meta.university)} ${meta.year}...</div>`;
  const payload = await fetch(meta.data_file).then((r) => {
    if (!r.ok) throw new Error(`Failed to load ${meta.data_file}: ${r.status}`);
    return r.json();
  });
  if (selectedKey() !== `${payload.university_key}-${payload.year}`) return;
  state.payload = payload;
  state.rows = payload.authors || [];
  applyFilters();
}

function currentParams() {
  return {
    field: $("field-select").value,
    minWorks: Number($("min-works").value || 0),
    minProb: Number($("min-prob").value || 0),
    minSchoolPapers: Number($("min-school-papers").value || 1),
    evidence: $("evidence-select").value,
    sortBy: $("sort-by").value,
    search: $("text-search").value.trim().toLowerCase(),
  };
}

function passes(a, params) {
  if (authorWorks(a) < params.minWorks) return false;
  if (Number(a.yp || 0) < params.minSchoolPapers) return false;
  if (fieldProb(a, params.field) < params.minProb) return false;
  if (params.evidence === "raw" && Number(a.raw || 0) <= 0) return false;
  if (params.evidence === "imputed" && Number(a.raw || 0) > 0) return false;
  if (params.search) {
    const hay = [a.n, a.a].filter(Boolean).join(" ").toLowerCase();
    if (!hay.includes(params.search)) return false;
  }
  return true;
}

function summaryHtml() {
  const p = state.payload;
  const params = currentParams();
  const rawTotal = state.rows.filter((a) => Number(a.raw || 0) > 0).length;
  const imputedTotal = Math.max(0, state.rows.length - rawTotal);
  return `
    <section class="dept-summary">
      <h2>${escapeHtml(p.university)}, ${p.year} - ${escapeHtml(fieldLabel(params.field))}</h2>
      <p>
        OpenAlex-only view: authors are included when the imputed paper-author affiliation file attaches them to this university in this year.
        Faculty roster data are not used here. This static build covers the four validation universities.
      </p>
      <p class="active-filter">
        Current filter:
        <strong>${escapeHtml(fieldLabel(params.field))} >= ${fmtPct(params.minProb)}</strong>,
        <strong>${fmtInt(params.minWorks)}+ OpenAlex works</strong>,
        and <strong>${fmtInt(params.minSchoolPapers)}+ selected-university papers</strong>.
      </p>
      <div class="summary-grid summary-grid-compact">
        <div class="summary-primary">
          <strong>${fmtInt(state.filtered.length)}</strong>
          <span>authors displayed</span>
        </div>
        <div>
          <strong>${fmtInt(state.rows.length)}</strong>
          <span>authors attached to ${escapeHtml(p.university)} in ${p.year}</span>
        </div>
        <div>
          <strong>${fmtInt(rawTotal)}</strong>
          <span>with at least one observed raw affiliation row</span>
        </div>
        <div>
          <strong>${fmtInt(imputedTotal)}</strong>
          <span>imputed-only in this university-year</span>
        </div>
      </div>
    </section>
  `;
}

function rowHtml(a, selectedField) {
  return `
    <tr>
      <td>
        <div class="table-title"><a href="${authorUrl(a.a)}" target="_blank" rel="noopener">${escapeHtml(a.n)}</a></div>
        <div class="table-sub">${escapeHtml(a.a)}</div>
      </td>
      <td>${metricsHtml(a)}</td>
      <td>${fieldsHtml(a, selectedField)}</td>
      <td>${evidenceHtml(a)}</td>
      <td>
        <div>${a.yf || a.yl ? `${fmtInt(a.yf)}-${fmtInt(a.yl)}` : ""}</div>
        <div class="table-sub">classifier-sample career span</div>
      </td>
    </tr>
  `;
}

function tableHtml() {
  const p = state.payload;
  return `
    <section class="browser-panel">
      <h3>OpenAlex candidates for ${escapeHtml(p.university)} in ${p.year}</h3>
      <p class="panel-note">
        These rows are a direct OpenAlex/SciSciNet candidate list for the selected institution-year and field.
        "Observed raw affiliation" means at least one underlying paper-author-institution row directly listed the university; otherwise the row enters through the conservative imputation file.
      </p>
      <div class="table-wrap">
        <table class="data-table candidate-table">
          <thead>
            <tr>
              <th>OpenAlex author</th><th>Works/citations</th><th>Field probabilities</th><th>Institution-year evidence</th><th>Classifier span</th>
            </tr>
          </thead>
          <tbody id="candidate-rows"></tbody>
        </table>
      </div>
      <button class="show-more" id="more-btn">Show ${PAGE} more</button>
    </section>
  `;
}

function renderRows(reset = true) {
  const container = $("candidate-rows");
  const selectedField = $("field-select").value;
  if (reset) {
    state.shown = 0;
    container.innerHTML = "";
  }
  const next = state.filtered.slice(state.shown, state.shown + PAGE);
  container.insertAdjacentHTML("beforeend", next.map((a) => rowHtml(a, selectedField)).join(""));
  state.shown += next.length;
  const btn = $("more-btn");
  if (btn) {
    btn.disabled = state.shown >= state.filtered.length;
    btn.textContent = btn.disabled ? "End of results" : `Show ${PAGE} more`;
  }
}

function render() {
  $("results").innerHTML = `
    ${summaryHtml()}
    ${tableHtml()}
  `;
  $("more-btn").onclick = () => renderRows(false);
  renderRows(true);
}

function applyFilters() {
  if (!state.payload) return;
  const params = currentParams();
  const xs = state.rows.filter((a) => passes(a, params));
  if (params.sortBy === "field_desc") {
    xs.sort((a, b) => fieldProb(b, params.field) - fieldProb(a, params.field) || authorWorks(b) - authorWorks(a));
  } else if (params.sortBy === "works_desc") {
    xs.sort((a, b) => authorWorks(b) - authorWorks(a));
  } else if (params.sortBy === "school_papers_desc") {
    xs.sort((a, b) => Number(b.yp || 0) - Number(a.yp || 0) || fieldProb(b, params.field) - fieldProb(a, params.field));
  } else if (params.sortBy === "name") {
    xs.sort((a, b) => String(a.n || "").localeCompare(String(b.n || "")));
  }
  state.filtered = xs;
  $("count-badge").textContent = `${fmtInt(xs.length)} OpenAlex authors displayed`;
  render();
}

function attachEvents() {
  $("university-select").addEventListener("change", loadSelectedYear);
  $("year-select").addEventListener("change", loadSelectedYear);
  ["field-select", "min-works", "min-prob", "min-school-papers", "evidence-select", "sort-by", "text-search"].forEach((id) => {
    $(id).addEventListener("input", applyFilters);
  });
  $("reset-btn").onclick = (e) => {
    e.preventDefault();
    const defaults = state.meta.defaults;
    $("university-select").value = defaults.university_key;
    $("year-select").value = String(defaults.year);
    $("field-select").value = defaults.field;
    $("min-works").value = defaults.min_works;
    $("min-prob").value = Number(defaults.min_field_probability).toFixed(2);
    $("min-school-papers").value = defaults.min_school_papers;
    $("evidence-select").value = "all";
    $("sort-by").value = "field_desc";
    $("text-search").value = "";
    loadSelectedYear();
  };
}

async function init() {
  try {
    const [meta, taxonomy] = await Promise.all([
      fetch("institution_candidates.json").then((r) => r.json()),
      fetch("taxonomy.json").then((r) => r.json()),
    ]);
    state.meta = meta;
    state.taxonomy = taxonomy;
    buildDropdowns();
    attachEvents();
    await loadSelectedYear();
  } catch (err) {
    $("results").innerHTML = `<div class="empty">Failed to load institution candidates:<br><pre>${escapeHtml(err.message)}</pre></div>`;
    console.error(err);
  }
}

init();
