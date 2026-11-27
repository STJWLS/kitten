# KittenPuppy4Ever 后端应用模板化评估

日期：2026-11-27
范围：`platform/projects/` 下 10 个后端 module
评估对象：manifest、base 继承、Python Project 子类、kp/1 API、专用 HTTP API、视图/模板、校验与测试

## 1. 结论摘要

| 维度 | 现状 | 评价 |
|---|---|---|
| 声明式 manifest | 10/10 通过 | 强 |
| base 继承链 | 10/10 使用 `json-doc` 或 `coin` | 强 |
| 页面模板绑定 | 10/10 有 `#module` / `#module.game` | 强 |
| path + GitHub Pages 壳 | 10/10 通过 | 强 |
| 共享 kp/1 `state/action` | 2/10 真正端到端使用 | 弱 |
| 自定义后端逻辑 | 3 个 `project.py` + 4 类写在 `kernel/server.py` 的专用路由 | 分裂 |
| 客户端 SDK `static/sdk.js` | 0/10 使用 | 基本未模板化 |
| 自动视图 `view.kind=auto` | 0/10 使用 | 模板能力闲置 |
| 行为/契约测试 | manifest 静态检查有；模块业务无 | 弱 |

**总评：格式和声明层已经模板化，业务后端和 API 层仍以“定制页面 + 内核专用路由”为主，整体约 2.4/5。**

当前更像“统一的模块外壳 + 三种不同后端实现范式”：

```text
A. 零代码通用 CRUD：scratchpad
B. 共享基类 + 业务子类：bottle / wishpool / schedule
C. 内核专用 API / 静态数据 / 纯客户端：ai / mock / schedule-debug / map / games / courtyard
```

## 2. 当前数据

### 2.1 模块清单

| 应用 | base | 自有 project.py | 主要后端入口 | 后端模板化 |
|---|---|---|---:|---:|
| ai | json-doc | 无 | `/api/ai/*` | 1/5 |
| bottle | json-doc | 有 | `/api/p/bottle/*` + 自定义动作 | 4/5 |
| courtyard | json-doc | 无 | 无（游戏状态在浏览器 localStorage） | 1/5 |
| games | json-doc | 无 | `/api/tree`（只读目录） | 1/5 |
| map | json-doc | 无 | 前端读取 `schedule.json` | 1/5 |
| mock | json-doc | 无 | `/mock/api/*` 反代 | 1/5 |
| schedule | json-doc | 有 | `/api/schedule/*` + `/api/p/schedule/*` | 3/5 |
| schedule-debug | json-doc | 无 | `/api/schedule/admin/*` | 1/5 |
| scratchpad | json-doc | 无 | `/api/p/scratchpad/state|action` | 5/5 |
| wishpool | coin | 有 | 旧 `/api/state`（前端）| 2/5 |

### 2.2 关键数量

```text
module 总数                 10
manifest 校验 PASS          10
硬性错误                    0
建议项                      2（mock.upstream、schedule.remind）
base 数                     3（abstract / json-doc / coin）
project.py                  3 / 10（bottle、schedule、wishpool）
project.py 总行数           325
使用 kp/1 业务 API          2 / 10（bottle、scratchpad）
使用 legacy /api/state      1 / 10（wishpool）
使用专用内核 API            4 / 10（ai、mock、schedule、schedule-debug）
纯客户端/静态数据            3 / 10（courtyard、games、map）
view.kind = custom         10 / 10
view.kind = auto            0 / 10
使用 static/sdk.js          0 / 10
```

## 3. 已经模板化的部分

### 3.1 Manifest 继承

`bases/abstract.json` → `bases/json-doc.json` → `bases/coin.json` 的 manifest 继承链可以复用：

- ACL
- capabilities
- UI theme 默认值
- view 默认值
- 项目自身字段覆盖

### 3.2 Python 类继承

`AbstractProject` → `JsonDocProject` → `CoinProject` 的类继承链已经成立，并且 registry 强校验：

```python
issubclass(Project, base_cls)
```

`project.py` 不需要重复实现持久化、rev、审计、ACL、ETag、409 冲突等基础设施。

### 3.3 kp/1 协议

`JsonDocProject` 自带：

```text
get / set / patch / append / remove / reset
state + rev + conflict + audit
```

`CoinProject` 额外提供：

```text
coins + log + grant / spend
```

### 3.4 页面模板

`static/template-tree.json`：

```text
#module
└── #game   → #module.game
```

所有 module 都继承 `#module`，游戏中心/造院使用 `#module.game`。

### 3.5 声明与路由

10/10 有显式 `path`，10/10 有 GitHub Pages 壳；`check_modules.py` 当前为 PASS 10 / FAIL 0。

## 4. 主要问题

### P0：专用后端路由写死在 `kernel/server.py`

现状：

