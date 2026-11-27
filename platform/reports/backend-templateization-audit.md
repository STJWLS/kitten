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
