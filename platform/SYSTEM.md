# KittenPuppy4Ever · 系统工程说明

版本：2026-11-27
入口：`platform/`，协议 `kp/1`

## 1. 系统目标

把工作台做成“可新增 module 而不改内核”的模板化系统：

```text
声明层    project.json
继承层    bases/*.json + kernel/bases/*.py
协议层    state / action / rev / audit / ACL
接线层    api.py / view / template tree / sdk.js
边界层    data 声明
门禁层    check_modules / check_templates / check_contracts / check_system
```

## 2. 目录职责

```text
platform/
├─ kernel/          registry / project / module_api / server / engine / auth
├─ bases/           abstract / json-doc / coin / keyed / keyed-coin
├─ projects/        11 个 module（含隐藏 holdem）
│  └─ <id>/
│     ├─ project.json
│     ├─ project.py       可选：Project 子类
│     ├─ api.py           可选：module-local HTTP API
│     └─ web/             可选：custom view
├─ static/          根壳、sdk.js、template.css、template-tree.json、auto-view.html
├─ tools/           check_modules / check_templates / check_contracts / check_system
├─ SYSTEM.md
└─ reports/
```

## 3. 继承关系

### manifest

```text
abstract ← json-doc ← coin
                    ↖ keyed
coin ← keyed-coin
```

### Python

```text
AbstractProject
├── JsonDocProject
│   ├── KeyedJsonDocProject
│   └── CoinProject
│       └── KeyedCoinProject
```

新增 base 必须同时：

1. 新增 `bases/<name>.json`；
2. 在 `kernel/registry.py` 的 `BASES` 注册；
3. 在 `tools/check_modules.py` 的类层级/注册表同步；
4. 在 `MODULE_SPEC.md` 登记。

## 4. 页面模板树

`static/template-tree.json`：

```text
#module
└── #game → #module.game
```

`ui.template` 指向模板路径；`_inject_shell` 注入模板 id 和 `template-tree.js`。

## 5. API 归属

### kp/1

```text
GET  /api/p/<id>/state
POST /api/p/<id>/action
```

### module-local

`projects/<id>/api.py`：

```python
PREFIXES = ["/api/example/"]
def handle(handler, method, path, parsed): ...
```

Registry 自动加载，server 先匹配 module API。

当前归属：

```text
ai              /api/ai/ /api/llm/ /api/files
map             /api/map/
mock            /mock/api/
schedule        /api/schedule/*
schedule-debug  /api/schedule/admin/*
wishpool        /api/wishpool/*
```

## 6. 数据边界

manifest 的 `data.kind`：

```text
project       项目 doc
service       专用服务/store
static        静态投影
tree          只读模块树
client        localStorage / 客户端状态
legacy-store  旧 store 兼容
proxy         反代
```

不声明 `data` 不会阻止运行，但会在系统门禁中提示。

## 7. 视图与 SDK

- auto：`static/auto-view.html` + `KittenProjectView`
- custom：`/static/template.css` + 可选 `KittenProjectView` / `KpSdk`
- 所有 module 页面自动注入 `sdk.js`
- `KpSdk` 提供 `request / getJSON / postJSON`，自动带 token

## 8. 门禁

在 `platform/` 下运行：

```bash
python tools/check_system.py
```

等价组合：

```bash
python tools/check_modules.py
python tools/check_templates.py
python tools/check_contracts.py
```

系统门禁额外检查：

- module-local API 前缀不冲突；
- 已迁移路由不再出现在 `kernel/server.py`；
- data.kind 合法；
- `SYSTEM.md` 存在；
- 11 个 module 契约可实例化。

## 9. 系统自描述

认证后：

```text
GET /api/system
```

返回：

- protocol / engine；
- modules（id/title/base/view/template/data/capabilities）；
- module API 归属；
- template tree；
- registry errors。

## 10. 当前状态

```text
11 modules
5 bases
2 page templates
6 module-local API owners
check_modules       11 PASS / 0 FAIL / 0 WARN
check_contracts     11/11
```

## 11. 新增 module 清单

1. `projects/<id>/project.json`
2. 选择 base（默认 json-doc；列表项目 keyed）
3. 需要业务规则 → `project.py`
4. 需要专用接口 → `api.py`
5. 页面 → `web/index.html` 或 `view.kind=auto`
6. 声明 `path`、`ui.template`、`data`
7. 更新 Pages 壳
8. 运行 `python tools/check_system.py`
