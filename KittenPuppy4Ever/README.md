# EMF 26R 课程看板（Fall 2026）

复旦大学泛海国际金融学院 EMF 26R 班 Module 1 & 2 秋季学期课程表数据看板。

## 页面（多 URL 结构）

- **周课表主页**：https://stjwls.github.io/kitten/emf-schedule/
  - 周课表（点击空白格子添加个人日程：时间/地点/备注，存本机 localStorage，可导出/导入 JSON）
  - 我的日程 / 课程信息 / 考试与节假日
- **地点地图子页**：https://stjwls.github.io/kitten/emf-schedule/map/
  - 天地图底图（key 复用论文项目）+ 地点标记 + 各地点安排（按地点聚合全部周次）

## 文件

| 路径 | 作用 |
| --- | --- |
| `index.html` | 周课表主页 |
| `map/index.html` | 地点地图子页 |
| `assets/dashboard.css` | 两页共享样式 |
| `schedule.json` | 单一数据源（课程/周次/考试/节假日/**venues 地点坐标**） |

## 配色

| 角色 | 颜色 |
| --- | --- |
| 主强调 | FISF 复旦蓝 `#003da5` |
| 底色 / 面板 | 米白 `#f8f4ec` / 白 `#ffffff` / 米色块 `#f2ecdf` |
| 文字 | 暖棕 `#42392b`（正文）/ 卡其灰 `#8a7f6d`（次要） |
| 课程色 | 马卡龙系：蓝 / 薄荷绿 / 薰衣草紫 / 柠檬黄 / 蜜桃橙 / 天蓝 / 粉 / 薄荷青 |
| 特殊 | CARE EN 粉棕 `#d9b0a6`、ELP 卡其 `#d3c39c`、节假日琥珀金 `#c98f2f`、考试粉棕珊瑚 `#c96a5a` |

## 架构

静态 GitHub Pages 看板（仓库 `STJWLS/kitten` 的 `emf-schedule/` 子目录）：

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

1. 编辑 `schedule.json`（本地：`school/dashboard/emf-schedule/schedule.json`）
2. **递增 `index.html` 中的 `DATA_V` 版本号**（绕开浏览器与 Pages CDN 的 10 分钟缓存，否则用户端看不到新数据）
3. 运行 `python sync_schedule.py`（使用 `~/.dashboard_config/` 下的 GitHub 凭据）
