# KittenPuppy4Ever · 后端 Module 规范（MODULE_SPEC.md）

> 版本：v2 · 2026-11-07 · 适用目录：`platform/`
>
> 事实来源（本规范不是凭空写的，每条规则都能在这些文件里找到依据）：
> - `platform/kernel/registry.py` —— manifest 继承链、默认值、类继承校验、扫描/错误处理；
> - `platform/kernel/project.py`、`platform/kernel/bases/coin.py` —— `AbstractProject` / `JsonDocProject` / `CoinProject` 协议；
> - `platform/bases/*.json` —— `abstract <- json-doc <- coin` 的 manifest 继承链与 capability 词表；
> - `platform/TEMPLATE.md` —— 页面模板 v1；
> - `platform/kernel/server.py` —— `/p/<id>/`、`_serve_view`、`canonical_paths`、`/api/p/<id>`；
> - `platform/static/index.html` —— 当前运行的树索引、首页卡片、`navigate()` 的 `?p=id` 回退（`static/check.js` 是未引用残留，不作为依据）；
> - `platform/projects/*/project.json`、`project.py`、`web/index.html` —— 现有 9 个 module 的既成事实。
>
> 配套只读校验器：`platform/tools/check_modules.py`。

---

## 0. 先读这一段：内核行为 ≠ 规范要求

`Registry._load()` 对每个项目单独 `try/except`：**单个项目坏掉不影响整棵树**，坏项目只进 `registry.errors`（`/api/health` 可看到），模块本身从树里消失。因此：

- **registry 不报错，不等于 module 合规**（字段类型错、路径错、声明自相矛盾都可能被“兜住”或静默回退）；
- **registry 报错，也不等于磁盘上格式一定坏**（例如 `project.py` 基类不匹配会在 import 后抛错）。

### 0.1 严重级别（校验器只有两级）

| 级别 | 含义 | 判定原则 |
| --- | --- | --- |
| **ERROR（硬性错误）** | module 无法被内核正确加载，或加载后没有可用入口/规范 URL/数据身份，或破坏类型契约、目录契约、路由契约、类继承契约。必须修。 | 只有“内核兜不住/兜出来是错的/契约被破坏”才记 ERROR。 |
| **WARN（建议项 / 规范偏离）** | 内核有正确可用的默认值（继承或兜底），module 能正常工作；只是显式性、一致性、文档债或功能降级问题。建议修，不阻塞。 | 能被内核正确兜底、或只是协议声明约定，一律 WARN。 |

### 0.2 三类“缺失”要分开看（本规范最重要的结论）

1. **可继承**：`base`、`capabilities`、`acl`、`ui`、`view` 缺失时由 `bases/*.json` 继承链补齐。
   - 缺 `base` → `registry` 用 `json-doc`（`own.get("base") or "json-doc"`），**行为正确**；
   - 缺 `capabilities` → 用 base 继承链上的能力列表，**行为正确**。
   - 结论：**缺 base / 缺 capabilities 是 WARN，不是违规**。
2. **有兜底默认值**：`id`（目录名）、`parent`（`root`）、`title`（id）、`icon`（📄）、`desc`（空串）、`order`（100）、`view`（`{"kind":"auto"}`）缺失时内核有可用默认，**WARN**。
3. **路由/刷新契约**：`path` 对可见 module **必填**。缺失时 registry 给 `""`，只能走首页 `?p=<id>` 回退；没有 GitHub 风格子路径，也没有可刷新的规范 URL。可见 module 缺 `path` 记 **ERROR**；显式 `hidden:true` 的工具模块可按例外记 **WARN**，但必须同时登记。
4. **GitHub Pages 壳**：有 `path` 还必须有 `KittenPuppy4Ever/<path>/index.html` 静态壳；否则 GitHub Pages 刷新 404，记 **ERROR**。

> 简言之：**缺省可继承 / 可兜底 → WARN；字段值/类型/结构/路由契约被破坏 → ERROR。**

---

## 1. 目录结构与发现

```
platform/
├─ bases/                      abstract.json / json-doc.json / coin.json / root.json
├─ kernel/                     registry.py / project.py / server.py / bases/coin.py ...
├─ projects/
│  └─ <dir>/                   module 目录，目录名即 module 身份
│     ├─ project.json          必需：declarative manifest
│     ├─ project.py            可选：Project = 基类子类
│     └─ web/                  可选：view.dir 指向的目录（custom view 必需 index.html）
└─ tools/check_modules.py      本规范的只读校验器
```

