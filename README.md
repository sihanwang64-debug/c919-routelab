# c919-routelab ✈️

**中文** · [English](#english) · [Français](#français)

> 基于 100% 公开数据的单通道民机航线运行分析工具包（非官方学习项目）。
> An open-source, learning-grade toolkit for route-level narrow-body operations analysis, built entirely on public data (unofficial study project).
> Une boîte à outils open source et pédagogique pour l'analyse opérationnelle des lignes aériennes, construite uniquement à partir de données publiques (projet d'étude non officiel).

![CI](https://github.com/sihanwang64-debug/c919-routelab/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**非官方声明**：本项目与中国商用飞机有限责任公司（COMAC）及其任何下属单位无任何隶属、合作或授权关系；"C919" 仅作为学习研究主题的名称使用，相关商标权利归其权利人所有。所有计算结果仅供学习演示，**不可用于飞行计划、工程或任何严肃用途**。详见 [DISCLAIMER.md](DISCLAIMER.md)。

## 这是什么

给定一条航线（比如浦东 → 乌鲁木齐），回答三件事：

1. **飞得过去吗？** —— 大圆航距、业载-航程包线、高原/高温机场的起降场长修正；
2. **要带多少油？** —— 巡航油耗估算 + 简化的 CCAR-121 式油量政策（滑行 / 航程 / 5% 应急 / 备降 / 最终储备）；
3. **延误会怎么扩散？** —— （路线图中）基于 ADS-B 实测数据的延误传播网络分析。

### 特性

- 🌍 大圆航距与初始航向（球面近似，误差约 0.5% 量级，见[方法学](docs/methodology.md)）
- 🛫 机场与跑道数据层（内置 [OurAirports](https://ourairports.com/data/) 公有领域数据样本，可通过环境变量切换完整数据集）
- ✈️ 两级性能模型：简化常数油耗（默认）+ 可选 [OpenAP](https://github.com/junzis/openap) 研究级燃烧模型（油耗随重量变化，`pip install -e ".[perf]"`）
- 📊 业载-航程包线（payload–range envelope）
- ⛽ 简化油量政策，逐项输出 breakdown
- 🖥️ Web 界面（前后端分离：FastAPI 后端 `server.py` + 原生 HTML/JS 前端 `web/`，双击 `start_webapp.bat` 即用）/ Streamlit 版 / CLI，计算层同源、数字一致
- 🧪 pytest 单元测试 + GitHub Actions CI + MkDocs 文档
- 🗣️ 中 / 英 / 法三语文档

## 快速开始

```bash
git clone https://github.com/sihanwang64-debug/c919-routelab.git
cd c919-routelab
pip install -e .

# 大圆距离与初始航向
routelab distance ZSPD ZWWW

# 单段航线的油量估算（代理机型，含备降与简化油量政策）
routelab range ZSPD ZWWW --alternate ZWSH --payload 15000

# 列出内置样本机场
routelab airports --country CN
```

不想敲命令行？双击 `start_webapp.bat` 打开 [Web 界面](#web-界面前后端分离fastapi--原生-htmljs)，选选机场拖拖参数就有同样的结果。

## Web 界面（前后端分离：FastAPI + 原生 HTML/JS）

**启动（Windows 最快路径）**：双击仓库根目录的 `start_webapp.bat` —— 自动选 venv/系统 Python、起后端并打开浏览器 [http://127.0.0.1:8300](http://127.0.0.1:8300)（`Ctrl+C` 停止）。

**手动启动**：

```bash
pip install -e ".[server]"     # 核心包 + fastapi + uvicorn
python run_server.py           # 或：uvicorn server:app --port 8300 --reload
```

**架构**（后续开发就按这个分层走）：

```
浏览器 web/（index.html + app.js + style.css，只做展示与交互）
    │  fetch /api/*
    ▼
server.py（FastAPI：REST API + 托管 web/ 静态文件，交互式文档在 /docs）
    │  直接调用
    ▼
src/routelab/（计算内核：airports / performance / fuel / planning / presets）
```

- 后端接口：`GET /api/airports`、`GET /api/presets`、`POST /api/route`（航段计划）、`POST /api/envelope`（业载-航程）、`POST /api/hot`（场长余量）
- 所有数字由 Python 包计算，前端零业务逻辑——CLI、Streamlit、Web 三个入口同源，数字永远一致
- 后端加功能 = 在 `routelab` 包里写函数 + 在 `server.py` 暴露端点；前端只需调接口

三个标签页的用法（左侧边栏为全局参数）：

### 航线规划

1. 下拉选择**出发 / 到达 / 备降**机场（内置 11 个样本机场，国内 8 个；接入完整 OurAirports 数据集的方法见[数据来源](docs/data-sources.md)）；
2. 地图即时画出大圆航线（红色实线）与备降航段（橙色虚线），悬停机场标记可看标高；
3. 下方给出航距（km/NM）、航程时间、轮档油、本航段可带业载与可行性判定，以及轮档油构成的条形图与明细表。

![航线规划页](docs/img/app-route-tab.png)

### 业载–航程

- 调整**储备油扣减**，整组包线左移——直观体会"手册航程是含储备的"；
- 勾选对比机型（A320neo / 737 MAX 8 / C919 估计值），与"当前自定义机型"同图对比，悬停曲线读任意业载点的最大航程。

![业载-航程页](docs/img/app-envelope-tab.png)

### 高原高温

- 为 8 个国内样本机场分别设定假设温度（默认七月午后情景）；
- 表格与柱状图输出：需要场长 vs 可用跑道的**余量**，以及"热到几度顶满跑道"的**临界温度**。

![高原高温页](docs/img/app-hothigh-tab.png)

### 侧栏参数说明

| 参数 | 含义 | 默认 |
|---|---|---|
| 机型参数 | MTOW / OEW / 最大油量 / 最大业载 / 巡航油耗 / 巡航 TAS | A320neo 级代理 |
| 业载 | 当前航段假设业载 | 15 t |
| 巡航顶风 | 平均巡航风分量，负值为顺风 | 0 km/h |
| 绕飞比例 | 占航程油的百分比 | 5% |
| 最终储备 | 30 min（ICAO 惯例）或 45 min（CCAR-121 国内惯例） | 30 min |
| 滑行油 | 固定滑行 allowance | 200 kg |

Web 界面与 CLI 共用同一个计算层 `routelab.planning.plan_leg()`，两边数字永远一致。仓库里另有等价的 Streamlit 版（`app.py`，`pip install -e ".[app]"` 后 `streamlit run app.py`）。

（可选）研究级性能模型：`pip install -e ".[perf]"` 安装 OpenAP，然后在界面左上「性能模型」切换为 OpenAP 模式（机型下拉选 a320/b738 等 37 个型号）。

## 案例集（cases/）

| 案例 | 问题 | 状态 |
|---|---|---|
| [01 业载-航程](cases/01_range_payload.ipynb) | C919（估计参数）vs A320neo vs 737 MAX 8 的业载-航程包线，谁被油箱卡住？OEW 敏感性多大？ | ✅ 已完成 |
| [02 高原高温](cases/02_hot_high.ipynb) | 浦东—乌鲁木齐/喀什：高温高原机场的起降场长余量与备降油量 | ✅ 已完成 |
| 03 延误传播 | 实测航班数据里，延误如何沿机尾号链传播？ | 📋 规划中 |
| 04 机队情景 | 2026–2030 假想航线网络覆盖与座位投放 | 📋 规划中 |

## 方法学与诚实话

- C919 没有公开性能数据，本仓库用**同级别代理机型**（约 170 座、LEAP-1 级发动机的 A320neo 级参数）做近似，所有参数与假设在 [docs/methodology.md](docs/methodology.md) 中逐条列明；
- 简化模式下巡航油耗视为常数；切换 OpenAP 模式后油耗随重量变化（见方法学 1b 节）；起降场长是启发式公式，系数全部写在代码里；
- 油量政策参考 CCAR-121 / ICAO Annex 6 的结构做了大幅简化，**不保守、不权威**；
- 数据来源全部公开，见 [docs/data-sources.md](docs/data-sources.md)。

## 路线图

- [x] v0.1 仓库骨架：CLI + 大圆 + 机场数据 + 性能/油量内核 + CI
- [x] v0.2 业载-航程案例 notebook + 高原高温案例 notebook
- [x] 前后端分离 Web 版：FastAPI API（`server.py`）+ 原生前端（`web/`），`start_webapp.bat` 一键启动
- [x] Streamlit Web 界面（`app.py`：地图航线规划 / 交互包线 / 高原高温）
- [ ] 文档站上线 GitHub Pages（工作流已就绪并停用中：私有仓库需 GitHub Pro，转公开即可启用）
- [x] OpenAP 研究级燃烧模型后端（`routelab/openap_backend.py`，CLI/API/界面均可切换）
- [ ] v0.3 OpenSky 延误传播网络分析（`network.py` + 案例 03）
- [ ] v1.0 机队情景案例 + 打 tag

## English

**c919-routelab** is an open-source, learning-grade toolkit for route-level operations analysis of single-aisle airliners, built entirely on public data (OurAirports airports and runways, public aircraft specifications, later OpenSky ADS-B). Given an origin–destination pair it estimates great-circle distance, a payload–range envelope, heuristic takeoff field lengths with altitude/temperature corrections, and a simplified CCAR-121-style fuel breakdown (taxi, trip, 5% contingency, alternate, final reserve). The C919 has no open performance data, so a clearly documented A320neo-class proxy aircraft is used; an optional `openap` extra is planned to swap in a research-grade model. An optional Streamlit web app (`pip install -e ".[app]"` then `streamlit run app.py`) puts the same computation layer behind a GUI: a map-based route planner with great-circle drawing, an interactive payload-range chart with aircraft comparison, and hot-and-high field-length margins. Everything here is for education only — not for flight planning or engineering. See `docs/` for methodology and data sources.

## Français

**c919-routelab** est une boîte à outils open source et pédagogique pour l'analyse opérationnelle des avions monocoulois, construite entièrement à partir de données publiques. Pour une paire origine–destination donnée, elle estime la distance orthodromique, l'enveloppe charge utile–distance, des longueurs de piste corrigées de l'altitude et de la température, ainsi qu'une décomposition simplifiée du carburant (roulage, trajet, contingence de 5 %, aérodrome de dégagement, réserve finale). En l'absence de données de performance ouvertes sur le C919, un appareil proxy de classe A320neo est utilisé et documenté. Une application web Streamlit optionnelle (`pip install -e ".[app]"` puis `streamlit run app.py`) propose la même couche de calcul en interface graphique : planification de routes sur carte, enveloppe charge–distance interactive et marges de longueur de piste en conditions chaudes et hautes. Réservé à l'apprentissage — pas pour le vol réel.

## License

MIT — see [LICENSE](LICENSE).
