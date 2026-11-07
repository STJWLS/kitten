# KittenPuppy4Ever · Module 文件格式独立审计报告

- 审计对象：`platform/projects/` 下 9 个 module（ai、bottle、courtyard、map、mock、schedule、schedule-debug、scratchpad、wishpool）
- 工作目录：`D:/KittenPuppy4Ever`
- 审计方式：**只读**源码审计（未修改任何 module / 平台代码，未启动服务，未提交 Git）
- 审计依据：`platform/TEMPLATE.md`、`platform/bases/*.json`、`platform/kernel/registry.py`、`platform/kernel/project.py`、`platform/kernel/auth.py`、`platform/kernel/server.py`、`platform/static/index.html`、各 `project.json` / `project.py` / `web/index.html`，并用 `platform/README.md`、`platform/DESIGN.md` 作为设计意图旁证
- 报告文件：本文件（`platform/reports/module-format-audit.md`，唯一写入）

> 结论先行：**PASS 7 / FAIL 0 / WARN 2**（WARN：bottle、scratchpad）。
> **未发现任何“会让 registry 加载失败或接口不可用”的硬性格式错误。**
> 最需要关注的是规范本身缺位（capabilities 无词汇表、acl 实际未生效、path 是否必填未定义），而不是现有文件写错。

---

## 1. 审计方法与判定标准

### 1.1 判定基线（权威优先级）

1. **可执行代码的真实行为**优先：`kernel/registry.py`（合并/默认值/校验）、`kernel/project.py`（基类）、`kernel/server.py`（视图与路径解析）、`static/index.html`（前端路由/隐藏/hidden 语义）。
2. **`bases/*.json`**：manifest 继承链的默认值来源。
3. **`TEMPLATE.md`**：页面骨架/组件规范（只约束 `web/index.html`，不约束 manifest 字段）。
4. **`README.md` / `DESIGN.md`**：设计意图与历史决定旁证；与代码冲突时以代码为准，冲突本身记入“规范歧义”。

### 1.2 判定定义

| 判定 | 含义 |
| --- | --- |
| **FAIL** | 会导致 registry 加载失败、接口 404/500、project.py 类校验失败、结构不可用，或明确违反文档中“必须”的硬规则 |
| **WARN** | 代码路径可正常运行，但与规范/仓库惯例不一致，或存在功能退化、误导性声明、需要规范补位确认 |
| **PASS** | 未发现上述问题 |

**重要原则**：字段“没写”≠违规。必须结合 registry 的默认值与继承结果判断（见 §4.1 的 scratchpad 专项）。

### 1.3 执行步骤

1. 全量列出 `platform/projects/` 目录与文件，确认 9 个 module 目录、无“有目录无 `project.json`”的模块。
2. 读取 `TEMPLATE.md`、`bases/{abstract,json-doc,coin,root}.json`、`registry.py`、`project.py`、`auth.py`、`server.py` 相关段落、`static/index.html` 路由段。
3. 用只读 Python 脚本（不 import kernel，避免 `registry._load` 的 `os.makedirs(data/<id>)` 副作用）**复刻** `deep_merge` / `_base_manifest` 逻辑，计算每个 module 的“有效 manifest”（继承后的真实结果），并做字段/类型/路径/重复项检查。
4. 用 `ast` 静态解析 3 个 `project.py`，核对 `Project` 类名、基类名与 manifest `base` 的一致性（不执行其模块代码）。
5. 逐页核对 `web/index.html`：文件存在性、`/static/template.css`、`body[data-project]`、`main.page`/`section.section` 骨架、页面内自带头部/登录/跨模块导航、本地资源引用可解析。
6. 交叉核对 `DESIGN.md` 中关于 map 子节点、schedule-debug roles/path、bottle 存档页、scratchpad `/p/` 形态的既有决定。
7. 在审计主体完成后，并行任务产出了 `platform/tools/check_modules.py`，已运行并做交叉验证（结果与分歧见 §7）。

---

## 2. 源码行为基线（判定依据的事实）

### 2.1 manifest 继承链

`registry.py:53-64` 的 `_base_manifest` 会递归向上合并，`spec["base"]` 最终被改写为实际基类名：

- `abstract.json`：`base: abstract`（自指），提供 `protocol: kp/1`、`capabilities: [state, action, audit]`、`acl`、`ui.theme`、`view: auto`（`bases/abstract.json:2-20`）
- `json-doc.json`：`base: abstract`，覆盖 `capabilities: [state, action, audit, crud]`、`view: auto`（`bases/json-doc.json:2-5`）
- `coin.json`：`base: json-doc`，覆盖 `capabilities: [state, action, audit, crud, coins]`（`bases/coin.json:2-4`）
- **`root.json` 不是项目基类**：它只有 `id/title/icon/desc`（`bases/root.json:1-6`），是树根节点元数据，未参与 manifest 继承（`registry.py:154-165` 单独读取）。

### 2.2 registry 的默认值与宽容度（决定“字段缺失”如何判定）

| 行为 | 源码位置 | 结果 |
| --- | --- | --- |
| `id` 缺省 | `registry.py:88` `own.setdefault("id", entry.name)` | 默认等于目录名 |
| `base` 缺省 | `registry.py:89` `own.get("base") or "json-doc"` | 默认 **json-doc** |
| manifest 合并 | `registry.py:90-91` + `deep_merge` `registry.py:32-40` | 继承链默认值 + 项目自身覆盖；**列表型字段（capabilities）被子层整体覆盖，不是追加** |
| `view` 缺省 | `registry.py:93` `spec.setdefault("view", {"kind": "auto"})` | 默认 auto |
| `project.py` 可选 | `registry.py:97-107` | 存在则必须 `Project` 且 `issubclass(candidate, base_cls)` |
| 类解析依据 | `registry.py:95` `BASES.get(base_key, JsonDocProject)` | `abstract→AbstractProject`、`json-doc→JsonDocProject`、`coin→CoinProject` |
| `parent` 缺省 | `registry.py:126` `spec.get("parent") or "root"` | 默认挂到 root |
| `order` 缺省 | `registry.py:129`、`138` | 默认 100；同 order 用 `id` 排序 |
| `path` 缺省 | `registry.py:139` `spec.get("path") or ""` | **默认空字符串，不报错** |
| `hidden` | `registry.py:140` `bool(...)` | 仅作为标记下发 |
| `capabilities` | `registry.py:141` | 直接下发合并结果；**代码中没有任何白名单校验** |
| `roles` | `registry.py:145` | 下发；访问控制由 `server.py` 使用 |
| `view.kind/url` | `registry.py:147-150` | 只透出 kind/url |