```text
AI        -> kernel/server.py 中的 /api/ai/*
Mock      -> MockGateway + /mock/api
Schedule  -> kernel/server.py 中的 /api/schedule/*
schedule-debug -> /api/schedule/admin/*
```

后果：

- 新增同类应用必须改内核，而不是只加 module；
- 这些应用无法通过 project manifest 声明自己的 API；
- 内核 `server.py` 变成业务路由集合，模块边界不清晰；
- 与 `projects/<id>` 的目录约定脱节。

这是当前后端模板化最大的断点。

### P0：wishpool 前端仍走 legacy `/api/state`

`wishpool` 有 `Project(CoinProject)`，但页面实际调用：

```text
GET /api/state
```

这会绕过：

- `/api/p/wishpool/state`
- kp/1 rev / ETag
- 项目级 ACL
- 新协议审计路径

业务类已经模板化，接入层没有接上。

### P1：`static/sdk.js` 已存在但 0/10 使用

SDK 已提供：

```text
KittenProjectView
state / rev / action / refresh
theme / esc / notify
```

但所有 10 个页面都各自重复写 `fetch()`、错误处理、rev、主题注入。

后果：

- 前后端协议变化时，10 个页面要分别改；
- 页面层没有真正模板化；
- 新应用无法只靠 SDK + 配置完成 CRUD 页面。

### P1：通用 `auto` 视图闲置

`view.kind=auto` 和 `AUTO_VIEW_HTML` 已存在，但 0 个 module 使用，全部是 custom view。

- 对 scratchpad 这种纯 CRUD 应用，custom view 并不必要；
- 自动视图能力没有被验证/维护，容易腐化。

### P1：能力声明与实现脱节

校验器提示：

```text
mock      capabilities 含 upstream（不在词表）
schedule  capabilities 含 remind（不在词表）
```

同时存在声明了 `state/action/audit/crud` 但实际没有走项目 API 的应用。

后果：capabilities 目前更多是“标签”，不是可执行契约。

### P1：`project.py` 业务模式重复

bottle / wishpool / schedule 重复实现：

```text
default_state
item_key
merge（按 key 并集）
_find
on_action 分支
notify(...) 调用
```

应抽成：

```text
KeyedJsonDocProject
NotifyingProject / notify_action helper
```

### P2：缺少行为契约测试

`check_modules.py` 只校验：

- manifest
- base
- path
- Pages 壳
- 静态 Python 结构

没有自动验证：

- 每个 module 的 `/state` 可读
- default actions 可用
- 自定义 action 正常
- rev 冲突返回 409
- ACL 生效
- custom view 真的调用项目 API

当前 10 PASS 只能说明“格式可加载”，不能说明“业务协议可用”。

### P2：数据源分裂

```text
project doc.json       大部分 module
notifications.json     通知
messages.db            私信
AI sessions            AI
schedule.json          地图/日程
localStorage           造院成就/游戏状态
```

其中 map 直接读静态 `schedule.json`，courtyard 游戏状态在客户端，wishpool 走 legacy store，导致后端模板无法统一治理。

## 5. 建议的目标架构

### 5.1 后端模板层次

建议明确四个模板层：

```text
L1 声明层：project.json
L2 类模板：AbstractProject / JsonDocProject / CoinProject
L3 协议层：kp/1 state/action + rev/audit/ACL
L4 接线层：module-local API / SDK / 自动视图
```

当前强在 L1/L2，弱在 L3/L4。

### 5.2 新增 module-local API

给 `Project` 增加 API 声明能力，例如：

```python
class Project(JsonDocProject):
    api_prefix = "/api/ai"
    def api_routes(self):
        return {...}
```

registry 或 server 统一挂载，避免继续往 `kernel/server.py` 加 if。

对 mock 这类反代，可声明：

```json
"backend": {"kind": "proxy", "target": "mock_gateway"}
```

对静态数据：

```json
"backend": {"kind": "static", "file": "schedule.json"}
```

### 5.3 新增共享基类

```text
KeyedJsonDocProject
  - item_key
  - merge_by_key
  - _find

NotifyingProject
  - notify_action(...)
  - 审计 + 通知组合
```

### 5.4 迁移路径

优先级排序：

1. wishpool 从前端 `/api/state` 迁到 `/api/p/wishpool/state|action`；
2. 把 ai/mock/schedule/schedule-debug 的专用路由迁出 `server.py`；
3. 用 `sdk.js` 替换各页面的重复 fetch 层；
4. 给 `scratchpad` 先切 `view.kind=auto`，验证自动视图；
5. 抽 `KeyedJsonDocProject` / 通知 helper；
6. 增加 module 行为契约测试；
7. 统一 map/courtyard 的数据持久化边界。

### 5.5 测试门禁建议

