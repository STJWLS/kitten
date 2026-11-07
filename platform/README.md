# KittenPuppy4Ever · 平台内核 v2（数据引擎）

树状项目库 + 抽象项目 + 无损迁移的数据引擎。**不影响线上 8767**，新引擎跑 **8772**。
三个既有标签（课程看板 / 猫猫许愿池 / MS 面试 Mock）已全部接入；旧页面零改动托管。

## 运行

```bat
C:\ProgramData\anaconda3\python.exe -u platform\run.py --port 8772
```

打开 http://127.0.0.1:8772/ （dev 模式：未登录自动以 puppy 进入，便于本地验证）。

```bat
:: 无损迁移 + 往返校验（源文件只读，自动备份）
python platform\tools\migrate.py
:: 33 项验收：树/无损/旧协议/新协议/旧页面/缓存/鉴权
python platform\tools\smoke_test.py
:: 性能对照（只读 8767，写基准只打新引擎）
python platform\tools\bench.py
:: 严格鉴权实例 + 校验
python platform\run.py --port 8774 --no-dev
python platform\tools\auth_check.py --base http://127.0.0.1:8774
```

## 结构

```
platform/
├─ kernel/        引擎（engine / project / registry / compat / auth / server / services）
├─ bases/         manifest 继承链：abstract ← json-doc ← coin
├─ projects/      schedule · map · wishpool · mock · scratchpad
├─ static/        根壳 index.html + sdk.js + project.css
├─ data/          <project>/doc.json + audit.jsonl（运行时数据，不进版本库）
├─ tools/         migrate / smoke_test / bench / auth_check / init_users / seed_demo
└─ run.py
```

## 页面

- 根壳 `/`：项目树 + 统一页头（标题/base/能力/ACL）+ 协议状态栏。
- `/legacy/...`：旧页面托管（`?v=mtime` 资源版本、`?embed=1` 去壳、内核会话桥）。
- `/p/<id>/`：新模板原生视图；`?auto` 项目由内核生成通用视图。

## 统一协议 kp/1

| 端点 | 说明 |
| --- | --- |
| `GET /api/tree` | 项目树 |
| `GET /api/p/<id>/state` | 读状态（rev、ETag/304、gzip） |
| `POST /api/p/<id>/action` | 写动作（payload + rev，冲突 409） |
| `GET /api/state` · `POST /api/save` | 旧协议兼容（store.json 语义，含保护合并） |
| `GET /api/metrics` | 引擎指标 |
| `/mock/api/*` | 反代 127.0.0.1:8768 |

错误码：`bad_request / not_found / unauthorized / forbidden / conflict / unsupported_action / unsupported_project / internal`。

## 新增一个标签页

1. 建目录 `projects/my-tab/`，写 `project.json`（id/parent/title/icon/base/capabilities/view/path）；可见模块 `path` 必填；
2. 需要业务规则 → 加 `project.py`：`Project = <正确基类子类>`，覆盖 `merge` / `on_action`；
3. 需要自定义界面 → `view.kind = "custom"` + `web/index.html`，使用 `/static/template.css`、`main.page > section.section` 模板骨架，不写页头/登录/全局 `<h1>`；`ui.template` 指向 `static/template-tree.json` 的路径（普通页面 `#module`，游戏页面 `#module.game`）；
4. 新增/修改页面模板 → 改 `static/template-tree.json`，运行 `python tools/check_templates.py`；
5. 生成 GitHub Pages 路径壳：`python tools/sync_pages_shells.py`；
6. 格式门禁：`python tools/check_modules.py`，ERROR 必须为 0（含 `E_PATH_MISSING`、`E_PAGES_SHELL_MISSING`）；
7. 部署后做刷新 E2E：GitHub Pages 子页面 200，刷新后 URL 不变且内容仍在。

纯 CRUD 标签页也必须有 `path` 与 Pages 壳；内核自动给 `/p/<id>/` 通用视图与 set/append/remove/reset 动作。

## 设计文档

- 迁移与无损证明、性能数据、切流步骤：`DESIGN.md`
- 旧版模块化评估（为什么这么改）见同文件历史章节

## 生产部署（2026-10-30 已切流）

- 公网入口：https://stjwls.github.io/kitten/KittenPuppy4Ever/
  - Pages 上的 `index.html` 只做一件事：读 `entry.json` → `location.replace` 到当前隧道（不再 iframe 套 iframe）
  - 隧道由内核守护更新，页面每次走"根壳 → 登录 → 项目树"
