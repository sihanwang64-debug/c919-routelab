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

// Curated OpenAP types offered as envelope comparison series (common
// narrowbodies); only those present in the installed OpenAP are shown.
const OPENAP_COMPARE = ["a320", "a20n", "a321", "b738", "b38m"];
const OPENAP_SERIES_COLORS = [THEME.accent, THEME.crimson, THEME.sage, THEME.ochre, THEME.slateLight];
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
    // every checked OpenAP type becomes a series; fall back to the route
    // actype when nothing is checked
    const checked = [...document.querySelectorAll("#openap-compare input:checked")]
      .map((c) => c.value);
    const types = checked.length ? checked : [actype()];
    let envs;
    const loading = $("env-loading");
    if (loading) loading.style.display = "";
    try {
      envs = await Promise.all(
        types.map(async (t, i) => ({
          t, i,
          env: await api("/api/envelope", {
            aircraft: aircraftPayload(), reserve_kg: reserve,
            backend: "openap", actype: t, step_kg: 250,
          }),
        }))
      );
      clearApiError();
    } catch (err) {
      showApiError(err);
    } finally {
      if (loading) loading.style.display = "none";
    }
    if (!envs) return;
    traces = envs.map(({ t, i, env }) => ({
      x: env.payload_kg.map((p) => p / 1000), y: env.max_range_km.map((r) => r / 1000),
      mode: "lines", name: t.toUpperCase() + " (OpenAP)",
      line: { color: OPENAP_SERIES_COLORS[i % OPENAP_SERIES_COLORS.length], width: 2 },
      hovertemplate: "业载 %{x:.1f} t · 航程 %{y:,.0f} km<extra>" + t.toUpperCase() + "</extra>",
    }));
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
  const note = $("env-note");
  if (note) note.textContent = backend() === "openap"
    ? "OpenAP 模型基于公开科研数据（BADA 派生），油耗随重量逐点积分；个别新机型（如 a20n）的数据偏乐观，读数时注意甄别。C919 无公开模型，a320 为同级别代理。"
    : "C919 预设为公开报道 + 估计值（非官方数据），曲线为常数油耗教学模型。调整左栏「储备油扣减」，包线整体左移——手册标称航程通常含储备。拐点含义：业载重于该点时受 MTOW 限制（油带不满），轻于该点时受油箱容量限制。";
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
  for (const p of ["route", "env", "hot", "delay"]) $("page-" + p).style.display = p === name ? "" : "none";
  for (const t of ["route", "env", "hot", "delay"]) $("tab-" + t).classList.toggle("active", t === name);
  renderActive(name);
}

let currentTab = "route";
function renderActive(name = currentTab) {
  currentTab = name;
  const fn = name === "route" ? renderRoute
    : name === "env" ? renderEnv
    : name === "hot" ? renderHot
    : renderDelay;
  fn().catch(console.error);
}

// ------------------------------------------------------------- tab 4

let delayRan = false;

async function runDelayAnalysis() {
  const source = $("d-source").value;
  const body = source === "opensky"
    ? { source, opensky_airport: $("d-os-airport").value.trim().toUpperCase(),
        opensky_client_id: $("d-os-id").value.trim(),
        opensky_client_secret: $("d-os-secret").value }
    : { source, n_aircraft: +$("d-aircraft").value, n_days: +$("d-days").value, seed: 42 };
  const btn = $("d-run");
  btn.disabled = true; btn.textContent = "分析中…";
  try {
    const data = await api("/api/delay", body);
    clearApiError();
    renderDelayResults(data);
  } catch (err) {
    showApiError(err);
  } finally {
    btn.disabled = false; btn.textContent = "开始分析";
  }
}

