// Author classifier explorer.

const PAGE = 8;
const state = {
  authors: [],
  taxonomy: { fields: {}, subfields: {} },
  filtered: [],
  shown: 0,
};

const $ = (id) => document.getElementById(id);

function fmtPct(p) {
  if (p == null) return "—";
  return (100 * p).toFixed(1) + "%";
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"})[c]);
}

function shortName(code, table) {
  return table[code] || code || "—";
}

function topNonNull(items, probs, n) {
  const out = [];
  for (let i = 0; i < items.length && out.length < n; i++) {
    if (items[i] != null && items[i] !== "" && probs[i] != null) {
      out.push([items[i], probs[i]]);
    }
  }
  return out;
}

function topMatchStatus(modelTop1, llmList) {
  if (!llmList || llmList.length === 0) return "none";
  if (modelTop1 === llmList[0]) return "match";
  if (llmList.includes(modelTop1)) return "partial";
  return "miss";
}

function llmFields(a) {
  return [a.llm_field, a.llm_field_alt, a.llm_secondary_field].filter(Boolean);
}

function llmSubfields(a) {
  return [a.llm_subfield, a.llm_subfield_alt, a.llm_secondary_subfield].filter(Boolean);
}

function renderRows(tops, table, status, scale = 1) {
  return tops.map(([code, prob], i) => {
    const cls = i === 0 ? `row top1 ${status}` : "row";
    const w = Math.min(100, prob * 100 * scale).toFixed(0);
    return `
      <div class="${cls}">
        <span class="name">${escapeHtml(shortName(code, table))}</span>
        <span class="bar"><span style="width: ${w}%"></span></span>
        <span class="prob">${fmtPct(prob)}</span>
      </div>`;
  }).join("");
}

function renderLlm(items, table, conf) {
  if (!items || items.length === 0) return "<span class='muted'>—</span>";
  return items.map((c, i) => `
    <div class="row llm-row${i === 0 ? " llm-top1" : ""}">
      <span class="name">${escapeHtml(shortName(c, table))}</span>
    </div>`).join("")
    + (conf != null ? `<div class="conf-line">LLM confidence: ${conf.toFixed(0)}</div>` : "");
}

function renderPapers(papers) {
  if (!papers || papers.length === 0) return "";
  const rows = papers.slice(0, 12).map((p) => {
    const bits = [
      p.year ? String(p.year) : "?",
      p.source_name ? escapeHtml(p.source_name) : "",
    ].filter(Boolean).join(" · ");
    return `<li><span class="paper-title">${escapeHtml(p.title || "(no title)")}</span><span class="paper-meta">${bits}</span></li>`;
  }).join("");
  return `<ol class="author-papers">${rows}</ol>`;
}

function renderCard(a) {
  const fields = state.taxonomy.fields;
  const subfields = state.taxonomy.subfields;
  const fieldTops = topNonNull(
    [a.field_top1, a.field_top2, a.field_top3],
    [a.field_p1, a.field_p2, a.field_p3], 3);
  const subTops = topNonNull(
    [a.subfield_top1, a.subfield_top2, a.subfield_top3, a.subfield_top4, a.subfield_top5],
    [a.sp1, a.sp2, a.sp3, a.sp4, a.sp5], 5);
  const fStatus = topMatchStatus(a.field_top1, llmFields(a));
  const sStatus = topMatchStatus(a.subfield_top1, llmSubfields(a));
  const yearSpan = [a.year_first, a.year_last].filter((x) => x != null).join("–");
  const byline = [
    a.AuthorID,
    `${a.n_papers?.toLocaleString() || "0"} papers`,
    yearSpan,
    a.paper_bucket ? `bucket ${a.paper_bucket}` : "",
  ].filter(Boolean).join(" · ");
  const badges = [
    a.sample_source ? `<span class="badge">${escapeHtml(a.sample_source)}</span>` : "",
    a.llm_interdisciplinary ? `<span class="badge active">interdisciplinary by LLM</span>` : "",
  ].join("");
  const llmFieldBlock = a.llm_field
    ? `<div class="llm-side"><h5>LLM said</h5>${renderLlm(llmFields(a), fields, a.llm_field_conf)}</div>`
    : "";
  const llmSubBlock = a.llm_subfield
    ? `<div class="llm-side"><h5>LLM said</h5>${renderLlm(llmSubfields(a), subfields, a.llm_subfield_conf)}</div>`
    : "";

  return `
    <article class="card author-card" data-id="${escapeHtml(a.AuthorID)}">
      <div class="title">${escapeHtml(a.AuthorName || "(unknown author)")}</div>
      <div class="byline">${escapeHtml(byline)}</div>
      <div class="badges">${badges}</div>
      <div class="author-meta">
        ${a.top_institutions ? `<div><strong>Affiliations:</strong> ${escapeHtml(a.top_institutions)}</div>` : ""}
        ${a.top_journals ? `<div><strong>Journals:</strong> ${escapeHtml(a.top_journals)}</div>` : ""}
      </div>
      <div class="preds">
        <div class="pred-col">
          <h4>Career Field</h4>
          <div class="pred-pair">
            <div class="model-side"><h5>Model top 3</h5>${renderRows(fieldTops, fields, fStatus)}</div>
            ${llmFieldBlock}
          </div>
        </div>
        <div class="pred-col">
          <h4>Career Subfield</h4>
          <div class="pred-pair">
            <div class="model-side"><h5>Model top 5</h5>${renderRows(subTops, subfields, sStatus, 1.5)}</div>
            ${llmSubBlock}
          </div>
        </div>
      </div>
      ${renderPapers(a.papers)}
    </article>
  `;
}