```text
check_modules.py             格式/继承/路径门禁（保留）
check_templates.py           页面模板树（保留）
check_module_contracts.py    新增：每个 module state/action/rev/ACL
smoke_test.py                新增：custom API 健康检查
```

## 6. 结论

- **声明式外壳已经成熟**：manifest、base、path、Pages 壳、页面模板树都能复用；
- **业务层只完成了一部分**：3 个 project.py 继承了基类，但其中 1 个还没接新协议；
- **真正的模板化断点在 API 接线**：专用路由和客户端直连散落在内核/页面里；
- **下一步不应继续加页面，而应把 API 从 `server.py` 收回 module，并让 SDK 成为默认客户端层**。

目标不是让所有应用都长一样，而是：

```text
通用 CRUD 应用        → 零代码 auto
有业务规则的应用      → project.py 子类 + kp/1
有专用接口的应用      → module-local API 声明
纯静态/游戏应用       → 明确声明 static/client 边界
```

这样“新增一个应用”才真正只需要增加一个 module 目录，而不是修改内核。

## 7. 修复进展（2026-11-27）

已完成的第一批：

1. **自动视图补齐**
   - 新增 `static/auto-view.html`；
   - `server._serve_auto_view` 从文件加载模板，不再引用未定义的 `AUTO_VIEW_HTML`；
   - `scratchpad` 从 custom view 切为 `view.kind=auto`，并删除旧的 `web/index.html`；
   - 自动视图使用 `static/sdk.js` 的 `KittenProjectView`，CRUD 实测通过。

2. **module-local API 框架**
   - 新增 `kernel/module_api.py`；
   - `Registry` 自动加载 `projects/<id>/api.py` 的 `PREFIXES` + `handle`；
   - `server` 先匹配 module API，再走旧路由；
   - 已迁移：
     - `/mock/api/*` → `projects/mock/api.py`
     - `/api/schedule/admin/*` → `projects/schedule-debug/api.py`

3. **共享 keyed merge helper**
   - `kernel/project.py` 新增：
     - `item_key_of`
     - `merge_items_by_key`
     - `find_item_by_key`
   - bottle / schedule / wishpool 删除各自重复的 merge/_find 代码。

4. **行为契约测试**
   - 新增 `tools/check_contracts.py`；
   - 实例化所有 10 个 module，在临时目录中验证 `state`、`append`、`remove`、rev、动作集合；
   - 当前 10/10 通过，不写平台真实数据。

5. **能力词表**
   - `upstream`、`remind` 作为平台扩展能力登记到 `EXTENSION_CAPABILITIES`；
   - `check_modules.py` 当前为 10 PASS / 0 WARN / 0 FAIL。

6. **SDK 采用起点**
   - 自动视图已使用 `KittenProjectView`；
   - 其余 custom view 的 SDK 迁移仍未完成。

### 仍未完成

- `ai`、`schedule` 的专用路由仍在 `kernel/server.py`；
- `wishpool` 前端仍走 legacy `/api/state`；
- 10 个 custom view 尚未统一 SDK；
- `KeyedJsonDocProject` 只抽了 helper，尚未抽成 manifest base；
- 地图/造院的数据边界还没统一。

## 8. 第二批修复（2026-11-27）

- 新增 manifest/Python base：
  - `keyed` → `KeyedJsonDocProject`
  - `keyed-coin` → `KeyedCoinProject`
- `schedule`、`bottle` 改用 `keyed`；
- `wishpool` 改用 `keyed-coin`；
- `bottle` 保留 `bottles` 字段 + layouts 合并；
- `schedule` / `bottle` / `wishpool` 的重复 `merge`、`_find` 已删除；
- `MODULE_SPEC.md` / `README.md` 已登记新 base；
- checker、契约测试均通过。

仍未完成：

- `ai`、`schedule` 的专用 GET/POST 路由仍在 `kernel/server.py`；
- `wishpool` 前端仍调用 legacy `/api/state`；
- 所有 custom view 尚未统一 SDK；
- map / courtyard 的持久化边界未统一。

## 9. 第三批修复（2026-11-27）

- `/api/schedule/courses`、`/api/schedule/venues`、`/api/schedule/events`、
  `/api/schedule/participants` 已从 `kernel/server.py` 迁到
  `projects/schedule/api.py`；
- `/api/schedule/admin/*` 继续由 `projects/schedule-debug/api.py` 处理；
- 新增 `_sched_save_locked` / `_sched_courses_save_locked`，module API 复用内核锁；
- 日程页面和四个 API 实测 200；
- `kernel/server.py` 中不再有 schedule 专用 GET/POST 分支。

仍未完成：

- `ai` 专用路由仍在 `kernel/server.py`；
- `wishpool` 前端仍走 `/api/state`；
- custom view 的 SDK 统一；
- map / courtyard 数据边界。