### 2.3 server / 前端的真实消费方式

- `/p/<id>/` 视图：`server.py:4925-4942`。`view.kind == "custom"` 时以 `spec["dir"]/view.dir`（默认 `web`）为静态根目录；因此 **custom 必须有 `web/index.html`**，否则该 URL 404。
- `/api/p/<id>` 与 `/api/p/<id>/state`：`server.py:3730-3748`，会做 `_can_access` 校验，并只回传 `id/title/icon/base/desc/capabilities/acl/view/ui`。
- `/api/p/<id>/action`：`server.py:4646-4676`，要求 `_can_access` + `_can_maintain`，然后 `dispatch(..., write_allowed=True)`。注意 `project.py:138`：`write_allowed=True` 会**绕过** `acl.write` 判断。
- `roles`：`server.py:3231-3238`，`_can_access` 中 `roles` 非空且当前用户 `role_of(user)` 不在其中即拒绝；**roles 是硬访问控制，不只是展示字段**。
- `path`：`server.py:5189-5194` 把非空 path 注册为 `canonical_paths`（旧式 URL `/dashboard/` 等）；前端 `static/index.html:1798-1803` 把非空 path 注册进路由表，`:1907-1909` 用 `/p/<id>/` 作为 iframe 源。
- `hidden`：仅前端过滤——首页只渲染 `!hidden` 的 root 子节点（`static/index.html:1820`），子页面链接同样过滤（`:1813-1815`）。
- **数据视图**：只有 `scratchpad`、`bottle` 的页面直接走 `/api/p/<id>/state|action`；其余 module 走旧兼容协议或各自专用 API（见 §3 明细），这解释了为何 capabilities 与实际使用常常不一致。

### 2.4 只读复刻得到的“有效 manifest”

（等于运行时 `Registry._load` 内 `spec` 的结果；`base` 已解析为实际基类名）

| module | 有效 base | 有效 capabilities | parent | path | view.kind |
| --- | --- | --- | --- | --- | --- |
| ai | json-doc | state | root | `/ai/` | custom |
| bottle | json-doc | state, action, audit | root | `/bottle/` | custom |
| courtyard | json-doc | state, action, audit | root | `/courtyard/` | custom |
| map | json-doc | state, action, audit, crud | **schedule** | `/dashboard/map/` | custom |
| mock | json-doc | state, action, audit, **upstream** | root | `/mock/` | custom |
| schedule | json-doc | state, action, audit, crud, **remind** | root | `/dashboard/` | custom |
| schedule-debug | json-doc | state | root | `/schedule-debug/` | custom |
| scratchpad | **json-doc（继承默认）** | **state, action, audit, crud（继承）** | root | **`""`（未提供）** | custom |
| wishpool | **coin** | state, action, audit, crud, coins | root | `/wishpool/` | custom |

---

## 3. 逐 module 判定

### 3.1 总表

| # | module | manifest | project.py | web/index.html | 总判定 | WARN 摘要 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | ai | 合法 | 无（用 JsonDocProject） | 存在（1498 行） | **PASS** | capabilities 收窄为 state 且页面不使用项目协议；`ai/check.js` 为未引用残留 |
| 2 | bottle | 合法 | `Project(JsonDocProject)`，base 匹配 | 存在（688 行） | **WARN** | 页面骨架违反 TEMPLATE.md（无 `main.page`、自带 `h1`、`.head` 代替 `.section-head`） |
| 3 | courtyard | 合法 | 无 | 存在（1221 行） | **PASS** | capabilities 与实际（纯前端）不符；acl 与 abstract 完全重复 |
| 4 | map | 合法 | 无 | 存在（530 行） | **PASS** | capabilities 声明 crud 但页面只读；作为 schedule 子节点不出现在首页根卡片 |
| 5 | mock | 合法 | 无 | 存在（1358 行） | **PASS** | capability `upstream` 不在任何 base 词汇表内（未定义） |
| 6 | schedule | 合法 | `Project(JsonDocProject)`，base 匹配 | 存在（1277 行） | **PASS** | capability `remind` 未定义；页面走 `/api/schedule/*` 而非项目状态 |
| 7 | schedule-debug | 合法 | 无 | 存在（166 行） | **PASS** | capabilities 收窄为 state，但页面走 `/api/schedule/admin/*`；页面 HTML 本身未做角色门禁 |
| 8 | scratchpad | 合法（base/capabilities 由默认继承补齐） | 无 | 存在（110 行） | **WARN** | 缺 `path`：无 canonical URL，前端走“隐藏项目 `?p=`”回退路径（功能不坏） |
| 9 | wishpool | 合法 | `Project(CoinProject)`，base 匹配 | 存在（1206 行） | **PASS** | 页面仍用旧协议 `/api/state`；其余见 §4.5 |

汇总：**PASS 7、FAIL 0、WARN 2**。

### 3.2 明细与证据

#### 1) ai — PASS（WARN×3）

- `projects/ai/project.json`：`id:"ai"`(:2)=目录名；`parent:"root"`(:3) 合法；`order:25`(:4)；`title/icon/desc`(:5-7)；`base:"json-doc"`(:8) 在 `bases/` 中存在；`capabilities:["state"]`(:9-11)；`view:{kind:"custom",dir:"web"}`(:17-20)；`path:"/ai/"`(:21) 以 `/` 开头结尾、全局唯一；`tags`(:12-16) 为字符串数组。
- `project.py` 不存在 → `registry.py:97` 直接以 `JsonDocProject` 实例化（`registry.py:95`），合法。
- `view: custom` → `web/index.html` 存在（1498 行），`server.py:4934-4936` 可命中；页面 `template.css` 在第 7 行、`body data-project="ai"` 第 248 行、`main.page` 第 249 行。
- WARN：
  - `capabilities:["state"]` 覆盖掉了 base 提供的 `action/audit/crud`（`registry.py:91` 列表整体覆盖），但页面实际调用 `/api/ai/*`、`/api/llm/*`、`/api/files/*`，**完全不使用 `/api/p/ai/...`**（全页无该前缀），声明与实现不一致。
  - `projects/ai/check.js`（1110 行）在仓库内**未被任何文件引用**（全仓 grep 无命中），属遗留文件。
  - 无 `ui.theme.accent`，首页卡片回退默认色（`static/index.html:1863`），非错误。

