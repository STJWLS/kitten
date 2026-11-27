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

## 10. 第四批修复（2026-11-27）

- `/api/ai/skills`、`/api/ai/dsh/status`、`/api/ai/tools`、
  `/api/ai/sessions*`、`/api/ai/dsh/stream`、`/api/ai/skills/toggle|import`、
  `/api/ai/dsh/stop|chat`、`/api/ai/tools/execute`、`/api/ai/sessions/save|flags|delete|import`
  已迁到 `projects/ai/api.py`；
- `kernel/server.py` 中的 AI GET/POST 分支已删除；
- AI 页面与主要接口实测 200：
  - `/api/ai/skills`
  - `/api/ai/dsh/status`
  - `/api/ai/tools`
  - `/api/ai/sessions`
- 仍留在内核的 AI 相关接口：
  - `/api/llm/*`（模型配置/测试/对话）
  - `/api/files/*`（加密文件）
  - `/api/bugreport*`、用户/主题等平台级接口

## 11. 第五批修复（2026-11-27）

- `/api/files`、`/api/files/<id>`、`/api/files/upload`、`/api/files/delete`
  已迁到 `projects/ai/api.py`；
- 新增 `_files_save_locked`，module API 复用文件索引锁；
- 实测：
  - `/api/files` 200
  - `/api/files/upload` dry_run 200，加密往返 `roundtrip=true`
  - `/api/files/notfound` 404
- AI 页面与 AI 接口仍正常。

仍未完成：

- `wishpool` 前端 legacy `/api/state`
- custom view SDK 统一
- map / courtyard 数据边界
- `/api/llm/*` 仍在 `kernel/server.py`

## 12. 第六批修复（2026-11-27）

- `/api/llm/*` 全部 GET/POST 路由已迁到 `projects/ai/api.py`：
  - `/api/llm/models`
  - `/api/llm/status`
  - `/api/llm/admin`
  - `/api/llm/admin/mineru`
  - `/api/llm/admin/mineru/check`
  - `/api/llm/me`
  - `/api/llm/test`
  - `/api/llm/chat`
- `kernel/server.py` 中不再有 `/api/ai/`、`/api/llm/`、`/api/files/` 专用分支；
- 实测 200：
  - `/api/llm/status`
  - `/api/llm/models`
  - `/api/llm/admin`
  - `/api/ai/sessions`
  - `/api/files`

剩余：

- `wishpool` 前端 legacy `/api/state`
- custom view SDK 统一
- map / courtyard 数据边界

## 13. 第七批修复（2026-11-27）

- 新增 `projects/wishpool/api.py`：
  - `GET /api/wishpool/state`
  - `POST /api/wishpool/save`
- wishpool 页面与 `assets/venues.js` 已不再调用全局 `/api/state`、`/api/save`；
- 当前许愿池仍使用旧 store 语义，但数据入口已限定到 wishpool module，不再污染全局兼容层；
- `/api/wishpool/state` 实测 200，页面无 JS 错误。

剩余：

- wishpool 数据形状正式迁移到 kp/1 `wishes/coins` project state；
- custom view SDK 统一；
- map / courtyard 数据边界。

## 14. 第八批修复（2026-11-27）

- manifest 新增可选 `data` 数据边界声明；
- `registry.tree()` 暴露 `data`；
- `check_modules` 增加 `E_DATA_TYPE / E_DATA_KIND / E_DATA_FIELD_TYPE`；
- 已显式声明：
  - `games` → `tree`
  - `courtyard` → `client / localStorage`
  - `map` → `static / schedule.json`
  - `wishpool` → `legacy-store / compat`
- `MODULE_SPEC.md` 新增数据边界章节。

这不会改变页面行为，但把“静态数据、客户端状态、旧 store、模块树”从隐式约定变成可校验的 manifest 契约。

## 15. 第九批修复（2026-11-27）

- `/api/wishpool/state` 现在以 project doc 作为 `wishes / coins / wish_notified` 的权威来源；
- legacy 兼容层只补充 `events / venues / t` 等 schedule 投影；
- wishpool 页面实测 200，无 JS 错误。