- registry 扫描 `projects/` 的**直接子目录**，按目录名排序；只读 `<dir>/project.json`；
- `<dir>/project.json` 不存在 → registry **静默跳过**该目录（模块不出现）→ 校验器记 **ERROR**；
- `projects/` 下的非目录条目被 registry 忽略 → 校验器记 **WARN**；
- module 的 `id` 默认取目录名（`own.setdefault("id", entry.name)`），但规范要求**显式写出且等于目录名**：
  - 数据目录是 `data/<id>/`，页面路由是 `/p/<id>/`，迁移/文档/镜像都按 `id`；
  - `id != 目录名` 时 registry 仍按 `id` 注册，等于同一个模块有两套名字，数据/目录脱节 → **ERROR**；
  - `id` 重复时 `self.projects[id]` 字典静默覆盖 → **ERROR**；
  - `id` 必须是 `[A-Za-z0-9_-]+`（`server.py` 的 `VIEW_RE = ^/p/([a-zA-Z0-9_-]+)` 只认这些字符），且不能是 `root` → **ERROR**。

---

## 2. manifest 继承链（registry 实际行为）

### 2.1 算法（与 `Registry._load` / `_base_manifest` 一致）

```text
own = json.load(projects/<dir>/project.json)
own.setdefault("id", <dir>)
base_key = own.get("base") or "json-doc"           # ← 缺 base 的默认值
spec = _base_manifest(base_key)                     # ← bases/<base_key>.json 递归向上合并
spec = deep_merge(spec, own)                        # ← 项目自身覆盖继承值
spec["dir"] = <项目绝对目录>
spec.setdefault("view", {"kind": "auto"})
base_cls = BASES.get(base_key, JsonDocProject)      # ← 未注册 base 静默回退
若存在 project.py：import 后取 `Project`，要求 issubclass(Project, base_cls)
否则直接用 base_cls 实例化（零代码标签页）
```

`_base_manifest(key)`：

```text
读 bases/<key>.json；任何异常 → {"base": "abstract"}（缺文件静默降级！）
parent = spec.get("base")
若 parent 存在且 != key：spec = deep_merge(_base_manifest(parent), spec)
spec["base"] = key
```

`deep_merge` 语义：字典递归合并；**标量/列表由子层整体覆盖**（不是并集）。
所以 `capabilities` 一旦在项目 manifest 里写出，就是**覆盖**继承列表（可以写子集），而不是追加。

### 2.2 继承链现状

```text
abstract.json   base=abstract            capabilities=[state, action, audit]
json-doc.json   base=abstract            capabilities=[state, action, audit, crud]   （覆盖父列表）
coin.json       base=json-doc            capabilities=[state, action, audit, crud, coins]（覆盖父列表）
bases/root.json 不是项目基类：只有根节点 id/title/icon/desc，不参与项目继承
```

`kernel/registry.py` 的 `BASES` 注册：`abstract -> AbstractProject`、`json-doc -> JsonDocProject`、`coin -> CoinProject`。
**新增 base 必须同时**：建 `bases/<name>.json`、在 `registry.py` 的 `BASES` 注册、在本规范 §10 登记 capability。

### 2.3 base 出错的后果（为什么是 ERROR）

| 情况 | registry 实际行为 | 结果 |
| --- | --- | --- |
| 缺 `base` | 默认 `json-doc` | 行为正确 → **WARN** |
| `base` 非字符串 | 走 `base_key = own.get("base") or "json-doc"` 后可能拿非字符串查文件 → 异常/跳过 | **ERROR** |
| `base` 文件不存在 | `_base_manifest` 捕获异常返回 `{"base":"abstract"}`，再设 `spec["base"]=<key>`；类回退 `JsonDocProject` | manifest 声明一个不存在的 base，继承却只来自 abstract，类却是 JsonDocProject → **ERROR** |
| base 文件存在但未在 `BASES` 注册 | manifest 继承链正常解析，但类回退 `JsonDocProject` | 声明（如 coin 能力）与实际类（JsonDocProject）不一致 → **ERROR** |
| 继承链断/成环 | `_base_manifest` 递归无环检测（环会递归爆栈被项目级 except 捕获） | **ERROR**（校验器的 `bases` 全局检查也会报） |