#### 2) bottle — WARN（模块格式 PASS；页面骨架 WARN×1）

- `projects/bottle/project.json`：`id:"bottle"`(:2)=目录名；`parent:"root"`(:3)；`order:26`(:4)；`base:"json-doc"`(:8)；`capabilities:[state,action,audit]`(:9-13)；`view:{kind:"custom",dir:"web"}`(:14-17) 且 `web/index.html` 存在（688 行）；`path:"/bottle/"`(:18)；`ui.theme.accent:"#6f8fc4"`(:19-23) 合法 6 位 hex；`tags`(:24-28) 合法。
- `projects/bottle/project.py:31-32`：`class Project(JsonDocProject)` + `base="json-doc"`；`registry.py:95` 的 `base_cls=JsonDocProject`，`registry.py:103` 的 `issubclass` 校验通过。
- WARN（页面模板）：`bottle/web/index.html` 加载了 `template.css`(:7) 与 `body[data-project="bottle"]`(:103)，但：
  - **没有 `main.page`/`section.section` 骨架**（全文无 `<main`，只有 `div.wrap` :104、`section.archive-panel` :111）；
  - **自带页面级标题** `<h1>🍾 时光漂流瓶</h1>`(:106) 与 `.head`(:105)，违反 `TEMPLATE.md:26`“页面不出现全局标题”；根壳 `.pbar` 已统一显示模块标题，实际会重复；
  - 使用自定义 `.head/.foot` 代替 `.section-head`（`TEMPLATE.md:15-16`、`TEMPLATE.md:64-71`）。
  - 这是“页面模板”维度的问题，不影响 manifest/视图解析，故总判定 WARN 而非 FAIL；bottle 是 2D 画布型全屏页，是否豁免应在规范中明确。

#### 3) courtyard — PASS（WARN×2）

- `projects/courtyard/project.json`：`id:"courtyard"`(:2)=目录名；`parent:"root"`(:3)；`order:25`(:4)；`base:"json-doc"`(:8)；`capabilities:[state,action,audit]`(:9-13)；`acl.read/write=[kitten,puppy]`(:14-23) 类型合法；`view custom dir web`(:24-27) 且 `web/index.html` 存在（1221 行）；`path:"/courtyard/"`(:28)；`ui.theme.accent:"#9e2a22"`(:29-33) 合法；`tags`(:34-38)。
- 无 `project.py`，`JsonDocProject` 实例化合法。
- WARN：`DESIGN.md:317` 明确 courtyard 为“纯前端实现，不需要新增后端接口”，但 manifest 声明 `state/action/audit`（且丢掉 base 的 crud）；声明与实现不符。`acl` 与继承自 abstract 的完全重复（`bases/abstract.json:5-8`），属冗余（非错误）。
- 页面骨架合规：`template.css`:7、`data-project="courtyard"`:61、`main.page`:62、`section.section`:64/90。

#### 4) map — PASS（WARN×2，重点项见 §4.3）

- `projects/map/project.json`：`id:"map"`(:2)=目录名；`parent:"schedule"`(:3) 存在且被 `DESIGN.md:16`“map 地点地图（schedule 子节点）”明确支持；`order:5`(:4) 是“在 schedule 子级内”的排序；`base:"json-doc"`(:8)；`capabilities:[state,action,audit,crud]`(:9-14)；`view custom dir web`(:15-18) 且 `web/index.html` 存在（530 行）；`path:"/dashboard/map/"`(:24) 合法且唯一；`ui.theme.accent:"#2f6fb5"`(:19-23) 合法；`tags`(:25-28)。
- 无 `project.py`，`JsonDocProject` 合法。
- WARN：
  - 因 `parent:schedule`，map 不是 `tree.root.children`，首页只把它渲染成 schedule 卡片下的子页面 chip（`static/index.html:1867-1877`、`:1813-1815`），**不会单独出卡片**——符合 DESIGN，但属产品语义，需在规范中说明“子页面不进首页”。
  - `capabilities` 声明 `crud`，但页面只 `fetch("schedule.json")` 静态数据（`DESIGN.md:16`“只读 schedule.json”），声明与实现不一致。
- 页面骨架合规：`template.css`:9、`data-project="map"`:183、`main.page`:184、`section.section`:185/206。

#### 5) mock — PASS（WARN×1）

- `projects/mock/project.json`：`id:"mock"`(:2)=目录名；`parent:"root"`(:3)；`order:15`(:4)；`base:"json-doc"`(:8)；`capabilities:[state,action,audit,upstream]`(:9-14)；`view custom dir web`(:15-18) 且 `web/index.html` 存在（1358 行）；`path:"/mock/"`(:24)；`ui.theme.accent:"#4f8f5f"`(:19-23)；`tags`(:25-29)。
- 无 `project.py`，`JsonDocProject` 合法；页面走进程内 `/mock/api/*`（`server.py:4954` 起）。
- WARN：`upstream`（`project.json:13`）**在任何 base 的 capabilities 中都不存在**（abstract/json-doc/coin 均无），且代码里没有 `capabilities` 消费/校验逻辑；“upstream”只与错误码字符串 `server.py:2743` 同名，属巧合。若后续规范要求“capabilities ⊆ 继承集合”，mock 将被判不合规；当前规范未定义，故只记 WARN/歧义。
- 页面骨架合规：`template.css`:7、`data-project="mock"`:68、`main.page`:69、`section.section`:72。

#### 6) schedule — PASS（WARN×2）

- `projects/schedule/project.json`：`id:"schedule"`(:2)=目录名；`parent:"root"`(:3)；`order:10`(:4)；`base:"json-doc"`(:8)；`capabilities:[state,action,audit,crud,remind]`(:9-15)；`acl`(:16-25) 类型合法（与 abstract 相同）；`view custom dir web`(:26-29) 且 `web/index.html` 存在（1277 行）；`path:"/dashboard/"`(:35)；`ui.theme.accent:"#2f6fb5"`(:30-34)；`tags`(:36-40)。
- `projects/schedule/project.py:13-14`：`class Project(JsonDocProject)` + `base="json-doc"`，与 registry 期望一致（`registry.py:95/103`）。
- WARN：
  - `remind`（`project.json:14`）不在任何 base 词汇表内；提醒能力实际由内核常驻服务提供（`kernel/services/reminders.py:204-209`、`118-141`），与模块能力的关联未定义。
  - 页面走 `/api/schedule/*`、`/api/mailstatus`（`projects/schedule/web/index.html`），不使用 `/api/p/schedule`；`state/action/audit` 声明主要是给旧协议兼容层（`kernel/compat.py`）和提醒服务（`reminders.py:123-124`）用。