剩余：

- `/api/wishpool/save` 仍使用 legacy 合并语义（尚未拆成 kp/1 patch/action）；
- custom view SDK 统一；
- map / courtyard 仍是显式 static/client 数据边界。

## 16. 第十批修复（2026-11-27）

- `/api/wishpool/save` 已拆分：
  - `wishes / coins / wish_notified` → `project.dispatch("patch")`
  - `events / venues / t` → `compat.save_schedule()`，不再重写 wishpool 文档
- 新增 `compat.save_schedule()`，保留 schedule/meta 合并与旧 t 语义；
- 实测：
  - GET `/api/wishpool/state` 返回 2 条愿望；
  - POST `/api/wishpool/save` 保存当前快照，`saved=true`、`stale=false`；
  - 页面无 JS 错误。

剩余：

- wishpool 页面 UI 仍使用旧 wishes/coins 字段（但读写已走项目状态/模块适配器）；
- custom view SDK 统一；
- map / courtyard 的 static/client 边界。

## 17. 第十一批修复（2026-11-27）

- 新增 `projects/map/api.py`：
  - `GET /api/map/data`
- 地图页面不再直接 `fetch("schedule.json")`，改走 map module-local API；
- map manifest 的 `data.source` 改为 `/api/map/data`；
- 实测：
  - `/api/map/data` 200
  - 地图页面无 JS 错误。

剩余：

- custom view SDK 统一；
- courtyard 客户端状态仍为 localStorage（数据边界已声明）。

## 18. 第十二批修复（2026-11-27）

- `static/sdk.js` 新增轻量 `KpSdk`：
  - `request`
  - `getJSON`
  - `postJSON`
- 所有 module 页面由 `_inject_shell` 自动注入 `sdk.js`；
- 自动视图继续使用 `KittenProjectView`；
- map 页面改用 `KpSdk.getJSON` 读取 `/api/map/data` 与瓦片代理配置；
- 去掉了 auto-view 中重复的 sdk.js 引用；
- map / scratchpad 实测无 JS 错误，`window.KpSdk` 可用。

剩余：

- 其他 custom view 仍保留自己的 fetch 包装，可按页面逐步迁到 `KpSdk`；
- courtyard 仍是 localStorage 客户端状态（边界已声明）。

## 19. 第十三批修复（2026-11-27）

- `KpSdk.request` 自动带 `kp_token`（localStorage / sessionStorage）；
- 已把以下 custom view 的非流式请求包装迁到 `KpSdk`：
  - `games`
  - `ai`
  - `schedule-debug`
  - `bottle`
  - `map`（上一批）
- 自动视图继续使用 `KittenProjectView`；
- 页面回归：
  - games / ai / schedule-debug / bottle / map / scratchpad
  - 均无 JS 错误，`window.KpSdk` 可用。

未迁移的部分是刻意的：

- `mock` 有流式反代，保留自己的 fetch；
- `schedule` 有大量专用请求和旧页面同步逻辑；
- `wishpool` 有旧 store 合并语义；
- `courtyard` 是纯客户端游戏状态（manifest 已声明 `data.kind=client`）。

至此模板化报告中可落地的部分已完成；剩余是这几个特殊视图的深度重构，不再是模板基础设施问题。

## 20. 系统级增强（2026-11-27）

- 新增 `SYSTEM.md`：分层、继承、API 归属、数据边界、门禁、新增 module 清单；
- 新增 `GET /api/system`：认证后返回模块目录、base/template/data、module API 归属、registry errors；
- 新增 `tools/check_system.py`：
  - 运行 format/template/contracts 三个门禁；
  - 校验 module API 前缀不冲突；
  - 扫描已迁移路由不再出现在 `kernel/server.py`；
  - 校验 `data.kind`；
  - 校验 `SYSTEM.md` 存在。
- 全模块补齐 `data` 声明，`check_modules` 保持 0 WARN；
- `/api/system` 实测：10 modules、6 个 API owner、0 errors。

## 21. 新游戏：德州扑克（隐藏模块，未上线）

