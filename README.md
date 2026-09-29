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
- ✈️ 同级代理机型性能模型（用公开资料的 A320neo 级参数近似 C919，诚实标注，后续可切换 [OpenAP](https://github.com/junzis/openap)）
- 📊 业载-航程包线（payload–range envelope）
- ⛽ 简化油量政策，逐项输出 breakdown
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

（可选）研究级性能模型：`pip install -e ".[perf]"` 安装 OpenAP 后端（规划中，见路线图）。

## 案例集（cases/）

| 案例 | 问题 | 状态 |
|---|---|---|
| [01 业载-航程](cases/01_range_payload.ipynb) | C919（估计参数）vs A320neo vs 737 MAX 8 的业载-航程包线，谁被油箱卡住？OEW 敏感性多大？ | ✅ 已完成 |
| [02 高原高温](cases/02_hot_high.ipynb) | 浦东—乌鲁木齐/喀什：高温高原机场的起降场长余量与备降油量 | ✅ 已完成 |
| 03 延误传播 | 实测航班数据里，延误如何沿机尾号链传播？ | 📋 规划中 |
| 04 机队情景 | 2026–2030 假想航线网络覆盖与座位投放 | 📋 规划中 |

## 方法学与诚实话

- C919 没有公开性能数据，本仓库用**同级别代理机型**（约 170 座、LEAP-1 级发动机的 A320neo 级参数）做近似，所有参数与假设在 [docs/methodology.md](docs/methodology.md) 中逐条列明；
- 球面地球大圆近似（~0.5% 误差）；巡航油耗视为常数；起降场长是启发式公式，系数全部写在代码里；
- 油量政策参考 CCAR-121 / ICAO Annex 6 的结构做了大幅简化，**不保守、不权威**；
- 数据来源全部公开，见 [docs/data-sources.md](docs/data-sources.md)。

## 路线图

- [x] v0.1 仓库骨架：CLI + 大圆 + 机场数据 + 性能/油量内核 + CI
- [x] v0.2 业载-航程案例 notebook + 高原高温案例 notebook
- [ ] 文档站上线 GitHub Pages（工作流已就绪并停用中：私有仓库需 GitHub Pro，转公开即可启用）
- [ ] OpenAP 研究级性能后端封装（可选 extra，规划中）
- [ ] v0.3 OpenSky 延误传播网络分析（`network.py` + 案例 03）
- [ ] v1.0 机队情景案例 + 打 tag

## English

**c919-routelab** is an open-source, learning-grade toolkit for route-level operations analysis of single-aisle airliners, built entirely on public data (OurAirports airports and runways, public aircraft specifications, later OpenSky ADS-B). Given an origin–destination pair it estimates great-circle distance, a payload–range envelope, heuristic takeoff field lengths with altitude/temperature corrections, and a simplified CCAR-121-style fuel breakdown (taxi, trip, 5% contingency, alternate, final reserve). The C919 has no open performance data, so a clearly documented A320neo-class proxy aircraft is used; an optional `openap` extra is planned to swap in a research-grade model. Everything here is for education only — not for flight planning or engineering. See `docs/` for methodology and data sources.

## Français

**c919-routelab** est une boîte à outils open source et pédagogique pour l'analyse opérationnelle des avions monocoulois, construite entièrement à partir de données publiques. Pour une paire origine–destination donnée, elle estime la distance orthodromique, l'enveloppe charge utile–distance, des longueurs de piste corrigées de l'altitude et de la température, ainsi qu'une décomposition simplifiée du carburant (roulage, trajet, contingence de 5 %, aérodrome de dégagement, réserve finale). En l'absence de données de performance ouvertes sur le C919, un appareil proxy de classe A320neo est utilisé et documenté. Réservé à l'apprentissage — pas pour le vol réel.

## License

MIT — see [LICENSE](LICENSE).
