const $ = (id) => document.getElementById(id);

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"})[c]);
}

function fmtInt(x) {
  return Number(x || 0).toLocaleString();
}

function fmtPct(x) {
  return `${(100 * Number(x || 0)).toFixed(1)}%`;
}

function shortName(d) {
  return d.display_name || d.institution_name || d.institution_id;
}

function summaryHtml(data) {
  const s = data.stats;
  return `
    <div class="summary-primary">
      <strong>${fmtInt(s.total_institutions)}</strong>
      <span>loaded institutions with 1980 data</span>
    </div>
    <div>
      <strong>${fmtInt(s.total_author_institution_placements)}</strong>
      <span>author-institution placements</span>
    </div>
    <div>
      <strong>${fmtInt(s.total_unique_authors)}</strong>
      <span>distinct authors</span>
    </div>
    <div>
      <strong>${fmtPct(s.top_5_share)}</strong>
      <span>covered by the top 5 loaded institutions</span>
    </div>
  `;
}

function axisTicks(maxValue, steps = 4) {
  const raw = maxValue / steps;
  const pow = 10 ** Math.floor(Math.log10(raw || 1));
  const nice = Math.ceil(raw / pow) * pow;
  const ticks = [];
  for (let v = 0; v <= nice * steps; v += nice) ticks.push(v);
  return ticks;
}

function barChart(data) {
  const rows = data.institutions.filter((d) => Number(d.author_count) > 0);
  const width = 920;
  const height = 420;
  const margin = { top: 18, right: 24, bottom: 112, left: 58 };
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;
  const maxY = Math.max(...rows.map((d) => Number(d.author_count)));
  const ticks = axisTicks(maxY, 5);
  const yMax = ticks[ticks.length - 1] || maxY || 1;
  const gap = 4;
  const barW = Math.max(8, (innerW - gap * (rows.length - 1)) / rows.length);
  const y = (v) => margin.top + innerH - (Number(v) / yMax) * innerH;
  const x = (i) => margin.left + i * (barW + gap);

  const grid = ticks.map((t) => `
    <g>
      <line x1="${margin.left}" y1="${y(t)}" x2="${width - margin.right}" y2="${y(t)}" class="viz-grid" />
      <text x="${margin.left - 8}" y="${y(t) + 4}" text-anchor="end" class="viz-axis-label">${fmtInt(t)}</text>
    </g>
  `).join("");

  const bars = rows.map((d, i) => {
    const h = innerH - (y(d.author_count) - margin.top);
    const label = shortName(d);
    const showLabel = rows.length <= 24;
    return `
      <g>
        <rect x="${x(i)}" y="${y(d.author_count)}" width="${barW}" height="${h}" class="viz-bar">
          <title>${escapeHtml(label)}: ${fmtInt(d.author_count)} authors</title>
        </rect>
        ${showLabel ? `<text x="${x(i) + barW / 2}" y="${height - margin.bottom + 12}" transform="rotate(55 ${x(i) + barW / 2} ${height - margin.bottom + 12})" class="viz-x-label">${escapeHtml(label)}</text>` : ""}
      </g>
    `;
  }).join("");

  return `
    <svg class="viz-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Authors per loaded institution in 1980">
      ${grid}
      <line x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}" class="viz-axis" />
      <line x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}" class="viz-axis" />
      ${bars}
      <text x="${margin.left}" y="14" class="viz-axis-title">authors in 1980</text>
    </svg>
  `;
}

function cumulativeChart(data) {
  const rows = data.cumulative.filter((d) => Number(d.author_count) > 0);
  const width = 920;
  const height = 420;
  const margin = { top: 20, right: 28, bottom: 54, left: 58 };
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;
  const n = Math.max(rows.length, 1);
  const x = (rank) => margin.left + ((Number(rank) - 1) / Math.max(n - 1, 1)) * innerW;
  const y = (share) => margin.top + innerH - Number(share) * innerH;
  const points = rows.map((d) => `${x(d.rank)},${y(d.cumulative_share)}`).join(" ");
  const yTicks = [0, 0.25, 0.5, 0.75, 1];
  const xTicks = Array.from(new Set([1, 5, 10, 15, 20, n].filter((v) => v <= n)));

  const grid = yTicks.map((t) => `
    <g>
      <line x1="${margin.left}" y1="${y(t)}" x2="${width - margin.right}" y2="${y(t)}" class="viz-grid" />
      <text x="${margin.left - 8}" y="${y(t) + 4}" text-anchor="end" class="viz-axis-label">${fmtPct(t)}</text>
    </g>
  `).join("");
  const xLabels = xTicks.map((t) => `
    <g>
      <line x1="${x(t)}" y1="${height - margin.bottom}" x2="${x(t)}" y2="${height - margin.bottom + 5}" class="viz-axis" />
      <text x="${x(t)}" y="${height - margin.bottom + 22}" text-anchor="middle" class="viz-axis-label">${t}</text>
    </g>
  `).join("");
  const dots = rows.map((d) => `
    <circle cx="${x(d.rank)}" cy="${y(d.cumulative_share)}" r="3" class="viz-dot">
      <title>Top ${d.rank}: ${fmtPct(d.cumulative_share)} through ${escapeHtml(shortName(d))}</title>
    </circle>
  `).join("");

  return `
    <svg class="viz-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Cumulative author share by number of loaded universities">
      ${grid}
      <line x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}" class="viz-axis" />
      <line x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}" class="viz-axis" />
      ${xLabels}
      <polyline points="${points}" class="viz-line" />
      ${dots}
      <text x="${margin.left}" y="14" class="viz-axis-title">cumulative share of placements</text>
      <text x="${width / 2}" y="${height - 10}" text-anchor="middle" class="viz-axis-title">number of loaded universities, sorted largest first</text>
    </svg>
  `;
}

function tableHtml(data) {
  const rows = data.top_institutions.slice(0, 12).map((d) => `
    <tr>
      <td>${fmtInt(d.rank)}</td>
      <td>${escapeHtml(shortName(d))}</td>
      <td>${escapeHtml(d.country_code || "")}</td>
      <td>${fmtInt(d.author_count)}</td>
    </tr>
  `).join("");
  return `
    <div class="table-wrap">
      <table class="data-table compact-table">
        <thead><tr><th>Rank</th><th>Institution</th><th>Country</th><th>1980 authors</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

async function init() {
  const data = await fetch("institution_overview_1980.json").then((r) => {
    if (!r.ok) throw new Error(`failed to load institution_overview_1980.json: ${r.status}`);
    return r.json();
  });
  $("institution-concentration-summary").innerHTML = summaryHtml(data);
  $("institution-bars").innerHTML = barChart(data);
  $("institution-cumulative").innerHTML = cumulativeChart(data);
  $("institution-top-table").innerHTML = tableHtml(data);
}

init().catch((err) => {
  $("institution-bars").innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
  $("institution-cumulative").innerHTML = "";
  console.error(err);
});