---

## 3. manifest 字段规范

> 类型列按 JSON 实际类型；「校验级别」对应 `tools/check_modules.py` 的输出级别。
> “缺失”只针对字段整体不存在；字段存在但类型/取值非法一律按“非法”处理。

| 字段 | 类型 / 取值 | 规范要求 | 缺失/非法时 registry 行为 | 校验级别 |
| --- | --- | --- | --- | --- |
| `id` | string | 显式写出；= 目录名；全局唯一；非 `root`；`[A-Za-z0-9_-]+` | 缺失→目录名；不一致仍按新 id 注册；重复静默覆盖 | 缺失 **WARN**；类型/不一致/重复/保留字/非法字符 **ERROR** |
| `parent` | string | `root` 或已知 module id；无自指、无环 | 缺失→`root`；未知 id → 树里挂空、模块不可见 | 缺失 **WARN**；类型/未知/自指/环 **ERROR** |
| `title` | string | 显式写出 | 兜底 `id` | 缺失 **WARN**；类型 **ERROR**；空串 **WARN** |
| `icon` | string | 显式写出 | 兜底 `📄` | 缺失 **WARN**；类型 **ERROR**；空串 **WARN** |
| `desc` | string | 显式写出 | 兜底 `""` | 缺失 **WARN**；类型 **ERROR** |
| `order` | number（有限，非 bool） | 显式写出 | 默认 `100`；树按 `(order, id)` 排序 | 缺失 **WARN**；类型/NaN **ERROR** |
| `hidden` | boolean | 可选 | `bool(...)` | 类型 **ERROR** |
| `tags` | string[] | 可选（首页搜索/标签筛选消费） | `[]` | 类型/元素 **ERROR** |
| `roles` | string[] | 可选；非空时只有这些角色可访问（`server._can_access`） | `[]`（不限制角色） | 类型/元素 **ERROR** |
| `acl` | object `{read?: role[], write?: role[]}` | 可选；缺省继承 base 的 `kitten/puppy` | `{}`；`read/write` 为空数组 = 对所有角色开放（`can_read: True if not allowed`） | 类型/元素 **ERROR**；未知键 **WARN** |
| `base` | string | 必须在 `bases/` 存在且在 `registry.BASES` 注册 | 缺失→`json-doc`；未知→静默回退（见 §2.3） | 缺失 **WARN**（继承）；类型/不存在/未注册/链坏 **ERROR** |
| `capabilities` | string[] | 可选；缺省继承；值建议在 base 词表内 | 缺失→继承链列表；值不校验 | 缺失 **WARN**（继承）；类型/元素 **ERROR**；词表外 **WARN** |
| `view` | object `{kind, dir?, url?}` | 可选；缺省 `auto`；`custom` 必须有 `web/index.html` | `setdefault {"kind":"auto"}`；kind 非法按 auto | 缺失 **WARN**；类型/kind 非法/custom 缺目录或 index/越界 **ERROR** |
| `path` | string，`/` 开头，全局唯一 | 可见 module **必填**；建议以 `/` 结尾；同时必须有对应 Pages 壳 | 缺失→`""`（首页 `?p=id` 回退，无 GitHub 子页面）；重复→前端路由/旧 URL 表互相覆盖 | 可见 module 缺失 **ERROR**；hidden 例外缺失 **WARN**；类型/不以 `/` 开头/重复 **ERROR**；尾斜杠/空白 **WARN**；Pages 壳缺失 **ERROR** |
| `ui` | object（`ui.theme.accent` 等） | 可选；tree 暴露给前端做主题 | `{}` | 类型/`accent` 类型 **ERROR** |
| 未知顶层键 | — | 不允许（可能是拼写错误） | 完全忽略 | **WARN** |
| `dir` | — | 保留键，不要写 | registry 用实际目录覆盖 | **WARN** |

### 3.1 `view` 的三种 kind（server.py `_serve_view`）

| kind | 页面来源 | 要求 |
| --- | --- | --- |
| `custom`（缺省 dir=`web`） | `projects/<id>/<dir>/` 静态托管，`/p/<id>/` 访问；目录/文件不存在 → 404 | 必须有 `<dir>/index.html`；`dir` 不得越出 module 目录（`_serve_static` 会 403） |
| `legacy` | 302 到 `view.url`（缺省 `/legacy/`）+ 子路径 | `url` 建议以 `/` 开头；项目目录本身不需要页面 |
| `auto`（默认） | `_serve_auto_view` 由内核生成通用 CRUD 页面 | 不依赖 `web/`；若存在 `web/index.html` 则不会被渲染（WARN） |

