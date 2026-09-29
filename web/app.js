/* c919-routelab frontend: presentation only -- every number comes from the API. */
"use strict";

const KM_PER_NM = 1.852;
const $ = (id) => document.getElementById(id);
const fmt = (v, d = 0) =>
  v == null ? "--" : v.toLocaleString("zh-CN", { maximumFractionDigits: d });

const state = { airports: [], presets: {}, aircraftTypes: [] };

// ------------------------------------------------------- chart theme

const THEME = {
  ink: "#23272b",
  muted: "#7a756c",
  grid: "#e7e4dc",
  accent: "#2f4f6f",
  crimson: "#a63d40",
  sage: "#4a7c59",
  ochre: "#b08a3e",
  slateLight: "#a9b8c4",
};
const BASE_FONT = { family: '"Segoe UI","Microsoft YaHei",sans-serif', size: 12, color: "#5a5f66" };
const TITLE_FONT = { family: 'Georgia,"Times New Roman","SimSun",serif', size: 14, color: "#23272b" };
const PLOTLY_CONFIG = { responsive: true, displayModeBar: false, scrollZoom: true };
function chartLayout(extra) {
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: BASE_FONT,
    hoverlabel: { bgcolor: "#23272b", bordercolor: "#23272b", font: { color: "#f6f5f1", size: 12 } },
    margin: { l: 60, r: 14, t: 40, b: 40 },
  }, extra);
}

// API returns lat_deg/lon_deg (Airport dataclass fields); add short aliases
// once at load so every consumer can use a.lat / a.lon.
function normalizeAirport(a) {
  return { ...a, lat: a.lat_deg, lon: a.lon_deg };
}

// ------------------------------------------------------------- helpers

function aircraftPayload() {
  return {
    mtow_kg: +$("p-mtow").value * 1000,
    oew_kg: +$("p-oew").value * 1000,
    max_fuel_kg: +$("p-fuel").value * 1000,
    max_payload_kg: +$("p-pay").value * 1000,
    cruise_tas_kmh: +$("p-tas").value,
    cruise_fuel_kg_per_h: +$("p-flow").value,
  };
}

function policyPayload() {
  return {
    contingency_frac: +$("p-cont").value / 100,
    final_reserve_min: +$("p-fr").value,
    taxi_kg: +$("p-taxi").value,
    approach_allowance_kg: +$("p-appr").value,
  };
}

const backend = () => $("p-backend").value;
const actype = () => $("p-actype").value;

