/* c919-routelab frontend: presentation only -- every number comes from the API. */
"use strict";

const KM_PER_NM = 1.852;
const $ = (id) => document.getElementById(id);
const fmt = (v, d = 0) =>
  v == null ? "--" : v.toLocaleString("zh-CN", { maximumFractionDigits: d });

const state = { airports: [], presets: {} };

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

async function api(path, body) {
  const res = await fetch(path, body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : undefined);
  if (!res.ok) throw new Error(`${path}: ${res.status} ${await res.text()}`);
  return res.json();
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
  const plan = await api("/api/route", {
    origin: o.ident, destination: d.ident,
    alternate: altV !== "-" ? altV : "",
    payload_kg: +$("p-payload").value * 1000,
    headwind_kmh: +$("p-wind").value,
    aircraft: aircraftPayload(), policy: policyPayload(),
  });
  const alt = altV !== "-" ? state.airports.find((a) => a.ident === altV) : null;

  $("route-metrics").innerHTML = `
    <div class="metric"><div class="k">航距</div><div class="v">${fmt(plan.distance_km)} km<br><span class="note">${fmt(plan.distance_nm)} NM</span></div></div>
    <div class="metric"><div class="k">航程时间</div><div class="v">${plan.trip_time_h.toFixed(2)} h</div></div>
    <div class="metric"><div class="k">轮档油</div><div class="v">${fmt(plan.block_kg)} kg</div></div>
    <div class="metric"><div class="k">本航段可带业载</div><div class="v">${(plan.max_payload_on_leg_kg / 1000).toFixed(1)} t</div></div>
    <div class="metric"><div class="k">业载 ${$("p-payload").value} t 可行性</div>
      <div class="v ${plan.feasible ? "ok" : "bad"}">${plan.feasible ? "✅ 可行" : "❌ 超限"}</div></div>`;

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
    line: { width: 2.5, color: "crimson" }, showlegend: false, hoverinfo: "skip",
  }];
  const marks = [[o, "出发", "blue"], [d, "到达", "green"]];
  if (alt) marks.push([alt, "备降", "orange"]);
  for (const [ap, role, color] of marks) {
    traces.push({
      type: "scattergeo", mode: "markers+text", lon: [ap.lon], lat: [ap.lat],
      text: [ap.ident], textposition: "top center",
      marker: { size: 10, color }, name: `${role} ${ap.ident}`,
      hovertext: `${ap.ident} ${ap.name}｜标高 ${fmt(ap.elev_ft)} ft｜跑道 ${fmt(ap.runway_m)} m`,
    });
  }
  if (alt) {
    const arc2 = arcPoints(d.lat, d.lon, alt.lat, alt.lon, 64);
    traces.push({
      type: "scattergeo", mode: "lines",
      lon: arc2.map((p) => p[1]), lat: arc2.map((p) => p[0]),
      line: { width: 1.8, color: "orange", dash: "dot" }, showlegend: false, hoverinfo: "skip",
    });
  }
  Plotly.react("map", traces, {
    height: 430, margin: { l: 0, r: 0, t: 0, b: 0 }, showlegend: true,
    geo: {
      projection: { type: "natural earth" }, showland: true, landcolor: "rgb(242,240,236)",
      showcountries: true, countrycolor: "grey", fitbounds: "locations",
    },
  }, { responsive: true });

  Plotly.react("fuel-chart", [{
    type: "bar", orientation: "h",
    x: [plan.trip_kg, plan.contingency_kg, plan.alternate_kg, plan.final_reserve_kg, plan.taxi_kg],
    y: ["航程", "绕飞", "备降", "最终储备", "滑行"], marker: { color: "indianred" },
    text: [fmt(plan.trip_kg), fmt(plan.contingency_kg), fmt(plan.alternate_kg), fmt(plan.final_reserve_kg), fmt(plan.taxi_kg)],
    textposition: "auto",
  }], { title: "轮档油构成 (kg)", height: 300, margin: { l: 70, r: 20, t: 40, b: 20 } }, { responsive: true });
}

// ------------------------------------------------------------- tab 2

async function renderEnv() {
  if (!window.Plotly) return;
  const reserve = +$("p-reserve").value * 1000;
  const jobs = [];
  if ($("c-custom").checked) jobs.push(["当前自定义机型", aircraftPayload()]);
  const presetJobs = [["c-a320", "A320neo (公开手册量级)"], ["c-max8", "737 MAX 8 (公开手册量级)"], ["c-c919", "C919 (公开报道+估计，非官方)"]];
  for (const [id, key] of presetJobs)
    if ($(id).checked && state.presets[key]) jobs.push([key, state.presets[key]]);
  const results = await Promise.all(
    jobs.map(async ([label, aircraft]) => [label, await api("/api/envelope", { aircraft, reserve_kg: reserve })])
  );
  const traces = results.map(([label, env]) => ({
    x: env.payload_kg.map((p) => p / 1000), y: env.max_range_km.map((r) => r / 1000),
    mode: "lines", name: label,
    hovertemplate: "业载 %{x:.1f} t<br>航程 %{y:,} km<extra>" + label + "</extra>",
  }));
  Plotly.react("env-chart", traces, {
    title: "业载-航程包线（含储备油）",
    xaxis: { title: "业载 (t)" }, yaxis: { title: "最大航程 (1000 km)" },
    height: 480, hovermode: "x unified", margin: { l: 60, r: 20, t: 50, b: 50 },
  }, { responsive: true });
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
    { x, y: rows.map((r) => r.runway_m), type: "bar", name: "可用跑道", marker: { color: "seagreen" } },
    { x, y: rows.map((r) => r.required_tofl_m), type: "bar", name: "需要场长（MTOW，无风）", marker: { color: "indianred" } },
  ], { title: "启发式起飞场长 vs 可用跑道（m）", barmode: "group", height: 400, margin: { l: 60, r: 20, t: 50, b: 50 } }, { responsive: true });
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

(async function init() {
  if (!window.Plotly) $("plot-error").style.display = "block";
  const [airports, presets] = await Promise.all([api("/api/airports"), api("/api/presets")]);
  state.airports = airports.map(normalizeAirport);
  state.presets = presets;
  fillSelects(); fillHotTemps();
  document.querySelectorAll("input,select").forEach((el) => {
    el.addEventListener("input", scheduleRender);
    el.addEventListener("change", scheduleRender);
  });
  renderActive();
})();