`/p/<id>/` 由 `VIEW_RE` 固定托管，**与 manifest 的 `path` 无关**；`path` 只决定首页卡片跳转用的规范 URL、旧 URL 兼容表 `canonical_paths`，以及前端 `app.routes` 索引。

---

## 4. 硬性错误（ERROR）清单

> 下列问题在 `check_modules.py` 中以 `ERROR` 输出、并使退出码为 1。

### 4.1 加载 / 目录身份
- `E_MANIFEST_MISSING`：`projects/<dir>/project.json` 不存在（registry 静默跳过）；
- `E_MANIFEST_JSON`：JSON 解析失败（registry 跳过该项目）；
- `E_MANIFEST_TYPE`：manifest 顶层不是对象；
- `E_ID_TYPE` / `E_ID_MISMATCH` / `E_ID_RESERVED` / `E_ID_PATTERN` / `E_ID_DUPLICATE`：
  目录名即身份；id 非法会让 `data/<id>`、`/p/<id>/`、目录名三套名字脱节，重复会静默覆盖。

### 4.2 树结构
- `E_PARENT_TYPE` / `E_PARENT_UNKNOWN` / `E_PARENT_SELF` / `E_PARENT_CYCLE`：
  `tree()` 只从 `root` 向下构建；未知 parent 或环上的节点不会出现在 `/api/tree`，模块不可见。

### 4.3 base / capabilities
- `E_BASE_TYPE`、`E_BASE_MISSING`、`E_BASE_UNREGISTERED`、`E_BASE_CHAIN`：见 §2.3；
- `E_CAPS_TYPE`、`E_CAPS_ITEM`：`capabilities` 必须是字符串数组（协议声明结构）；
- 词表外的 capability **不是 ERROR**（内核不校验，见 §6.2/§6.3），记 `W_CAP_UNKNOWN`。

### 4.4 view
- `E_VIEW_TYPE`、`E_VIEW_KIND_TYPE`、`E_VIEW_KIND_INVALID`（非法 kind 会被静默当 auto，与声明不符）；
- `E_VIEW_DIR_TYPE`、`E_VIEW_DIR_ESCAPE`、`E_VIEW_DIR_MISSING`、`E_VIEW_INDEX_MISSING`、`E_VIEW_INDEX_EMPTY`（custom view 404/空白）。

### 4.5 path 与 GitHub 子页面
- `E_PATH_MISSING`：可见 module 未声明 `path`（无 GitHub 风格子路径/刷新 URL）；显式 `hidden:true` 可例外，记 `W_PATH_HIDDEN_EXCEPTION`；
- `E_PATH_TYPE`：非字符串；
- `E_PATH_SLASH`：已声明但不以 `/` 开头（不能作为 URL）；
- `E_PATH_DUPLICATE`：多模块同 path（`app.routes` / `canonical_paths` 后者覆盖前者）；
- `E_PAGES_SHELL_MISSING`：缺少 `KittenPuppy4Ever/<path>/index.html`（GitHub Pages 刷新会 404）；
- `E_PAGES_PATH_UNSAFE` / `E_PAGES_SHELL_READ`：Pages 壳路径越界或读取失败；
- `W_PAGES_SHELL_FRAME` / `W_PAGES_SHELL_BASE` / `W_PAGES_SHELL_PATH` / `W_PAGES_SHELL_HISTORY`：壳存在但刷新/iframe/入口/路径同步标记不完整。
- 生成入口：`python tools/sync_pages_shells.py`；刷新验收见 §9.5。

### 4.6 其它字段类型契约
- `E_FIELD_TYPE`（title/icon/desc 非字符串）、`E_ORDER_TYPE`、`E_HIDDEN_TYPE`、
  `E_TAGS_TYPE|ITEM`、`E_ROLES_TYPE|ITEM`、`E_ACL_TYPE|SIDE`、`E_UI_TYPE|THEME_TYPE|ACCENT_TYPE`。