- 页面骨架合规：`template.css`:7、`data-project="schedule"`:15、`main.page`:16、`section.section`:19/52/74/88。

#### 7) schedule-debug — PASS（WARN×1，重点项见 §4.2）

- `projects/schedule-debug/project.json`：`id:"schedule-debug"`(:2)=目录名；`parent:"root"`(:3)；`order:30`(:4)；`base:"json-doc"`(:8)；`roles:["superadmin"]`(:9-11)；`capabilities:["state"]`(:12-14)；`view custom dir web`(:20-23) 且 `web/index.html` 存在（166 行）；`path:"/schedule-debug/"`(:24)；`hidden:true`(:25)；`tags`(:15-19)。
- `roles` 值合法：`auth.py:32` `ROLE_SUPER = "superadmin"`；`users.json` 中 puppy 的 role 为 superadmin。硬控制生效于 `server.py:3231-3238`（树/接口过滤）与 `server.py:3462-3465`、`4228-4231`、`4255-4258`（`/api/schedule/admin/*` 仅 super）。
- `hidden:true` 被前端正确消费：首页/子链接过滤（`static/index.html:1820`、`:1813-1815`）；入口在调试抽屉 `/p/schedule-debug/?drawer=1`（`static/index.html:2725`）与直接 URL，符合 `DESIGN.md:755-756`。
- WARN：`capabilities:["state"]` 与页面实际使用的 `/api/schedule/admin/*` 不一致；且 `server.py:4925-4936` 明确“页面本身不挡”（注释 `server.py:4930-4931`），非 super 用户仍可加载该 HTML（数据接口会 403）。这是既有设计取舍，不是格式错误，但建议规范写明“页面 HTML 不做门禁，数据接口做门禁”。
- 页面骨架合规：`template.css`:7、`data-project="schedule-debug"`:36、`main.page`:37、`section.section`:38。

#### 8) scratchpad — WARN（模块可运行；缺 path；详见 §4.1）

- `projects/scratchpad/project.json` 只有：`id`(:2)、`parent:"root"`(:3)、`order:40`(:4)、`title/icon/desc`(:5-7)、`view:{kind:"custom",dir:"web"}`(:8-11)、`tags`(:12-16)；**没有 `base`、`capabilities`、`path`**。
- 但按 §2.2：`base` 默认 `json-doc`（`registry.py:89`），`capabilities` 继承 `[state,action,audit,crud]`（`bases/json-doc.json:4` + `registry.py:90-91`），`view` 为显式 custom（覆盖默认 auto），且 `web/index.html` 存在（110 行）。运行时等价于其他 `base=json-doc` 的 module。
- 功能证据：`web/index.html:35` 使用 `const API = "/api/p/scratchpad"`，`:68` 读 `/state`，`:75-79` POST `/action`，`:90` 用 `append`、`:63` 用 `remove`——全部来自继承的 `JsonDocProject.ACTIONS`（`project.py:239-294`）。即“缺字段”没有造成能力缺失。
- WARN 仅来自 `path`：有效 path 为 `""`（`registry.py:139`）→ 不注册 canonical URL（`server.py:5189-5194`），前端也不建路由（`static/index.html:1801`）；点击卡片走 `navigate()` 的“隐藏项目”分支（`static/index.html:2055-2061`），URL 变成 `/home?p=scratchpad`。功能不坏，但普通的非隐藏模块走了调试回退路径，且无 `/scratchpad/` 这类稳定 URL。
- 页面骨架合规：`template.css`:7、`data-project="scratchpad"`:9、`main.page`:10、`section.section`:12/27。

#### 9) wishpool — PASS（WARN×1，重点项见 §4.5）

- `projects/wishpool/project.json`：`id:"wishpool"`(:2)=目录名；`parent:"root"`(:3)；`order:20`(:4)；`base:"coin"`(:8) 存在；`capabilities:[state,action,audit,crud,coins]`(:9-15)，其中 `coins` 来自 `bases/coin.json:4`；`acl`(:16-25) 类型合法；`view custom dir web`(:26-29) 且 `web/index.html` 存在（1206 行）；`path:"/wishpool/"`(:35)；`ui.theme.accent:"#c96a8f"`(:30-34)；`tags`(:36-40)。
- `projects/wishpool/project.py:16-17`：`class Project(CoinProject)` + `base="coin"`；`kernel/bases/coin.py:13` 的 `CoinProject` 是 `JsonDocProject` 子类；registry `base_cls=CoinProject`（`registry.py:25-29`、`:95`），`issubclass` 通过（`registry.py:103`）。
- WARN：页面仍用旧协议 `/api/state` + `/api/save`（`projects/wishpool/web/index.html`），而非 `/api/p/wishpool`；这与 DESIGN 的旧协议兼容层设计一致，但意味着 `capabilities`（协议能力）与页面实际调用面不同。
- 页面骨架合规：`template.css`:8、`data-project="wishpool"`:11、`main.page`:12、`section.section`:15/32/43/66。

---

## 4. 重点核对项（专项结论）

### 4.1 scratchpad 缺 `base` / `capabilities` / `path` 是否违规（核心）

**结论：`base`、`capabilities` 缺失不违规；`path` 缺失不导致不可用，但属于与惯例/规范不一致的 WARN。**

1. **base 缺失**：`registry.py:89` 的 `own.get("base") or "json-doc"` 明确把缺省值定为 `json-doc`；随后 `registry.py:90-91` 用 `deep_merge(_base_manifest("json-doc"), own)` 合并，得到完整继承链 `abstract ← json-doc`。`registry.py:95` 选择 `JsonDocProject`，`registry.py:97-107` 因无 `project.py` 直接使用基类实例化。**运行时与显式写 `"base":"json-doc"` 完全等价**。
2. **capabilities 缺失**：`json-doc` 的 capabilities 是 `[state, action, audit, crud]`（`bases/json-doc.json:4`），合并后 tree/`/api/p` 都会下发这 4 项（`registry.py:141`、`server.py:3745-3746`）。页面正是用 `state` + `append/remove`（`web/index.html:35/68/75/90/63`），能力实际可用。**若只按“字段没写”判 FAIL，会误伤一个完全正常的模块。**
3. **path 缺失**：这是唯一有真实影响的缺项。`registry.py:139` 把 path 兜底为 `""`，不抛错；后果是 `server.py:5189-5194` 不登记 canonical path、前端不建路由（`static/index.html:1801`），点击时走 `static/index.html:2055-2061` 的“隐藏项目（调试用）：用 ?p=id 打开”分支。**功能可达、无报错**，但（a）没有稳定 URL，刷新依赖 `?p=`；（b）一个可见的正常模块被当成调试项目处理；（c）`DESIGN.md:19` 只记录了 `/p/scratchpad/` 这一形态，未说明为何不给 path。故判 **WARN，建议补 `"path": "/scratchpad/"`**。
4. 另注：`registry.py:88` 连 `id` 缺失都会用目录名补齐，说明内核设计哲学就是“最小 manifest 也能跑”（`project.py:11-18` 注释“零代码创建标签页”）。用“必填字段缺失”来判错，与内核行为相悖。

