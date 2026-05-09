"use strict";

let DATA = null;
const CARDS_PER_PAGE = 50;
let visibleCount = CARDS_PER_PAGE;

function fmt(n) {
  if (n == null) return "";
  return n.toLocaleString();
}

function yearRange(m) {
  if (m.oa_year_first != null && m.oa_year_last != null) {
    return `${m.oa_year_first}–${m.oa_year_last}`;
  }
  if (m.imp_year_first != null && m.imp_year_last != null) {
    return `${m.imp_year_first}–${m.imp_year_last} (imp)`;
  }
  return "—";
}

function bucketize(n, buckets) {
  for (const b of buckets) {
    if (b.test(n)) return b.label;
  }
  return null;
}

function sizeBucket(s) {
  if (s === 2) return "2";
  if (s === 3) return "3";
  if (s <= 5) return "4-5";
  if (s <= 10) return "6-10";
  return "11+";
}

function worksBucket(w) {
  if (w == null) return null;
  if (w === 1) return "1";
  if (w <= 10) return "2-10";
  if (w <= 50) return "11-50";
  if (w <= 200) return "51-200";
  return "201+";
}

function bigWorks(c) {
  let mx = -1;
  for (const m of c.members) {
    const w = m.works_count == null ? 0 : m.works_count;
    if (w > mx) mx = w;
  }
  return mx;
}

function passesFilters(c, f) {
  if (f.tier && c.best_tier !== f.tier) return false;
  if (f.size && sizeBucket(c.size) !== f.size) return false;
  if (f.bigworks) {
    const bw = bigWorks(c);
    if (worksBucket(bw) !== f.bigworks) return false;
  }
  if (f.q) {
    const q = f.q.toLowerCase();
    let hit = false;
    for (const m of c.members) {
      if ((m.display_name || "").toLowerCase().includes(q) ||
          (m.authorid || "").toLowerCase().includes(q)) {
        hit = true; break;
      }
    }
    if (!hit) return false;
  }
  return true;
}

function getFilters() {
  return {
    tier:     document.getElementById("filter-tier").value,
    size:     document.getElementById("filter-size").value,
    bigworks: document.getElementById("filter-bigworks").value,
    sort:     document.getElementById("sort-by").value,
    q:        document.getElementById("text-search").value.trim(),
  };
}

function sortClusters(clusters, sort) {
  const arr = clusters.slice();
  if (sort === "size_desc") arr.sort((a,b) => b.size - a.size);
  else if (sort === "size_asc") arr.sort((a,b) => a.size - b.size);
  else if (sort === "bigworks_desc") arr.sort((a,b) => bigWorks(b) - bigWorks(a));
  else if (sort === "bigworks_asc") arr.sort((a,b) => bigWorks(a) - bigWorks(b));
  else {
    // random — shuffle once per render
    arr.sort((a,b) => (Math.random() - 0.5));
  }
  return arr;
}

function renderCluster(c) {
  let html = `<div class="card dup-card">`;
  html += `<div class="title">Cluster — ${c.size} duplicate IDs · `
       + `<code class="tier-tag">${c.best_tier}</code></div>`;
  html += `<table class="dup-mem"><thead><tr>`
       + `<th>AuthorID</th><th>Name</th><th>Works</th>`
       + `<th>Years</th><th>Last institution</th>`
       + `</tr></thead><tbody>`;
  for (let i = 0; i < c.members.length; i++) {
    const m = c.members[i];
    const cls = i === 0 ? "canon" : "";
    const yr = yearRange(m);
    html += `<tr class="${cls}">`
         + `<td><a target="_blank" href="https://api.openalex.org/authors/${m.authorid}">${m.authorid}</a></td>`
         + `<td>${(m.display_name||"")}</td>`
         + `<td>${m.works_count==null?"":fmt(m.works_count)}</td>`
         + `<td>${yr}</td>`
         + `<td>${m.last_known_institution||""}</td>`
         + `</tr>`;
  }
  html += "</tbody></table>";

  if (c.edges && c.edges.length) {
    html += `<details class="dup-edges"><summary>${c.edges.length} edges</summary>`;
    html += `<table class="dup-mem"><thead><tr>`
         + `<th>Edge</th><th>Tier</th><th>shared_papers</th><th>shared_coauthors</th>`
         + `<th>shared_institutions</th><th>bucket_size</th>`
         + `</tr></thead><tbody>`;
    for (const e of c.edges) {
      html += `<tr>`
           + `<td><code>${e.left}↔${e.right}</code></td>`
           + `<td><code>${e.tier}</code></td>`
           + `<td>${e.shared_papers}</td>`
           + `<td>${e.shared_coauthors}</td>`
           + `<td>${e.shared_institutions}</td>`
           + `<td>${e.bucket_size}</td>`
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
  for (const c of DATA.clusters) tiers.add(c.best_tier);
  const sorted = Array.from(tiers).sort();
  const sel = document.getElementById("filter-tier");
  for (const t of sorted) {
    const opt = document.createElement("option");
    opt.value = t; opt.textContent = t;
    sel.appendChild(opt);
  }
}

function bindControls() {
  for (const id of ["filter-tier","filter-size","filter-bigworks","sort-by","text-search"]) {
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
    for (const id of ["filter-tier","filter-size","filter-bigworks","text-search"]) {
      document.getElementById(id).value = "";
    }
    document.getElementById("sort-by").value = "random";
    visibleCount = CARDS_PER_PAGE;
    render();
  };
}

fetch("duplicates.json").then(r => r.json()).then(json => {
  DATA = json;
  populateTierSelect();
  bindControls();
  render();
}).catch(err => {
  document.getElementById("results").innerHTML =
    `<div class="loader" style="color:#c2424a">Failed to load duplicates.json: ${err}</div>`;
});