function render(reset = true) {
  const main = $("results");
  if (reset) {
    state.shown = 0;
    main.innerHTML = "";
  }
  $("count-badge").textContent = `${state.filtered.length.toLocaleString()} authors match`;
  if (state.filtered.length === 0) {
    main.innerHTML = `<div class="empty">No authors match these filters.</div>`;
    return;
  }
  const next = state.filtered.slice(state.shown, state.shown + PAGE);
  const html = next.map(renderCard).join("");
  if (reset) {
    main.innerHTML = html + `<button class="show-more" id="more-btn">Show ${PAGE} more</button>`;
  } else {
    $("more-btn").insertAdjacentHTML("beforebegin", html);
  }
  state.shown += next.length;
  const btn = $("more-btn");
  if (btn) {
    btn.disabled = state.shown >= state.filtered.length;
    btn.textContent = btn.disabled ? "End of results" : `Show ${PAGE} more`;
    btn.onclick = () => render(false);
  }
}

function applyFilters() {
  const bucket = $("filter-bucket").value;
  const field = $("filter-field").value;
  const subfield = $("filter-subfield").value;
  const cMin = parseFloat($("conf-field-min").value || "0");
  const cMax = parseFloat($("conf-field-max").value || "1");
  const sortBy = $("sort-by").value;
  const agree = document.querySelector('input[name="agree"]:checked').value;
  const search = $("text-search").value.trim().toLowerCase();
  let xs = state.authors.slice();
  xs = xs.filter((a) => {
    if (bucket && a.paper_bucket !== bucket) return false;
    if (field && a.field_top1 !== field) return false;
    if (subfield && a.subfield_top1 !== subfield) return false;
    if (a.field_p1 == null || a.field_p1 < cMin || a.field_p1 > cMax) return false;
    if (agree !== "any") {
      const fStatus = topMatchStatus(a.field_top1, llmFields(a));
      const sStatus = topMatchStatus(a.subfield_top1, llmSubfields(a));
      if (agree === "field_match" && fStatus !== "match") return false;
      if (agree === "field_partial" && fStatus !== "partial") return false;
      if (agree === "field_miss" && fStatus !== "miss") return false;
      if (agree === "sub_match" && sStatus !== "match") return false;
      if (agree === "sub_partial" && sStatus !== "partial") return false;
      if (agree === "sub_miss" && sStatus !== "miss") return false;
    }
    if (search) {
      const paperText = (a.papers || []).map((p) => p.title || "").join(" ");
      const hay = `${a.AuthorName || ""} ${a.top_institutions || ""} ${paperText}`.toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });
  if (sortBy === "random") {
    for (let i = xs.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [xs[i], xs[j]] = [xs[j], xs[i]];
    }
  } else if (sortBy === "lowfield") {
    xs.sort((a, b) => (a.field_p1 ?? 9) - (b.field_p1 ?? 9));
  } else if (sortBy === "highfield") {
    xs.sort((a, b) => (b.field_p1 ?? -1) - (a.field_p1 ?? -1));
  } else if (sortBy === "papers_desc") {
    xs.sort((a, b) => (b.n_papers ?? 0) - (a.n_papers ?? 0));
  } else if (sortBy === "papers_asc") {
    xs.sort((a, b) => (a.n_papers ?? 0) - (b.n_papers ?? 0));
  }
  state.filtered = xs;
  render(true);
}

function buildDropdowns() {
  Object.entries(state.taxonomy.fields).sort((a, b) => a[1].localeCompare(b[1]))
    .forEach(([code, name]) => $("filter-field").insertAdjacentHTML("beforeend",
      `<option value="${code}">${escapeHtml(name)}</option>`));
  Object.entries(state.taxonomy.subfields)
    .map(([code, name]) => [code, name, state.taxonomy.fields[code.split("_")[0]] || code])
    .sort((a, b) => a[2].localeCompare(b[2]) || a[1].localeCompare(b[1]))
    .forEach(([code, name, parent]) => $("filter-subfield").insertAdjacentHTML("beforeend",
      `<option value="${code}">${escapeHtml(parent)} &rsaquo; ${escapeHtml(name)}</option>`));
}

function attachEvents() {
  ["filter-bucket","filter-field","filter-subfield","conf-field-min","conf-field-max","sort-by","text-search"]
    .forEach((id) => $(id).addEventListener("input", applyFilters));
  document.querySelectorAll('input[name="agree"]').forEach((el) => el.addEventListener("change", applyFilters));
  $("random-btn").onclick = (e) => {
    e.preventDefault();
    $("sort-by").value = "random";
    applyFilters();
  };
  $("reset-btn").onclick = (e) => {
    e.preventDefault();
    $("filter-bucket").value = "";
    $("filter-field").value = "";
    $("filter-subfield").value = "";
    $("conf-field-min").value = "0.00";
    $("conf-field-max").value = "1.00";
    $("text-search").value = "";
    $("sort-by").value = "random";
    document.querySelector('input[name="agree"][value="any"]').checked = true;
    applyFilters();
  };
}

async function init() {
  try {
    const [aa, tx] = await Promise.all([
      fetch("authors.json").then((r) => r.json()),
      fetch("taxonomy.json").then((r) => r.json()),
    ]);
    state.authors = aa;
    state.taxonomy = tx;
    const judged = aa.filter((a) => a.llm_field).length;
    $("data-source").textContent = `${aa.length.toLocaleString()} authors (${judged.toLocaleString()} LLM judged)`;
    buildDropdowns();
    attachEvents();
    applyFilters();
  } catch (err) {
    $("results").innerHTML = `<div class="empty">Failed to load <code>authors.json</code> / <code>taxonomy.json</code>:<br><pre>${escapeHtml(err.message)}</pre></div>`;
    console.error(err);
  }
}

init();