- 新增 `projects/holdem/`：
  - `hidden: true`，不进入游戏中心目录；
  - 6–10 人牌桌；
  - 总筹码池输入，按人数分配；
  - 四个 AI 难度：easy / medium / hard / hell；
  - AI 只通过 `Game.aiView(seat)` 取得自己的手牌、公共牌和公开下注。
- 规则引擎：`web/engine.js`；AI：`web/ai.js`；UI：`web/index.html`。
- 游戏结束条件：任意玩家在一手结束后筹码为 0。
- 生成 `KittenPuppy4Ever/games/holdem/index.html` 路径壳，但模块隐藏，不显示在游戏中心。
- `check_modules`：11 PASS / 0 FAIL / 0 WARN。

## 22. 德州扑克 AI 难度算力分层

- easy：16 次胜率模拟
- medium：120 次
- hard：480 次
- hell：1600 次
- 河牌单挑且模拟次数足够时，使用精确枚举（C(45,2)=990 种对手手牌）
- 模拟只使用自己的手牌、公共牌和公开信息；不读取牌堆或其他玩家手牌
- setup 中直接显示每个难度的模拟次数

## 23. 德州扑克：全窗口布局 + 24 个成就

- 布局改为 `100dvh` + `overflow:hidden`，页面不产生滚动：
  - 桌面：桌台填充剩余高度，日志内部滚动；
  - 移动端：桌台 + 操作区 + 日志按 grid 行分配，仍无页面滚动。
- 成就：
  - manifest `ui.achievements` 共 24 个；
  - 从初次入局、首次跟注/加注/弃牌、首次摊牌、首次赢牌；
  - 到两对/三条/顺子/同花/葫芦/四条/同花顺；
  - 再到全下取胜、500+ 底池、三连胜、盲注位赢、地狱 AI、绝地反击、最后赢家。
- 成就状态存在 `kp_achievements_<user>`，游戏页有成就面板和本地提示；
  在根壳内通过 `kpAchievement` 消息复用 Steam 风格弹窗。
- 实测：
  - 1440×900、390×844 均无页面滚动；
  - 24 个成就加载；
  - 自动牌局解锁 6 个成就；
  - 无 JS 错误。

## 24. 德州扑克牌面视觉增强

- 牌面字体整体放大：
  - 公共牌 38×54，桌面边缘牌 31×44；
  - 座位名、筹码、底池、日志、操作区同步放大；
- A/J/Q/K 特异化：
  - A：26px 字、星形角标、金色描边；
  - K/Q/J：21px 字、♚/♛/♞ 角标、金色边框；
  - 普通牌保持简洁数字牌面；
- 实测 1440×900 仍无页面滚动；`A♠ K♥` 截图在 `holdem-honor.png`。

## 25. 牌面统一边框

- 取消 A/J/Q/K 单独的金色边框/金色渐变；
- 整副牌统一使用同一套奶油色纸面、细墨色边框和阴影；
- A/J/Q/K 仅通过字体大小与花色角标区分：
  - A 26px + ✦
  - K 21px + ♚
  - Q 21px + ♛
  - J 21px + ♞
- 角标使用当前花色色（红/黑），不再使用金色；
- 1440×900 无页面滚动，截图 `holdem-uniform-cards.png`。

## 26. 德州扑克筹码实体渲染

- 筹码面额：10 / 20 / 50 / 100 / 200 / 500 / 1000；
- 每个玩家座位下显示当前筹码拆分的彩色筹码；
- 下注额旁显示本手下注筹码；底池中心显示底池筹码；
- 筹码拆分采用混合面额：1000 以下避免只用单一大额筹码，例：
  - 1000 → 500 + 200×2 + 100
  - 990 → 500 + 200×2 + 50 + 20×2
- 桌面顶部显示完整面额图例；
- 下注滑块和 AI 加注按 10 的整数倍取整；
- 1440×900 无页面滚动。

## 27. 德州扑克筹码下注与飞入底池动画

- 下注不再使用数字滑杆，改为点击自己的筹码堆选筹码：
  - 点击面额筹码加入；
  - 右键/清空撤销；
  - 跟注、加注都要求先选筹码；