### 4.2 schedule-debug 的 `roles` / `hidden` / `path`

- `roles:["superadmin"]`：值合法（`auth.py:32`），且**不是装饰字段**——`server.py:3231-3238` 在 `_can_access` 中按 `auth.role_of(user)` 过滤，`puppy` 角色为 superadmin 故可见，`kitten`（admin）不可见；后端 `/api/schedule/admin/*` 也二次校验 `is_super`（`server.py:3462-3465/4228-4231/4255-4258`）。**PASS**。
- `hidden:true`：`registry.py:140` 原样下发，前端首页过滤（`static/index.html:1820`）、子链接过滤（`:1813-1815`），入口保留在调试抽屉（`:2725`）。与 `DESIGN.md:755-756` 一致。**PASS**。
- `path:"/schedule-debug/"`：格式合法（`/` 开头、`/` 结尾），全局唯一，`server.py:5189-5194` 可登记，与 DESIGN 记录一致。**PASS**。
- 唯一提醒：`server.py:4925-4936` 对 `/p/<id>/` 页面不做访问校验（注释 `:4930-4931` 明说“页面本身不挡”），所以非 super 用户直接访问 `/p/schedule-debug/` 能拿到 HTML 但接口 403；这不是格式问题，建议在规范中明示该安全模型。

### 4.3 map 的 `parent` / `path`

- `parent:"schedule"`：`schedule` 存在于 `projects/schedule/`，`registry.tree()`（`registry.py:123-127`）会把 map 挂到 schedule 的 children 下；`DESIGN.md:16` 明确写“map 地点地图（schedule 子节点）”。**PASS**。
- `path:"/dashboard/map/"`：与父级 `/dashboard/` 前缀一致，格式合法且与其它 8 个 module 无冲突；`server.py:5189-5194` 对 `/dashboard` 与 `/dashboard/map` 做精确匹配（`canonical_paths` 是 dict，无前缀误匹配）。**PASS**。
- 注意（非错误）：map 作为子节点不会出现在首页根卡片（`static/index.html:1820` 只遍历 root children），只能经 schedule 卡片的子页面 chip 或 URL 进入——这是设计意图，但建议规范写明“parent 非 root 的模块不进首页”。
- 另：`order:5` 只在 schedule 子级内参与排序（`registry.py:129`）。

### 4.4 ai 的 `capabilities` 与 custom view

- `view:{kind:"custom",dir:"web"}` + 真实存在的 `web/index.html`（1498 行）→ `server.py:4934-4936` 可正常服务 `/p/ai/`。**PASS**。
- `capabilities:["state"]`：合并时会**整体覆盖** base 的 `[state,action,audit,crud]`（`registry.py:91`），最终 tree/`/api/p/ai` 只显示 `state`。但全页没有任何 `/api/p/ai/...` 调用，实际能力面是 `/api/ai/*`、`/api/llm/*`、`/api/files/*`。因此该字段**既不描述真实能力、也不影响运行**（代码无任何 capabilities 校验/分支）。判定：**WARN/规范歧义**，不是 FAIL。
- 无 `project.py` → 以 `JsonDocProject` 实例化，`data/ai/` 下不会自动产生 doc（只有写动作才落盘），无副作用。**PASS**。

### 4.5 `project.py` 的 `Project` 基类（类继承校验）

| module | 文件:类 | 实际基类 | manifest base | registry 期望类 | 结果 |
| --- | --- | --- | --- | --- | --- |
| bottle | `projects/bottle/project.py:31` | `JsonDocProject`（import :8） | json-doc（json:8） | `JsonDocProject` | PASS |
| schedule | `projects/schedule/project.py:13` | `JsonDocProject`（import :9） | json-doc（json:8） | `JsonDocProject` | PASS |
| wishpool | `projects/wishpool/project.py:16` | `CoinProject`（import :10） | coin（json:8） | `CoinProject` | PASS |

- `registry.py:97-107` 会在动态导入后检查 `hasattr(mod,"Project")` 且 `issubclass(Project, base_cls)`，否则把错误记入 `Registry.errors` 并跳过该项目（`registry.py:115-116`）。三个 `project.py` 均满足。
- AST 检查确认三个文件顶层除 docstring/import/类定义外**没有**网络/文件副作用语句；`bottle`/`wishpool` 仅在运行时（action 内）调用 `notify()` 写通知，不在 import 阶段执行。
- 其余 6 个 module 无 `project.py`，按 `registry.py:97-98` 直接使用基类，属规范允许的“零代码 module”。

### 4.6 `web/index.html` 是否存在

| module | view | 文件 | 本地资源引用 | 结果 |
| --- | --- | --- | --- | --- |
| ai | custom/web | 存在（1498 行） | 9 个本地引用均可解析（`about:blank` 为 iframe 占位，非资源） | PASS |
| bottle | custom/web | 存在（688 行） | 1 个均可解析 | PASS |
| courtyard | custom/web | 存在（1221 行） | 1 个均可解析 | PASS |
| map | custom/web | 存在（530 行） | 5 个均可解析（含 leaflet 资源） | PASS |
| mock | custom/web | 存在（1358 行） | 1 个均可解析 | PASS |
| schedule | custom/web | 存在（1277 行） | 6 个均可解析（含 assets/leaflet、schedule.css、venues.js、schedule.json） | PASS |
| schedule-debug | custom/web | 存在（166 行） | 1 个均可解析 | PASS |
| scratchpad | custom/web | 存在（110 行） | 1 个均可解析 | PASS |
| wishpool | custom/web | 存在（1206 行） | 5 个均可解析 | PASS |

