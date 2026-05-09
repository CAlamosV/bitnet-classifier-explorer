"use strict";

let DATA = null;
const CARDS_PER_PAGE = 50;
let visibleCount = CARDS_PER_PAGE;

function fmt(n) {
  if (n == null) return "";
  return n.toLocaleString();
}

function sizeBucket(s) {
  if (s === 2) return "2";
  if (s === 3) return "3";
  if (s <= 5) return "4-5";
  if (s <= 10) return "6-10";
  return "11+";
}

function maxCites(c) {
  let mx = -1;
  for (const m of c.members) {
    const v = (m.cited_by_count == null) ? 0 : m.cited_by_count;
    if (v > mx) mx = v;
  }
  return mx;
}

function canonicalYear(c) {
  for (const m of c.members) if (m.is_canonical && m.year != null) return m.year;
  for (const m of c.members) if (m.year != null) return m.year;
  return null;
}

function yearBucket(y) {
  if (y == null) return null;
  if (y < 1950) return "pre-1950";
  if (y < 1980) return "1950-1979";
  if (y < 2000) return "1980-1999";
  if (y < 2010) return "2000-2009";
  return "2010-";
}

function isCrossYear(c) {
  let lo = null, hi = null;
  for (const m of c.members) {
    if (m.year == null) continue;
    if (lo == null || m.year < lo) lo = m.year;
    if (hi == null || m.year > hi) hi = m.year;
  }
  return lo != null && hi != null && lo !== hi;
}

function passesFilters(c, f) {
  if (f.tier && c.best_tier !== f.tier) return false;
  if (f.size && sizeBucket(c.size) !== f.size) return false;
  if (f.year) {
    const yb = yearBucket(canonicalYear(c));
    if (yb !== f.year) return false;
  }
  if (f.crossyear) {
    const cy = isCrossYear(c);
    if (f.crossyear === "yes" && !cy) return false;
    if (f.crossyear === "no" && cy) return false;
  }
  if (f.q) {
    const q = f.q.toLowerCase();
    let hit = false;
    for (const m of c.members) {
      if ((m.title || "").toLowerCase().includes(q) ||
          (m.doi || "").toLowerCase().includes(q) ||
          (m.paperid || "").toLowerCase().includes(q)) {
        hit = true; break;
      }
    }
    if (!hit) return false;
  }
  return true;
}

function getFilters() {
  return {
    tier:      document.getElementById("filter-tier").value,
    size:      document.getElementById("filter-size").value,
    year:      document.getElementById("filter-year").value,
    crossyear: document.getElementById("filter-crossyear").value,
    sort:      document.getElementById("sort-by").value,
    q:         document.getElementById("text-search").value.trim(),
  };
}

function sortClusters(clusters, sort) {
  const arr = clusters.slice();
  if (sort === "size_desc") arr.sort((a,b) => b.size - a.size);
  else if (sort === "size_asc") arr.sort((a,b) => a.size - b.size);
  else if (sort === "cites_desc") arr.sort((a,b) => maxCites(b) - maxCites(a));
  else if (sort === "cites_asc")  arr.sort((a,b) => maxCites(a) - maxCites(b));
  else arr.sort(() => Math.random() - 0.5);
  return arr;
}