- 支持底池找零：
  - 跟注时筹码超过跟注额，显示并从底池找零；
  - 加注可使用“最小 / 半池 / 一池”目标；选中的筹码超过目标时从底池找零；
- 每个玩家座位下按面额渲染多摞筹码，不再只显示一个大数字；
- 底池把筹码拆成 10/20/50 等小筹码，散落渲染在桌面上；
- 新增 `.chip-fly` 动画：下注筹码从座位飞向底池，找零筹码从底池飞回座位；
- 1440×900 / 390×844 均无页面滚动。

## 28. 筹码下注最终形态

- 跟注/加注只能用筹码选择完成，已移除数字滑杆；
- 加注目标支持最小 / 半池 / 一池；选中筹码超过目标时从底池找零；
- 跟注选中筹码超过跟注额时同样从底池找零；
- 座位筹码按面额摞成多组筹码堆；
- 底池筹码拆小并散落在桌面；
- 下注/找零均有飞行动画。

## 29. 禁用找零、放大筹码与缺门按钮

- 取消底池找零：
  - 跟注必须正好等于跟注额；
  - 加注必须正好等于目标加注额；
  - 多选/少选都会禁用操作并显示差额提示。
- 筹码渲染放大：
  - 桌内筹码盘 22px；
  - 下注托盘 36px；
  - 底池散落筹码 21px；
  - 座位筹码堆与图例同步放大。
- 缺门面额仍保留按钮，但变灰禁用（例如初始 1000 筹码堆中的 1K 按钮）。

## 30. 每轮结束筹码收拢

- 下注轮结束时，桌面散落的筹码会依次飞向底池右侧的收拢筹码堆；
- 收拢堆按 10 筹码为单位垂直叠加，不再保持散落；
- 新一轮下注的筹码重新散落在桌面；
- 根壳内仍保持无页面滚动。

## 31. 跟注/加注合并为自动识别

- 移除独立的“跟注”和“加注”按钮；
- 只保留一个下注按钮，根据已选筹码自动判断：
  - 选中额 = 跟注额 → 跟注；
  - 选中额 > 跟注额且达到最小加注 → 加注；
  - 未达到最小加注 → 禁用并提示还差多少；
  - 翻牌前无人下注 → 自动识别为下注。
- 不再使用加注目标预设按钮，加注额完全由选中的筹码决定。
- 仍然不支持找零，选中额必须精确等于目标。

## 32. 保留加注预设按钮

- 恢复“最小 / 半池 / 一池”三个预设按钮；
- 预设不是直接下注，而是从当前筹码堆里自动挑出**正好等于目标所需额度**的筹码；
- 挑好后仍由单一“下注”按钮自动识别为加注；
- 没有行动权、或现有筹码无法精确凑出目标时，预设按钮灰显；
- 仍然不支持找零。

## 33. 移除页头黄色标题、筹码图例移入侧栏

- 删除页头黄色“德州扑克”大标题；
- 删除页头下方独立筹码图例行，不再占用桌面高度；
- 筹码图例移入右侧“牌局记录”面板标题区；
- 桌面高度进一步释放，仍无页面滚动。

## 34. 奖杯/成就入口移入侧栏

- 页头不再放奖杯行；
- 奖杯按钮移入右侧“牌局记录”标题行；
- 筹码图例放在标题行下方，同样不占桌面高度；
- 成就面板标题简化为“成就”；
- 1440×900 无页面滚动。

## 35. 筹码选择只刷新下注托盘

- 点击/移除筹码不再调用整页 `render()`；
- 只调用 `renderTray()` 更新：
  - 已选额度；
  - 可用面额；
  - 下注按钮状态；
  - 预设按钮状态；
- 座位、公共牌、底池不因选筹码而重绘；
- 实测连续选 5 次筹码，`#seats` MutationObserver 计数为 0。

## 36. 初始筹码分配优化

- 全桌总筹码先归一化为“每人筹码 × 人数”，且每人筹码为 10 的倍数；
- 不再把余数塞给 1 号位，所有玩家起始筹码完全相等；
- 设置页显示：
  - 每人起始筹码；
  - 实际全桌筹码；
  - 输入被取整时的提示；
