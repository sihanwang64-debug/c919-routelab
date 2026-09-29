"""Streamlit web UI for c919-routelab (route planning, envelope, hot & high).

Run with::

    pip install -e ".[app]"
    streamlit run app.py

All computation lives in the ``routelab`` package; this file is presentation
only. Chinese UI on purpose (the project's primary audience).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from routelab.airports import Airport, AirportDB
from routelab.fuel import FuelPolicy
from routelab.greatcircle import intermediate_points
from routelab.performance import (
    ProxyAircraft,
    isa_temperature_c,
    payload_range_table,
    takeoff_field_length_m,
)
from routelab.planning import plan_leg
from routelab.presets import PRESET_AIRCRAFT

st.set_page_config(page_title="c919-routelab ✈️", page_icon="✈️", layout="wide")

# 夏季午后的假设温度（教学假设，可改）——默认值与 cases/02 保持一致
DEFAULT_SUMMER_T_C = {"ZSPD": 33.0, "ZWWW": 34.0, "ZWSH": 34.0, "ZPPP": 24.0}


@st.cache_resource
def airport_db() -> AirportDB:
    return AirportDB()


def airport_label(a: Airport) -> str:
    iata = a.iata if a.iata else "--"
    return f"{a.ident}（{iata}）{a.name}"


def sidebar_inputs() -> tuple[ProxyAircraft, float, float, FuelPolicy]:
    """Aircraft (editable proxy), payload, headwind and fuel-policy inputs."""
    d = ProxyAircraft()
    with st.sidebar.expander("机型参数（A320neo 级代理，可调）"):
        mtow = st.number_input("MTOW (t)", 60.0, 100.0, d.mtow_kg / 1000, 0.5) * 1000
        oew = st.number_input("OEW (t)", 35.0, 65.0, d.oew_kg / 1000, 0.5) * 1000
        max_fuel = st.number_input("最大油量 (t)", 10.0, 30.0, d.max_fuel_kg / 1000, 0.5) * 1000
        max_payload = st.number_input(
            "最大业载 (t)", 10.0, 30.0, d.max_payload_kg / 1000, 0.5
        ) * 1000
        flow = st.number_input("巡航油耗 (kg/h)", 1200.0, 3000.0, d.cruise_fuel_kg_per_h, 50.0)
        tas = st.number_input("巡航 TAS (km/h)", 700.0, 950.0, d.cruise_tas_kmh, 5.0)
    payload = st.sidebar.slider("业载 (t)", 0.0, 25.0, 15.0, 0.5) * 1000
    headwind = st.sidebar.slider("巡航顶风 (km/h，负值为顺风)", -80.0, 120.0, 0.0, 5.0)
    with st.sidebar.expander("油量政策"):
        contingency = st.slider("绕飞比例 (%)", 0.0, 10.0, 5.0, 0.5) / 100
        final_reserve_min = st.select_slider("最终储备 (min)", [30, 45], 30)
        taxi = st.number_input("滑行油 (kg)", 0.0, 500.0, 200.0, 50.0)
    ac = ProxyAircraft(
        name="自定义代理机型", mtow_kg=mtow, oew_kg=oew, max_fuel_kg=max_fuel,
        max_payload_kg=max_payload, cruise_tas_kmh=tas, cruise_fuel_kg_per_h=flow,
    )
    policy = FuelPolicy(
        contingency_frac=contingency, final_reserve_min=float(final_reserve_min), taxi_kg=taxi
    )
    return ac, payload, headwind, policy


def route_map(db: AirportDB, origin: str, destination: str, alternate: str) -> go.Figure:
    o, d = db.get(origin), db.get(destination)
    fig = go.Figure()
    path = intermediate_points(o.lat_deg, o.lon_deg, d.lat_deg, d.lon_deg, 96)
    fig.add_trace(
        go.Scattergeo(
            lon=[p[1] for p in path], lat=[p[0] for p in path],
            mode="lines", line={"width": 2.5, "color": "crimson"},
            hoverinfo="skip", showlegend=False,
        )
    )
    marks = [(o, "出发", "blue"), (d, "到达", "green")]
    if alternate:
        marks.append((db.get(alternate), "备降", "orange"))
    for ap, role, color in marks:
        fig.add_trace(
            go.Scattergeo(
                lon=[ap.lon_deg], lat=[ap.lat_deg], mode="markers+text",
                text=[ap.ident], textposition="top center",
                marker={"size": 10, "color": color},
                name=f"{role} {ap.ident}",
                hovertext=f"{ap.ident} {ap.name}<br>标高 {ap.elevation_ft:.0f} ft",
            )
        )
    if alternate:
        alt = db.get(alternate)
        leg2 = intermediate_points(d.lat_deg, d.lon_deg, alt.lat_deg, alt.lon_deg, 64)
        fig.add_trace(
            go.Scattergeo(
                lon=[p[1] for p in leg2], lat=[p[0] for p in leg2], mode="lines",
                line={"width": 1.8, "color": "orange", "dash": "dot"},
                hoverinfo="skip", showlegend=False,
            )
        )
    fig.update_geos(
        projection_type="natural earth", showland=True, landcolor="rgb(242,240,236)",
        showcountries=True, countrycolor="grey", fitbounds="locations",
    )
    fig.update_layout(height=480, margin={"l": 0, "r": 0, "t": 0, "b": 0})
    return fig


def tab_route(db: AirportDB, ac: ProxyAircraft, payload: float, headwind: float,
              policy: FuelPolicy) -> None:
    idents = sorted(a.ident for a in db.by_country("CN")) + \
        sorted(a.ident for a in db.all() if a.iso_country != "CN")
    col1, col2, col3 = st.columns([2, 2, 2])
    origin = col1.selectbox("出发机场", idents, format_func=lambda i: airport_label(db.get(i)))
    dest_options = [i for i in idents if i != origin]
    destination = col2.selectbox("到达机场", dest_options,
                                 index=dest_options.index("ZWWW"),
                                 format_func=lambda i: airport_label(db.get(i)))
    no_alt = "（无备降，按 300 km 默认）"
    alt_options = [no_alt] + [i for i in idents if i not in (origin, destination)]
    alternate_raw = col3.selectbox("备降机场", alt_options)
    alternate = "" if alternate_raw.startswith("（") else alternate_raw

    plan = plan_leg(db, ac, origin, destination, alternate, payload, headwind, policy)
    st.plotly_chart(route_map(db, origin, destination, alternate), use_container_width=True)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("航距", f"{plan.route.distance_km:,.0f} km", f"{plan.route.distance_nm:,.0f} NM")
    m2.metric("航程时间", f"{plan.trip_time_h:.2f} h")
    m3.metric("轮档油", f"{plan.fuel.block_kg:,.0f} kg")
    m4.metric("本航段可带业载", f"{plan.max_payload_on_leg_kg / 1000:.1f} t")
    verdict = "✅ 可行" if plan.feasible else "❌ 超限"
    m5.metric(f"业载 {payload / 1000:.1f} t 可行性", verdict)

    left, right = st.columns([3, 2])
    b = plan.fuel
    items = ["航程", "绕飞", f"备降（{plan.alternate_note}）", "最终储备", "滑行"]
    values = [b.trip_kg, b.contingency_kg, b.alternate_kg, b.final_reserve_kg, b.taxi_kg]
    fig = go.Figure(go.Bar(x=values, y=items, orientation="h",
                           text=[f"{v:,.0f}" for v in values],
                           textposition="outside", marker_color="indianred"))
    fig.update_layout(title="轮档油构成 (kg)", height=300,
                      margin={"l": 10, "r": 40, "t": 40, "b": 10})
    left.plotly_chart(fig, use_container_width=True)
    right.dataframe(pd.DataFrame({
        "项目": ["航程油", "绕飞", "备降", "最终储备", "滑行", "轮档油", "油量上限", "超限?"],
        "kg": [b.trip_kg, b.contingency_kg, b.alternate_kg, b.final_reserve_kg,
               b.taxi_kg, b.block_kg, plan.fuel_limit_kg,
               "否" if plan.feasible else "是"],
    }), use_container_width=True, hide_index=True)


def tab_envelope(ac: ProxyAircraft) -> None:
    col1, col2 = st.columns([3, 1])
    reserve_t = col1.slider("储备油扣减 (t)", 0.0, 5.0, 2.5, 0.1)
    defaults = list(PRESET_AIRCRAFT)
    chosen = col2.multiselect("对比机型（预设）", list(PRESET_AIRCRAFT), defaults)
    fig = go.Figure()
    series = [("当前自定义机型（侧栏）", ac)] + [(k, PRESET_AIRCRAFT[k]) for k in chosen]
    for label, plane in series:
        df = payload_range_table(plane, step_kg=100, reserve_kg=reserve_t * 1000)
        fig.add_trace(go.Scatter(
            x=df["payload_kg"] / 1000, y=df["max_range_km"] / 1000,
            mode="lines", name=label,
            hovertemplate="业载 %{x:.1f} t<br>航程 %{y:,.0f} km<extra>" + plane.name + "</extra>",
        ))
    fig.update_layout(
        title="业载-航程包线（含储备油）", xaxis_title="业载 (t)", yaxis_title="最大航程 (1000 km)",
        height=520, hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "C919 预设为公开报道+估计值（非官方数据）；曲线为常数油耗教学模型，见 docs/methodology.md。"
    )


def tab_hot_high(db: AirportDB) -> None:
    idents = [a.ident for a in db.by_country("CN")]
    chosen = st.multiselect("机场", idents, ["ZSPD", "ZWWW", "ZWSH", "ZPPP"],
                            format_func=lambda i: airport_label(db.get(i)))
    if not chosen:
        st.info("请至少选择一个机场。")
        return
    cols = st.columns(len(chosen))
    temps: dict[str, float] = {}
    for c, ident in zip(cols, chosen):
        default_t = DEFAULT_SUMMER_T_C.get(ident, 30.0)
        temps[ident] = c.number_input(f"{ident} 温度 °C", -20.0, 55.0, default_t, 1.0)

    rows = []
    for ident in chosen:
        ap = db.get(ident)
        isa = isa_temperature_c(ap.elevation_ft)
        req = takeoff_field_length_m(ap.elevation_ft, temps[ident] - isa)
        avail = db.max_runway_m(ap) or 0.0
        scan = np.arange(0.0, 61.0, 0.5)
        need = [takeoff_field_length_m(ap.elevation_ft, t - isa) for t in scan]
        over = [t for t, r in zip(scan, need) if r > avail]
        rows.append({
            "机场": f"{ap.ident} {ap.iata}", "标高 ft": ap.elevation_ft,
            "ISA °C": isa, "假设温度 °C": temps[ident], "ISA 偏差 °C": temps[ident] - isa,
            "需要场长 m": req, "可用跑道 m": avail, "余量 m": avail - req,
            "临界温度 °C": (f"{over[0]:.0f}" if over else ">60"),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df.round(1), use_container_width=True, hide_index=True)

    fig = go.Figure()
    x = np.arange(len(df))
    fig.add_bar(x=x - 0.2, y=df["可用跑道 m"], width=0.4, name="可用跑道", marker_color="seagreen")
    fig.add_bar(x=x + 0.2, y=df["需要场长 m"], width=0.4, name="需要场长（MTOW，无风）",
                marker_color="indianred")
    fig.update_layout(
        title="启发式起飞场长 vs 可用跑道（m）", xaxis_tickvals=x, xaxis_ticktext=df["机场"],
        height=420, barmode="group",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "场长公式为教学级启发式（与重量无关、无障碍物/襟翼/V1 等要素），只展示修正方向与量级。"
    )


def main() -> None:
    st.title("c919-routelab ✈️ 航线运行分析台")
    st.caption(
        "基于公开数据的学习级工具（非官方，不可用于飞行计划/工程）——A320neo 级代理机型近似 C919"
    )
    ac, payload, headwind, policy = sidebar_inputs()
    t1, t2, t3 = st.tabs(["🛫 航线规划", "📊 业载-航程", "🌡️ 高原高温"])
    with t1:
        tab_route(airport_db(), ac, payload, headwind, policy)
    with t2:
        tab_envelope(ac)
    with t3:
        tab_hot_high(airport_db())


main()