function renderCluster(c) {
  let html = `<div class="card dup-card">`;
  html += `<div class="title">Cluster &mdash; ${c.size} duplicate IDs &middot; `
       + `<code class="tier-tag">${c.best_tier || "?"}</code>`;
  if (isCrossYear(c)) html += ` &middot; <span class="dup-meta">cross-year</span>`;
  html += `</div>`;

  html += `<table class="dup-mem"><thead><tr>`
       +  `<th>PaperID</th><th>Title</th><th>DOI</th>`
       +  `<th>Doctype</th><th>Year</th><th>Cites</th>`
       +  `</tr></thead><tbody>`;
  for (const m of c.members) {
    const cls = m.is_canonical ? "canon" : "";
    const ti = m.title || "";
    const tiTrunc = ti.length > 110 ? ti.slice(0, 107) + "&hellip;" : ti;
    const doi = m.doi
      ? `<a target="_blank" href="https://doi.org/${m.doi}">${m.doi}</a>`
      : "";
    html += `<tr class="${cls}">`
         + `<td><a target="_blank" href="https://api.openalex.org/works/${m.paperid}">${m.paperid}</a></td>`
         + `<td title="${ti.replace(/"/g, "&quot;")}">${tiTrunc}</td>`
         + `<td>${doi}</td>`
         + `<td>${m.doctype || ""}</td>`
         + `<td>${m.year == null ? "" : m.year}</td>`
         + `<td>${m.cited_by_count == null ? "" : fmt(m.cited_by_count)}</td>`
         + `</tr>`;
  }
  html += "</tbody></table>";

  if (c.edges && c.edges.length) {
    html += `<details class="dup-edges"><summary>${c.edges.length} edges</summary>`;
    html += `<table class="dup-mem"><thead><tr>`
         + `<th>Edge</th><th>Tier</th></tr></thead><tbody>`;
    for (const e of c.edges) {
      html += `<tr>`
           + `<td><code>${e.left}&harr;${e.right}</code></td>`
           + `<td><code>${e.tier}</code></td>`
           + `</tr>`;
    }
    html += "</tbody></table></details>";
  }

  html += "</div>";
  return html;
}

function render() {
  if (!DATA) return;
  const f = getFilters();
  let arr = DATA.clusters.filter(c => passesFilters(c, f));
  arr = sortClusters(arr, f.sort);
  const total = arr.length;
  const slice = arr.slice(0, visibleCount);

  const main = document.getElementById("results");
  let html = "";
  for (const c of slice) html += renderCluster(c);
  if (slice.length < total) {
    html += `<div class="loader"><a href="#" id="more-btn">show more (${total - slice.length} remaining)</a></div>`;
  } else if (total === 0) {
    html = `<div class="loader">No clusters match your filters.</div>`;
  }
  main.innerHTML = html;
  document.getElementById("count-badge").textContent =
    `${fmt(total)} clusters match (showing ${fmt(slice.length)})`;
  const more = document.getElementById("more-btn");
  if (more) more.onclick = e => { e.preventDefault(); visibleCount += CARDS_PER_PAGE; render(); };
}

function populateTierSelect() {
  const tiers = new Set();
  for (const c of DATA.clusters) tiers.add(c.best_tier || "?");
  const sorted = Array.from(tiers).sort();
  const sel = document.getElementById("filter-tier");
  for (const t of sorted) {
    const opt = document.createElement("option");
    opt.value = t; opt.textContent = t;
    sel.appendChild(opt);
  }
}

function bindControls() {
  for (const id of ["filter-tier","filter-size","filter-year","filter-crossyear","sort-by","text-search"]) {
    document.getElementById(id).addEventListener("input", () => { visibleCount = CARDS_PER_PAGE; render(); });
  }
  document.getElementById("random-btn").onclick = e => {
    e.preventDefault();
    document.getElementById("sort-by").value = "random";
    visibleCount = CARDS_PER_PAGE;
    render();
  };
  document.getElementById("reset-btn").onclick = e => {
    e.preventDefault();
    for (const id of ["filter-tier","filter-size","filter-year","filter-crossyear","text-search"]) {
      document.getElementById(id).value = "";
    }
    document.getElementById("sort-by").value = "random";
    visibleCount = CARDS_PER_PAGE;
    render();
  };
}

fetch("work_duplicates.json").then(r => r.json()).then(json => {
  DATA = json;
  populateTierSelect();
  bindControls();
  render();
}).catch(err => {
  document.getElementById("results").innerHTML =
    `<div class="loader" style="color:#c2424a">Failed to load work_duplicates.json: ${err}</div>`;
});
