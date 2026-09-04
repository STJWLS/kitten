# EMF 26R 课程看板（Fall 2026）

复旦大学泛海国际金融学院 EMF 26R 班 Module 1 & 2 秋季学期课程表数据看板。

- **在线入口**：https://stjwls.github.io/emf-schedule/
- **数据**：`schedule.json`（单一数据源，前端零逻辑改动即可更新课表）
- **前端**：`index.html`（自包含深色监控台界面，无任何第三方依赖）
- **设计参照**：大论文 vault 的「大论文实验看板」（`dashboard.html` 同款设计语言）

## 架构

静态 GitHub Pages 看板，无需本地服务器与隧道：

```
schedule.json  ──fetch──▶  index.html（纯前端渲染）
     ▲
     │  sync_schedule.py 推送（GitHub Contents API）
 本地 school/dashboard/
```

> 与「大论文实验看板」的差异：实验看板因数据每 30 分钟更新（本机 JSON + 图表），采用「本地 Python 服务 + Cloudflare 隧道 + 跳转页」；课表数据为静态数据，直接用 GitHub Pages 托管更简单且 7×24 在线。

## 数据说明

- 数据由官方课程表 PDF 经 MinerU 解析后，按**坐标重建网格**逐格核验生成（108 个课程格）。
- 已核验的特殊点：CARE EN 各场次日期/时间、W14 周六课调至周日、TPM 周六为单节课、中秋/国庆/元旦标注范围。

## 更新课表

1. 编辑 `schedule.json`（本地：`school/dashboard/schedule.json`）
2. 运行 `python sync_schedule.py`（使用 `~/.dashboard_config/` 下的 GitHub 凭据）