- 本机守护：`platform/tools/kp_guard.py`
  - 保活 8772 引擎（Mock 在引擎进程内，不再有 8768）与 cloudflared 隧道，并在隧道换地址时更新 GitHub 的 `entry.json`
  - 计划任务 `KittenPuppy4Ever-Platform`（登录时 + 每 5 分钟）跑 `tools/run_ensure_platform.vbs`
  - 日志：`data/_migration/guard.log`、`engine.log`、`mock.log`
- 鉴权：`config/platform.json` 的 `dev_mode=false`；登录走 `/api/login`，口令是 `config/users.json` 里的 PBKDF2 哈希；会话是 HttpOnly cookie（7 天）
- 旧栈状态：`tunnel_supervisor.py` / `public_dash.py` / `local_store.py` / `mock_web.py` 均已停用，
  `KittenPuppy4Ever-Backend`、`KittenPuppy4Ever-Ensure` 两个计划任务已禁用；8765 消融看板隧道不受影响
- 回滚（恢复到旧栈）：
  1. 结束 `kp_guard.py` 与 `cloudflared --url 8772`、`run.py --port 8772`
  2. `Enable-ScheduledTask KittenPuppy4Ever-Backend`、`KittenPuppy4Ever-Ensure`
  3. 运行 `localdata\run_start_all.vbs`，旧 `public_dash.py` 会重新拉起 8767 隧道并更新 `entry.json`

## 前端与 URL（第二版 · 2026-10-30）

URL 结构与旧版一致，**地址栏保持 github.io**：
GitHub Pages 的每个路径是一层全屏 iframe 承载页，隧道里的工作台用 postMessage 把
内部路径同步给父页（replaceState），所以地址栏始终是
`https://stjwls.github.io/kitten/KittenPuppy4Ever/...`，不会变成 cloudflare 域名。
服务端 CSP 只放行本站与 `https://stjwls.github.io` 作为 frame-ancestor。路径：

| 路径 | 页面 |
| --- | --- |
| `/` | 工作台（登录 → 看板卡片） |
| `/dashboard/` | 课程看板 |
| `/dashboard/map/` | 地点地图 |
| `/wishpool/` | 猫猫许愿池 |
| `/mock/` | MS 面试 Mock |
| `/bottle/` | 时光漂流瓶 |
| `/courtyard/` | 造院（中式院落小游戏） |

- 前端只呈现"工作台 + 看板"：首页是卡片，点进去是看板页（统一页头 + 内容），**不显示项目树**；
- `puppy`（维护者）登录后左下角多一个「🐶 调试」：可展开后端项目树与引擎指标（缓存命中/写放大/304），
  kitten 完全看不到；
- 树结构仍只存在于后端（`/api/tree`、manifest 的 `parent/path/order`），前端只用来生成卡片与路由；
- 动效：卡片错峰入场、悬停抬升/图标回弹、视图切换淡入、iframe 渐显、登录失败抖动、`prefers-reduced-motion` 自动降级。

## 安全（本次一并处理）

- 明文口令已从 `emf-schedule/assets/auth.js` 删除；登录只走服务器 `/api/login`（PBKDF2 哈希 + HttpOnly cookie）；
- 公开仓库清理：删除 `KittenPuppy4Ever/{dashboard,wishpool,mock}` 下 12 个旧静态文件，
  只保留 4 个"路径跳转壳"；已扫描仓库确认无口令字符串；旧资源路径现在 404；
- 登录失败节流：同 IP 5 次/5 分钟 → 429；会话 cookie HttpOnly + SameSite=Lax；
- 响应头：`X-Content-Type-Options`、`Referrer-Policy`、`X-Frame-Options: SAMEORIGIN`、`Permissions-Policy`；
- 测试工具不再需要明文口令：`tools/_session.py` 用本机会话密钥签发测试 cookie。

## 登录排障 / 改口令

- 口令只以 PBKDF2 哈希存在 `config/users.json`，服务器和仓库都不存明文；
- 连续输错会触发节流：同一真实 IP 10 次失败 / 10 分钟 → 429。经隧道访问时按
  `CF-Connecting-IP` 区分用户（本机直连测试单独计桶），不会"一人输错、全家被锁"；
- 改口令（只写哈希，不回显）：
  ```
  python platform/tools/set_password.py kitten
  python platform/tools/set_password.py puppy
  ```
  改完等守护自动重启引擎（约 20 秒）即可用新口令登录；
- 若"输入正确仍报错"：先强制刷新（Ctrl+F5）排除旧页面缓存，再确认角色选择和口令对应，
  最后看是否被节流（提示会写"失败次数过多，请 10 分钟后再试"）。