async function api(path, body) {
  const res = await fetch(path, body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : undefined);
  if (!res.ok) {
    let msg;
    try { msg = (await res.json()).detail || res.statusText; } catch { msg = res.statusText; }
    const err = new Error(`${msg}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

function showApiError(err) {
  const el = $("api-error");
  if (!el) console.error(err);
  else el.innerHTML = `<p class="bad">请求失败：${err.message}</p>`;
}
function clearApiError() {
  const el = $("api-error");
  if (el) el.innerHTML = "";
}

// great-circle arc for the map (geometry only, drawn client-side)
function arcPoints(lat1, lon1, lat2, lon2, n) {
  const rad = (d) => (d * Math.PI) / 180, deg = (r) => (r * 180) / Math.PI;
  const p1 = rad(lat1), l1 = rad(lon1), p2 = rad(lat2), l2 = rad(lon2);
  const v1 = [Math.cos(p1) * Math.cos(l1), Math.cos(p1) * Math.sin(l1), Math.sin(p1)];
  const v2 = [Math.cos(p2) * Math.cos(l2), Math.cos(p2) * Math.sin(l2), Math.sin(p2)];
  const dot = Math.max(-1, Math.min(1, v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]));
  const w = Math.acos(dot);
  if (w < 1e-9) return Array(n).fill([lat1, lon1]);
  const sw = Math.sin(w), pts = [];
  for (let i = 0; i < n; i++) {
    const f = i / (n - 1), a = Math.sin((1 - f) * w) / sw, b = Math.sin(f * w) / sw;
    const x = a * v1[0] + b * v2[0], y = a * v1[1] + b * v2[1], z = a * v1[2] + b * v2[2];
    pts.push([deg(Math.asin(z)), deg(Math.atan2(y, x))]);
  }
  // unwrap longitudes across the antimeridian so the drawn path stays
  // continuous instead of snapping back across the map at +-180 deg
  for (let i = 1; i < pts.length; i++) {
    while (pts[i][1] - pts[i - 1][1] > 180) pts[i][1] -= 360;
    while (pts[i][1] - pts[i - 1][1] < -180) pts[i][1] += 360;
  }
  return pts;
}

// ------------------------------------------------------------- tab 1

function fillSelects() {
  const cn = state.airports.filter((a) => a.ident.startsWith("Z"));
  const other = state.airports.filter((a) => !a.ident.startsWith("Z"));
  const all = [...cn, ...other];
  const mk = (sel, list, none) => {
    sel.innerHTML =
      (none ? `<option value="-">${none}</option>` : "") +
      list.map((a) => `<option value="${a.ident}">${a.ident}（${a.iata || "--"}）${a.name}</option>`).join("");
  };
  mk($("origin"), all); $("origin").value = "ZSPD";
  mk($("dest"), all.filter((a) => a.ident !== "ZSPD")); $("dest").value = "ZWWW";
  mk($("altn"), all, "（无备降，按 300 km 默认）");
}

async function renderRoute() {
  const o = state.airports.find((a) => a.ident === $("origin").value);
  const d = state.airports.find((a) => a.ident === $("dest").value);
  const altV = $("altn").value;
  let plan;
  try {
    plan = await api("/api/route", {
      origin: o.ident, destination: d.ident,
      alternate: altV !== "-" ? altV : "",
      payload_kg: +$("p-payload").value * 1000,
      headwind_kmh: +$("p-wind").value,
      aircraft: aircraftPayload(), policy: policyPayload(),
      backend: backend(), actype: backend() === "openap" ? actype() : null,
    });
    clearApiError();
  } catch (err) {
    showApiError(err);
    return;
  }
  const alt = altV !== "-" ? state.airports.find((a) => a.ident === altV) : null;

  $("route-metrics").innerHTML = `
    <div class="metric"><div class="k">航距</div><div class="v">${fmt(plan.distance_km)} km<span class="note">${fmt(plan.distance_nm)} NM</span></div></div>
    <div class="metric"><div class="k">航程时间</div><div class="v">${plan.trip_time_h.toFixed(2)}<span class="note">h</span></div></div>
    <div class="metric"><div class="k">轮档油</div><div class="v">${fmt(plan.block_kg)}<span class="note">kg</span></div></div>
    <div class="metric"><div class="k">本航段可带业载</div><div class="v">${(plan.max_payload_on_leg_kg / 1000).toFixed(1)}<span class="note">t</span></div></div>
    <div class="metric"><div class="k">业载 ${$("p-payload").value} t 可行性</div>
      <div class="v ${plan.feasible ? "ok" : "bad"}">${plan.feasible ? "可行" : "超限"}</div></div>`;

  $("fuel-table").innerHTML = `<table><tr><th>项目</th><th>kg</th></tr>
    <tr><td>航程油</td><td>${fmt(plan.trip_kg)}</td></tr>
    <tr><td>绕飞 ${$("p-cont").value}%</td><td>${fmt(plan.contingency_kg)}</td></tr>
    <tr><td>备降（${alt ? alt.ident + " " + fmt(plan.alternate_distance_km) + " km" : "默认 300 km"}）</td><td>${fmt(plan.alternate_kg)}</td></tr>
    <tr><td>最终储备 ${$("p-fr").value} min</td><td>${fmt(plan.final_reserve_kg)}</td></tr>
    <tr><td>滑行</td><td>${fmt(plan.taxi_kg)}</td></tr>
    <tr><td><b>轮档油</b></td><td><b>${fmt(plan.block_kg)}</b></td></tr>
    <tr><td>油量上限</td><td>${fmt(plan.fuel_limit_kg)}</td></tr></table>`;

  if (!window.Plotly) return;
  const arc = arcPoints(o.lat, o.lon, d.lat, d.lon, 96);
  const traces = [{
    type: "scattergeo", mode: "lines",
    lon: arc.map((p) => p[1]), lat: arc.map((p) => p[0]),
    line: { width: 2, color: THEME.crimson }, showlegend: false, hoverinfo: "skip",
  }];
  const marks = [[o, "出发", THEME.accent], [d, "到达", THEME.sage]];
  if (alt) marks.push([alt, "备降", THEME.ochre]);
  for (const [ap, role, color] of marks) {
    traces.push({
      type: "scattergeo", mode: "markers+text", lon: [ap.lon], lat: [ap.lat],
      text: [ap.ident], textposition: "top center",
      marker: { size: 8, color }, name: `${role} ${ap.ident}`,
      textfont: { size: 11, color: "#4a4f55" },
      hovertext: `${ap.ident} ${ap.name}｜标高 ${fmt(ap.elev_ft)} ft｜跑道 ${fmt(ap.runway_m)} m`,
    });
  }
  if (alt) {
    const arc2 = arcPoints(d.lat, d.lon, alt.lat, alt.lon, 64);
    traces.push({
      type: "scattergeo", mode: "lines",
      lon: arc2.map((p) => p[1]), lat: arc2.map((p) => p[0]),
      line: { width: 1.4, color: THEME.ochre, dash: "dot" }, showlegend: false, hoverinfo: "skip",
    });
  }
  Plotly.react("map", traces, chartLayout({
    height: 440, margin: { l: 0, r: 0, t: 0, b: 0 }, showlegend: false,
    geo: {
      projection: { type: "natural earth" }, showland: true, landcolor: "#eceae3",
      showcountries: true, countrycolor: "#cfcabf", showcoastlines: false,
      bgcolor: "rgba(0,0,0,0)", fitbounds: "locations",
      // keep default resolution (110m): 50m topojson is fetched from the CDN,
      // which breaks offline / flaky-network use
    },
  }), PLOTLY_CONFIG);

  Plotly.react("fuel-chart", [{
    type: "bar", orientation: "h",
    x: [plan.trip_kg, plan.contingency_kg, plan.alternate_kg, plan.final_reserve_kg, plan.taxi_kg],
    y: ["航程", "绕飞", "备降", "最终储备", "滑行"], marker: { color: THEME.accent },
    text: [fmt(plan.trip_kg), fmt(plan.contingency_kg), fmt(plan.alternate_kg), fmt(plan.final_reserve_kg), fmt(plan.taxi_kg)],
    textposition: "outside", textfont: { size: 11, color: THEME.ink }, cliponaxis: false,
    hoverinfo: "x",
  }], chartLayout({
    title: { text: "轮档油构成（kg）", font: TITLE_FONT, x: 0, xanchor: "left" },
    height: 310, margin: { l: 74, r: 34, t: 44, b: 30 },
    xaxis: { gridcolor: THEME.grid, zeroline: false },
    yaxis: { ticks: "" },
  }), PLOTLY_CONFIG);
}

// ------------------------------------------------------------- tab 2

async function renderEnv() {
  if (!window.Plotly) return;
  const reserve = +$("p-reserve").value * 1000;
  let traces;
  if (backend() === "openap") {
    let env;
    try {
      env = await api("/api/envelope", {
        aircraft: aircraftPayload(), reserve_kg: reserve,
        backend: "openap", actype: actype(),
      });
      clearApiError();
    } catch (err) { showApiError(err); return; }
    traces = [{
      x: env.payload_kg.map((p) => p / 1000), y: env.max_range_km.map((r) => r / 1000),
      mode: "lines", name: `${env.actype}（OpenAP）`, line: { color: THEME.accent, width: 2.2 },
      hovertemplate: "业载 %{x:.1f} t · 航程 %{y:,.0f} km<extra>" + env.actype + " (OpenAP)</extra>",
    }];
  } else {
    const jobs = [];
    if ($("c-custom").checked) jobs.push(["当前机型", aircraftPayload(), THEME.crimson, 2.4]);
    const presetDefs = [
      ["c-a320", "A320neo (公开手册量级)", "A320neo", THEME.accent, 1.7],
      ["c-max8", "737 MAX 8 (公开手册量级)", "737 MAX 8", THEME.sage, 1.7],
      ["c-c919", "C919 (公开报道+估计，非官方)", "C919（估计）", THEME.ochre, 1.7],
    ];
    for (const [id, key, short, color, width] of presetDefs)
      if ($(id).checked && state.presets[key]) jobs.push([short, state.presets[key], color, width]);
    let results;
    try {
      results = await Promise.all(
        jobs.map(async ([label, aircraft, color, width]) => ({
          label, color, width,
          env: await api("/api/envelope", { aircraft, reserve_kg: reserve }),
        }))
      );
      clearApiError();
    } catch (err) { showApiError(err); return; }
    traces = results.map(({ label, color, width, env }) => ({
      x: env.payload_kg.map((p) => p / 1000), y: env.max_range_km.map((r) => r / 1000),
      mode: "lines", name: label, line: { color, width },
      hovertemplate: "业载 %{x:.1f} t · 航程 %{y:,.0f} km<extra>" + label + "</extra>",
    }));
  }
  Plotly.react("env-chart", traces, chartLayout({
    title: { text: "业载–航程包线（含储备油）", font: TITLE_FONT, x: 0, xanchor: "left" },
    height: 470,
    xaxis: { title: { text: "业载（t）" }, gridcolor: THEME.grid, zeroline: false },
    yaxis: { title: { text: "最大航程（1000 km）" }, gridcolor: THEME.grid, zeroline: false },
    hovermode: "x unified",
    legend: { orientation: "h", y: -0.22, x: 0 },
  }), PLOTLY_CONFIG);
}

// ------------------------------------------------------------- tab 3

function fillHotTemps() {
  $("hot-temps").innerHTML = state.airports
    .filter((a) => a.ident.startsWith("Z"))
    .map((a) => `
      <div class="field"><label>${a.ident} ${a.iata} 温度 °C</label>
      <input type="number" class="hot-t" id="t-${a.ident}" value="${{ ZSPD: 33, ZWWW: 34, ZWSH: 34, ZPPP: 24 }[a.ident] ?? 30}" step="1" min="-20" max="55"></div>`)
    .join("");
}

async function renderHot() {
  const airports = [...document.querySelectorAll(".hot-t")].map((inp) => ({
    ident: inp.id.slice(2), temp_c: +inp.value,
  }));
  const rows = await api("/api/hot", { airports });
  $("hot-table").innerHTML = `<table>
    <tr><th>机场</th><th>标高 ft</th><th>ISA °C</th><th>假设温度 °C</th><th>ISA 偏差</th>
        <th>需要场长 m</th><th>可用跑道 m</th><th>余量 m</th><th>临界温度 °C</th></tr>
    ${rows.map((r) => `<tr><td>${r.ident} ${r.iata}</td><td>${fmt(r.elevation_ft)}</td>
      <td>${r.isa_temp_c}</td><td>${r.temp_c}</td><td>+${r.isa_dev_c}</td>
      <td>${fmt(r.required_tofl_m)}</td><td>${fmt(r.runway_m)}</td>
      <td class="${r.margin_m >= 0 ? "ok" : "bad"}">${fmt(r.margin_m)}</td>
      <td>${r.critical_temp_c == null ? "&gt;60" : r.critical_temp_c}</td></tr>`).join("")}</table>`;
  if (!window.Plotly) return;
  const x = rows.map((r) => r.ident);
  Plotly.react("hot-chart", [
    { x, y: rows.map((r) => r.runway_m), type: "bar", name: "可用跑道",
      marker: { color: THEME.slateLight } },
    { x, y: rows.map((r) => r.required_tofl_m), type: "bar", name: "需要场长（MTOW，无风）",
      marker: { color: THEME.crimson } },
  ], chartLayout({
    title: { text: "启发式起飞场长 vs 可用跑道（m）", font: TITLE_FONT, x: 0, xanchor: "left" },
    height: 400, barmode: "group", bargap: 0.32,
    xaxis: { ticks: "" },
    yaxis: { gridcolor: THEME.grid, zeroline: false },
    legend: { orientation: "h", y: -0.18, x: 0 },
  }), PLOTLY_CONFIG);
}

// ------------------------------------------------------------- wiring

function showTab(name) {
  for (const p of ["route", "env", "hot"]) $("page-" + p).style.display = p === name ? "" : "none";
  for (const t of ["route", "env", "hot"]) $("tab-" + t).classList.toggle("active", t === name);
  renderActive(name);
}

let currentTab = "route";
function renderActive(name = currentTab) {
  currentTab = name;
  const fn = name === "route" ? renderRoute : name === "env" ? renderEnv : renderHot;
  fn().catch(console.error);
}

let timer = null;
function scheduleRender() {
  clearTimeout(timer);
  timer = setTimeout(() => renderActive(), 250);
}

// OpenAP mode: MTOW/OEW/burn/TAS come from the OpenAP database, so the
// corresponding sidebar inputs stop applying; tank/payload caps stay live.
function applyBackendMode() {
  const openapMode = backend() === "openap";
  $("actype-field").style.display = openapMode ? "" : "none";
  $("backend-note").style.display = openapMode ? "" : "none";
  for (const id of ["p-mtow", "p-oew", "p-flow", "p-tas"]) $(id).disabled = openapMode;
  for (const id of ["c-a320", "c-max8", "c-c919"]) {
    $(id).disabled = openapMode;
    if (openapMode) $(id).checked = false;
  }
  $("c-custom").disabled = openapMode;
  $("c-custom").checked = !openapMode ? $("c-custom").checked : true;
}

(async function init() {
  if (!window.Plotly) $("plot-error").style.display = "block";
  try {
    const [airports, presets, aircraftTypes] = await Promise.all([
      api("/api/airports"), api("/api/presets"), api("/api/aircraft-types"),
    ]);
    state.airports = airports.map(normalizeAirport);
    state.presets = presets;
    state.aircraftTypes = aircraftTypes;
  } catch (err) {
    // aircraft-types 503 = openap not installed: degrade gracefully
    try {
      const [airports, presets] = await Promise.all([api("/api/airports"), api("/api/presets")]);
      state.airports = airports.map(normalizeAirport);
      state.presets = presets;
    } catch (e2) { showApiError(e2); }
  }
  if (state.aircraftTypes.length) {
    $("p-actype").innerHTML = state.aircraftTypes
      .map((t) => `<option value="${t}">${t.toUpperCase()}</option>`).join("");
    $("p-actype").value = "a320";
  } else {
    $("p-backend").querySelector('option[value="openap"]').disabled = true;
  }
  $("p-backend").addEventListener("change", () => { applyBackendMode(); scheduleRender(); });
  applyBackendMode();
  fillSelects(); fillHotTemps();
  document.querySelectorAll("input,select").forEach((el) => {
    el.addEventListener("input", scheduleRender);
    el.addEventListener("change", scheduleRender);
  });
  renderActive();
})();