- 筹码拆解优先保留小面额：
  - 100 → 50 + 20×2 + 10；
  - 1000 → 500 + 200×2 + 50 + 20×2 + 10；
- 避免出现“只有一张 100 筹码、无法下 20 盲注”的情况；
- 输入框步长改为 10。

## 37. 初始筹码按面额循环均衡分配

- `chipBreakdown` 不再优先用大额筹码，而是按：
  ```text
  10 → 20 → 50 → 100 → 200 → 500 → 1000
  ```
  循环发牌式分配；
- 每种面额的数量尽量接近，大额筹码不会一口吞掉整份起始筹码；
- 例如 1000 筹码：
  ```text
  10×4 + 20×3 + 50×2 + 100 + 200 + 500
  ```
- 850 筹码：
  ```text
  10×4 + 20×3 + 50×3 + 100×2 + 200×2
  ```
- 小面额始终有库存，能正常下盲注和凑出精确下注；
- 每人起始筹码仍然完全相等。

## 38. 修正 AI 弃牌率过高

根因：

- 旧逻辑用“绝对胜率”对比固定弃牌线；
- 6–10 人桌中 raw equity 天然接近 `1/人数`，导致大多数手牌都被判为弱牌。

修正：

- 用 `relative equity = equity × (有效对手数 + 1)` 衡量相对牌力；
- 只有“相对牌力低 + 不满足底池赔率”时才弃牌；
- 提高加注阈值改为相对胜率阈值，多人底池强牌也能加注；
- 保留四种难度差异：
  - 简单更松、更容易跟注；
  - 地狱更紧、计算更多。
- 6 人桌自动牌局实测 12 秒：弃牌 3 次、跟注 6 次、加注 2 次、过牌 3 次，无 JS 错误。

## 39. 牌桌座位布局去重叠

- 座位中心被限制在桌内，避免底部座位压到操作区；
- 英雄座位单独固定到桌底内侧，并与公共牌区动态保持间距；
- 小屏/矮窗口下左右座位若与公共牌相交，会自动顺到公共牌下方；
- 公共阶段的 `PREFLOP / FLOP / TURN / RIVER` 移入底池行，不再占用公共牌下方空间；
- 移除座位外侧的下注金额气泡和下注筹码，改为在座位 meta 行显示“· 注 X”；
- 座位 meta 固定高度，避免有下注时座位突然变高；
- 实测桌面 1666×824、移动端 390×844 均无座位/公共牌/桌面边界重叠，且无页面滚动。

## 40. 牌桌布局算法修复

- 新增 `resolveSeatLayout()` 碰撞消解器：
  - 桌面边界约束；
  - 公共牌/底池安全区约束；
  - 座位之间的最小间距；
  - 迭代后再次做边界收敛；
- 英雄座位与公共牌底部动态保持间距；
- 8/10 人桌对座位做缩放，避免横向溢出；
- 移除座位外侧下注气泡，下注信息并入座位 meta；
- 公共阶段文字移入底池行；
- 最终额外 `clampSeatsToTable()`，防止最后一次互相推挤把座位挤出桌外。
- 修复后 6 人桌实测无座位/公共牌/底池/桌面边界重叠。

## 41. 玩家座位改为上下两排

- 不再使用椭圆环 + 碰撞推挤；
- 改为确定性的上下两排槽位：
  - 上排：AI 玩家；
  - 下排：其余 AI + 英雄座位；
  - 每排根据人数平均分布；
- 每位玩家都保留 24px 左右/上下边距，不再贴边；
- 按人数和可用高度自动缩放座位；
- 底排额外上移，留出桌底边距；
- 6 人桌实测所有 6 位玩家全部可见，无座位/公共牌/桌面重叠。

## 42. 座位放大、隐藏常驻筹码、悬停查看

- 座位基准尺寸从 146px 放大到 170px；
- 字体、筹码数、牌面同步放大；
- 每排按可用宽度缩放，桌面分辨率下视觉尺寸接近；
- 不再在座位内常驻渲染每种面额的筹码；
- 鼠标悬停座位时弹出浮动窗口，显示：
  - 玩家名；
  - 总筹码；
  - 每种面额数量和价值；