即：**9/9 custom view 都有 `web/index.html`**，`server.py:4935` 的静态根目录均可命中，无“custom 却无页面”的配置错误。

### 4.7 页面模板一致性（TEMPLATE.md，次要维度）

`TEMPLATE.md:3` 要求所有工作台项目“必须”用同一套模板；本审计把它作为独立维度（不影响 manifest 判定）：

| module | `template.css` | `body[data-project]` 与 id 一致 | `main.page` | `section.section` | 自带头部/登录/跨模块导航 | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| ai | `:7` | `:248` ai | `:249` | 有 `section`（class 为项目专有 `ai-chat`/`ai-side-panel`:250/314/320） | 无 | PASS（特殊抽屉页，class 属专有组件） |
| bottle | `:7` | `:103` bottle | **无** | 只有 `section.archive-panel`:111 | 有 `<h1>`:106 + `.head`:105 | **WARN** |
| courtyard | `:7` | `:61` courtyard | `:62` | `:64/90` | 无 | PASS |
| map | `:9` | `:183` map | `:184` | `:185/206` | 无 | PASS |
| mock | `:7` | `:68` mock | `:69` | `:72` | 无 | PASS |
| schedule | `:7` | `:15` schedule | `:16` | `:19/52/74/88` | 无 | PASS |
| schedule-debug | `:7` | `:36` schedule-debug | `:37` | `:38` | 无 | PASS |
| scratchpad | `:7` | `:9` scratchpad | `:10` | `:12/27` | 无 | PASS |
| wishpool | `:8` | `:11` wishpool | `:12` | `:15/32/43/66` | 无 | PASS |

- 全部 9 页均无登录门禁（无 `loginState()`）、无 `<header>`、无返回工作台/跨模块导航链接，符合 `TEMPLATE.md:26-28`。
- 仅 bottle 违反 `TEMPLATE.md:8-24` 的骨架与 `:26` 的“不出现全局标题”；其余页面符合。
- 另：README 说 custom 视图应“继承 `/static/project.css`、`/static/sdk.js`”（`README.md:62`），但 9 页实际统一加载 `/static/template.css` 且均未引 `sdk.js`。以 `TEMPLATE.md` 为准可判定为“文档过时”，记入 §6.3。

---

## 5. 问题汇总（按严重级别）

### 5.1 高（会阻断加载/接口不可用）

**无。** 9 个 module 的 `project.json` 均可被 registry 解析，3 个 `project.py` 类校验全部通过，9 个 custom view 都有 `web/index.html`，无重复 `id`/`path`，无非法 `base`/`parent`。

### 5.2 中（可运行，但存在功能退化或明确不符合硬规范）

| # | 问题 | 位置 | 影响 |
| --- | --- | --- | --- |
| M1 | scratchpad 无 `path`，普通模块走“隐藏项目”回退，无 canonical URL | `projects/scratchpad/project.json`（无 path）；`registry.py:139`；`static/index.html:2055-2061` | `/home?p=scratchpad` 可刷新但 URL 不稳定；`/scratchpad/` 404 |
| M2 | bottle 页面骨架违反 TEMPLATE.md（无 `main.page`、自带 `h1`、`.head` 代替 `.section-head`） | `projects/bottle/web/index.html:103-118`；`TEMPLATE.md:8-28` | 与根壳 `.pbar` 标题重复；模板样式/间距/入场动画不生效 |
| M3 | capabilities 词汇表缺失且声明与实现普遍不一致 | ai `json:9-11`、mock `json:13`、schedule `json:14`、schedule-debug `json:12-14`、courtyard `json:9-13`、map `json:9-14` | 字段既不被校验也不被消费，无法作为能力契约；未来做校验会大面积误报 |

### 5.3 低（整洁性/冗余/可读性，不影响运行）

| # | 问题 | 位置 |
| --- | --- | --- |
| L1 | `order` 重复（ai 与 courtyard 均为 25），靠 id 兜底排序 | `projects/ai/project.json:4`、`projects/courtyard/project.json:4`；`registry.py:129` |
| L2 | `acl` 与 abstract 完全重复（courtyard/schedule/wishpool） | `projects/{courtyard,schedule,wishpool}/project.json` 的 acl 段 |
| L3 | 未引用的遗留文件 `projects/ai/check.js`（1110 行，全仓无引用） | `projects/ai/check.js` |
| L4 | bottle 额外保留 `archive/3d-index.html`（已明确不在路由输出，`DESIGN.md:2147`） | `projects/bottle/archive/3d-index.html` |
| L5 | 3 个 module 无 `ui.theme.accent`，首页回退默认色 | ai、schedule-debug、scratchpad |
| L6 | `__pycache__` 出现在各 module 目录（运行时产物） | `projects/{bottle,schedule,wishpool}/__pycache__`，已被 `.gitignore` 忽略 |

---

## 6. 硬性错误 / 建议项 / 规范歧义（严格区分）

### 6.1 硬性错误（本次审计 = 0）

判定“硬性错误”的标准是“代码会失败或明确违反 ‘必须’ 规则”。逐项排除如下：

- **JSON 语法/结构**：9 个 `project.json` 与 4 个 `bases/*.json` 全部可 `json.load`。
- **id**：9/9 与目录名一致；无重复。
- **base**：9/9 有效（scratchpad 走默认 json-doc）；无未知 base。
- **parent**：9/9 有效（root 或已存在的 `schedule`）。
- **path**：8/9 合法且唯一；scratchpad 为空是“缺失”而非“非法”（`registry.py:139` 有兜底，不抛错）。
- **view**：9/9 为 `custom` 且 `dir` 有效、`web/index.html` 存在。
- **project.py**：3/3 的 `Project` 与 manifest base 的期望基类一致，无 import 期副作用。
- **TEMPLATE.md**：bottle 的页面骨架违规被归为 WARN 而非 FAIL，因为它不违反 `TEMPLATE.md` 以外的任何可执行规则，且未导致页面不可用；若团队把 TEMPLATE.md 视为“发布门禁”，则 bottle 应升级为 FAIL——这是判定口径问题，报告已标注。
- **与 `check_modules.py` 的口径差异**：该工具把 mock / schedule（capabilities 未知值）与 scratchpad（缺 path）判为 FAIL，但那 3 条依据的是其并行拟定的 `MODULE_SPEC.md` 规则（审计时该文件尚未落地），不是 `registry.py`/`project.py` 的现有约束；逐条核对见 §7.1。本报告按“源码行为 = 最终权威”维持 0 硬性错误，同时保留“若规范采纳闭集/path 必填则升级”的条件判定。