### 4.7 project.py（可选，若存在）
- `E_PY_SYNTAX`：语法错误（registry import 会失败）；
- `E_PY_NO_PROJECT`：没有顶层 `Project` 类或赋值（registry 抛 `ValueError: project.py 里没有 Project`）；
- `E_PY_NO_BASE` / `E_PY_PROJECT_UNRESOLVED`：Project 没继承或无法静态确认基类；
- `E_PY_BASE_MISMATCH`：Project 不是 manifest base 对应类的子类（registry `issubclass` 拒绝）；
  允许集合：`base=abstract -> {AbstractProject, JsonDocProject, CoinProject}`，
  `base=json-doc -> {JsonDocProject, CoinProject}`，`base=coin -> {CoinProject}`；
- `E_PY_IMPORT_SIDE_EFFECT`：module 顶层（非 class/function 体、非 `__main__` 保护）出现
  `open/os.makedirs/requests/urllib/subprocess/notify` 等调用——registry 会 `exec_module`，
  import 期产生网络/文件副作用属于硬违规。
- 说明：校验器用 AST 静态分析、不导入项目代码；启发式可能漏报（如经变量间接调用），
  但报出的都是明确可疑点。

### 4.8 bases / 全局完整性
- `E_BASES_DIR`、`E_BASE_JSON`、`E_BASE_REGISTERED_NO_FILE`、`E_BASE_CHAIN_UNREGISTERED`、
  `E_BASE_FIELD_TYPE`、`E_BASE_CAPS_TYPE/ITEM`、`E_BASE_ACL_TYPE/SIDE`、`E_BASE_VIEW_TYPE`；
- `E_PROJECTS_DIR`、`E_REGISTRY_MISSING`。

---

## 5. 建议项（WARN）清单

| code | 含义 |
| --- | --- |
| `W_BASE_DEFAULTED` | 缺 `base`；registry 默认 `json-doc` 继承（**非违规**） |
| `W_CAPS_INHERITED` | 缺 `capabilities`；继承 base 链列表（**非违规**） |
| `W_CAP_UNKNOWN` | capability 不在 base 词表；内核不校验，属协议声明偏离 / 文档债 |
| `W_PATH_HIDDEN_EXCEPTION` | `hidden:true` module 未声明 path；允许工具入口，但无 GitHub 子页面/刷新保证 |
| `W_PAGES_ROOT_MISSING` | 未找到 `KittenPuppy4Ever/`；无法验证 GitHub 子页面壳 |
| `W_ID_DEFAULTED` | 缺 `id`；默认目录名（行为正确） |
| `W_PARENT_DEFAULTED` | 缺 `parent`；默认 `root`（行为正确） |
| `W_FIELD_DEFAULTED` / `W_FIELD_EMPTY` | title/icon/desc 缺失或空串，走兜底 |
| `W_ORDER_DEFAULTED` | 缺 `order`；默认 100 |
| `W_VIEW_DEFAULTED` / `W_VIEW_KIND_DEFAULTED` / `W_VIEW_DIR_DEFAULTED` / `W_LEGACY_URL_DEFAULTED` | view 相关缺省，走默认 |
| `W_AUTO_VIEW_UNUSED_WEB` | `view.kind=auto` 但存在 `web/index.html`（不会被渲染） |
| `W_UNKNOWN_FIELD` / `W_RESERVED_DIR` / `W_VIEW_UNKNOWN_KEY` / `W_ACL_UNKNOWN_KEY` | 拼写/冗余/无用键 |
| `W_PATH_TRAILING_SLASH` / `W_PATH_WHITESPACE` | 规范化建议 |
| `W_PY_BASE_ATTR` / `W_PY_BASE_ATTR_MISMATCH` / `W_PY_BASE_LOOSER` / `W_PY_PROJECT_ALIAS` | project.py 与 manifest 的声明一致性问题（registry 不读取 `base` 类属性） |
| `W_TEMPLATE_CSS` / `W_TEMPLATE_PROJECT_ATTR` / `W_TEMPLATE_HEADER` / `W_TEMPLATE_PAGE` / `W_TEMPLATE_SECTION` / `W_TEMPLATE_H1` | 页面模板规范（TEMPLATE.md）的轻量静态检查：template.css、data-project、无 `<header>`、`main.page`、`section.section`、无全局 `<h1>` |
| `W_BASE_UNREGISTERED` | `bases/*.json` 存在但未在 `BASES` 注册（不能作为项目 base） |
| `W_PROJECTS_STRAY_FILE` | `projects/` 下的非目录条目（registry 忽略） |

