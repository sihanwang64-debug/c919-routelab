# c919-routelab

Learning-grade narrow-body route operations analysis on public data.

- 中文主页见仓库 [README](https://github.com/sihanwang64-debug/c919-routelab)。
- [Methodology](methodology.md)：每个模型假设的来源与局限。
- [Data sources](data-sources.md)：数据出处与许可。
- 案例 notebooks（GitHub 在线渲染）：
    - [案例 01 · 业载-航程包线：C919（估计）vs A320neo vs 737 MAX 8](https://github.com/sihanwang64-debug/c919-routelab/blob/main/cases/01_range_payload.ipynb)
    - [案例 02 · 高原与高温：浦东—乌鲁木齐—喀什](https://github.com/sihanwang64-debug/c919-routelab/blob/main/cases/02_hot_high.ipynb)

```bash
pip install -e .
routelab distance ZSPD ZWWW
routelab range ZSPD ZWWW --alternate ZWSH
```

> 非官方学习项目，与 COMAC 无关联；所有输出仅供学习，不可用于飞行计划或工程。见 DISCLAIMER.md。
