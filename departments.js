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
  if (code === "COMP_ENGG") return "Computer Science or Engineering";
  return state.taxonomy.fields[code] || code || "field";
}

function fieldProb(author, code) {
  if (code === "COMP_ENGG") {
    return Number(author.field_prob_COMP || 0) + Number(author.field_prob_ENGG || 0);
  }
  return Number(author[`field_prob_${code}`] || 0);
}

function statusLabel(status) {
  if (status === "department_roster") return "in this roster";
  if (status === "other_bleemer_roster") return "other Bleemer roster";
  return "not in Bleemer";
}

function statusClass(status) {
  if (status === "department_roster") return "status-good";
  if (status === "other_bleemer_roster") return "status-warn";
  return "status-muted";
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

function setDepartment(key) {
  state.department = state.data.departments.find((d) => d.dept_key === key) || state.data.departments[0];
  $("dept-select").value = state.department.dept_key;
  $("field-select").value = state.department.target_field || "COMP";
  applyFilters();
}

function summaryHtml(d) {
  const totalBleemer = Number(d.clusters || d.bleemer_roster.length || 0);
  const matched = Number(d.matched || 0);
  const defaultCount = Number(d.default_openalex_count || 0);
  const defaultDept = Number(d.default_matched_department_count || 0);
  const defaultOther = Number(d.default_other_roster_count || 0);
  const missingDefault = Math.max(0, defaultCount - defaultDept - defaultOther);
  return `
    <section class="dept-summary">
      <div>
        <h2>${escapeHtml(d.university)} - ${escapeHtml(d.department)}, ${d.audit_year}</h2>
        <p>
          Bleemer roster: ${fmtInt(totalBleemer)} people, ${fmtInt(matched)} matched to OpenAlex in the manual audit
          (${fmtPct(d.match_share)}).
        </p>
      </div>
      <div class="summary-grid">
        <div><strong>${fmtInt(defaultCount)}</strong><span>OpenAlex authors at default filters</span></div>
        <div><strong>${fmtInt(defaultDept)}</strong><span>also in this Bleemer department</span></div>
        <div><strong>${fmtInt(defaultOther)}</strong><span>in another Bleemer roster</span></div>
        <div><strong>${fmtInt(missingDefault)}</strong><span>not found in Bleemer</span></div>
      </div>
    </section>
  `;
}

function rosterTableHtml(rows) {
  const body = rows.map((r) => {
    const status = r.audit_status || "";
    const found = r.matched_author_id
      ? `<span class="status-badge status-good">OpenAlex</span>`
      : `<span class="status-badge status-muted">no match</span>`;
    return `
      <tr>
        <td>${escapeHtml(r.bleemer_name)}</td>
        <td>${escapeHtml(r.audit_position_label || "")}</td>
        <td>${escapeHtml(r.cluster_departments || "")}</td>
        <td>${r.is_research_role ? "research" : "other"}</td>
        <td>${found}</td>
        <td>${escapeHtml(r.matched_display_name || "")}</td>
        <td>${escapeHtml(status.replaceAll("_", " "))}</td>
      </tr>`;
  }).join("");
  return `
    <section class="browser-panel">
      <h3>Bleemer faculty roster</h3>
      <p class="panel-note">Course-catalog roster for this department-year. The match column reflects the manual department audit.</p>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>Name</th><th>Position</th><th>Departments</th><th>Role</th><th>Matched?</th><th>OpenAlex name</th><th>Audit status</th>
            </tr>
          </thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    </section>
  `;
}

function openAlexRowHtml(a, thresholdField) {
  const p = fieldProb(a, thresholdField);
  const status = a.bleemer_status || "not_in_bleemer";
  const rosterText = status === "department_roster"
    ? `${a.department_bleemer_names || ""} ${a.department_bleemer_positions ? "· " + a.department_bleemer_positions : ""}`
    : status === "other_bleemer_roster"
      ? `${a.university_bleemer_names || ""} ${a.university_bleemer_departments ? "· " + a.university_bleemer_departments : ""}`
      : "";
  return `
    <tr>
      <td><span class="status-badge ${statusClass(status)}">${statusLabel(status)}</span></td>
      <td>
        <div class="table-title">${escapeHtml(a.display_name)}</div>
        <div class="table-sub">${escapeHtml(a.AuthorID)}</div>
      </td>
      <td>${fmtInt(a.n_papers)}</td>
      <td>${fmtPct(p)}</td>
      <td>${escapeHtml(fieldLabel(a.field_top1))}<div class="table-sub">${fmtPct(a.field_p1)}</div></td>
      <td>${fmtInt(a.papers_at_school_year)}</td>
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
  return `
    <section class="browser-panel">
      <h3>OpenAlex authors assigned to this school in 1985</h3>
      <p class="panel-note">
        Rows come from the original imputed paper-author institution file. The field threshold uses career-level author field probabilities.
      </p>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>Bleemer status</th><th>Author</th><th>Publications</th><th>Threshold field prob.</th><th>Top field</th><th>School papers in 1985</th><th>Roster link</th>
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
  const minPapers = Number($("min-papers").value || 0);
  const minProb = Number($("min-prob").value || 0);
  const thresholdField = $("field-select").value;
  const statuses = new Set(selectedStatuses());
  const sortBy = $("sort-by").value;
  const search = $("text-search").value.trim().toLowerCase();

  let xs = d.openalex_authors.slice().filter((a) => {
    if (!statuses.has(a.bleemer_status || "not_in_bleemer")) return false;
    if (Number(a.n_papers || 0) < minPapers) return false;
    if (fieldProb(a, thresholdField) < minProb) return false;
    if (search) {
      const hay = [
        a.display_name, a.AuthorID, a.department_bleemer_names,
        a.department_bleemer_positions, a.university_bleemer_names,
        a.university_bleemer_departments,
      ].filter(Boolean).join(" ").toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });

  const statusRank = { department_roster: 0, other_bleemer_roster: 1, not_in_bleemer: 2 };
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
  $("count-badge").textContent = `${xs.length.toLocaleString()} OpenAlex authors match`;
  render(true);
}

function render() {
  const d = state.department;
  const main = $("results");
  main.innerHTML = `
    ${summaryHtml(d)}
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
  ["field-select", "min-papers", "min-prob", "sort-by", "text-search"].forEach((id) => {
    $(id).addEventListener("input", applyFilters);
  });
  document.querySelectorAll(".status-filter").forEach((el) => el.addEventListener("change", applyFilters));
  $("reset-btn").onclick = (e) => {
    e.preventDefault();
    $("min-papers").value = state.data.defaults.min_papers;
    $("min-prob").value = Number(state.data.defaults.field_probability).toFixed(2);
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
    buildDepartmentDropdown();
    attachEvents();
    setDepartment(data.departments[0].dept_key);
  } catch (err) {
    $("results").innerHTML = `<div class="empty">Failed to load department data:<br><pre>${escapeHtml(err.message)}</pre></div>`;
    console.error(err);
  }
}

init();