---

## 6. 关键判定口径（scratchpad / mock / schedule）

> 这一节是本规范对“registry 实际行为”与“规范要求”分歧的正式裁决，也是 `check_modules.py` 当前输出的依据。

### 6.1 scratchpad：已补齐 base / capabilities / path

`projects/scratchpad/project.json` 现已显式声明：

```json
"base": "json-doc",
"capabilities": ["state", "action", "audit", "crud"],
"path": "/scratchpad/"
```

并生成 `KittenPuppy4Ever/scratchpad/index.html` Pages 壳。

历史结论仍保留为参考：`base`/`capabilities` 缺失时 registry 会正确继承，属于 WARN；但 `path` 对可见 module 是硬性路由契约，缺失会失去 GitHub 风格子页面和刷新能力，现在按 `ERROR` 处理。

### 6.2 mock：capabilities 含 `"upstream"`

- `runtime` 事实：`kernel/registry.py`、`kernel/server.py` 都**不校验 capability 值**；`/mock/api/*` 反代由 `config/platform.json` 的 `upstreams`（或默认 `127.0.0.1:8768`）决定，和 `"upstream"` 这个 capability 字符串无关。
- 因此它不影响加载、不影响功能；只是 `capabilities` 作为协议声明与 bases 词表不一致。
- **判定：WARN（`W_CAP_UNKNOWN`），不是 ERROR。**
- 建议修法（二选一）：① 从 manifest 删除 `"upstream"`（推荐，能力无关的部署细节放 `ui`/`tags`/README）；② 若团队决定把它作为正式能力，先写进 `bases/json-doc.json`（或新 base）并在 §10 登记语义。

### 6.3 schedule：capabilities 含 `"remind"`

- 同上：内核不校验 capability 值；提醒是 `kernel/services/reminders.py` 的**全局轮询服务**（`server.py` 启动时 `reminders.start(...)`），不是 project capability。
- **判定：WARN（`W_CAP_UNKNOWN`），不是 ERROR。**
- 建议修法同 mock：删除 `"remind"`，或把它升级为 bases 里定义的正式能力（并在规范里说明“schedule 声明了自己支持提醒”的语义）。

### 6.4 当前判定汇总（2026-11-07 实测）

```
9 modules · PASS 9 · FAIL 0 · 硬性错误 0 · 建议 2
mock       : W_CAP_UNKNOWN(upstream)
schedule   : W_CAP_UNKNOWN(remind)
```

> 可见 module 缺 `path` 已从 WARN 升级为 ERROR；当前 9 个可见 module 都有 `path` 和 Pages 壳，故无 path 错误。

---

## 7. 页面模板要求（TEMPLATE.md 摘要）

所有 `view.kind=custom` 的页面**必须**遵守 `platform/TEMPLATE.md`：

- 骨架：`<link rel="stylesheet" href="/static/template.css">` + `<body data-project="<id>">` +
  `<main class="page"><section class="section">…`；
- 页面**不出现**全局标题/页脚、登录框/身份切换/退出、项目间导航（由根壳统一提供）；
- 颜色/圆角/字号引用模板令牌（`--bg/--card/--line/--ink/--muted/--accent` 等）；
- 组件优先用 `template.css` 的 `.page/.section/.section-head/.toolbar/.grid/.stat/.list/.row/.chip/.btn/.tabs/.empty/.modal/.input/.note`；
- 项目专有组件（课表网格、转录气泡、评分卡等）可保留自己的类，但颜色/圆角/字号必须引用模板令牌；
- 数据接口沿用 `/api/p/<id>/state|action`（旧页面 `/api/state`、`/api/save` 仅兼容层使用）。

校验器对模板只做低风险静态检查（`W_TEMPLATE_*`）；更强的视觉/结构一致性不在只读校验器范围内。

---

## 8. `project.py` 与数据协议

### 8.1 类继承

- `project.py` 可选；**没有 project.py 时**内核直接用 base 类实例化（零代码标签页），这是合法常态；
- 有 project.py 时，顶层必须有 `Project`（类或别名），且必须是 manifest base 对应类或其子类：
  - `base=abstract` → `AbstractProject` 子类；
  - `base=json-doc` → `JsonDocProject` 子类（`CoinProject` 也通过 registry 的 issubclass，但比声明更宽 → WARN）；
  - `base=coin` → `CoinProject` 子类（其他都会被 registry 拒绝 → ERROR）；
