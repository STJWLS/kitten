# KittenPuppy4Ever · 统一页面模板 v1

所有工作台项目（课表、地图、许愿池、Mock、便签）**必须**用同一套页面模板渲染。
模板只规定"页面骨架 + 组件语言"，各项目只提供内容；不允许项目自带页头、页脚、登录门禁或独立主题。

## 1. 页面骨架

```html
<link rel="stylesheet" href="/static/template.css">
<body data-project="<id>">
  <main class="page">
    <section class="section">                     <!-- 可以有多张 -->
      <div class="section-head">
        <h2>区块标题</h2>
        <span class="hint">一句说明</span>
        <div class="actions"><button class="btn soft">操作</button></div>
      </div>
      <div class="toolbar">…筛选/开关…</div>        <!-- 可选 -->
      <div class="grid">…卡片/统计…</div>           <!-- 可选 -->
      <div class="list">…行…</div>                  <!-- 可选 -->
    </section>
  </main>
</body>
```

- 页面**不出现**全局标题：标题/描述/返回由根壳的项目栏统一提供；
- 页面**不出现**登录框、身份切换、退出按钮：身份由根壳统一管理；
- 页面**不出现**项目间导航（工作台/其它项目链接）：导航由根壳统一提供。

## 2. 设计令牌

| 令牌 | 值 | 用途 |
| --- | --- | --- |
| `--bg` | `#f8f4ec` | 页面底色（由根壳统一铺） |
| `--card` | `#fffdf8` | 区块卡片 |
| `--line` | `#e8dfd2` | 描边/分隔 |
| `--ink` / `--muted` | `#42392b` / `#8a7f6d` | 主文字 / 次文字 |
| `--accent` | `#003da5` | 主行动色 |
| 圆角 | 卡片 16px · 控件 10px · 胶囊 999px | |
| 间距 | 页面 18px · 区块间 14px · 卡片内 16/18px | |
| 阴影 | `0 8px 26px rgba(66,57,43,.06)` | 卡片 |
| 字号 | 标题 15px · 区块标题 13px · 正文 13px · 辅助 11.5px | |

## 3. 组件清单（template.css）

| 组件 | 类名 |
| --- | --- |
| 页面容器 | `.page` |
| 区块卡片 | `.section` |
| 区块头 | `.section-head`（`h2` + `.hint` + `.actions`） |
| 工具条 | `.toolbar` |
| 栅格 | `.grid` / `.grid.two` / `.grid.three` |
| 统计卡 | `.stat`（`.k` 标签 / `.v` 数值） |
| 列表 | `.list` + `.row`（`.k` 主键 / `.grow` / `.t` 标题 / `.s` 辅助） |
| 胶囊标签 | `.chip`（`.ok` / `.warn` / `.bad`） |
| 按钮 | `.btn` + `.primary` / `.soft` / `.danger` / `.ghost` / `.sm` |
| 页签 | `.tabs` + `.tab.active` |
| 空态 | `.empty` |
| 弹层 | `.modal` + `.modal-box` + `.modal-head` |
| 输入 | `.input` / `.select` |
| 提示条 | `.note` |
| 动效 | 卡片入场 `fadeUp`、行悬停、按钮按压缩放、`prefers-reduced-motion` 关闭 |

## 4. 迁移规则（原页面 → 模板视图）

1. 页面放入 `projects/<id>/web/index.html`，manifest 用 `"view": {"kind": "custom", "dir": "web"}`；
2. 删除原页的 `<header>`、页脚、返回链接、登录门禁、`loginState()` 判断；
3. 原业务 JS **尽量原样保留**（录音、课表渲染、许愿币规则等），只删除与"页面外壳"相关的代码；
4. 内容结构改为 `.page > .section…`；卡片/按钮/标签统一用模板组件类；
5. 项目专有组件（课表网格、转录气泡、评分卡）保留自己的类，但颜色/圆角/字号必须引用模板令牌；
6. 数据接口不变：课表/许愿池继续用 `/api/state`、`/api/save`；Mock 用 `/mock/api/*`；地图用查看器数据源。

## 5. 路由与刷新

页面模板之外，可见 module 还必须具备可刷新的 GitHub 风格子页面：

- `project.json` 声明唯一的 `path`（如 `/my-tab/`）；
- 生成 `KittenPuppy4Ever/<path>/index.html` Pages 壳：`python tools/sync_pages_shells.py`；
- 壳读取 `entry.json` 后 iframe 到后端同路径，并把内层 `kpPath` 用 `replaceState` 同步回地址栏；
- 验收：GitHub Pages 子页面 200，刷新后 URL 不变、页面不 404。

详见 `MODULE_SPEC.md` §4.5 / §9.5。

## 6. 窗口/路由树规则

每个界面必须同时维护“路由树”和“窗口树”，二者不能脱节：

### 6.1 路由树

```text
root
└── games                 /games/
    └── courtyard         /games/courtyard/
```

- 子 module 的 `path` 必须位于父 module `path` 之下；
- 禁止孤儿子页面、环、与父级平级的路径；
- `parent` 只能指向 `root` 或已存在的 module；
- 校验器对应 `E_PARENT_PATH_MISMATCH`、`E_PARENT_UNKNOWN`、`E_PARENT_CYCLE`。

### 6.2 页面窗口树

每个页面只有一个窗口根：

```text
main.page
└── section.section
    ├── section-head
    ├── toolbar / grid / list / cards
    └── modal / drawer（必须是页面内的后代节点，默认关闭）
```

- 不允许多个互不归属的 `main.page`；
- 弹层/抽屉必须是当前页面的后代，不得跨页面复用同一 DOM；
- `id` 在同一页面内唯一，禁止把子页面 window 挂到父页面之外；
- 目录 list 页面（工作台、游戏中心）使用同一组：
  `home-tools`、`home-search-wrap`、`home-tags`、`cards`、`card`；
- 列表卡片点击必须通过路由树导航：在根壳内用 `kpNavigate` 消息更新父路由，不能只改 iframe 自身 URL。

### 6.3 目录 list 模板

`ui.template = "directory-list"` 表示该页面是目录列表页：

- 搜索、标签筛选、计数、卡片、子页面入口；
- 游戏中心 `/games/` 是第一个使用该模板的 module；
- 工作台首页与游戏中心共用 `template.css` 的目录 list 组件；
- 页面不出现全局 `<h1>`，标题由根壳 pbar 提供。
