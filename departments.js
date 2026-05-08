// Department roster browser.

const PAGE = 80;
const state = {
  data: null,
  taxonomy: { fields: {} },
  department: null,
  filteredOpenAlex: [],
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

function subfieldLabel(code) {
  return state.taxonomy.subfields?.[code] || code || "subfield";
}

function fieldProb(author, code) {
  if (code === "COMP_ENGG") {
    return Number(author.field_prob_COMP || 0) + Number(author.field_prob_ENGG || 0);
  }
  return Number(author[`field_prob_${code}`] || 0);
}

function statusLabel(status) {
  if (status === "department_roster") return "in this roster";
  if (status === "same_department_other_year") return "same department, other years";
  if (status === "other_bleemer_roster") return "other faculty roster";
  return "not in roster";
}

function statusClass(status) {
  if (status === "department_roster") return "status-good";
  if (status === "same_department_other_year") return "status-info";
  if (status === "other_bleemer_roster") return "status-warn";
  return "status-muted";
}

function authorUrl(authorId) {
  return authorId ? `https://openalex.org/${encodeURIComponent(authorId)}` : "#";
}

function paperUrl(paperId) {
  return paperId ? `https://openalex.org/${encodeURIComponent(paperId)}` : "#";
}

function probChip(label, value) {
  if (!label) return "";
  return `<span class="prob-chip">${escapeHtml(label)} <strong>${fmtPct(value)}</strong></span>`;
}

function authorFieldHtml(a, thresholdField) {
  const top = [
    [a.field_top1, a.field_p1],
    [a.field_top2, a.field_p2],
    [a.field_top3, a.field_p3],
  ].filter(([code]) => code).map(([code, p]) => [fieldLabel(code), p]);
  return `
    <div class="chip-stack">${top.map(([label, p]) => probChip(label, p)).join("")}</div>
    <div class="table-sub">selected ${escapeHtml(fieldLabel(thresholdField))}: ${fmtPct(fieldProb(a, thresholdField))}</div>
  `;
}

function authorSubfieldHtml(a) {
  const top = [
    [a.subfield_top1, a.sp1],
    [a.subfield_top2, a.sp2],
    [a.subfield_top3, a.sp3],
  ].filter(([code]) => code).map(([code, p]) => [subfieldLabel(code), p]);
  if (!top.length) return `<span class="table-sub">No subfield probabilities in local paper predictions.</span>`;
  return `<div class="chip-stack">${top.map(([label, p]) => probChip(label, p)).join("")}</div>`;
}

function institutionHtml(a) {
  const xs = a.career_institutions || [];
  if (!xs.length) return `<span class="table-sub">No education-affiliation rows.</span>`;
  const visible = xs.slice(0, 5).map((x) => {
    const years = x.year_first && x.year_last ? ` (${x.year_first}-${x.year_last})` : "";
    return `<li><strong>${fmtInt(x.n_papers)}</strong> ${escapeHtml(x.name)}${escapeHtml(years)}</li>`;
  }).join("");
  return `<ol class="mini-list">${visible}</ol>`;
}

function metricsHtml(a) {
  if (!a) return "";
  const items = [
    ["sample pubs", a.n_papers],
    ["OpenAlex works", a.openalex_works_count],
    ["citations", a.openalex_cited_by_count],
    ["h-index", a.sciscinet_h_index],
  ].filter(([, value]) => value != null && value !== "");
  if (!items.length) return `<span class="table-sub">No counts available.</span>`;
  return `
    <div class="metric-stack">
      ${items.map(([label, value]) => `<div><strong>${fmtInt(value)}</strong><span>${escapeHtml(label)}</span></div>`).join("")}
    </div>
  `;
}

function publicationHtml(a) {
  const pubs = a.recent_publications || [];
  if (!pubs.length) return `<span class="table-sub">No classified publications found for this author.</span>`;
  const rows = pubs.map((p) => {
    const title = p.title || p.paper_id;
    const inst = p.assigned_institutions
      ? `<div class="table-sub">assigned institution: ${escapeHtml(p.assigned_institutions)}</div>`
      : `<div class="table-sub">assigned institution: not available</div>`;
    return `
      <li>
        <a href="${paperUrl(p.paper_id)}" target="_blank" rel="noopener">${escapeHtml(title)}</a>
        <div class="table-sub">${escapeHtml(p.year)} - ${escapeHtml(fieldLabel(p.field_top1))} ${fmtPct(p.field_p1)}; ${escapeHtml(subfieldLabel(p.subfield_top1))} ${fmtPct(p.sp1)}</div>
        ${inst}
      </li>
    `;
  }).join("");
  return `
    <details class="pub-details">
      <summary>${pubs.length} classified publications closest to ${state.department.audit_year}</summary>
      <ol class="mini-list">${rows}</ol>
    </details>
  `;
}

function currentFilterParams() {
  return {
    minPapers: Number($("min-papers").value || 0),
    minProb: Number($("min-prob").value || 0),
    minRosterYears: Number($("min-roster-years").value || 1),
    thresholdField: $("field-select").value,
    statuses: new Set(selectedStatuses()),
  };
}

function passesAuthorFilters(a, params, checkStatus = false) {
  if (!a) return false;
  if (checkStatus && !params.statuses.has(a.bleemer_status || "not_in_bleemer")) return false;
  if (Number(a.n_papers || 0) < params.minPapers) return false;
  if (fieldProb(a, params.thresholdField) < params.minProb) return false;
  return true;
}

function currentSummary(d) {
  const rows = state.filteredOpenAlex || [];
  const params = currentFilterParams();
  const rosterRows = d.bleemer_roster || [];
  const rosterRowsCurrent = rosterRows.filter((r) => Number(r.years_in_selected_department || 0) >= params.minRosterYears);
  const rosterTotal = rosterRows.length;
  const rosterCurrentTotal = rosterRowsCurrent.length;
  const rosterExcludedYears = Math.max(0, rosterTotal - rosterCurrentTotal);
  const rosterMatched = rosterRowsCurrent.filter((r) => r.matched_author_id).length;
  const rosterPass = rosterRowsCurrent.filter((r) => passesAuthorFilters(r.openalex_profile, params)).length;
  const rosterNotPass = Math.max(0, rosterCurrentTotal - rosterPass);
  const statusCount = (status) => rows.filter((r) => (r.bleemer_status || "not_in_bleemer") === status).length;
  const inDept = statusCount("department_roster");
  const sameDeptOtherYear = statusCount("same_department_other_year");
  const otherRoster = statusCount("other_bleemer_roster");
  const noRoster = statusCount("not_in_bleemer");
  return {
    rows,
    rosterTotal,
    rosterCurrentTotal,
    rosterExcludedYears,
    rosterMatched,
    rosterPass,
    rosterNotPass,
    inDept,
    sameDeptOtherYear,
    otherRoster,
    noRoster,
    extraNotInCurrentRoster: Math.max(0, rows.length - inDept),
  };
}

function filterSentence(d) {
  const params = currentFilterParams();
  const selected = fieldLabel(params.thresholdField);
  const target = fieldLabel(d.target_field);
  const warning = params.thresholdField !== d.target_field
    ? `<span class="filter-warning">This department defaults to ${escapeHtml(target)}, but the current filter is ${escapeHtml(selected)}.</span>`
    : "";
  return `
    <p class="active-filter">
      Current OpenAlex filter:
      <strong>${escapeHtml(selected)} >= ${fmtPct(params.minProb)}</strong>,
      <strong>${fmtInt(params.minPapers)}+ sample publications</strong>,
      and <strong>${fmtInt(params.minRosterYears)}+ roster year${params.minRosterYears === 1 ? "" : "s"}</strong>.
      ${warning}
    </p>
  `;
}

function selectedStatuses() {
  return Array.from(document.querySelectorAll(".status-filter:checked")).map((x) => x.value);
}

function buildDepartmentDropdown() {
  const select = $("dept-select");
  select.innerHTML = "";
  state.data.departments.forEach((d) => {
    select.insertAdjacentHTML(
      "beforeend",
      `<option value="${escapeHtml(d.dept_key)}">${escapeHtml(d.university)} - ${escapeHtml(d.department)} (${d.audit_year})</option>`
    );
  });
}

async function loadDepartment(meta) {
  if (meta.openalex_authors) return meta;
  const payload = await fetch(meta.data_file).then((r) => {
    if (!r.ok) throw new Error(`Failed to load ${meta.data_file}: ${r.status}`);
    return r.json();
  });
  Object.assign(meta, payload.department);
  return meta;
}

async function setDepartment(key) {
  const meta = state.data.departments.find((d) => d.dept_key === key) || state.data.departments[0];
  state.department = meta;
  $("dept-select").value = meta.dept_key;
  $("field-select").value = meta.target_field || "COMP";
  $("count-badge").textContent = "loading department data...";
  $("results").innerHTML = `<div class="loader">Loading ${escapeHtml(meta.university)} - ${escapeHtml(meta.department)}...</div>`;
  try {
    const loaded = await loadDepartment(meta);
    if (state.department.dept_key !== loaded.dept_key) return;
    state.department = loaded;
    applyFilters();
  } catch (err) {
    $("results").innerHTML = `<div class="empty">Failed to load department data:<br><pre>${escapeHtml(err.message)}</pre></div>`;
    console.error(err);
  }
}

function summaryHtml(d) {
  const s = currentSummary(d);
  const rosterMatchPct = fmtPct(s.rosterMatched / Math.max(1, s.rosterCurrentTotal));
  const openAlexRosterPct = fmtPct(s.inDept / Math.max(1, s.rows.length));
  const rosterPassPct = fmtPct(s.rosterPass / Math.max(1, s.rosterCurrentTotal));
  return `
    <section class="dept-summary">
      <div>
        <h2>${escapeHtml(d.university)} - ${escapeHtml(d.department)}, ${d.audit_year}</h2>
        <p>
          Faculty roster: ${fmtInt(s.rosterTotal)} people. The percentages below use the current filters.
        </p>
        ${filterSentence(d)}
      </div>
      <div class="summary-grid summary-grid-compact">
        <div class="summary-primary">
          <strong>${rosterMatchPct}</strong>
          <span>faculty roster matched to OpenAlex (${fmtInt(s.rosterMatched)} of ${fmtInt(s.rosterCurrentTotal)})</span>
        </div>
        <div class="summary-primary">
          <strong>${openAlexRosterPct}</strong>
          <span>displayed OpenAlex authors in this roster (${fmtInt(s.inDept)} of ${fmtInt(s.rows.length)})</span>
        </div>
        <div>
          <strong>${rosterPassPct}</strong>
          <span>faculty roster passing current OpenAlex filters (${fmtInt(s.rosterPass)} of ${fmtInt(s.rosterCurrentTotal)})</span>
        </div>
        <div>
          <strong>${fmtInt(s.extraNotInCurrentRoster)}</strong>
          <span>displayed OpenAlex authors not in this roster</span>
        </div>
      </div>
      <p class="summary-footnote">
        Additional displayed OpenAlex authors: ${fmtInt(s.sameDeptOtherYear)} in the same department in other roster years,
        ${fmtInt(s.otherRoster)} in another faculty roster in ${d.audit_year},
        and ${fmtInt(s.noRoster)} not found in faculty rosters.
        The minimum-years filter excludes ${fmtInt(s.rosterExcludedYears)} of ${fmtInt(s.rosterTotal)} roster people.
      </p>
    </section>
  `;
}

function sourceNoteHtml(d) {
  return `
    <section class="source-note">
      <div><strong>Faculty roster data</strong><span>Names, positions, and department membership in ${d.audit_year} come from the manually audited California faculty roster slice.</span></div>
      <div><strong>OpenAlex data</strong><span>OpenAlex names, author links, publications, institution histories, and field/subfield predictions come from SciSciNet/OpenAlex plus our classifier outputs.</span></div>
    </section>
  `;
}

function rosterTableHtml(rows) {
  const thresholdField = $("field-select").value;
  const params = currentFilterParams();
  const visibleRows = rows.filter((r) => Number(r.years_in_selected_department || 0) >= params.minRosterYears);
  const body = visibleRows.map((r) => {
    const status = r.audit_status || "";
    const a = r.openalex_profile;
    const pass = passesAuthorFilters(a, currentFilterParams());
    const found = a
      ? `<div class="table-title"><a href="${authorUrl(a.AuthorID)}" target="_blank" rel="noopener">${escapeHtml(a.display_name || r.matched_display_name)}</a></div>
         <div class="table-sub">${escapeHtml(a.AuthorID)}</div>
         <span class="status-badge ${pass ? "status-good" : "status-muted"}">${pass ? "passes filters" : "does not pass filters"}</span>`
      : r.matched_author_id
        ? `<span class="status-badge status-warn">matched, no local profile</span><div class="table-sub">${escapeHtml(r.matched_display_name || r.matched_author_id)}</div>`
      : `<span class="status-badge status-muted">no match</span>`;
    return `
      <tr>
        <td>
          <div class="table-title">${escapeHtml(r.bleemer_name)}</div>
          <div class="table-sub">${r.is_research_role ? "research" : "other"}</div>
          <div class="table-sub">${fmtInt(r.years_in_selected_department)} years in selected department${r.selected_department_min_year ? ` (${r.selected_department_min_year}-${r.selected_department_max_year})` : ""}</div>
        </td>
        <td>${escapeHtml(r.audit_position_label || "")}</td>
        <td class="dept-cell">${escapeHtml(r.cluster_departments || "")}</td>
        <td>${found}</td>
        <td>${a ? metricsHtml(a) : ""}</td>
        <td>${a ? authorFieldHtml(a, thresholdField) : ""}</td>
        <td>${a ? authorSubfieldHtml(a) : ""}</td>
        <td>${a ? institutionHtml(a) : ""}</td>
        <td>${a ? publicationHtml(a) : ""}</td>
        <td>${escapeHtml(status.replaceAll("_", " "))}</td>
      </tr>`;
  }).join("");
  return `
    <section class="browser-panel">
      <h3>Faculty roster for this department-year</h3>
      <p class="panel-note">Course-catalog roster data. The table applies the minimum-years roster filter, currently showing ${fmtInt(visibleRows.length)} of ${fmtInt(rows.length)} people.</p>
      <div class="table-wrap">
        <table class="data-table roster-table">
          <thead>
            <tr>
              <th>Roster person</th><th>Position</th><th>Departments</th><th>OpenAlex match</th><th>Works/citations</th><th>Field probabilities</th><th>Subfields</th><th>Career institutions</th><th>Recent publications</th><th>Audit status</th>
            </tr>
          </thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    </section>
  `;
}

function openAlexRowHtml(a, thresholdField) {
  const status = a.bleemer_status || "not_in_bleemer";
  const rosterText = status === "department_roster"
    ? `${a.department_bleemer_names || ""} ${a.department_bleemer_positions ? " - " + a.department_bleemer_positions : ""}`
    : status === "same_department_other_year"
      ? `${a.same_department_names || ""} ${a.same_department_year_ranges ? " - years " + a.same_department_year_ranges : ""}${a.same_department_positions ? " - " + a.same_department_positions : ""}`
    : status === "other_bleemer_roster"
      ? `${a.university_bleemer_locations || ""}${a.university_bleemer_positions ? " - " + a.university_bleemer_positions : ""}`
      : "";
  return `
    <tr>
      <td><span class="status-badge ${statusClass(status)}">${statusLabel(status)}</span></td>
      <td>
        <div class="table-title"><a href="${authorUrl(a.AuthorID)}" target="_blank" rel="noopener">${escapeHtml(a.display_name)}</a></div>
        <div class="table-sub">${escapeHtml(a.AuthorID)}</div>
      </td>
      <td>${fmtInt(a.n_papers)}</td>
      <td>${authorFieldHtml(a, thresholdField)}</td>
      <td>${authorSubfieldHtml(a)}</td>
      <td>${fmtInt(a.papers_at_school_year)}</td>
      <td>${institutionHtml(a)}</td>
      <td>${publicationHtml(a)}</td>
      <td>${escapeHtml(rosterText)}</td>
    </tr>
  `;
}

function renderOpenAlex(reset = true) {
  const container = $("openalex-rows");
  const thresholdField = $("field-select").value;
  if (reset) {
    state.shown = 0;
    container.innerHTML = "";
  }
  const next = state.filteredOpenAlex.slice(state.shown, state.shown + PAGE);
  container.insertAdjacentHTML("beforeend", next.map((a) => openAlexRowHtml(a, thresholdField)).join(""));
  state.shown += next.length;
  const btn = $("more-btn");
  if (btn) {
    btn.disabled = state.shown >= state.filteredOpenAlex.length;
    btn.textContent = btn.disabled ? "End of results" : `Show ${PAGE} more`;
  }
}

function openAlexTableHtml() {
  const d = state.department;
  return `
    <section class="browser-panel">
      <h3>OpenAlex authors assigned to ${escapeHtml(d.university)} in ${d.audit_year}</h3>
      <p class="panel-note">
        Rows come from the original imputed paper-author institution file. "Selected-university papers" is the number of distinct papers in ${d.audit_year}
        where this author is assigned to ${escapeHtml(d.university)}. Field filters use career-level author probabilities.
      </p>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>Roster status</th><th>OpenAlex author</th><th>Total pubs</th><th>Field probabilities</th><th>Subfields</th><th>Selected-university papers</th><th>Career institutions</th><th>Recent publications</th><th>Roster match</th>
            </tr>
          </thead>
          <tbody id="openalex-rows"></tbody>
        </table>
      </div>
      <button class="show-more" id="more-btn">Show ${PAGE} more</button>
    </section>
  `;
}

function applyFilters() {
  const d = state.department;
  if (!d) return;
  const params = currentFilterParams();
  const thresholdField = params.thresholdField;
  const sortBy = $("sort-by").value;
  const search = $("text-search").value.trim().toLowerCase();

  let xs = d.openalex_authors.slice().filter((a) => {
    if (!passesAuthorFilters(a, params, true)) return false;
    if (search) {
      const hay = [
        a.display_name, a.AuthorID, a.department_bleemer_names,
        a.department_bleemer_positions, a.university_bleemer_names,
        a.university_bleemer_departments, a.university_bleemer_locations,
        a.same_department_names, a.same_department_positions,
        a.same_department_year_ranges,
      ].filter(Boolean).join(" ").toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });

  const statusRank = { department_roster: 0, same_department_other_year: 1, other_bleemer_roster: 2, not_in_bleemer: 3 };
  if (sortBy === "field_desc") {
    xs.sort((a, b) => fieldProb(b, thresholdField) - fieldProb(a, thresholdField) || Number(b.n_papers || 0) - Number(a.n_papers || 0));
  } else if (sortBy === "papers_desc") {
    xs.sort((a, b) => Number(b.n_papers || 0) - Number(a.n_papers || 0));
  } else if (sortBy === "school_papers_desc") {
    xs.sort((a, b) => Number(b.papers_at_school_year || 0) - Number(a.papers_at_school_year || 0));
  } else if (sortBy === "bleemer_first") {
    xs.sort((a, b) => (statusRank[a.bleemer_status] ?? 9) - (statusRank[b.bleemer_status] ?? 9) || fieldProb(b, thresholdField) - fieldProb(a, thresholdField));
  } else if (sortBy === "name") {
    xs.sort((a, b) => String(a.display_name || "").localeCompare(String(b.display_name || "")));
  }

  state.filteredOpenAlex = xs;
  $("count-badge").textContent = `${xs.length.toLocaleString()} OpenAlex authors displayed`;
  render(true);
}

function render() {
  const d = state.department;
  const main = $("results");
  main.innerHTML = `
    ${summaryHtml(d)}
    ${sourceNoteHtml(d)}
    <div class="browser-grid">
      ${rosterTableHtml(d.bleemer_roster)}
      ${openAlexTableHtml()}
    </div>
  `;
  $("more-btn").onclick = () => renderOpenAlex(false);
  renderOpenAlex(true);
}

function attachEvents() {
  $("dept-select").addEventListener("change", () => setDepartment($("dept-select").value));
  ["field-select", "min-papers", "min-prob", "min-roster-years", "sort-by", "text-search"].forEach((id) => {
    $(id).addEventListener("input", applyFilters);
  });
  document.querySelectorAll(".status-filter").forEach((el) => el.addEventListener("change", applyFilters));
  $("reset-btn").onclick = (e) => {
    e.preventDefault();
    $("min-papers").value = state.data.defaults.min_papers;
    $("min-prob").value = Number(state.data.defaults.field_probability).toFixed(2);
    $("min-roster-years").value = state.data.defaults.min_roster_department_years || 1;
    $("sort-by").value = "field_desc";
    $("text-search").value = "";
    document.querySelectorAll(".status-filter").forEach((el) => { el.checked = true; });
    $("field-select").value = state.department.target_field || "COMP";
    applyFilters();
  };
}

async function init() {
  try {
    const [data, taxonomy] = await Promise.all([
      fetch("departments.json").then((r) => r.json()),
      fetch("taxonomy.json").then((r) => r.json()),
    ]);
    state.data = data;
    state.taxonomy = taxonomy;
    $("min-papers").value = data.defaults.min_papers;
    $("min-prob").value = Number(data.defaults.field_probability).toFixed(2);
    $("min-roster-years").value = data.defaults.min_roster_department_years || 1;
    buildDepartmentDropdown();
    attachEvents();
    await setDepartment(data.departments[0].dept_key);
  } catch (err) {
    $("results").innerHTML = `<div class="empty">Failed to load department data:<br><pre>${escapeHtml(err.message)}</pre></div>`;
    console.error(err);
  }
}

init();
