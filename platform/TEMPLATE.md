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

> 目录列表页（工作台 / 游戏中心）允许用
> `<div id="content" class="home-wrap" data-template="directory-list">`
> 作为内容骨架，等价于模板中的 `section.section`；标题/描述仍由根壳 pbar 提供。

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

## 6. 窗口树（半径计算）与路由树

“窗口树”专指 **Popup/Drawer 的静态层级树**，用来计算 `--kp-popup-radius`。
它和“页面内 section 的 DOM 层级”不是一回事；“路由树”是另一条独立的 module/path 树。

### 6.1 半径窗口树

网页端唯一权威：

```js
KP_POPUP_TREE   // key -> { parent, children, button }
KP_POPUP_EL     // key -> CSS selector
KP_DRAWER_KEYS  // 哪些 key 是抽屉
```

树根固定：

```text
window
├── ai-drawer
├── bottle-status-drawer
├── debug
├── settings-popup
│   ├── settings-side-drawer
│   └── settings-help-drawer
├── manage-popup
│   └── manage-side-drawer
├── bug-popup
├── birthday-popup
└── mail-popup
    └── mail-side-drawer
```

半径算法固定为：

```text
m = 8

抽屉：
  父节点也是抽屉 → 0
  否则           → 22 + m = 30

非抽屉 Popup：
  没有 children → 22 + m = 30
  有 children   → m + max(child radius) = 38
```

规则：

- 每个 Popup/Drawer 必须同时登记 `KP_POPUP_TREE` 和 `KP_POPUP_EL`；
- 抽屉必须登记进 `KP_DRAWER_KEYS`；抽屉的 `data-button` 必须能找到绑定按钮；
- `parent` 必须存在，禁止孤儿子节点和环；
- 圆角只能由 `kpPopupRadius()` 计算并写到 `--kp-popup-radius`；
  禁止在 Popup/Drawer 上手写 `border-radius`；
- `window` 之外的所有节点必须能从 `window` 可达；
- 新增/移动窗口后必须重跑 `setupPopupTreeRadius()`；
- 运行时校验函数 `validateKpPopupTree()` 会检查：
  父子存在、元素存在、半径变量与递归结果一致；
- 原生 `KpTemplate.java` 必须维护同一棵树和同一套半径算法。

### 6.2 路由树

```text
root
└── games                 /games/
    └── courtyard         /games/courtyard/
```

- 子 module 的 `path` 必须位于父 module `path` 之下；
- 禁止孤儿子页面、环、与父级平级的路径；
- `parent` 只能指向 `root` 或已存在的 module；
- 校验器对应 `E_PARENT_PATH_MISMATCH`、`E_PARENT_UNKNOWN`、`E_PARENT_CYCLE`。

### 6.3 移动端窗口规则

- 非抽屉 Popup 宽度：`100% - 2m`；
- 嵌套抽屉：`inset:0`、宽高 100%、`border-radius:0`；
- 顶层抽屉：保留 `R30`（按半径树）；
- 抽屉开关、关闭键：44px，关闭键始终最上层；
- 内容 padding：桌面 `2m + 抽屉让位`，移动端固定 `2m`。

### 6.4 目录 list 模板

`ui.template = "directory-list"` 表示该页面是目录列表页：

- 内容根固定为 `<div id="content" class="home-wrap" data-template="directory-list">`；
- 搜索、标签筛选、计数、卡片、子页面入口；
- 游戏中心 `/games/` 是第一个使用该模板的 module；
- 工作台首页与游戏中心共用 `template.css` 的目录 list 组件；
- 页面不出现全局 `<h1>`，标题由根壳 pbar 提供；
- 游戏中心的统计入口属于根壳右下按钮区：可见顺序为 `🐞 / 🤖 / 📊`，统计是第三个按钮；
  点击打开 `game-stats-drawer`（复用标准 `.ai-drawer.kp-drawer` 右侧抽屉模板，R30，桌面 25vw，移动端全宽）；
  打开时给 `body` 加 `game-stats-open`，让 `#host` 宽度让位；关闭时恢复。不是页面内 section，也不是顶部按钮；
  抽屉在半径窗口树中登记为 `window > game-stats-drawer`。

## 7. 模板树（页面模板继承）

页面模板的权威文件：

```text
platform/static/template-tree.json
```

当前树：

```text
#module
└── #game                 → 选择路径为 #module.game
```

- 节点文件里只写短 id：根 `#module`，子节点 `#game`；
- 选中子节点时拼接为类属性式路径：`#module.game`；
- `#module`：所有普通 module 的页面模板，默认值；
- `#module.game`：游戏页面模板，继承 `#module` 全部 properties；
- 子模板继承父模板全部 properties，自己的 properties 覆盖标量、合并对象、拼接去重数组；
- 新增页面模板必须挂到树中，不能孤立存在；
- 服务端从 `project.json` 的 `ui.template` 注入 `window.__KP_TEMPLATE__`（缺省 `#module`）；
- `/static/template-tree.js` 读取 JSON、解析继承并应用：
  - `main.page` 加上解析后的 `pageClasses`；
  - `data-template-resolved` 记录最终模板 id；
  - `window.KP_TEMPLATE_RESOLVED` 暴露合并后的 properties；
- 新增/修改模板后运行：

```bash
python tools/check_templates.py
```

当前属性：

```text
#module
  pageClasses: [page, module-page]
  sectionClasses: [section]
  contentTemplate: sections

#module.game (inherits #module)
  pageClasses: [page, module-page, module-game]
  contentTemplate: directory-list
  contentId: content
  achievements:
    - first_drop / 落子无悔 / 落下第一件构件 / 🧱
    - first_house / 第一座宅院 / 完成第一座宅院 / 🏠
    - grade_a / 甲等宅院 / 营造评分达到 90 分 / 🏅
    - eight_in / 八间俱全 / 八件构件全部收进地界 / 🧩
    - host_hit / 主家满意 / 达成主家要求 / 🤝
```

成就达成状态由游戏页面写入：

```text
localStorage.kp_achievements_<user> = {
  "<game-id>": { "<achievement-id>": "<ISO timestamp>" }
}
```

解锁时游戏页面向根壳发送 `kpAchievement` 消息，根壳显示 Steam 风格右上角提示；
统计抽屉读取同一份 localStorage，未达成的成就使用 `locked` 灰色样式。

游戏中心使用 `ui.template = "#module.game"`；其余 module 未显式声明时使用 `#module`。