- 浮动窗口固定在视口内，不会出现页面滚动；
- 6 人桌桌面/移动端均可见全部 6 名玩家。

## 43. 修复进入游戏后座位突然变小

根因：

- 开局首帧读取牌桌 `clientHeight` 时，页面布局尚未完全稳定；
- 首帧量到更大的高度，座位缩放系数为 0.96；
- 后续 AI 行动触发重绘，量到稳定高度，缩放降到约 0.88，座位突然变小。

修复：

- 使用稳定的牌桌外框尺寸计算可用宽高；
- `startGame` 后追加一次 `requestAnimationFrame(render)`，在布局稳定后重新落位；
- 座位基准宽度提升到 190px；
- 桌面端座位稳定在约 166px 宽，不再先大后小；
- 悬停筹码浮动窗口保留。

## 44. 采用更大的稳定座位尺寸

- 用户偏好首帧较大的座位版本；
- 将稳定布局调整为：
  - 座位基准宽度 190px；
  - 桌面上稳定缩放约 0.96；
  - 实际座位宽度约 182px；
- 缩小布局边距并取消底排额外上移，给大座位腾出空间；
- 桌面实测座位稳定 182px 宽，不随 AI 行动变化；
- 悬停筹码浮窗和上下两排布局保持不变，无重叠。

## 45. 固定设计宽度，避免宽屏座位间距变大

现象原因：

- 座位有最大尺寸（约 182px）；
- 但每排座位按牌桌完整宽度平均分布；
- 浏览器窗口越宽，牌桌越宽，座位本身不放大，间距却被拉大；
- 因此在宽屏上会感觉每个座位周围空白比 1666px 截图更大。

修复：

- 页面最大宽度固定为 1666px；
- 超过该宽度时整页居中，不再无限拉伸；
- 座位仍在固定宽度牌桌内按原间距分布；
- 初始大尺寸和悬停筹码窗口保持不变。

## 46. 前端看不到更新的原因与修复

- 代码本身已推送，`/p/holdem/` 服务端已包含新样式；
- 但根工作台通过固定 `src` 的 iframe 复用旧页面；
- 已在以下入口加 `?v=Date.now()`：
  - 根工作台模块 iframe；
  - GitHub Pages 11 个模块壳；
  - 页面入口 wrapper；
- HTML 响应改为 `Cache-Control: no-store, no-cache, must-revalidate`；
- 需要完整刷新一次顶层工作台或直接打开带时间戳的模块 URL。

## 47. 跑道形牌桌 + 底池移到公共牌左侧

- 牌桌从椭圆改为跑道形（圆角胶囊）；
- 公共牌区域改为左右两栏：
  - 左侧：底池说明、底池筹码、阶段；
  - 右侧：公共牌；
- 底池信息不再占用公共牌上方高度，公共牌区域高度由约 195px 降到约 102px；
- 座位缩放获得更多垂直空间；
- 跑道形桌面按圆弧计算左右安全边距，座位不再压到圆角外；
- 移动端使用圆角矩形，避免窄屏胶囊形导致座位无法容纳。

## 48. 取消玩家手牌卡片的固定缩小

- 玩家座位手牌不再使用 `.card.small`；
- 与公共牌统一尺寸：
  - 桌面 38×54；
  - 不再受旧的 `28×40` / `22×32` 媒体规则限制；
- 桌面座位不再强制缩放到小于 1.0；
- 6 人桌桌面座位宽约 190px，手牌约 38×54，字号可辨；
- 底池移到公共牌左侧、跑道形桌面与悬停筹码窗口保持不变。

## 49. 8 人以上启用牌桌两端座位

- 8 人及以上、牌桌宽度足够时，左右两端各坐 1 人；
- 其余玩家分布到上下两排；
- 8 人：上 3、下 3、两端 2；
- 10 人：上 4、下 4、两端 2；
- 两端座位按跑道圆弧计算安全位置，不压圆角、不压公共牌；
- 窄屏移动端仍使用上下两排，避免两端座位挤在胶囊端部；
- 10 人桌实测 10 个座位全部可见且无重叠。

