// Classifier explorer: filter/sort N papers, render cards.

const PAGE = 5;
const state = {
  papers: [],
  taxonomy: { fields: {}, subfields: {} },
  filtered: [],
  shown: 0,
};

const $ = (id) => document.getElementById(id);

function fmtPct(p) {
  if (p == null) return "—";
  return (100 * p).toFixed(1) + "%";
}

function shortName(code, table) {
  return table[code] || code;
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"})[c]);
}

function formatAuthors(authors) {
  if (!authors || authors.length === 0) return "";
  const names = authors.slice(0, 4).map((a) => a.name).filter(Boolean);
  const more = authors.length > 4 ? ` (+${authors.length - 4} more)` : "";
  return names.join(", ") + more;
}

function topInst(authors) {
  if (!authors) return "";
  for (const a of authors) {
    if (a.inst) return a.inst;
  }
  return "";
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

// Status of a model top-1 prediction relative to LLM labels:
//   "match"   — model top-1 == LLM top-1 (green)
//   "partial" — model top-1 is in LLM's alternative list but not its top-1 (yellow)
//   "miss"    — model top-1 not in LLM's list at all (orange)
//   "none"    — paper not in training set (no LLM label to compare against)
function topMatchStatus(modelTop1, llmList) {
  if (!llmList || llmList.length === 0) return "none";
  if (modelTop1 === llmList[0]) return "match";
  if (llmList.includes(modelTop1)) return "partial";
  return "miss";
}

function renderCard(p) {
  const fieldNames = state.taxonomy.fields;
  const subNames = state.taxonomy.subfields;
  const fieldTops = topNonNull(
    [p.field_top1, p.field_top2, p.field_top3],
    [p.field_p1, p.field_p2, p.field_p3], 3);
  const subTops = topNonNull(
    [p.subfield_top1, p.subfield_top2, p.subfield_top3, p.subfield_top4, p.subfield_top5],
    [p.sp1, p.sp2, p.sp3, p.sp4, p.sp5], 5);

  const llm = p.in_training ? p : null;
  const llmFields = (llm && llm.llm_fields) || [];
  const llmSubs = (llm && llm.llm_subfields) || [];

  const fieldStatus = llm ? topMatchStatus(p.field_top1, llmFields) : "none";
  const subStatus = llm ? topMatchStatus(p.subfield_top1, llmSubs) : "none";

  const renderRow = (code, prob, table, isTop1, status, barScale = 1) => {
    const cls = isTop1 ? `row top1 ${status}` : "row";
    const w = Math.min(100, prob * 100 * barScale).toFixed(0);
    return `
      <div class="${cls}">
        <span class="name">${escapeHtml(shortName(code, table))}</span>
        <span class="bar"><span style="width: ${w}%"></span></span>
        <span class="prob">${fmtPct(prob)}</span>
      </div>`;
  };

  const fieldRows = fieldTops.map(([code, prob], i) =>
    renderRow(code, prob, fieldNames, i === 0, fieldStatus, 1)).join("");
  const subRows = subTops.map(([code, prob], i) =>
    renderRow(code, prob, subNames, i === 0, subStatus, 1.5)).join("");

  const renderLlmList = (items, table, conf) => {
    if (!items || items.length === 0) return "<span class='muted'>—</span>";
    return items.map((c, i) => `
      <div class="row llm-row${i === 0 ? " llm-top1" : ""}">
        <span class="name">${escapeHtml(shortName(c, table))}</span>
      </div>`).join("")
      + (conf != null ? `<div class="conf-line">LLM confidence: ${conf.toFixed(0)}</div>` : "");
  };

  const llmFieldBlock = llm ? `
    <div class="llm-side">
      <h5>LLM said</h5>
      ${renderLlmList(llmFields, fieldNames, llm.llm_field_conf)}
    </div>` : "";
  const llmSubBlock = llm ? `
    <div class="llm-side">
      <h5>LLM said</h5>
      ${renderLlmList(llmSubs, subNames, llm.llm_subfield_conf)}
    </div>` : "";

  const inst = topInst(p.authors);
  const byline = [
    p.year ? `<span>${p.year}</span>` : "",
    p.source_name ? `<span>${escapeHtml(p.source_name)}</span>` : "",
    p.authors && p.authors.length ? `<span>${escapeHtml(formatAuthors(p.authors))}</span>` : "",
    inst ? `<span>${escapeHtml(inst)}</span>` : "",
  ].filter(Boolean).join(" &middot; ");

  const badges = [
    p.in_training
      ? `<span class="badge training">in training (${escapeHtml(p.llm_source || "llm")})</span>`
      : `<span class="badge">corpus</span>`,
  ].join("");

  const abstract = p.abstract ? `
    <div class="abstract collapsed" data-abstract="1">${escapeHtml(p.abstract)}</div>
    <span class="toggle">show full</span>
  ` : "";

  return `
    <article class="card" data-id="${p.paper_id}">
      <div class="title">${escapeHtml(p.title) || "(no title)"}</div>
      <div class="byline">${byline}</div>
      <div class="badges">${badges}</div>
      ${abstract}
      <div class="preds">
        <div class="pred-col">
          <h4>Field</h4>
          <div class="pred-pair">
            <div class="model-side">
              <h5>Model top 3</h5>
              ${fieldRows || "<span class='muted'>none</span>"}
            </div>
            ${llmFieldBlock}
          </div>
        </div>
        <div class="pred-col">
          <h4>Subfield</h4>
          <div class="pred-pair">
            <div class="model-side">
              <h5>Model top 5</h5>
              ${subRows || "<span class='muted'>none</span>"}
            </div>
            ${llmSubBlock}
          </div>
        </div>
      </div>
    </article>
  `;
}

function attachCardEvents(root) {
  root.querySelectorAll(".toggle").forEach((el) => {
    el.addEventListener("click", (e) => {
      const card = e.target.closest(".card");
      const ab = card && card.querySelector("[data-abstract]");
      if (!ab) return;
      ab.classList.toggle("collapsed");
      e.target.textContent = ab.classList.contains("collapsed") ? "show full" : "show less";
    });
  });
}

function render(reset = true) {
  const main = $("results");
  if (reset) {
    state.shown = 0;
    main.innerHTML = "";
  }
  if (state.filtered.length === 0) {
    main.innerHTML = `<div class="empty">No papers match these filters.</div>`;
    $("count-badge").textContent = "0 papers match";
    return;
  }
  $("count-badge").textContent = `${state.filtered.length.toLocaleString()} papers match`;
  const next = state.filtered.slice(state.shown, state.shown + PAGE);
  const html = next.map(renderCard).join("");
  if (reset) {
    main.innerHTML = html + `<button class="show-more" id="more-btn">Show ${PAGE} more</button>`;
  } else {
    const btn = $("more-btn");
    btn.insertAdjacentHTML("beforebegin", html);
  }
  state.shown += next.length;
  attachCardEvents(main);
  const btn = $("more-btn");
  if (btn) {
    btn.disabled = state.shown >= state.filtered.length;
    btn.textContent = btn.disabled ? "End of results" : `Show ${PAGE} more`;
    btn.onclick = () => render(false);
  }
}

function applyFilters() {
  const setFilter = document.querySelector('input[name="set"]:checked').value;
  const fieldFilter = $("filter-field").value;
  const subFilter = $("filter-subfield").value;
  const numOr = (s, fallback) => {
    const v = parseFloat(s);
    return Number.isFinite(v) ? v : fallback;
  };
  const intOr = (s, fallback) => {
    const v = parseInt(s, 10);
    return Number.isFinite(v) ? v : fallback;
  };
  const cMinF = numOr($("conf-field-min").value, 0);
  const cMaxF = numOr($("conf-field-max").value, 1);
  const cMinS = numOr($("conf-sub-min").value, 0);
  const cMaxS = numOr($("conf-sub-max").value, 1);
  const yearMin = intOr($("year-min").value, -Infinity);
  const yearMax = intOr($("year-max").value, Infinity);
  const sortBy = $("sort-by").value;
  const agree = document.querySelector('input[name="agree"]:checked').value;
  const search = $("text-search").value.trim().toLowerCase();

  let xs = state.papers.slice();

  xs = xs.filter((p) => {
    if (setFilter === "train" && !p.in_training) return false;
    if (setFilter === "corpus" && p.in_training) return false;
    if (fieldFilter && p.field_top1 !== fieldFilter) return false;
    if (subFilter && p.subfield_top1 !== subFilter) return false;
    if (p.field_p1 == null || p.field_p1 < cMinF || p.field_p1 > cMaxF) return false;
    if (p.sp1 == null || p.sp1 < cMinS || p.sp1 > cMaxS) return false;
    if (p.year != null && (p.year < yearMin || p.year > yearMax)) return false;
    if (p.year == null && yearMin !== -Infinity) return false;

    if (agree !== "any") {
      if (!p.in_training) return false;
      const fStatus = topMatchStatus(p.field_top1, p.llm_fields || []);
      const sStatus = topMatchStatus(p.subfield_top1, p.llm_subfields || []);
      if (agree === "field_match" && fStatus !== "match") return false;
      if (agree === "field_partial" && fStatus !== "partial") return false;
      if (agree === "field_miss" && fStatus !== "miss") return false;
      if (agree === "sub_match" && sStatus !== "match") return false;
      if (agree === "sub_partial" && sStatus !== "partial") return false;
      if (agree === "sub_miss" && sStatus !== "miss") return false;
    }

    if (search) {
      const hay = ((p.title || "") + " " + (p.abstract || "")).toLowerCase();
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
  } else if (sortBy === "lowsub") {
    xs.sort((a, b) => (a.sp1 ?? 9) - (b.sp1 ?? 9));
  } else if (sortBy === "highsub") {
    xs.sort((a, b) => (b.sp1 ?? -1) - (a.sp1 ?? -1));
  } else if (sortBy === "year_asc") {
    xs.sort((a, b) => (a.year ?? 9999) - (b.year ?? 9999));
  } else if (sortBy === "year_desc") {
    xs.sort((a, b) => (b.year ?? -1) - (a.year ?? -1));
  }

  state.filtered = xs;
  render(true);
}

function buildDropdowns() {
  const fEl = $("filter-field");
  const sEl = $("filter-subfield");
  const fields = state.taxonomy.fields;
  Object.entries(fields).sort((a, b) => a[1].localeCompare(b[1]))
    .forEach(([code, name]) => fEl.insertAdjacentHTML("beforeend",
      `<option value="${code}">${escapeHtml(name)}</option>`));
  Object.entries(state.taxonomy.subfields)
    .map(([code, name]) => {
      const parent = code.split("_")[0];
      return [code, name, fields[parent] || parent];
    })
    .sort((a, b) => a[2].localeCompare(b[2]) || a[1].localeCompare(b[1]))
    .forEach(([code, name, parentName]) => sEl.insertAdjacentHTML("beforeend",
      `<option value="${code}">${escapeHtml(parentName)} &rsaquo; ${escapeHtml(name)}</option>`));
}

function attachFilterEvents() {
  ["filter-field","filter-subfield","conf-field-min","conf-field-max",
   "conf-sub-min","conf-sub-max","year-min","year-max","sort-by","text-search"]
    .forEach(id => $(id).addEventListener("input", applyFilters));
  document.querySelectorAll('input[name="set"], input[name="agree"]').forEach((el) => {
    el.addEventListener("change", applyFilters);
  });
  $("random-btn").addEventListener("click", (e) => {
    e.preventDefault();
    $("sort-by").value = "random";
    applyFilters();
  });
  $("reset-btn").addEventListener("click", (e) => {
    e.preventDefault();
    document.querySelector('input[name="set"][value="train"]').checked = true;
    document.querySelector('input[name="agree"][value="any"]').checked = true;
    $("filter-field").value = "";
    $("filter-subfield").value = "";
    $("conf-field-min").value = "0.00";
    $("conf-field-max").value = "1.00";
    $("conf-sub-min").value = "0.00";
    $("conf-sub-max").value = "1.00";
    $("year-min").value = "";
    $("year-max").value = "";
    $("text-search").value = "";
    $("sort-by").value = "random";
    applyFilters();
  });
}

async function init() {
  try {
    const [pp, tx] = await Promise.all([
      fetch("papers.json").then((r) => r.json()),
      fetch("taxonomy.json").then((r) => r.json()),
    ]);
    state.papers = pp;
    state.taxonomy = tx;
    $("data-source").textContent = `${pp.length.toLocaleString()} papers (`
      + `${pp.filter(p => p.in_training).length.toLocaleString()} in LLM training set, `
      + `${pp.filter(p => !p.in_training).length.toLocaleString()} from corpus)`;
    buildDropdowns();
    attachFilterEvents();
    applyFilters();
  } catch (err) {
    $("results").innerHTML = `<div class="empty">Failed to load <code>papers.json</code> / <code>taxonomy.json</code>:<br><pre>${escapeHtml(err.message)}</pre>
    <p>Make sure the files are in the same folder as <code>index.html</code>, and serve via a static server (e.g. <code>python3 -m http.server</code>).</p></div>`;
    console.error(err);
  }
}

init();