function renderDelayResults(data) {
  const s = data.summary;
  $("delay-metrics").innerHTML = `
    <div class="metric"><div class="k">数据源</div><div class="v" style="font-size:15px">${data.source === "opensky" ? "OpenSky 实测" : "合成机队"}</div></div>
    <div class="metric"><div class="k">航班</div><div class="v">${fmt(s.n_flights)}</div></div>
    <div class="metric"><div class="k">机尾</div><div class="v">${fmt(s.n_tails)}</div></div>
    <div class="metric"><div class="k">轮转链边</div><div class="v">${fmt(s.n_edges)}</div></div>
    <div class="metric"><div class="k">平均到达延误</div><div class="v">${s.mean_delay_min}<span class="note">min</span></div></div>`;

  $("delay-inheritance").innerHTML = `<table>
    <tr><th>阈值</th><th>过站对</th><th>上一班延误</th><th>两班都延误</th>
        <th>P(下一班延误)</th><th>P(下一班延误 | 上一班延误)</th><th>lift</th></tr>
    ${data.inheritance.map((r) => `
      <tr><td>${r.threshold_min} min</td><td>${fmt(r.n_pairs)}</td>
      <td>${fmt(r.n_prev_delayed)}</td><td>${fmt(r.n_propagated)}</td>
      <td>${r.p_next_delayed ?? "--"}</td><td>${r.p_next_given_prev ?? "--"}</td>
      <td class="${(r.lift ?? 1) > 1.3 ? "bad" : ""}">${r.lift ?? "--"}</td></tr>`).join("")}
  </table>`;

  if (!window.Plotly) return;
  const hubs = data.hubs;
  if (hubs.length) {
    Plotly.react("delay-hubs", [{
      type: "bar", orientation: "h",
      x: hubs.map((h) => h.propagation_ratio), y: hubs.map((h) => h.airport),
      customdata: hubs.map((h) => h.label),
      marker: { color: THEME.crimson },
      text: hubs.map((h) => (h.propagation_ratio * 100).toFixed(0) + "%"),
      textposition: "outside", textfont: { size: 11 }, cliponaxis: false,
      hovertemplate: "%{customdata}<br>传播比例 %{x:.1%}<extra></extra>",
    }], chartLayout({
      title: { text: "传播枢纽：延误越过过站的占比", font: TITLE_FONT, x: 0, xanchor: "left" },
      height: 360, margin: { l: 120, r: 40, t: 44, b: 30 },
      xaxis: { tickformat: ".0%", zeroline: false }, yaxis: { autorange: "reversed", ticks: "" },
    }), PLOTLY_CONFIG);
  }

  const flow = data.flow;
  if (flow.length) {
    Plotly.react("delay-flow", [
      { type: "bar", name: "送出 sent", x: flow.map((f) => f.airport),
        y: flow.map((f) => f.sent / 60), marker: { color: THEME.accent } },
      { type: "bar", name: "接收 received", x: flow.map((f) => f.airport),
        y: flow.map((f) => f.received / 60), marker: { color: THEME.slateLight } },
    ], chartLayout({
      title: { text: "机场延误流量（小时，按继承延误合计）", font: TITLE_FONT, x: 0, xanchor: "left" },
      height: 360, barmode: "group", bargap: 0.3,
      yaxis: { gridcolor: THEME.grid, zeroline: false },
      legend: { orientation: "h", y: -0.22, x: 0 },
    }), PLOTLY_CONFIG);
  }
}

function renderDelay() {
  if (!delayRan) { delayRan = true; runDelayAnalysis(); }
}

function applyDelaySourceMode() {
  const os = $("d-source").value === "opensky";
  $("d-synth-field").style.display = os ? "none" : "";
  $("d-synth-field2").style.display = os ? "none" : "";
  $("d-os-field").style.display = os ? "" : "none";
  $("d-os-field2").style.display = os ? "" : "none";
  $("d-os-field3").style.display = os ? "" : "none";
}

let timer = null;
function scheduleRender() {
  clearTimeout(timer);
  timer = setTimeout(() => renderActive(), 250);
}

// OpenAP mode: MTOW/OEW/burn/TAS come from the OpenAP database, so the
// corresponding sidebar inputs stop applying; tank/payload caps stay live.
// Comparison switches from the simple-model presets to OpenAP type codes.
function fillOpenapCompare() {
  const available = OPENAP_COMPARE.filter((t) => state.aircraftTypes.includes(t));
  const list = available.length ? available : state.aircraftTypes.slice(0, 5);
  $("openap-compare").innerHTML = list
    .map((t) => `<label class="chk"><input type="checkbox" value="${t}" checked> ${t.toUpperCase()}</label>`)
    .join("");
}

function applyBackendMode() {
  const openapMode = backend() === "openap";
  $("actype-field").style.display = openapMode ? "" : "none";
  $("backend-note").style.display = openapMode ? "" : "none";
  $("openap-compare-field").style.display = openapMode ? "" : "none";
  $("simple-compare-field").style.display = openapMode ? "none" : "";
  for (const id of ["p-mtow", "p-oew", "p-flow", "p-tas"]) $(id).disabled = openapMode;
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
  $("d-source").addEventListener("change", applyDelaySourceMode);
  applyBackendMode();
  applyDelaySourceMode();
  fillSelects(); fillHotTemps(); fillOpenapCompare();
  document.querySelectorAll("input,select").forEach((el) => {
    el.addEventListener("input", scheduleRender);
    el.addEventListener("change", scheduleRender);
  });
  renderActive();
})();