## 50. 底池筹码按面额分类 + 悬停明细

- 收拢后的底池筹码按面额分成独立筹码堆；
- 每种面额最多渲染 5 个筹码，超过 5 个显示 `5+`；
- 底池筹码堆支持鼠标悬停，浮动窗口显示每种面额的真实数量和金额；
- 浮动窗口复用座位筹码提示的定位逻辑，自动避开视口边缘；
- 实测底池 100：50×1、20×1、10×3，悬停显示正确。

## 51. 底池筹码悬停改为底池数字

- 悬停触发点从收拢筹码堆改为底池数字 `#pot`；
- 浮动窗口显示当前底池总额（含本轮下注）的面额分布；
- 收拢筹码堆不再拦截鼠标悬停；
- 底池数字带 `cursor:help`。

## 52. 牌面统一渲染

- 所有牌使用统一牌面尺寸与字号：
  - 桌面 38×54；
  - 字号统一 18px，不再给 A/J/Q/K 单独放大字号；
  - 花色统一 13px；
- 牌背景改为奶油纸张渐变 + 细纹理；
- 增加内外双线装饰边框；
- A/J/Q/K 只通过右上角小装饰区分：
  - A ✦、K ♚、Q ♛、J ♞；
  - 不改变字号、边框和底色；
- 公共牌与玩家手牌使用同一套牌面样式。

## 53. 操作按钮并入筹码行 + 一键跟注

- 弃牌、过牌、一键跟注、下注并入下注面板标题行，不再单独占一行；
- 新增“一键跟注”：
  - 自动从当前筹码中挑出正好等于跟注额的筹码；
  - 无法精确凑出时禁用；
  - 仍然不支持找零；
- 操作区高度下降，牌桌获得更多空间；
- 桌面 1440×900 无页面滚动，一键跟注实测成功。

## 54. 底部两栏、取消牌面点击、记牌器

- 底部操作区改成两栏：
  - 左栏玩家信息左对齐；
  - 右栏操作按钮/提示右对齐；
  - 筹码托盘占下一行全宽，整体高度下降。
- 牌面取消可点击特征：
  - `cursor:default`、`pointer-events:none`、无 hover/active 变换。
- 开局设置新增“禁用记牌器”复选框，默认勾选。
- 未勾选时，右侧牌局记录下方显示 3×3 记牌器：
  - 9 种牌型；
  - 显示当前手牌+公共牌继续发完后，最终成为各牌型的概率；
  - 高亮当前已组成的最大牌型；
  - 概率枚举剩余转牌/河牌组合；
  - 只使用自己的手牌和公共牌，不读取 AI 手牌。
- 实测 1440×900 无页面滚动，记牌器 9 格概率合计 100%。

## 55. 手牌与筹码分列

- 底栏第一行：
  - 左侧：玩家名、手牌；
  - 右侧：筹码、本轮下注、状态；
- 手牌与筹码不再同处左侧；
- 操作按钮、已选额度、提示放在下方操作行；
- 筹码托盘与操作行同区域，玩家行动时展开；
- 底栏高度约 147px，页面仍无滚动。

## 56. 手牌与筹码同一行

- `hero-row` 强制 `flex-wrap:nowrap`；
- 左侧手牌组与右侧筹码组设置同一固定行高（54px），顶部/底部对齐；
- 手牌在左、筹码/下注/状态在右，同一行展示；
- 操作按钮和筹码托盘放在下一行，保持动作与下注信息的逻辑关系；
- 实测 1440×900 手牌组与筹码组 top/bottom 完全一致。

## 57. 手牌和筹码托盘同一行

- 底栏第一行：
  - 左：玩家名 + 手牌；
  - 右：可选筹码托盘；
- 底栏第二行：
  - 左：筹码/本轮下注/状态；
  - 右：弃牌、一键跟注、下注、提示、预设；
- 手牌与筹码托盘同一行且 top/bottom 对齐；
- 筹码信息和动作按钮同一行，保持“下注动作对应筹码信息”的逻辑。