- `Project.base = "<base>"` 类属性 registry **不读取**，但建议与 manifest 一致（WARN）；
- project.py 顶层代码会在 registry 加载时被 `exec_module` 执行：**禁止** import 期网络/文件副作用；
  业务初始化放在 `default_state()` / 方法里。

### 8.2 数据与动作（`JsonDocProject` 默认协议）

- 数据：`data/<id>/doc.json`（`engine` 存在时由引擎托管），带 `_rev` 与 `_audit`；
- 动作：`get`（不涨版本）、`set`、`patch`、`append`、`remove`、`reset`；子类可覆盖 `merge`/`on_action`/`default_action` 增加业务动作；
- 写动作：`rev` 乐观并发（旧 rev → 409 conflict）、`acl.write` 鉴权（`can_write`）、审计记录；
- `acl.read/write` 缺省继承 base（`kitten/puppy`）；空数组 = 对所有角色开放；
- 数据目录由 registry 启动时 `os.makedirs(data/<id>)` 创建；校验器**不写**任何数据。

---

## 9. 校验器用法（`tools/check_modules.py`）

### 9.1 运行

```bat
:: 在 platform/ 根目录（推荐）
python tools\check_modules.py
python tools\check_modules.py --json

:: 在任意目录指定 platform 根
python D:\KittenPuppy4Ever\platform\tools\check_modules.py --root D:\KittenPuppy4Ever\platform
```

- Python 3，纯标准库；只读：只解析 JSON / Python AST / 读取 `web/index.html`，**不导入项目代码、不写文件、不启动服务、不访问网络**；
- 默认根目录 = 脚本上一级目录（即 `platform/`）；根目录校验失败退出码 2；
- 退出码：`0` = 全部 PASS（允许 WARN）；`1` = 存在硬性 ERROR；`2` = 参数/根目录错误。

### 9.2 人类可读输出

每个 module 一行 `PASS/FAIL`，缩进列出 `ERROR`/`WARN`；末尾汇总
`modules / PASS / FAIL / 硬性错误 / 建议`。同时检查 bases 继承链与 `projects/` 全局结构。

### 9.3 `--json` 输出结构

```json
{
  "tool": "check_modules.py", "version": 1,
  "platform_root": "D:\\KittenPuppy4Ever\\platform",
  "ok": true,
  "bases": {
    "registered": {"abstract": "AbstractProject", "json-doc": "JsonDocProject", "coin": "CoinProject"},
    "files": ["abstract", "coin", "json-doc", "root"],
    "chains": {"coin": ["coin", "json-doc", "abstract"]},
    "errors": [], "warnings": []
  },
  "global": {"errors": [], "warnings": []},
  "modules": [
    {
      "dir": "projects/schedule", "id": "schedule", "status": "PASS",
      "errors": [], "warnings": [{"code": "W_CAP_UNKNOWN", "message": "…"}],
      "effective": {
        "id": "schedule", "parent": "root", "base": "json-doc",
        "view_kind": "custom", "view_dir": "web", "path": "/dashboard/",
        "capabilities": ["state", "action", "audit", "crud", "remind"]
      }
    }
  ],
  "summary": {
    "modules": 9, "pass": 9, "fail": 0, "errors": 0, "warnings": 5,
    "module_errors": 0, "module_warnings": 5,
    "base_errors": 0, "base_warnings": 0,
    "global_errors": 0, "global_warnings": 0
  }
}
```

- `status` 只由 `errors` 决定：`FAIL` ⇔ 存在硬性错误；WARN 不影响 PASS；
- `effective` 是校验器按 registry 规则推演出的有效值（含继承后的 base/capabilities、默认 view），便于排查；
- 同一套规则下，`ok = (module errors + base errors + global errors) == 0`。

### 9.4 已知限制

- `project.py` 用 AST 静态解析（不 import），`E_PY_IMPORT_SIDE_EFFECT` 是启发式：明确可疑的顶层调用会报，间接调用可能漏报；
- 模板检查覆盖 `template.css`/`data-project`/`<header>`/`main.page`/`section.section`/`<h1>`；不做完整 HTML/CSS 结构或视觉校验；
- Pages 壳检查只验证文件存在与关键标记（iframe/entry.json/路径还原/replaceState），不替代浏览器 E2E；
- 校验器与 `kernel/registry.py` 的 `BASES` 通过 AST 同步；若 registry 结构大改（如 `BASES` 不再是字面量 Dict），会退回内置映射并输出 `W_REGISTRY_BASES_FALLBACK`。