### 6.2 建议项（不是错误，不应阻断合并/发布）

1. **给 scratchpad 补 `"path": "/scratchpad/"`**（或明确它在规范中豁免 path），消除“普通模块走隐藏项目回退”的语义错位。
2. **给 bottle 页面补 `main.page > section.section` 骨架并移除页面内 `<h1>`**；若 2D 全屏页确实需要例外，请在 `TEMPLATE.md` 中写明“canvas 型模块可豁免骨架，但仍不得自带全局标题”。
3. **在规范中定义 capabilities 词汇表**（如 `state/action/audit/crud/coins/remind/upstream` 各是什么、是否允许自定义），并决定是否校验“⊆ 继承集合”。
4. **统一/清理 capabilities 声明**：mock、schedule 的 `upstream`/`remind` 要么进词汇表，要么删除；ai、schedule-debug 收窄为 `state` 时应确保与页面实际协议一致（或写明“capabilities 只描述项目协议，不描述页面内部 API”）。
5. **给 ai/courtyard 的 `order` 去重**（例如 courtyard 改 26 或 ai 改 24），让首页排序显式可控。
6. **删除未引用的 `projects/ai/check.js`**，或移入 `archive/` 并说明。
7. **移除与 abstract 重复的 `acl`**，减少三份冗余配置漂移风险。
8. **修正 README 与 TEMPLATE 的页面资源说明**：现 README 说继承 `project.css` + `sdk.js`，实际全部使用 `template.css` 且不引 `sdk.js`。
9. **在规范中写明 `acl` 的真实效力**：当前 `/api/p/<id>/action` 以 `write_allowed=True` 绕过 `acl.write`（`project.py:138`、`server.py:4671`），`can_read` 也无调用点；若保留该字段，需说明它目前不生效，否则会误导配置者。

### 6.3 规范歧义 / 建议补充点（无法用现有文档唯一判定）

| # | 歧义 | 依据冲突 |
| --- | --- | --- |
| A1 | **module manifest 的必填字段到底有哪些？** | `README.md:60` 只列 `id/parent/title/icon/base/view`；`DESIGN.md:219` 又依赖 `parent/order/path`；`TEMPLATE.md` 完全不谈 manifest。因此“缺 base/capabilities/path 是否违规”在文档层无法判定，只能以 registry 默认行为推断（本报告采用后者）。 |
| A2 | **capabilities 是“协议能力”还是“功能标签”？** | bases 只给 `state/action/audit/crud/coins`；项目里出现 `upstream`(mock)、`remind`(schedule)；ai/schedule-debug 只留 `state`。代码从读取该字段（仅 `project.py:60` 与 tree 透出），无校验/分支。 |
| A3 | **path 是否必填？** | 所有旧式入口依赖 path（`server.py:5189-5194`、`static/index.html:1799-1803`），但 registry 允许缺省为空（`registry.py:139`），DESIGN 又记录 scratchpad 只用 `/p/scratchpad/`（`DESIGN.md:19`）。 |
| A4 | **acl 的键是用户名还是角色？是否生效？** | `bases/abstract.json:5-8` 写 `kitten/puppy`（用户名）；`project.py:216-224` 的 `can_read/can_write(role)` 只在无参调用点之外未被使用；dispatch 传 `role=user`（`server.py:4671`）。语义与效力都需要规范确认。 |
| A5 | **roles 与 hidden 的职责边界** | schedule-debug 同时用了两者：`roles` 做硬访问控制（`server.py:3231-3238`），`hidden` 只影响首页展示（`static/index.html:1820`）。建议规范明确“hidden ≠ 权限”。 |
| A6 | **`bases/root.json` 是不是基类？** | 它在 `bases/` 目录但无 `base`/`capabilities`，不是 manifest 继承链成员，只被 `registry.py:154-165` 当作根节点元信息读取。新同学容易误写 `"base":"root"`（会得到无 capabilities/acl 的 manifest）。 |
| A7 | **`view.kind` 支持哪些值、`auto`/`legacy` 是否仍可用？** | registry/server 支持 `auto/custom/legacy` + `view.url`（`registry.py:147-150`、`server.py:4934-4941`），但 TEMPLATE 只写 `custom`，README 也只提 custom；现有 9 个模块全是 custom。 |
| A8 | **path 命名风格不统一** | schedule 用旧式 `/dashboard/`、map 用 `/dashboard/map/`，其他用 `/<id>/`。属历史兼容，但规范应说明“新模块用 `/<id>/`”。 |
| A9 | **module 目录是否允许放额外文件** | `ai/check.js`、`bottle/archive/` 等不被禁止也不被使用；规范可规定“只允许 project.json/project.py/web/（+可选 assets）”。 |
| A10 | **page 资源约定冲突** | `TEMPLATE.md:9` 用 `/static/template.css`；`README.md:62` 说继承 `/static/project.css` + `sdk.js`。实际 9/9 用 template.css、0/9 用 sdk.js。 |

---

## 7. 交叉验证与可复现性

### 7.1 与 `platform/tools/check_modules.py` 的交叉验证

审计主体完成后，`platform/tools/check_modules.py`（v1，只读）出现，运行结果：

```
PASS  ai / bottle / courtyard / map / schedule-debug / wishpool   （6）
FAIL  mock       E_CAP_UNKNOWN: capabilities ['upstream'] 不在继承集合
FAIL  schedule   E_CAP_UNKNOWN: capabilities ['remind']   不在继承集合
FAIL  scratchpad E_PATH_MISSING: 未声明 path（视为硬性必填）
                  + W_BASE_DEFAULTED / W_CAPS_INHERITED（均判为“缺省可继承，不是违规”）
汇总：9 modules · PASS 6 · FAIL 3 · 硬性错误 3
```

**一致部分**：`ai/bottle/courtyard/map/schedule-debug/wishpool` 的 PASS；`scratchpad` 的 base/capabilities 两项被该工具同样判定为“可以继承、不是违规”（与 §4.1 一致）；`bottle` 的页面模板偏差不在该工具范围（与本报告 §4.7 属不同维度，不冲突）。

**分歧 1：scratchpad 的 path 是否硬性错误**

