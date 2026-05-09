// OpenAlex-only institution-year-field candidate browser.

const PAGE = 100;
const state = {
  meta: null,
  taxonomy: { fields: {}, subfields: {} },
  payload: null,
  rows: [],
  filtered: [],
  shown: 0,
  institutionValues: new Map(),
  fieldValues: new Map(),
  loadTimer: null,
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

function subfieldLabel(code) {
  return state.taxonomy.subfields?.[code] || code || "subfield";
}

function institutionLabel(u) {
  if (!u) return "";
  return u.name || "";
}

function authorUrl(authorId) {
  return authorId ? `https://openalex.org/${encodeURIComponent(authorId)}` : "#";
}

function workUrl(paperId) {
  return paperId ? `https://openalex.org/${encodeURIComponent(paperId)}` : "#";
}

function institutionOptions() {
  const exported = new Map();
  for (const row of state.meta.school_years || []) {
    const id = row.institution_id || row.university_key;
    if (!id || exported.has(id)) continue;
    exported.set(id, {
      key: row.university_key,
      name: row.university,
      institution_id: row.institution_id,
      author_count: row.author_count,
      year_min: row.year,
      year_max: row.year,
    });
  }
  for (const row of state.meta.school_years || []) {
    const id = row.institution_id || row.university_key;
    const current = exported.get(id);
    if (!current) continue;
    current.year_min = Math.min(Number(current.year_min), Number(row.year));
    current.year_max = Math.max(Number(current.year_max), Number(row.year));
    current.author_count = Math.max(Number(current.author_count || 0), Number(row.author_count || 0));
  }
  if (exported.size) {
    return [...exported.values()].sort((a, b) => a.name.localeCompare(b.name));
  }
  return (state.meta.universities || []).map((u) => ({
    ...u,
    institution_id: u.institution_id,
    author_count: u.author_count,
    year_min: u.year_min,
    year_max: u.year_max,
  }));
}

function selectedInstitution() {
  const raw = $("university-input").value.trim();
  const low = raw.toLowerCase();
  if (state.institutionValues.has(raw)) return state.institutionValues.get(raw);
  const opts = institutionOptions();
  return opts.find((u) => u.institution_id?.toLowerCase() === low)
    || opts.find((u) => u.name?.toLowerCase() === low)
    || opts.find((u) => institutionLabel(u).toLowerCase().includes(low))
    || opts.find((u) => u.key === state.meta.defaults.university_key)
    || opts[0];
}

function selectedYear() {
  const m = $("year-input").value.match(/\d{4}/);
  return m ? Number(m[0]) : Number(state.meta.defaults.year);
}

function selectedField() {
  const raw = $("field-input").value.trim();
  const low = raw.toLowerCase();
  if (state.fieldValues.has(raw)) return state.fieldValues.get(raw);
  const codes = ["COMP_ENGG", ...(state.meta.fields || [])];
  return codes.find((code) => code.toLowerCase() === low)
    || codes.find((code) => fieldLabel(code).toLowerCase() === low)
    || codes.find((code) => fieldLabel(code).toLowerCase().includes(low))
    || state.meta.defaults.field;
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

function fieldsHtml(a, selectedFieldCode) {
  const top = (a.tf || []).map(([code, p]) => [fieldLabel(code), p]);
  const chips = top.length
    ? top.map(([label, p]) => probChip(label, p)).join("")
    : `<span class="table-sub">No career field probabilities in classifier sample.</span>`;
  return `
    <div class="chip-stack">${chips}</div>
    <div class="table-sub">selected ${escapeHtml(fieldLabel(selectedFieldCode))}: ${fmtPct(fieldProb(a, selectedFieldCode))}</div>
  `;
}

function subfieldsHtml(a) {
  const top = (a.ts || []).map(([code, p]) => [subfieldLabel(code), p]);
  if (!top.length) {
    return `<span class="table-sub">No career subfield probabilities in this browser sample.</span>`;
  }
  return `<div class="chip-stack">${top.map(([label, p]) => probChip(label, p)).join("")}</div>`;
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
  const sameYearPapers = Number(a.yp || 0);
  const label = raw > 0
    ? "same-year raw evidence"
    : sameYearPapers > 0
      ? "same-year imputed evidence"
      : "panel gap-filled year";
  const cls = raw > 0 ? "status-good" : sameYearPapers > 0 ? "status-muted" : "status-info";
  const span = a.ps || a.pe ? `${fmtInt(a.ps)}-${fmtInt(a.pe)}` : "";
  return `
    <span class="status-badge ${cls}">${label}</span>
    <div class="table-sub">${fmtInt(a.ip)} evidence papers at selected institution${span ? `; panel span ${escapeHtml(span)}` : ""}</div>
    <div class="table-sub">${fmtInt(sameYearPapers)} same-year papers${raw > 0 ? `; ${fmtInt(raw)} raw rows` : ""}</div>
  `;
}

function worksHtml(a) {
  const works = a.wk || [];
  if (!works.length) {
    return `<span class="table-sub">No classified publications found for this author in the browser data.</span>`;
  }
  const rows = works.map((w) => {
    const title = w.t || w.p;
    const field = w.f ? `${fieldLabel(w.f)} ${fmtPct(w.fp)}` : "field unavailable";
    const subfield = w.s ? `${subfieldLabel(w.s)} ${fmtPct(w.sp)}` : "subfield unavailable";
    const evidence = Number(w.raw || 0) > 0 ? "observed affiliation" : "imputed affiliation";
    const institutions = w.i ? `; institutions: ${w.i}` : "";
    return `
      <li>
        <a href="${workUrl(w.p)}" target="_blank" rel="noopener">${escapeHtml(title)}</a>
        <span class="paper-meta">${fmtInt(w.y)}; ${escapeHtml(field)}; ${escapeHtml(subfield)}; ${escapeHtml(evidence)}${escapeHtml(institutions)}</span>
      </li>
    `;
  }).join("");
  return `
    <details class="pub-details">
      <summary>${works.length} classified publications closest to ${escapeHtml(state.payload?.year || "")}</summary>
      <ol class="mini-list work-list">${rows}</ol>
    </details>
  `;
}

function selectedKey() {
  const inst = selectedInstitution();
  return `${inst?.institution_id || inst?.key || ""}-${selectedYear()}`;
}

function yearMeta() {
  const inst = selectedInstitution();
  const year = selectedYear();
  if (!inst || !year) return null;
  return state.meta.school_years.find((d) =>
    Number(d.year) === year
    && (d.institution_id === inst.institution_id || d.university_key === inst.key)
  );
}

function buildDropdowns() {
  state.institutionValues.clear();
  const instOptions = institutionOptions().map((u) => {
    const value = u.institution_id || u.key || u.name;
    state.institutionValues.set(value, u);
    state.institutionValues.set(institutionLabel(u), u);
    return `<option value="${escapeHtml(value)}">${escapeHtml(institutionLabel(u))}</option>`;
  });
  $("university-input").innerHTML = instOptions.join("");
  $("year-options").innerHTML = (state.meta.years || []).map((y) =>
    `<option value="${escapeHtml(y)}"></option>`
  ).join("");

  state.fieldValues.clear();
  const fields = ["COMP_ENGG", ...(state.meta.fields || [])];
  $("field-options").innerHTML = fields.map((code) => {
    const label = fieldLabel(code);
    state.fieldValues.set(label, code);
    state.fieldValues.set(code, code);
    return `<option value="${escapeHtml(label)}"></option>`;
  }).join("");

  const defaults = state.meta.defaults;
  const defaultInst = institutionOptions().find((u) =>
    u.key === defaults.university_key || u.institution_id === defaults.institution_id
  ) || institutionOptions()[0];
  $("university-input").value = defaultInst?.institution_id || defaultInst?.key || defaultInst?.name || "";
  $("year-input").value = String(defaults.year);
  $("field-input").value = fieldLabel(defaults.field);
  $("min-works").value = defaults.min_works;
  $("min-prob").value = Number(defaults.min_field_probability).toFixed(2);
}

function noDataHtml(inst, year) {
  const label = inst ? institutionLabel(inst) : "that institution";
  return `
    <div class="empty">
      No precomputed candidate file for ${escapeHtml(label)} in ${escapeHtml(year)}.
      <br>
      This static site only loads exported five-year panel snapshots for the selected institutions.
    </div>
  `;
}

async function loadSelectedYear() {
  const inst = selectedInstitution();
  const year = selectedYear();
  const meta = yearMeta();
  if (!meta) {
    state.payload = null;
    state.rows = [];
    state.filtered = [];
    $("count-badge").textContent = "no exported candidate file";
    $("results").innerHTML = noDataHtml(inst, year);
    return;
  }
  $("count-badge").textContent = "loading candidates...";
  $("results").innerHTML = `<div class="loader">Loading ${escapeHtml(meta.university)} ${meta.year}...</div>`;
  const payload = await fetch(meta.data_file).then((r) => {
    if (!r.ok) throw new Error(`Failed to load ${meta.data_file}: ${r.status}`);
    return r.json();
  });
  const currentInst = selectedInstitution();
  if ((currentInst?.institution_id || "") !== (payload.institution_id || "") || selectedYear() !== Number(payload.year)) return;
  state.payload = payload;
  state.rows = payload.authors || [];
  applyFilters();
}

function currentParams() {
  const minExportWorks = Number(state.meta?.export_filters?.min_openalex_works || state.meta?.defaults?.min_works || 0);
  return {
    field: selectedField(),
    minWorks: Math.max(minExportWorks, Number($("min-works").value || 0)),
    minProb: Number($("min-prob").value || 0),
    evidence: $("evidence-select").value,
    sortBy: $("sort-by").value,
    search: $("text-search").value.trim().toLowerCase(),
  };
}

function passes(a, params) {
  if (authorWorks(a) < params.minWorks) return false;
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
        OpenAlex-only view: authors are included when the author-institution-year panel attaches them to this university in this year.
        Years between an author's evidence years at the same institution are shown even when the author has no paper at that institution in the selected year.
        This online export keeps five-year snapshots and authors with at least ${fmtInt(state.meta?.export_filters?.min_openalex_works || state.meta?.defaults?.min_works || 0)} OpenAlex works.
        Faculty roster data are not used here.
      </p>
      <p class="active-filter">
        Current filter:
        <strong>${escapeHtml(fieldLabel(params.field))} >= ${fmtPct(params.minProb)}</strong>,
        and <strong>${fmtInt(params.minWorks)}+ OpenAlex works</strong>.
      </p>
      <div class="summary-grid summary-grid-compact">
        <div class="summary-primary">
          <strong>${fmtInt(state.filtered.length)}</strong>
          <span>authors displayed</span>
        </div>
        <div>
          <strong>${fmtInt(state.rows.length)}</strong>
          <span>author-institution panel rows at ${escapeHtml(p.university)} in ${p.year}</span>
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

function rowHtml(a, selectedFieldCode) {
  return `
    <tr>
      <td>
        <div class="table-title"><a href="${authorUrl(a.a)}" target="_blank" rel="noopener">${escapeHtml(a.n)}</a></div>
        <div class="table-sub">${escapeHtml(a.a)}</div>
      </td>
      <td>${metricsHtml(a)}</td>
      <td>${fieldsHtml(a, selectedFieldCode)}</td>
      <td>${subfieldsHtml(a)}</td>
      <td>${evidenceHtml(a)}</td>
      <td>${worksHtml(a)}</td>
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
        The evidence column separates same-year raw paper evidence, same-year imputed paper evidence, and gap-filled panel years.
      </p>
      <div class="table-wrap">
        <table class="data-table candidate-table">
          <thead>
            <tr>
              <th>OpenAlex author</th><th>Works/citations</th><th>Field probabilities</th><th>Subfield probabilities</th><th>Institution-year evidence</th><th>Works</th><th>Classifier span</th>
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
  const selectedFieldCode = selectedField();
  if (reset) {
    state.shown = 0;
    container.innerHTML = "";
  }
  const next = state.filtered.slice(state.shown, state.shown + PAGE);
  container.insertAdjacentHTML("beforeend", next.map((a) => rowHtml(a, selectedFieldCode)).join(""));
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
    xs.sort((a, b) => Number(b.ip || 0) - Number(a.ip || 0) || fieldProb(b, params.field) - fieldProb(a, params.field));
  } else if (params.sortBy === "name") {
    xs.sort((a, b) => String(a.n || "").localeCompare(String(b.n || "")));
  }
  state.filtered = xs;
  $("count-badge").textContent = `${fmtInt(xs.length)} OpenAlex authors displayed`;
  render();
}

function debounceLoad() {
  clearTimeout(state.loadTimer);
  state.loadTimer = setTimeout(loadSelectedYear, 250);
}

function attachEvents() {
  $("university-input").addEventListener("change", loadSelectedYear);
  $("year-input").addEventListener("input", debounceLoad);
  $("year-input").addEventListener("change", loadSelectedYear);
  ["field-input", "min-works", "min-prob", "evidence-select", "sort-by", "text-search"].forEach((id) => {
    $(id).addEventListener("input", applyFilters);
  });
  $("reset-btn").onclick = (e) => {
    e.preventDefault();
    const defaults = state.meta.defaults;
    const defaultInst = institutionOptions().find((u) =>
      u.key === defaults.university_key || u.institution_id === defaults.institution_id
    ) || institutionOptions()[0];
    $("university-input").value = defaultInst?.institution_id || defaultInst?.key || defaultInst?.name || "";
    $("year-input").value = String(defaults.year);
    $("field-input").value = fieldLabel(defaults.field);
    $("min-works").value = defaults.min_works;
    $("min-prob").value = Number(defaults.min_field_probability).toFixed(2);
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