### 9.5 GitHub 子页面刷新验收

新 module 必须完成：

```bash
# 1) 生成/更新所有 module 的 Pages 壳
python tools/sync_pages_shells.py
# 2) 静态门禁：0 ERROR，且存在 E_PAGES_SHELL_*
python tools/check_modules.py
# 3) 部署后浏览器 E2E（本机可用 Playwright）
#    打开 https://stjwls.github.io/kitten/KittenPuppy4Ever/<path>/
#    刷新，断言 URL 不变、不是 404、iframe 仍在
```

验收标准：

- GitHub Pages 路径返回 200；
- 刷新后 `location.pathname` 不变；
- 页面不是 GitHub 404；
- iframe 加载的是同一 module；
- 后端 `/p/<id>/` 与 `/<path>/` 均 200。

`tools/sync_pages_shells.py` 从 manifest 的 `path` 生成壳；壳运行时读取 `entry.json`，因此隧道地址变化不需要重建壳。

---

## 10. 附录 A：bases 与 capability 词表

| base | Python 基类 | 继承链 | capability 并集（继承后可用） |
| --- | --- | --- | --- |
| `abstract` | `AbstractProject` | abstract | `state, action, audit` |
| `json-doc` | `JsonDocProject` | json-doc <- abstract | `state, action, audit, crud` |
| `coin` | `CoinProject` | coin <- json-doc <- abstract | `state, action, audit, crud, coins` |
| `root` | —（根节点元信息，不是项目 base） | — | — |

- 新增 capability：先加到合适的 `bases/*.json` 的 `capabilities` 数组，再在本表登记；
- 项目 manifest 的 `capabilities` 写出即**覆盖**继承列表，可写子集；缺省则继承；
- 当前内核不按 capability 鉴权/分派动作（仅随 manifest/tree 暴露给前端与调试），但这不改变它是协议声明的事实。

---

## 11. 附录 B：新增 module 检查清单

1. 建目录 `projects/<id>/`（`id` 与目录名一致，`[A-Za-z0-9_-]+`）；
2. 写 `project.json`：`id/parent/order/title/icon/desc/view/path` 显式写出；
   `base` 与 `capabilities` 建议显式写出（缺省可继承 `json-doc`）；
3. 需要业务规则 → `project.py`：`class Project(<正确基类>)`，`base` 属性与 manifest 一致；
   不在 import 期做 I/O；覆盖 `merge`/`on_action` 时保持 `rev` 与 ACL 语义；
4. 需要自定义页面 → `view.kind=custom`、`view.dir=web`、`web/index.html`（按 TEMPLATE.md）；
5. `path` 选一个未被占用的 URL，以 `/` 开头、以 `/` 结尾；
6. 生成 Pages 壳：`python tools/sync_pages_shells.py`；确认 `KittenPuppy4Ever/<path>/index.html` 已存在；
7. 跑 `python tools/check_modules.py`，ERROR 必须为 0（含 `E_PATH_MISSING`、`E_PAGES_SHELL_MISSING`），WARN 逐条确认；
8. 部署后按 §9.5 做 GitHub 子页面刷新 E2E；
9. 若新增 base 或 capability：先改 `bases/*.json`、`kernel/registry.py` 的 `BASES`，再更新本规范 §10。

---

## 12. 变更记录

- **v2 · 2026-11-07**：将可见 module 的 `path` 升级为硬性要求（`E_PATH_MISSING`）；
  新增 GitHub Pages 壳检查（`E_PAGES_SHELL_MISSING`）与生成器 `tools/sync_pages_shells.py`；
  新增 §9.5 刷新 E2E 验收；scratchpad 已补 base/capabilities/path 并生成壳。
- **v1 · 2026-11-07**：首版。基于 registry/bases/TEMPLATE.md/现有 9 个 module 提炼；
  明确 ERROR/WARN 分级、缺省继承与兜底行为、`path`/`capabilities` 的定性依据；
  配套只读校验器 `tools/check_modules.py`。