- 工具判 FAIL（E_PATH_MISSING），给的理由是“模块不会进入工作台卡片/路由（`static/check.js` 只索引有 path 的节点）”。
- 该理由与线上源码不符：运行壳是 `static/index.html`（`server.py:3313-3322` 明确返回该文件），`static/check.js` 是被 `.gitignore` 忽略的开发残留（根 `.gitignore` 第 3 段）；且 `static/index.html:1820` 的首页只过滤 `!hidden`、**不要求 path**，scratchpad 作为 root 子节点仍会出卡片；点击走 `static/index.html:2055-2061` 的 `?p=` 回退，刷新由 `:2663-2670` 的 `p` 参数处理。实测语义：**卡片可点、页面可开、可刷新，只是没有稳定 URL**。
- 结论：本报告维持 **WARN**，并主张“path 至少是强建议项”；若团队在 MODULE_SPEC 中正式把 path 定为必填，则应把 scratchpad 记 FAIL，并同步修正该工具中“check.js 只索引有 path 的节点”这一不准确依据（应引用 `static/index.html`）。

**分歧 2：mock/schedule 的 capabilities 是否硬性错误**

- 工具采用“capabilities ⊆ base 继承集合”的闭集规则，故 `upstream`/`remind` 判 FAIL。
- 该规则在 `bases/*.json` 与 `registry.py` 中**不存在**：`registry.py:141` 只是把数组合并下发，内核无任何 capabilities 校验/分支（全仓仅 `project.py:60` 读取）。`upstream`/`remind` 是未定义的自由标签。若 MODULE_SPEC 采纳闭集规则，则 FAIL 成立（且规范应同时说明新增能力必须先写进 `bases/*.json`）；若 capabilities 定位为功能标签，则应以“未定义词汇”记 WARN。
- 结论：本报告维持 **WARN/规范歧义**（§5.2-M3、§6.3-A2），并建议在 `MODULE_SPEC.md` 中正式裁决，而不是让工具单方面引入规则。

**共同结论**：三处分歧都源于 §6.3 列的规范空白（path 是否必填、capabilities 是否闭集），**没有一处是现有文件写了非法值**；校验器可作为门禁，但需先让 MODULE_SPEC 与源码行为对齐（尤其修正 `static/check.js` 的引用）。

### 7.2 独立复核的覆盖范围

- 复刻 registry 合并逻辑所用的只读校验（未执行 `Registry()`，避免 `registry.py:109-110` 的 `os.makedirs` 副作用）覆盖：
  1. `deep_merge` + `_base_manifest` 计算有效 manifest；
  2. `id==目录名`、`id/path` 唯一性；
  3. `base ∈ bases/`、`parent ∈ {root} ∪ 项目 id`；
  4. `path` 以 `/` 开头/结尾；
  5. `view.kind` 枚举、`custom` 的目录与 `index.html` 存在性；
  6. `tags/roles/hidden/order/acl` 类型；
  7. `project.py` 的 AST 类/基类核对。
- 页面核对：`grep` `template.css`/`data-project`/`main`/`section`/`h1`/`header`/`loginState`/跨模块链接；本地 `src|href` 相对路径解析（所有可解析）。
- 全程未启动服务、未写 `projects/`、`kernel/`、`bases/`，未提交 Git。

---

## 附录 A：关键证据索引

| 事实 | 证据位置 |
| --- | --- |
| 继承链 abstract←json-doc←coin | `registry.py:53-64`；`bases/*.json` |
| base 缺省 json-doc | `registry.py:89` |
| id 缺省目录名 | `registry.py:88` |
| capabilities 列表整体覆盖 | `registry.py:32-40`、`:91` |
| path 缺省 "" | `registry.py:139` |
| parent 缺省 root；order 缺省 100 | `registry.py:126-129` |
| project.py 类校验 | `registry.py:95-107` |
| custom → web/index.html | `server.py:4925-4942` |
| canonical_paths 由 path 生成 | `server.py:5189-5194` |
| roles 硬过滤 | `server.py:3231-3238` |
| schedule-debug 接口仅 super | `server.py:3462-3465`、`:4228-4231`、`:4255-4258` |
| 前端路由注册/隐藏/回退 | `static/index.html:1798-1803`、`:1813-1815`、`:1820`、`:1907-1909`、`:2055-2061` |
| JSON-DOC 基类动作 | `project.py:227-296` |
| ACL 在写动作被绕过 | `project.py:138`；`server.py:4671` |
| scratchpad 页面用继承动作 | `projects/scratchpad/web/index.html:35/63/68/75/90` |
| bottle 页面骨架偏差 | `projects/bottle/web/index.html:103-118` |
| TEMPLATE 骨架/禁项 | `TEMPLATE.md:8-28`、`:64-71` |
| map 为 schedule 子节点 | `DESIGN.md:16` |
| schedule-debug roles/path | `DESIGN.md:755-756` |
| scratchpad 仅 /p/ 形态 | `DESIGN.md:19` |
| bottle 3D 页移入 archive | `DESIGN.md:2147` |

---

*报告结束。本报告只读审计，未改动任何模块或平台代码。*

---

## 补充：2026-11-07 模板统一化后复审

审计后已按 `TEMPLATE.md` 统一页面骨架，以下为当前状态：

- `projects/bottle/web/index.html`：改为 `main.page.bottle-page` + 两个 `section.section`（海面、已打开），移除页面级 `<h1>`，按钮移入 `.section-head .actions`；
- `projects/ai/web/index.html`：`section.ai-chat` 增加模板 `section` 类，保留 AI 专有布局覆盖；
- `tools/check_modules.py`：模板静态检查新增 `main.page`、`section.section`、无全局 `<h1>`；
- 复审命令：`python tools/check_modules.py`
- 复审结果：`10 PASS / 0 FAIL / 2 WARN`；剩余 2 条是 mock `upstream`、schedule `remind`，与页面模板无关。
- 原 §3.1 中 bottle 的“页面骨架 WARN”已关闭，bottle 现在通过模板结构检查。
- `scratchpad` 已补 `base/capabilities/path`，不再走 `?p=` 回退；`path` 对可见 module 已升级为硬性 ERROR。
- 已追加 GitHub Pages 子页面壳检查：10 个 module 的 `KittenPuppy4Ever/<path>/index.html` 全部存在，且含 iframe/entry.json/路径还原/replaceState 标记。
- `scratchpad` 的 GitHub Pages 子页面：`/kitten/KittenPuppy4Ever/scratchpad/` 现在具备可刷新入口。
- 新增 `games` 游戏中心（`/games/`），`courtyard` 改为其子游戏（`/games/courtyard/`），旧 `/courtyard/` 保留重定向。
