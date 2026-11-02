# KittenPuppy4Ever 平台内核 v2 · 数据引擎与无损迁移

> 位置：`D:\KittenPuppy4Ever\platform`（跑在 **8772**，线上 8767 未动）
> 迁移源（只读）：`localdata/store.json`、`emf-schedule/`、`MockInterview/`（后端 8768）
> 验收：迁移往返**全等**；协议冒烟 **33/33**；严格鉴权 **6/6**；性能见第 5 节

---

## 0. 现在是什么状态

三个既有标签已经全部接入新内核，旧页面一行没改地跑在新引擎上：

| 树节点 | 视图 | 数据 |
| --- | --- | --- |
| `schedule` 课程看板 | `/p/schedule/`（模板原生视图） | schedule 分片文档 |
| `map` 地点地图（schedule 子节点） | `/p/map/`（模板原生视图） | 同上（只读 schedule.json） |
| `wishpool` 猫猫许愿池 | `/p/wishpool/`（模板原生视图） | wishpool 分片文档 |
| `mock` MS 面试 Mock | `/legacy/mock/` | 会话数据留在 8768 后端，`/mock/api/*` 由内核反代 |
| `scratchpad` 临时便签 | `/p/scratchpad/`（模板原生视图） | 独立项目文档 |

根壳只做四件事：身份、项目树、主题、`/api/p/<id>` 路由。业务数据全部下沉到项目分片。

---

## 1. 引擎结构

```
platform/
├─ kernel/
│  ├─ engine.py      数据引擎：分片文档 + 内存缓存 + 原子写 + 版本 + 指标 + 审计(jsonl)
│  ├─ project.py     抽象项目：AbstractProject / JsonDocProject（rev、乐观并发、ACL、审计）
│  ├─ bases/coin.py  中间基类：硬币账本
│  ├─ registry.py    manifest 继承链 + 项目树
│  ├─ compat.py      旧协议兼容层（store.json 语义：t 单调、保护合并、愿望并集）
│  ├─ auth.py        PBKDF2 口令 + HMAC 会话 cookie
│  ├─ server.py      HTTP/1.1（keep-alive）、gzip、ETag/304、旧页托管、反代、指标
│  └─ services/      mail.py（SMTP）、reminders.py（课程/愿望提醒，20s 轮询）
├─ bases/            abstract ← json-doc ← coin 的 manifest 继承链
├─ projects/         schedule / map / wishpool / mock / scratchpad
├─ static/           根壳 index.html + sdk.js + project.css
├─ data/             <project>/doc.json（数据）+ audit.jsonl（审计）
├─ tools/            migrate.py（无损迁移）/ smoke_test.py / bench.py / auth_check.py
└─ run.py            python platform/run.py --port 8772 [--no-dev]
```

请求路径：

```
浏览器 ── /                     根壳（树 + 项目页头 + 内容区 iframe）
        ├─ /legacy/<path>       旧页面（注入 ?v=mtime 资源版本、?embed=1 去壳、会话桥）
        ├─ /p/<id>/             新模板原生视图（auto 视图由内核生成）
        ├─ /api/p/<id>/state    统一读（ETag/304 + gzip）
        ├─ /api/p/<id>/action   统一写（rev 乐观并发、ACL、审计）
        ├─ /api/state /api/save 旧协议兼容（三个页面的现有同步代码不用改）
        ├─ /mock/api/*          反代 127.0.0.1:8768
        └─ /api/tree /session /login /metrics
```

---

## 2. 无损迁移（怎么证明"不损失任何信息"）

字段级映射，原样搬运，不做任何形状改写：

| store.json | 去向 |
| --- | --- |
| `events` / `venues` | `schedule` 文档（events / venues） |
| `reminders_sent` | `schedule` 文档（提醒去重记录） |
| `wishes` / `coins` | `wishpool` 文档 |
| `wish_notified` | `wishpool` 文档（审批通知去重） |
| `t` | `meta` 文档 |
| 未知顶层字段 | `meta.extras`（逐字段保留，当前为无） |

校验链（`python platform/tools/migrate.py`）：

1. 源文件只读，先备份到 `data/_migration/backup/store-<ts>.json`；
2. 写入三份分片文档后，从引擎**重建**一份 store；
3. 与原件做 `json.dumps(sort_keys=True)` 全等比较；
4. 统计每个字段条数/键数、写报告（含源文件与 schedule.json / mail_config.json 的 sha256）。

实测结果（2026-10-30）：

```
OK events 0 · OK venues 0 · OK wishes 2 · OK coinLog 265
OK reminders_sent 153 · OK wish_notified 14 · OK t 1793296113738
未知顶层字段：无
往返全等：是（无损）
```

旧引擎的"防丢数据"语义也一起搬进了兼容层，没有因为换引擎而退化：

- `t` 单调：旧快照（`t` 更小）的写入被拒（`stale`）；
- 新浏览器/空缓存推送空数据 → 不覆盖服务端日程/地点/余额（`protected`）；
- 愿望只增不删：按 id 求并集，同一 id 取流程日志更新的一份；
- "刚开户"余额（只有 grant/interest）不覆盖有经济行为的余额。

这些规则在旧实现里散落在 `local_store.py` 与 `venues.js` 两处，现在集中在内核 `compat.py` 一处，并有测试覆盖。

---

## 3. 旧页面怎么接进来（页面模板统一，但功能不重写）

页面模板策略：**根壳统一 chrome，内容区按项目类型渲染**。

- 统一部分（每个项目完全一致）：左侧项目树、顶部项目页头（标题/描述/base/能力/ACL 徽章/新窗口打开）、底部协议状态栏、cream+蓝主题。
- 内容区两种渲染器：
  - `legacy`：旧页面原样托管，注入三样东西——
    1. `?v=mtime` 资源版本号（改完即刷 + 长缓存）；
    2. `?embed=1` 去壳 CSS（隐藏旧页自己的 header，标题/身份由根壳提供）；
    3. **会话桥**：把内核 cookie 会话写进旧页认的 `localStorage`（`emf_login_v1` 等），所以"根登录一次，子页面都认得你"，不会再各自弹登录。
  - `native`：新模板 + `sdk.js`（`KittenProjectView`），`scratchpad` 即此形态。

这样三个既有标签**功能零损失**（课表网格、个人日程、地点地图、许愿币经济、审批、Mock 录音/ASR 都还在），同时共享同一套壳与协议；等以后重写某个页面，只需把 `view.kind` 从 `legacy` 换成 `custom`。

---

## 4. 统一协议 `kp/1`

```json
{ "ok": true,  "protocol": "kp/1", "project": "...", "rev": 3, "data": { ... } }
{ "ok": false, "protocol": "kp/1", "error": { "code": "conflict", "message": "..." } }
```

| 端点 | 语义 |
| --- | --- |
| `GET /api/tree` | 项目树（id/parent/title/base/view/capabilities/children） |
| `GET /api/p/<id>` | manifest + 当前 rev |
| `GET /api/p/<id>/state` | `{rev, data}`；ETag/304、gzip |
| `POST /api/p/<id>/action` | `{action, payload, rev}`；过期 rev → `409` |
| `GET/POST /api/state` `/api/save` | 旧协议兼容（见第 2 节） |
| `GET /api/metrics` | 引擎指标：缓存命中率、读写字节、304 次数 |

错误码白名单：`bad_request / not_found / unauthorized / forbidden / conflict / unsupported_action / unsupported_project / internal`；每个写动作落一条审计到 `data/<id>/audit.jsonl`（独立文件，不膨胀 doc）。

---

## 5. 性能（`python platform/tools/bench.py`，2026-10-30）

| 场景 | p50 | p95 | mean | 响应字节 | 吞吐 |
| --- | --- | --- | --- | --- | --- |
| 新引擎 `GET /api/state`（兼容层） | **1.65 ms** | 1.88 ms | 1.84 ms | 25 099 | 543 /s |
| 旧引擎 `GET /api/state`（实时 8767） | 14.96 ms | 15.75 ms | 14.42 ms | 25 099 | 69 /s |
| 新引擎 `GET /api/p/schedule/state` | **0.77 ms** | 0.85 ms | 0.86 ms | 3 643 | 1 165 /s |
| 新引擎 `GET /api/p/wishpool/state` | 1.45 ms | 1.63 ms | 1.61 ms | 22 652 | 621 /s |
| 新引擎 `GET /api/state` + gzip | 2.18 ms | 2.39 ms | 2.20 ms | **2 730** | 454 /s |
| 新引擎条件请求（304） | 1.56 ms | 1.83 ms | 1.60 ms | **0** | 626 /s |
| 新引擎并发 8×40 `GET /api/state` | 9.49 ms | 15.04 ms | 9.82 ms | 25 099 | **787 /s** |
| 旧引擎并发 8×40 | 22.76 ms | 34.75 ms | 24.75 ms | 25 099 | 238 /s |
| 新引擎 `POST /api/save` | 7.28 ms | 8.78 ms | 7.45 ms | **67 B 落盘** | 134 /s |

**写放大**：旧引擎每次保存整份 `store.json` 重写（34 048 B）；新引擎只写变化的分片——只有 `t` 变化时写 **meta 67 B**，改日程写 schedule 3 535 B，改愿望/余额才写 wishpool 30 544 B。

性能来自四件事：HTTP/1.1 keep-alive（省 TCP 建连）、内存缓存（mtime 失效，不重复解析 JSON）、分片写（写放大降 3 个数量级）、gzip + ETag/304（隧道流量降 9 倍 / 轮询可到 0 字节）。

---

## 6. 验收

```
python platform/run.py --port 8772          # 新引擎
python platform/tools/migrate.py            # 无损迁移 + 往返校验
python platform/tools/smoke_test.py         # 33 项：树/无损/兼容/协议/旧页/缓存/鉴权
python platform/tools/bench.py              # 性能对照（只读 8767）
python platform/run.py --port 8774 --no-dev # 严格鉴权实例
python platform/tools/auth_check.py --base http://127.0.0.1:8774   # 6 项
```

截图：`kp-v2-schedule.png` / `kp-v2-wishpool.png` / `kp-v2-mock.png`（统一 chrome + 各自业务内容）。

---

## 7. 切流（2026-10-30 已完成）

实际执行顺序：

1. 备份在迁移时已生成：`data/_migration/backup/store-*.json`；
2. 新引擎验收：`verify_prod.py` 11/11（匿名被挡 / 登录 / 旧页面会话桥）、`smoke_test.py` 34/34；
3. 停旧栈：结束 `tunnel_supervisor.py`、`public_dash.py`、`local_store.py`、`cloudflared --url 8767`，
   禁用计划任务 `KittenPuppy4Ever-Backend` / `KittenPuppy4Ever-Ensure`（否则它们会把 8767 重新拉起）；
4. 起新守护：`platform/tools/kp_guard.py`（引擎 8772 + Mock 8768 + 隧道 + 更新 `entry.json`），
   注册计划任务 `KittenPuppy4Ever-Platform`（登录 + 每 5 分钟保活）；
5. Pages 入口页从 iframe 改成顶层跳转（`tools/publish_entry.py`），
   当前链路：`stjwls.github.io/kitten/KittenPuppy4Ever/` → `entry.json` → 新隧道 → 登录壳；
6. 8765 消融看板隧道与旧 `store.json` 均未受影响。

注意事项：

- **Pages 的 `entry.json` 有 CDN 缓存**（约几分钟到 10 分钟）。隧道地址变化后这段时间内入口页可能仍跳旧地址；
  `entry.json` 与 `index.html` 的缓存窗口不一致时，打开入口页会看到"连接超时/白屏"——等缓存过期或手动刷新即可。
  长期建议：给 Cloudflare 账号建 named tunnel（固定域名）来消除地址漂移。
- 回滚：结束 guard + 8772 相关进程，重新启用上面两个旧任务并运行 `localdata\run_start_all.vbs`，
  旧 `public_dash.py` 会重新拉起 8767 隧道并更新 `entry.json`；新引擎数据在 `platform/data/`，不影响旧 `store.json`。
- 旧静态页已从公开仓库移除（12 个文件，含所有 `assets/` 副本），仅保留 4 个路径跳转壳；
  详见 9.3；若担心历史泄露，仍建议轮换一次口令。

---

## 9. 第二版：旧 URL、看板前端、安全与动效

### 9.1 URL 结构回到旧版

引擎对以下路径统一返回同一个壳（前端按 `location.pathname` 路由），内容仍由 `/legacy/...` 提供：

```
/                    -> 工作台（卡片）
/dashboard/          -> 课程看板
/dashboard/map/      -> 地点地图
/wishpool/           -> 猫猫许愿池
/mock/               -> MS 面试 Mock
```

GitHub Pages 侧为每个路径保留了一层跳转壳（`tools/publish_paths.py`），
所以外部链接仍是旧格式；跳转后地址栏主机变为当前隧道域名，路径不变。

### 9.2 前端：工作台 / 看板，而非项目树

- 首页 = 工作台卡片（来自后端 `/api/tree` 的根节点，`hidden` 的节点不展示）；
- 看板页 = 统一页头（返回工作台 / 标题 / 描述 / 路径 / 子页面数）+ 内容 iframe；
- 项目树只在后端（manifest 的 `parent/order/path`），前端不显示；
- `puppy` 登录后多一个可收起的「调试」侧栏：后端树 + 引擎指标（缓存命中率、读写、304），
  `kitten` 不可见。

### 9.3 安全

- 删除前端明文口令；登录仅服务器校验（PBKDF2 200k + HttpOnly/SameSite=Lax，7 天）；
- 登录节流：同 IP 5 次失败 / 5 分钟 → 429；
- 安全响应头：`X-Content-Type-Options: nosniff`、`Referrer-Policy: same-origin`、
  `X-Frame-Options: SAMEORIGIN`、`Permissions-Policy: microphone=(self), camera=(self)`；
- 公开仓库清理：删除旧静态页 12 个文件（含所有 `assets/` 副本），仅保留路径跳转壳；
  已扫描仓库确认无口令字符串，旧资源路径 404；
- 测试工具改用 `tools/_session.py` 直接签发本机会话，不再依赖明文口令。

### 9.4 动效

卡片错峰入场（60ms 间隔）、悬停抬升 + 图标回弹 + 光斑跟随、视图切换淡入上移、
iframe 渐显、登录失败抖动、调试侧栏滑入；`prefers-reduced-motion` 下全部关闭。

### 9.5 当前状态

- 生产隧道：`capability-evaluate-devon-jack.trycloudflare.com`（守护自动写入 `entry.json`）
- 验收：`verify_prod.py` 15/15（含 4 个旧路径、登录、节流）、`smoke_test.py` 34/34
- 截图：`kp-v3-login.png`、`kp-v3-home.png`、`kp-v3-dashboard.png`、`kp-v3-debug.png`

---

## 8. 已知限制 / 下一步

- 旧页面的登录仍是客户端判断（会话桥把内核身份喂给它）；正式上线前应删除 `auth.js` 里的明文口令，页面只读内核会话。
- Mock 页面已是模板原生视图；其后端以进程内 ASGI 方式挂在引擎里（见第 12 节）。
- 提醒线程与 `/api/save` 并发写同一分片存在极小竞态窗口，后续可加项目级文件锁。
- Mock 会话数据（5.7 MB）留在 8768 后端，不在迁移范围（搬迁无收益且会破坏其现有索引）。
- GitHub Pages 入口保持现状（只做隧道跳转）；如需 Pages 直接托管壳，可把 `/api/tree` 固化发布成 `tree.json`。


## 10. Mock 页面迁移（2026-10-30）

MS Mock 原来是整站式页面（自带大标题、返回链接、页脚、登录门禁、独立 CSS），
嵌进根壳后明显和课表/许愿池不一致。处理方式不是注入皮肤，而是**直接迁移成项目原生视图**：

- 文件：projects/mock/web/index.html（业务 JS 原样搬运，录音/VAD/ASR/TTS/评分/报告逻辑未改）
- 模板：/static/project.css + 页面内组件样式，卡片/按钮/间距/圆角与模板一致；
- 骨架：去掉自带标题、返回工作台、页脚、登录门禁（身份由根壳统一校验），
  面试设置收进一张控制卡片；
- manifest：view: {kind: custom, dir: web}；
- 旧页面 emf-schedule/mock/index.html 保留作回滚，不再被入口使用。


## 11. 统一页面模板 v1（2026-10-30）

规范：`platform/TEMPLATE.md`；共享样式：`platform/static/template.css`。

- 所有项目页面结构统一为 `main.page > section.section > section-head`；
- 页头/返回/身份/项目间导航一律由根壳提供，项目页不再自带；
- 组件语言统一：`.btn`(+primary/soft/danger/ghost/sm)、`.chip`、`.tabs/.tab`、`.stat`、
  `.list/.row`、`.empty`、`.modal`、`.input/.select`；项目专有组件（课表网格、转录气泡、
  许愿币卡、地图容器）保留自己的类，但颜色/圆角/字号引用模板令牌；
- 全部 5 个项目已迁移为 `views: custom`：schedule（含 assets/schedule.css）、map（含 Leaflet 资源）、
  wishpool（含 wishpool.css）、mock、scratchpad；旧 `/legacy/…` 页面保留作回滚，不再被导航使用；
- 项目描述统一改为"只描述内容"：不再出现"旧页面/新引擎/零代码/反代/子节点"等实现或补丁措辞；
- 验收：`verify_prod` 15/15、`smoke_test` 34/34；生产 `/dashboard/`、`/dashboard/map/`、
  `/wishpool/`、`/mock/` 均加载模板原生视图。


## 12. Mock 后端并入引擎（2026-10-30）

原架构：引擎 8772 用 HTTP 反代到常驻的 MockInterview FastAPI（8768），多一个进程、多一个端口，
且 8768 有独立看门狗（run_mock_backend.bat）会自行复活。

现架构：**看板引擎是唯一后端**。

- `kernel/mock_gateway.py`：把 MockInterview 的 FastAPI 应用作为 **进程内 ASGI 应用** 调用，
  不再有 8768、不再有网络回环与代理超时；
- 懒加载：首次 `/mock/api/*` 请求才导入 FastAPI 应用并创建后台事件循环（冷启动约 6 秒），
  之后常驻；启动时不加载，引擎启动速度不变；
- 跳过原应用 startup 的流式 ASR 预热，模型改为按需加载；
- 引擎改用 `D:\KittenLisaWork\MockInterview\.venv\Scripts\python.exe` 运行（依赖在 venv 里），
  `kp_guard.py` 的 `ENGINE_PY` 指向它；
- 8768 看门狗（run_mock_backend.bat）与 mock_web 进程已停止，旧任务保持禁用；
- 验证：`/mock/api/health` 200、`/mock/api/voice/puppy/status` 200、真实 `/mock/api/start` 返回题目与音频；
  生产 `verify_prod` 15/15。


## 13. 造院：逆向后重做的中式小游戏（2026-10-30）

参考站点：https://se-n.com/madori/（「マドリ」：吊车把房间落进 6×6 基地，8 间后结算，
按委托/门/格局生成房产传单）。只逆向其**玩法规则**，未复制任何代码、素材或文案。

中式化设计（原创实现）：

- 主题：四合院 / 宅院营造，宣纸、朱红、墨色、青瓦配色；
- 6×6 宅基地，院门朝南（画面下方），正房宜坐北（画面上方）；
- 吊车沿院墙来回，点按 / 空格落子；构件从北侧落下并向南沉降，叠放成型；
- 8 件构件：正房(3×2)、厢房(2×2)、书房(2×2)、天井(2×1)、门楼(1×1)、厨房、净房、回廊(1×3)、影壁；
  稀有构件：月洞门、戏台、太湖石、水阁（10% 概率）；
- 主家委托 6 种：门楼朝南、天井≥4 格、正房坐北、房间种类≥6、要有稀罕物、要有回廊；
- 验收出具「宅院契」：评分（甲/乙/丙/丁）、天井格数、门第种类、估价、随机宅名、评语；
- 最佳分保存在 localStorage；支持音效开关；`?auto=1` 为 QA 自动落子参数；
- 纯前端实现，不需要新增后端接口；manifest：`projects/courtyard/project.json`，路径 `/courtyard/`。


## 14. 地址栏保持在 GitHub（2026-10-30）

- GitHub Pages 每个路径（`/`、`/dashboard/`、`/dashboard/map/`、`/wishpool/`、`/mock/`、`/courtyard/`）
  都放同一份全屏 iframe 承载页：读 `entry.json`，iframe 当前隧道 + 同路径；
- 工作台检测到自己被 iframe 承载时，用 `postMessage({kpPath})` 通知父页，
  父页 `history.replaceState` 把地址栏保持为 `github.io/kitten/KittenPuppy4Ever/...`；
- 引擎响应头改为 `Content-Security-Policy: frame-ancestors 'self' https://stjwls.github.io`
  （去掉 X-Frame-Options），只允许 GitHub Pages 与本站嵌入；
- iframe 首次跨域加载偶尔慢，承载页会在 6 秒后自动换 URL 重试（最多 3 次）。
- 注意：quick tunnel 冷启动、Cloudflare 边缘抖动仍可能让首次加载慢几秒；
  真正想彻底稳定，建议换成 Cloudflare named tunnel 固定域名。

## 15. 造院核心算法订正（对齐 madori）

第一版把落房做成了"向下坠落"，与参考站不符。按 `house.js` 重写为：

- 6×6 地界，**落点 = 该列已有堆叠的最高点**（`landing = max(y+h)`），所以房子从街面一侧向上长；
- 非方形构件随机旋转（rot 交换 w/h），吊车只沿 x 移动；
- 完成后做图结构分析（对齐 analyze）：
  - owner 网格 + 开敞区泛洪 / 封闭夹缝；
  - 相邻房间自动开门（一对邻房一道门）→ 邻接图；
  - 入口判定：门楼朝街 > 门楼朝院 > 朝街房间借窗；
  - BFS 算入口到各房间距离、不可达房间；
  - 每间房的朝街/朝外面数。
- 8 条主家委托（对齐 REQUESTS）：净房东北、门楼临街、卧室见光、净房邻卧室、动线≤3、
  空地≥6、八间收进地界、净房离正房。
- 评分按：收地界/入口/空地/夹缝/不可达/稀有/委托达成 综合，出宅院契。


## 16. 造院的动画与轴测表现（2026-10-30）

参考站的观感很大程度来自三件事，已按"机制可复刻、素材原创"补上：

- **落子动画**：构件从地界上方缓入到"该列堆叠最高点"，缓出曲线 420ms；落定后再换下一件；
- **完工过场**：8 件落满后主画布切到**轴测视角**（iso 投影，房屋按 x+u 深度排序、画南/东墙 + 屋面 + 正脊），
  标题「宅院落成 · 轴测动线」，约 2.4 秒后进入宅院契；
- **动线动画**：按 analyze 的 BFS 生成树（入口 → 各房间）绘制门图动线。
  - 地面淡虚线作为底稿；
  - 屋顶上方一层亮红**流动虚线**沿动线逐段推进，带发光游标与"入"口标记；
  - 宅院契里嵌 700×360 轴测画布，动线循环播放（可收起/重开）。
- **平面图门窗**：每落一件即重算 analyze 并绘制：
  - 相邻房间自动开门（取共享墙中间一段，画门洞 + 门扇 + 门弧）；
  - 朝街/朝院的每个外墙单元自动开窗（蓝色双线，临街略深）；
  - 入口那面墙画红门洞并标「门」；门数/入口与宅院契「门第」同源。
- QA：`?auto=1&nokine=1` 直接出契（跳过过场），`?auto=1` 看过场。


## 17. 按参考站制图方式重画平面与轴测（2026-10-30）

对照 `render.js` / `iso.js`，放弃"色块 + 假屋顶"的画法，改成建筑制图：

**平面（render.js 的 drawHouse 思路）**
- 房间浅色铺地 + 室内材质线：厢房榻榻米（逐格、方向交替）、正房/书房地板、回廊板缝、天井砂石、水池波纹、门楼斜铺垫；
- 固定家具：正房条案与椅、厨房台面灶眼、净房洁具、书桌；
- 墙为粗黑线（`max(2.6, cell*0.052)`），房间名称白底标签；
- 门：门洞 + 门扇 + 四分之一门弧，`side` 由相邻房间判断、开向房内；
- 窗：墙上开洞 + 三条细线（临街窗另加蓝线）；入口红门并标「门」。

**轴测（iso.js 的 buildScene / drawScene 思路）**
- 不是给房间盖屋顶，而是**平面向上拉起的剖切模型**：地面 → 房间铺地 → 逐单元边拉起墙体；
- 墙体高度按关系取：两间室内 0.55，临街/西侧外墙 0.16（剖切看进室内），后墙 0.95；
- 门在墙上留洞（分两段墙），后墙开内凹窗；夹缝填黑；
- 标签为白底黑框小牌；
- 过场动画：`t: 0 → 1` 把平面连续拉到轴测（标题「合上图纸 · 立起墙体」→「宅院落成 · 轴测动线」），随后动线动画。


## 18. 小人动线与传单输出（2026-10-30）

- **红色小人**：轴测场景里按 BFS 生成树逐段行走（位置由 flow 插值、带步态上下浮动），
  腿/身体/头用轴测投影，画在墙体之后以保持可见；过场与宅院契里循环播放。
- **传单**：宅院契新增「存为传单」，离屏渲染 1200×630 PNG：
  左栏宅名/等第/宣传语/占地/天井/门第/委托/估价/评语，右栏轴测图，右下朱红「宅」印；
  下载文件名 `宅院契_<宅名>.png`。
- 顺带修正 `openYard` 只统计**地界内**的开敞空地（之前把屋顶以上天空也算进去，导致 30+ 格）。


## 19. 路径同步与制图几何修正（2026-10-30）

- **GitHub 子路径丢失**：`goPath()`/`navigate()` 只 `pushState` 没通知父页，地址栏停在根路径。
  现在每次进入项目/隐藏项目都调用 `postPath()`，父页 `replaceState` 到
  `github.io/kitten/KittenPuppy4Ever/<项目路径>`。
- **门窗错位**：`rowTop(i)` 是第 i 行**上边**。修正后：
  - 水平相邻房间的共享墙：`i = y`（之前写 `y+1`，整道门高了一格，落到走廊/房间里）；
  - 南墙：临街用 `road:true` 取路缘，否则 `i = r.y-1`；
  - 北墙：`i = r.y+h-1`。
- **大房间轴测内部被砌墙**：`wallH` 未处理 `a === b`（同一间房的两个单元），现在同一房间内部返回 0，
  只保留四周墙；不同房间之间才是 0.55 内隔墙。
- **门端与墙不对齐**：墙之前用 `gx(x)+2 / w*cell-4` 内缩绘制，而门窗用原始格边，导致门洞比墙偏 2px；
  现在墙体画在真实格边上；门洞改为「两端各留墙头 + 洞口在墙厚范围内切断」：
  - 不画通长门框线（会重新封住洞口）；
  - 铰链固定在洞口一端，门扇长度=洞口宽度；
  - 摆动方向按"房间位于边界哪一侧"判定（水平边界：`r.y > i` 为北侧，临街 `road` 为北侧）；
  - 门洞两端只补与墙厚同长的小门垛。


## 20. 视图 403 与旧版双主题继承（2026-10-30）

- **403 "没有该项目的读权限"**：`/p/<id>/` 页面层用 cookie 鉴权，GitHub iframe 里第三方 cookie
  被拦时页面直接被拒（token 只在 fetch 里带）。现在：
  - 页面本身不再做登录校验（静态内容，无数据）；
  - 数据接口仍鉴权（无会话 401 / 无 ACL 403）；
  - 所有由内核服务的 HTML（壳、原生视图、auto 视图、旧页面）都注入 `kp-auth`，
    把 `localStorage.kp_token` 以 `Authorization: Bearer` 附到 fetch 上。
- **旧版双主题**：`kitten=玫瑰粉`、`puppy=复旦蓝` 的 `--pink/--pink-deep` 覆盖在统一模板里丢了。现在：
  - `template.css` 增加 `body.user-kitten{--pink:#ec9fbe;--pink-deep:#b25e83}`、
    `body.user-puppy{--pink:#8fb3e8;--pink-deep:#2a5fb8;--mint:#8fb3e8}`；
  - 壳在 boot 后按 session user 切 body class；项目 iframe 加载后由壳把 class/accent 写进 contentDocument；
  - 服务端对 HTML 注入 body class，并按 manifest `ui.theme.accent` 注入 `--accent`。


## 21. 稳定性、首屏提速与自定义主题（2026-10-30）

### 为什么"刷新进不去"
1. 浏览器走系统代理 `127.0.0.1:7892`，但代理未放行 `*.trycloudflare.com` / `github.io`，
   而 curl 不走 IE 代理所以正常 → 浏览器 `ERR_CONNECTION_CLOSED`。已在 ProxyOverride 加直连例外。
2. guard 读取隧道 URL 后**不再读 cloudflared stderr**，日志写满 64KB 管道后进程阻塞/退出。
   现改为持续排空 stderr。
3. guard 用 urllib 探测隧道，Windows TLS 偶发 `SSL: UNEXPECTED_EOF`，把活隧道误判成死的并换 URL；
   改为 curl 探测（`--max-time`），并先探测本机引擎，引擎重启时不重启隧道。
4. 新隧道先等边缘可达再写 GitHub entry，减少把死链推给用户的时间窗口。
5. 前端主题按钮的 JS 在 markup 缺失时 `null.onclick` 抛错导致整个 boot 脚本中断；
   已补 markup + null 守卫。

### 首屏提速
- 新增 `GET /api/bootstrap`：一次返回 session + project tree + theme；
  壳首次加载从 3 个 API 往返（bootstrap 失败时才会回退）降到 1 个，登录后 4 个降到 2 个。
- SDK `mount()` 改为只请求 `/api/p/<id>/state`（已含 manifest），少一次往返。
- JSON 仍 gzip；本地 `/api/bootstrap` 约 3ms / 3.3KB。

### 每人自定义主题色
- `data/themes.json` 按用户名存 `{color, deep}`；
- `GET /api/theme` / `POST /api/theme {color}`（#rrggbb，自动算深色）；
- 壳顶栏「🎨 主题」：预设色 + 取色器，保存后即时生效并写回账号；
- 服务端注入 `body,body.user-kitten,body.user-puppy{--pink:...}`，壳把颜色写进项目 iframe；
- 默认值保持旧版 kitten 粉 / puppy 蓝。


## 22. 目录迁移与用户/权限系统（2026-10-30）

### 目录
- 整个 `school/dashboard` 迁到 **`D:\KittenPuppy4Ever`**（platform + emf-schedule + localdata 一起），
  `ensure_platform.ps1` / `run_guard.vbs` / 计划任务路径已更新，新目录运行、隧道与 entry 正常。
- 旧目录只剩被进程占用的空 `platform` 壳，重启后可删。

### 用户与权限
- 角色：`superadmin` / `admin` / `user`，初始 kitten=admin、puppy=superadmin。
- `users.json` 增加 `role`、`modules`（每模块访问）、`maintain`（每模块维护）、
  `last_seen`、`active_seconds`、`created_at`。
- 判定：superadmin/admin 天然可访问全部模块；user 只能访问 `modules[id]=true`；
  superadmin 天然可维护全部；admin 维护权默认全开、可由 superadmin 逐模块关掉。
- 数据接口按模块鉴权：项目 API + 旧页面 `/api/state`/`/api/save` 都校验；
  旧页面/原生视图注入 `window.__KP_MODULE__`，fetch 自动带 `X-KP-Module`。
- 管理接口：`GET /api/admin/users`、建用户、改角色、重置口令、删除、
  `POST /api/admin/users/<u>/module|maintain|role|password`。
- UI：顶栏「👥 用户」仅 admin/superadmin 可见；行内显示角色、在线状态、累计在线时长，
  模块访问/维护复选框按角色显示；支持新建、重置口令、删除、升降级。
- 活跃统计：每次鉴权请求更新 `last_seen`，间隔 ≤5 分钟累计进 `active_seconds`；
  面板显示活跃用户数（5 分钟内）与总在线时长。


## 23. Bug 反馈与主题色收口（2026-10-30）

### Bug 反馈
- 顶栏「🐞 反馈」（所有登录用户）；
- 表单：页面自动、标题、严重级别、描述；
- **输入即实时保存**：600ms 防抖，`POST /api/bugreport`（draft=true）追加/更新本地
  `data/bugreports.json` 并追加 `data/bugreports.jsonl` 审计流水，面板显示"已实时保存到本地 HH:MM:SS"；
- 提交后状态从 draft→open；草稿 id 存 localStorage，刷新可恢复；
- `GET /api/bugreports`：普通用户只看自己的，admin/superadmin 看全部；
- admin 可把状态改为 待处理/处理中/已修复/已关闭（`POST /api/bugreports/<id>/status`）。

### 主题色为什么还有蓝色
- 用户主题之前只覆盖 `--pink`，但按钮/芯片/输入焦点/进度条用的是 `--accent`（默认复旦蓝/项目清单蓝），
  项目 iframe 还会被 manifest accent 覆盖；
- 现在用户主题同时覆盖 `--accent/--pink/--pink-deep/--mint/--p-accent`：
  - 壳/模板增加 `body.user-kitten{--accent:#b25e83;--mint:#f0c3d6}`、`body.user-puppy{--accent:#2a5fb8}`；
  - 服务端注入的用户主题样式放在项目 accent 之后（用户优先）；
  - 壳把主题写进 iframe 的 html/body 变量；
  - 登录按钮渐变、卡片 accent、课表标签、地图圆点、Mock 进度条等硬编码蓝改为 CSS 变量。


## 24. 用户卡片菜单、统一设置/管理弹窗、主题色 + colormap（2026-10-30）

- 右上角改为用户卡片，点击下拉：**个人设置 / 管理（admin+）/ 切换用户 / 退出**；
- 个人设置与管理共用统一弹窗模板：左侧子项栏 + 右侧内容；
  - 个人设置：主题（主题色预设/取色器 + colormap 选择 + 调色板预览）；
  - 管理：用户、反馈、统计三个子页；
- 主题色成为用户属性（`data/themes.json`，含 `color` + `colormap`），默认 `monochrome`；
- 服务端 `build_palette(color, colormap)` 计算 `accent/deep/soft/mint/bg/card/line/ink`，
  注入 CSS 变量；壳与项目 iframe 同步应用；
  - monochrome：同一色相派生深/浅变体；
  - viridis/plasma/inferno/magma/cividis/turbo：按主题色色相在 colormap 上取样；
  - 背景渐变也由 `--bg/--pink/--mint` 计算，不再有固定蓝色/米色。
- 新用户默认 monochrome；旧主题记录缺 colormap 时按 monochrome 处理。


## 25. 6 级主题层级色、PinkFDU 与菜单/权限收口（2026-10-30）

- **6 级层级色**：主题色经 `build_palette` 生成 `--tone-1`（最浅）…`--tone-6`（最深），
  语义变量由层级映射：`bg/card` 用浅层，`line/soft/mint` 用中层，`accent` 用第 5 层，`deep` 用第 6 层；
  monochrome 为同色相 6 级，固定 colormap 在 6 个位置取样。
- **PinkFDU**：新增粉蓝渐变 colormap，排在 monochrome 之后（第二个）。
- **个人设置**：新增「应用」按钮（只应用到当前界面、不写账号），「保存主题」才持久化。
- **下拉菜单**：个人设置 / 反馈 / 管理（admin+）/ 切换用户 / 退出；反馈菜单打开 bug 表单。
- **切换用户**：修复退出时清除 cookie 的属性不一致（Secure/Partitioned 与登录时匹配），现在会回到登录页。
- **用户可见性**：admin 与 superadmin 都能看到全部用户；`can_manage` 决定行内是否可操作：
  admin 只能管理 user，superadmin 可管理 admin/user，superadmin 行只读。
- **课表卡片**：课程卡片颜色不再用固定色，课程按索引映射 `--tone-3..6`，
  卡片渐变/边框/图例/详情圆点全部改用主题层级色。


## 26. monochrome 层级色与色卡一致（2026-10-30）

之前 monochrome 的 6 级色是固定亮度/饱和度公式独立算的，主题色本身没出现在层级里；
色卡预览条又只取 mint/soft/deep 三色，所以和下面 6 个样块对不上。

现在：
- monochrome 以「用户选的主题色 = tone-4(L4)」为基准，向浅/深按剩余亮度空间均匀展开：
  tone-1/2/3 + tone-4(原色) + tone-5/6；
- 色卡预览条直接用这 6 个 tone 颜色做渐变，与样块一一对应；
- 固定 colormap 也按 6 个位置取样，预览条同样用取样结果。


## 27. 连续色卡、音序课程、登录页主题（2026-10-30）

- 主题引擎额外输出 **64 级连续 ramp**（`--kp-ramp-0..63`）：
  monochrome 在 6 级之间插值，固定 colormap 沿 stops 取样；壳与项目 iframe 都注入。
- 课表：
  - 课程按 `Intl.Collator("zh-Hans-CN")` 的音序/首字母排序（中英混合）；
  - 课程数量为 N 时，第 i 门取 `ramp[round(i/(N-1)*63)]`，数量变化也保持连续分布；
  - 卡片、图例、课程表色块都使用该连续颜色。
- 新建用户默认色卡 **PinkFDU**（主题色按角色给默认粉色/蓝色）。
- 登录页：
  - 增加用户名输入框（不再只能选 kitten/puppy），角色按钮仍可快速选择；
  - 输入/选择用户时请求 `GET /api/public-theme?user=`，把该用户的调色板应用到登录页；
  - 登录遮罩背景、卡片、激活角色样式都由 `--pink/--mint/--bg` 计算，不再固定粉蓝。
- 6 级层级色加大区分度：单色按剩余亮度空间拉开（近白 → 深色），默认粉主题实测
  `#fdfafb / #f5e6ec / #efcad9 / #ec9fbe / #e23379 / #98164a`。


## 28. 6 级层级色在页面中的角色分配（2026-10-30）

不是单纯把颜色拉得更开，而是让 6 级分别承担固定 UI 角色：

| 层级 | 页面角色 |
| --- | --- |
| tone-1 | 页面底色 / 列表行底 |
| tone-2 | 卡片、区块、弹窗、顶栏的面 |
| tone-3 | 边线、分隔线、标签底 |
| tone-4 | hover、次级高亮、软色块 |
| tone-5 | 主按钮、页签激活、链接、强调条 |
| tone-6 | 标题、强文字、主按钮 hover |

palette 语义变量直接映射到层级（bg=tone1、card=tone2、line=tone3、soft=tone4、
accent=tone5、deep=tone6），并在 `template.css` / 壳 / 课表 CSS 中逐组件落到这些 token 上，
不再全部挤在 `--accent` 一个颜色上。


## 29. 卡片比页面浅 + 登录页主题过渡（2026-10-30）

- 层级角色调整：**页面底 = tone-2，卡片面 = tone-1**（卡片更浅）；区块/卡片/弹窗/顶栏用 tone-1，
  页面背景用 tone-2，边线 tone-3，hover tone-4，主按钮 tone-5，标题 tone-6。
- 登录页切换用户时使用 `document.startViewTransition` 做整页颜色交叉淡入，
  同时给登录遮罩/卡片/角色卡补 `background/border/color` 0.5s 过渡；重叠请求加 busy 守卫避免
  "Transition was skipped" 报错。


## 30. 登录页流畅化（2026-10-30）

- **消除首屏闪错主题**：
  - `:root` 默认色改为中性暖灰，不再先闪 PinkFDU；
  - `<head>` 内联脚本同步读取 `kp_pubtheme_<当前用户>`，在首次绘制前写入 CSS 变量；
  - 每次切换/登录后把调色板缓存到 localStorage，刷新即用。
- **提前预取**：head 脚本与主脚本都提前预取 kitten/puppy 的主题，首次切换命中缓存。
- **切换用户**：先用缓存立即上屏，再后台校验公共主题接口，有变化才更新；
  - View Transition 时长 300ms→240ms，并相同调色板直接跳过；
  - `vtBusy` 守卫避免重叠过渡报错。
- 登录遮罩/卡片/角色按钮过渡时长 500ms→320ms。


## 31. 启动遮罩：消除"主页标题闪帧"（2026-10-30）

- 壳不再在 boot 完成前暴露首页/顶栏；`<body>` 先渲染一个与 GitHub 连接页同风格的
  `#boot-splash`（🐱🐶 + "正在进入工作台…"），背景同样使用主题层级色。
- `boot()` 决定「登录 / 首页」后调用 `hideSplash()` 淡出（240ms），
  登录分支（401）与异常兜底也会隐藏，避免遮罩拦截点击。
- 登录页刷新时主题缓存先于首绘应用，遮罩本身也使用该主题色，和连接页过渡连续。
- 实测：首屏 splash 可见、home 不可见；登录/刷新后 splash 移除、无首页标题闪帧。


## 32. Tailscale Funnel 固定域名接入（2026-10-30）

- 安装 Tailscale 1.104.4，开启 Funnel：`tailscale funnel --bg 8772`，
  固定公网地址 `https://02f5c6734009.tail4ba04e.ts.net/`（HTTPS 443 -> 127.0.0.1:8772）。
- `config/tunnel.json` 切换为 `mode: tailscale`，guard 不再启动 cloudflared quick tunnel，
  只维护引擎 + 校验 Funnel 状态，`entry.json` 固定指向 ts.net。
- GitHub Pages 入口改成**静态固定 iframe shim**：直接写死 `BASE` 并解析期设置 iframe src，
  不再 fetch entry.json / 动态设 src，避免加载抖动。
- 注意：Playwright 自动化（headless 甚至 headful）对 `*.ts.net` iframe 会表现为"不加载"，
  但真实浏览器访问正常，不能据此判定线上失败；后续以真实浏览器/用户反馈为准。


## 33. 自适应性能档位（2026-10-30）

- `PERF_PATCH` 注入到壳与所有项目页：根据
  `prefers-reduced-motion`、`connection.saveData`、2G、`hardwareConcurrency ≤ 4`、
  `deviceMemory ≤ 4` 判定低档；高档再跑 4 秒 FPS 采样，低于 38fps 自动降档。
- `html[data-perf="low"]` 下：
  - 关闭 animation/transition、backdrop-filter、box-shadow、hover 位移、iframe 淡入；
  - 页面背景退化为纯 `var(--bg)`，去掉径向渐变；
  - 登录切主题不使用 ViewTransition。
- 旧浏览器回退：`background-color` 兜底、`@supports not (color-mix)` 给关键组件纯色。
- 首屏主题预取改为 `requestIdleCallback`，避免与 `/api/bootstrap` 抢慢速隧道的首屏带宽。
- GitHub shim 增加 `preconnect/dns-prefetch` 到固定 Funnel 域名，缩短首次 TLS 握手等待。


## 34. Puppy 声纹 503 修复（2026-10-30）

- 根因：项目从 `D:\KittenLisaWork\school\dashboard` 搬到 `D:\KittenPuppy4Ever` 后，
  Mock 后端默认相对路径 `root/../../.. /MockInterview` 算成了 `D:\MockInterview`，
  `import mock_web` 失败，网关对所有 `/mock/api/*` 返回 503。
- 修复：`config/platform.json` 显式配置 `mock_dir`，服务端再按
  `mock_dir → KP_MOCK_DIR → 旧相对路径 → D:\KittenLisaWork\MockInterview → ~/MockInterview`
  逐个探测 `mock_web.py`。
- 启动预热：`run.py` 在端口绑定后延迟 2 秒在后台导入 Mock 后端，避免拖慢启动/被 guard 误判；
  首次声纹请求不再等 19 秒；前端状态请求超时放宽到 60 秒。
- 验证：`/mock/api/voice/puppy/status` 200，页面显示「6 段样本 · Puppy 音色可用 · 语料 3/5」。


## 35. 注册、日程管理与参与占用（2026-10-30）

- 登录页支持**注册**：`POST /api/register`，新用户默认 role=user、全部模块可访问、主题 PinkFDU，
  注册后自动登录；不再必须选 kitten/puppy。
- 「课程看板」改名「日程管理」；课程仍是共享周表，个人日程改为服务端存储
  `data/schedule_events.json`，按用户过滤：创建者/被提到/参与人才可见。
- 日程新增 `participants`（参与人）：
  - 新日程默认 `mentions=[自己]`；
  - 参与人选择器调用 `/api/schedule/participants` 列出当前时段所有系统用户，被占用者禁用；
  - 保存时服务端校验每人同一时段只能参与一个日程，冲突返回 409（被提到不算占用）。
- 管理页移除「新建用户」表单；注册入口统一到登录页。


## 36. 切换用户修复（2026-10-30）

- 注册后 `loginMode` 会停留在 register：切换用户时显示成注册表单。现在 `doLogout()` 与登录成功后
  都会 `setLoginMode("login")`，并清空确认口令。
- 切换用户时清空 `loginUser`、localStorage `kp_login_user`、用户名输入框与角色选中态，
  避免看起来"还是同一个人"；点角色或输入新用户名即可登录。


## 37. 独立 /login 子页面（2026-10-30）

- 新增 `static/login.html`，服务端路由 `GET /login`；登录/注册不再复用壳内遮罩。
- 未登录访问壳：`showLogin()` 直接 `location.replace("/login?next=...")`，不再显示同页遮罩；
- `doLogout()` 清 token 后直接跳 `/login`，不再 `boot()` 重渲染；
- 登录页：
  - 支持角色快捷选择、任意用户名、注册（自动登录）；
  - 支持 `next` 回跳（只允许站内绝对路径）；
  - 已有会话访问 `/login` 自动回工作台；
  - 主题缓存首绘应用；iframe 内通过 `postMessage({kpPath:"/login"})` 同步 GitHub 地址栏；
- 登录成功后回到 `next`（默认 `/`），切换用户不再残留旧用户名/注册模式/遮罩状态。


## 38. 无后缀首页 + /home 工作台（2026-10-30）

- `GET /` / `/index.html` → `static/landing.html`：无后缀全首页，含「登录」「注册」两个入口；
  登录/注册分别跳 `/login?next=/home` 与 `/login?mode=register&next=/home`；已登录时按钮变为「进入工作台 / 切换账号」。
- `GET /home` → 原工作台壳 `index.html`；`goHome()`、登录后默认回跳、项目「← 工作台」都指向 `/home`。
- `/login` 默认 `next=/home`，支持 `mode=register`。
- 旧项目 URL（`/dashboard/` 等）保持不变；GitHub Pages 入口根路径展示全首页，`/home` 展示工作台。


## 39. 首页固定 PinkFDU（2026-10-30）

- 无后缀全首页固定使用 PinkFDU 粉蓝渐变，不再读取/应用登录用户的主题缓存；
- 使用 PinkFDU 实际层级色：`#e899ba / #d67dab / #b96fa9 / #936fb6 / #657cc4 / #174eae`，
  主按钮粉→紫→蓝渐变，标题深蓝，卡片浅粉白；
- 登录页仍按用户主题，只有首页保持统一品牌色。


## 40. 首页题头语轮转（2026-10-30）

- 首页去掉具体功能卡片与功能描述，只保留品牌、题头语、登录/注册入口和快速入口；
- 题头语 6 句随机起始，每 6.5 秒随机切换，点击标题也可立即换一句（键盘 Enter/空格）；
- 高档模式给标题加 `tag-swap` 缩放动画（0.26s），低性能/减弱动效模式不加动画。


## 41. 首页极简：浅色底 + PinkFDU 文字（2026-10-30）

- 去掉渐变背景、右侧快速入口面板、所有卡片/阴影；
- 默认浅色底 `#f8f5f0`，只保留品牌、题头语、说明、登录/注册文字入口和页脚；
- 标题整段使用 PinkFDU 渐变文字（pink → purple → blue），入口也是深蓝/粉紫文字；
- 题头语随机轮转与点击切换保留，高档缩放动画、低性能关闭均不变。


## 42. 文案修正：不再称"两个人的工作台"（2026-10-30）

- 已支持注册多用户，首页/顶部文案统一改为「私人工作台」；
- 英文 kicker 由 `A PRIVATE WORKBENCH FOR TWO` 改为 `A QUIET PRIVATE WORKBENCH`；
- 题头语移除「两个人的工作台」「只属于 Kitten 和 Puppy」，改为「自己的工作台」「只属于你的」等；
- 说明文案不再写"只属于两个人"；kitten/puppy 仅保留为初始账号/角色，不再代表唯一用户。


## 43. 首页居中 + 实色文字（2026-10-30）

- 首页整体改为居中：品牌/题头语/说明/入口/页脚都居中；
- 标题去掉渐变裁切，改为实色三色：第一行墨黑 `#272c3a`，第二行前半深蓝 `#174eae`、后半粉紫 `#b96fa9`；
- 保持浅色默认背景 `#f8f5f0`、无卡片、无面板；
- 题头语随机轮转/点击切换/高档缩放动画保持不变。


## 44. 管理界面修复（2026-10-30）

- 根因：移除“新建用户”表单后，`openUsers()` 仍引用已删除的 `#nu-role`，抛 TypeError，管理弹窗打不开。
- 修复：删除残留的 `nu-role/nu-name/nu-pass/nu-create` 引用；管理入口恢复。
- 反馈管理：`/api/bugreports` 对 admin/superadmin 返回全部反馈，管理页可切换 open/doing/fixed/closed；
  实测两个不同用户提交的反馈均可被 kitten 管理员看到并处理。


## 45. 课程可见性 + GitHub Issue 风格反馈（2026-10-30）

- 课程增加 `owner/participants` 字段（现有课程 participants=["kitten"]）；
  日程页加载后按当前用户过滤 `DATA.courses / specials / exams`，puppy 不再看到 kitten 的课程。
- 反馈管理改为 GitHub Issue 风格：
  - 绿色 `Open` / 紫色 `Closed` 状态徽章；
  - 标签显示处理中/已修复/severity；
  - 操作按钮：标记处理中、标记已修复、关闭 issue、重新打开；
  - 顶部统计 `全部 N 条 · Open X · Closed Y`。


## 46. 反馈跟帖、日程调试、AI 服务、模块标签（2026-10-30）

- **反馈 Issue 跟帖**：`GET/POST /api/bugreports/<id>/comments`，提交者本人和 admin/superadmin 可回复；
  管理页与反馈弹窗都显示评论区，可连续跟帖。
- **superadmin 日程调试**：新模块 `schedule-debug`（roles=["superadmin"]，path `/schedule-debug/`），
  独立窗口查看/新增/编辑/删除所有人的日程；后端 `/api/schedule/admin/events` 仅 super。
- **课程可见性**：课程与个人日程使用同一规则（owner/mentions/participants），不再特殊；
  现有课程 participants=["kitten"]，puppy 不可见。
- **AI 服务模块**：新模块 `ai`（`/ai/`）。admin 可设全局 Base URL/Key/Model，普通用户可选
  “使用服务端”或“个人覆盖”；未配置服务端时提示联系管理员。支持常见 OpenAI 兼容服务自动识别、
  DeepSeek 本机 DSH（base 含 3786）、测试连接与 `/api/llm/chat` 代理；Key 服务端保存、接口只回掩码。
- **模块标签 + 首页搜索**：每个项目 manifest 增加 `tags[]`；tree 返回 tags；home 增加搜索框与标签筛选，
  支持按标题/描述/标签过滤。


## 47. 课程统一为普通日程 / 调试 / 搜索 / 全局 AI 管理（2026-10-30）

- 课程在服务端展开为普通日程事件写入 `data/schedule_events.json`（tag=课程、带 owner/participants），
  superadmin 调试窗口按普通事件展示/管理；删除课程事件写入 `deleted_course_ids` 防止再次展开。
- 调试页移除单独的「课程（只读）」区块，课程与个人日程同在事件列表。
- 首页搜索改为完整搜索栏：放大镜、清空按钮、`/` 快捷键、模块计数；标签筛选保留。
- 全局 AI 配置移到「管理 → AI 服务」及用户下拉的 AI 菜单；AI 模块页只保留个人覆盖/测试对话。
- 反馈 Issue 跟帖继续保留（管理页与反馈弹窗）。


## 48. GitHub Pages 子路由 shim（2026-10-30）

- GitHub Pages 纯静态，`/home` 没有 `home/index.html` 会直接 404，进不到 iframe。
- 已为 `home/ login/ ai/ schedule-debug/` 发布同一 shim，并加入 `publish_frames.py` 的 PATHS；
  发布脚本优先使用 `platform/data/shim.html`，避免回退到旧动态 shim。
- 直接访问 `/home` 会 301 到 `/home/`，现在 200。


## 49. 左右抽屉与 AI 入口收口（2026-10-30）

- 用户下拉移除独立「AI 服务」；全局 AI 只在「管理 → AI 服务」中配置，管理 pane 增加状态卡、
  服务商/模型/Base URL/Key 两列布局、状态 pill 与测试按钮。
- 非 AI 模块页右侧增加 AI 抽屉：右缘竖标签唤起，宽度 25vw，top 从顶栏下方到底部 bug 按钮上方，
  左侧圆角；打开时 `#view-project` right=25vw 重排，不遮挡 iframe。抽屉内可直接对话、打开 AI 模块/配置。
- superadmin 增加左侧「日程调试」抽屉：左缘竖标签唤起，宽度 25vw、全高、右侧圆角；
  打开时 body padding-left=25vw 重排；内嵌 `/p/schedule-debug/?drawer=1`。日程调试模块在首页隐藏。
- 抽屉动画在低性能模式关闭。


## 50. 抽屉位置/边距与管理 AI UI（2026-10-30）

- 右侧 AI 抽屉上沿改为模块标题栏 `.pbar` 下方 12px；上/下/右统一 margin 12px，四角圆角；
  打开时 `#view-project` right=25vw+12px、bug 按钮左移，避免遮挡。
- 管理 → AI 服务重新设计：hero 状态卡（头像/状态/配置 pill）、连接/认证分区、
  Provider/Model 两列、Base URL 全宽、Key 显示切换、支持服务列表、保存/测试按钮。
- 左侧日程调试抽屉保持 25vw 全高、右侧圆角、body padding-left 重排；调试模块首页隐藏，由左缘标签唤起。
- 课程作为普通事件在调试抽屉中展示，可编辑删除。


## 51. AI 抽屉底边对齐 bugreport + 标题栏全宽（2026-10-30）

- AI 抽屉底边改为 `bottom:78px`，位于 bugreport 按钮上方（按钮 top≈834，抽屉 bottom≈822）；
- 标题栏 `.pbar` 不再随抽屉收窄：`#view-project` 保持全宽，只给 `#host` 加
  `margin-right: calc(25vw + 12px)`，loading 同步让位；pbar 始终 100vw 宽。
- 抽屉上/右 margin 12px，底部对齐 bug 按钮上方。


## 52. AI 抽屉打开时正文真正重排（2026-10-30）

- 之前只给 `#host` 加 margin-right，iframe 仍保持 100% 宽度，正文没有真正重排。
- 现在 `body.ai-open #host { width: calc(100% - 25vw - 24px); align-self:flex-start; }`，
  iframe 内部宽度实际缩小；`.pbar` 保持 100vw。
- 实测 1440 视口：pbar=1440、iframe=1056、抽屉 left=1068，正文重排且不遮挡；抽屉底部 822，在 bugreport top 834 上方。


## 53. AI/调试入口改为 FAB + 合并调试抽屉（2026-10-30）

- AI 入口改为 bugreport 上方的圆形 FAB（44px，right 22 / bottom 76），与 bugreport 同一视觉格式；
  AI 抽屉打开时隐藏该 FAB。
- 旧「后端调试」和「日程调试」合并为左下角单个圆形 FAB（left 22 / bottom 22）：
  - 抽屉内标签页：「后端」= 项目树/指标，「日程调试」= 内嵌 schedule-debug 页面；
  - 抽屉宽 25vw，右侧圆角；
  - 上边缘动态：home 时对齐 `#hello` 大标题，模块内时对齐 `.pbar` 小标题；
  - 打开时 body padding-left=25vw 重排。
- 移除独立 sched-edge / sched-drawer。


## 54. 调试抽屉打开时总标题栏保持全宽（2026-10-30）

- 不再用 `body{padding-left:25vw}`（会连 header 一起挤窄）；
- 改为 `body.debug-open main { margin-left:25vw; }`，只让正文区域重排；
- 顶部 `.top` 始终 100vw；1440 视口实测 header=1440、main margin-left=360。


## 55. 调试栏统一 margin/圆角、与 AI 上界对齐、标题全宽（2026-10-30）

- 调试抽屉改为 `left:12px; bottom:12px; top:var(--kp-debug-top); width:25vw; border-radius:16px`；
- 模块内调试 top = `.pbar.bottom + 12`，与 AI 抽屉 top 完全一致；home 时对齐 `#hello` 大标题；
- 正文只偏移 iframe / home-wrap，不再移动 `main`；`.pbar` 与总 header 始终 100%；
- 同时打开 AI 时 iframe 宽度扣除左右两侧。
- 实测 1440：AI top=debug top=126、debug left=12、bottom=12、radius=16px、pbar=1440、host left=384 width=1056。


## 56. 页面背景连续无分缝（2026-10-30）

- 壳 `body` 背景加 `background-attachment: fixed`，整页共用一张渐变；
- 顶部 header 改透明，不再形成一条色带；
- 项目 iframe 页面 `body[data-project]` 背景透明，壳背景透过来，消除 iframe 边界分缝；
- 低性能模式 header 同样透明；
- 左右抽屉重排时只移动内容，背景保持同一张。


## 57. AI 抽屉改为模块引用（2026-10-30）

- 删除壳内独立实现的 AI 聊天/状态 UI，抽屉只保留 header + `<iframe src="/p/ai/?drawer=1">`；
- 抽屉内容就是 AI 模块页面本身，后续修改 AI 模块自动同步，不再维护两份实现；
- AI 模块根据 `drawer=1` 加 `drawer-mode` 紧凑样式，适配 25vw 宽度；
- 抽屉 header 提供「打开模块」与关闭。


## 58. AI 默认对话页 + 主题 tone 变量修复（2026-10-30）

- 根因：服务端注入的主题样式把 `--tone-*` 写成了 `tone-*`，项目 iframe 读不到主题层级色，
  回退到 template.css 米色默认值。已补 `--` 前缀，登录后所有项目页不再出现米色。
- AI 模块重写为「对话 / 设置」双页，默认显示对话；抽屉 iframe `/p/ai/?drawer=1` 直接落在对话页。
- 抽屉 iframe 加载后由壳把当前用户 theme 变量注入，避免无 cookie 场景退回默认色。


## 59. AI/调试抽屉返回键与 AI 对话页（2026-10-30）

- AI 模块去掉顶部单独的「AI 服务」卡片，默认对话页；历史/设置为页内 tab。
- AI 页面额外提供两个圆形 FAB 叠在 bugreport 上方：⚙️ 配置（bottom130）、🕘 历史（bottom76），
  通过 postMessage 切换 iframe 内 AI 页 tab。
- AI 抽屉不再用右上角 ×：FAB 原位变为 ← 关闭；🕘 历史在抽屉右下角、← 的左边。
- 调试抽屉同样不再用 ×：左下角 FAB 原位变为 ← 关闭。
- 同心圆：按钮 44px/r22，抽屉圆角 22px；AI 按钮 right12/bottom78 与抽屉同角同心；
  调试按钮 left12/bottom12 与抽屉同角同心。


## 60. AI/调试抽屉按钮几何与 AI 面板（2026-10-30）

- 收起态 AI 按钮 right22/bottom76，与 bugreport（right22/bottom22）右对齐；调试按钮 left22/bottom22。
- AI 抽屉 right14/bottom68/radius30，返回键 right22/bottom76/r22，与抽屉右下角圆心重合、内缩8px；
  调试抽屉 left14/bottom14/radius30，返回键 left22/bottom22/r22，同理。
- 两个抽屉都取消右上角 ×：返回键就是原 FAB 位置/尺寸。
- AI 抽屉历史 🕘（bottom130）、设置 ⚙️（bottom184）依次叠在返回键上方；
  AI 页面原位置也提供历史/设置 FAB（bottom76/130），点击后该按钮变 ←，且同时只开一个面板。
- AI 页面去掉顶部「AI 服务」卡片，默认对话；历史/设置改为从模块标题下弹出的右侧面板。


## 61. AI 面板按钮顺序/返回态与同心圆（2026-10-30）

- AI 页面：历史面板 bottom=22px（bug 位置），设置面板 bottom=76px（历史按钮位置）；
  点历史/设置后对应按钮变 ←，再次点击回到对话；设置与历史同时只开一个。
- AI 抽屉：设置 ⚙️（bottom184）、历史 🕘（bottom130）依次在返回键（bottom76）上方；
  点击后该按钮变 ←，另一个保持原图标；只开一个面板。
- 抽屉四角统一 30px；按钮 44px、r22：
  - AI 抽屉 right14/bottom68 → 右下角圆心 (1396,802)；返回键 right22/bottom76 → 圆心 (1396,802)；
  - 调试抽屉 left14/bottom14 → 左下角圆心 (44,856)；返回键 left22/bottom22 → 圆心 (44,856)。
- 收起 AI 按钮 right22/bottom76，与 bugreport right22 对齐。


## 62. AI 抽屉双返回键/面板边界/抽屉化占满（2026-10-30）

- AI 抽屉打开时主返回键（#ai-edge）加主题色底色，和子面板的 ← 区分。
- AI 模块页（未抽屉化）：历史面板 bottom=68px（与 AI 抽屉底边一致），设置面板 bottom=76px（历史按钮位置）。
- 历史/设置切换：先关闭当前面板，180ms 后再打开另一个，绝不会同时出现。
- AI 抽屉化时：历史/设置不再按抽屉处理，`inset:0` 占满整个 iframe 并隐藏对话，`#ai-drawer-frame` margin-bottom 从 190→0；返回键仍生效。
- 主返回键 colored：`body.ai-open #ai-edge { background:var(--tone-5); color:#fff; }`。


## 63. AI 抽屉化历史/设置彻底占满内容（2026-10-30）

- AI 抽屉内不再有“抽屉中的抽屉”：`drawer-mode.panel-open` 时隐藏对话，历史/设置 section
  变为 static、width 100%、height 100vh、radius 0，直接铺满 iframe；
- `#ai-drawer-frame` margin-bottom 在面板打开时 190→0，面板内容区从顶到底；
- AI 模块页设置面板 bottom=120px，正好等于历史按钮上边缘（历史按钮 bottom76 + 高44），
  历史面板 bottom=68px（与其他窗口 AI 抽屉底边一致）；
- 主抽屉返回键（#ai-edge）在 ai-open 时使用主题色底/白字，与子面板 ← 区分；
- 历史/设置切换时先关闭当前面板，180ms 后再开另一个。


## 64. AI 右侧面板默认误显示修复（2026-10-30）

- 根因：`.section { animation: fadeUp ... both }` 的最终 transform 覆盖了 `.ai-side-panel` 的
  `translateX(100%+24px)`，同时面板默认是 `display:block`，所以进入 AI 模块时两个面板看起来一直打开；
- 修复：`.ai-side-panel` 默认 `display:none; animation:none !important;`，仅 `.open` 时 `display:block; transform:none`；
- 抽屉化模式下仍保持 `:not(.open){display:none}`，历史/设置打开时占满 iframe。


## 65. AI 抽屉内历史/设置直接切换（2026-10-30）

- `drawer-mode` 下点击历史/设置直接 `applyPanel(name)`，不执行关闭-180ms-打开的流程；
- 普通 AI 页面仍保留先关后开，避免两个侧面板同时出现。


## 66. 多供应商多 Key / 模型搜索 / effort / 上下文（2026-10-30）

- `llm.json` 的 global 新增 `providers: [{id,name,provider,base_url,model,context_window,keys:[...],enabled}]`
  与 `active_provider`；旧单 provider 字段仍兼容并自动迁移。
- `/api/llm/admin` GET/POST 支持 providers 列表（keys_text 每行一个 Key，CLEAR 清空，留空保留）。
- 新增 `/api/llm/models`：按当前/指定 provider 请求 `/models`，自动返回模型 ID 列表。
- `/api/llm/chat` 支持 body.model / body.effort / provider_id，并返回 usage 与 context_window。
- 管理 → AI 服务改为多服务商卡片：名称、服务商、Base URL、模型、上下文窗口、多 Key textarea、当前 provider 单选。
- AI 模块对话不再放在卡片内；顶部工具栏含自动搜索模型、effort 滑块、上下文用量。
- AI 页面/抽屉的历史、设置返回按钮使用主题色背景；调试主返回键也使用主题色。


## 67. AI 对话新布局（2026-10-30）

- 新对话：slogan 在输入框上方，输入框+模型/effort/上下文统计整体垂直居中；
- 有历史消息（`body.has-chat`）：消息区占满，输入/统计/调节固定到页面下部；
- 输入框 60px 高、圆角 30px；发送按钮 44px/r22 嵌在输入框内部右侧，右边距 8px，
  按钮圆心与输入框右侧圆角圆心重合；
- 历史消息从 localStorage 渲染，发送后自动切换到下部布局；
- AI 页面/抽屉返回键保持主题色。


## 68. AI 输入框多行右下角对齐（2026-10-30）

- 输入框 placeholder 居中（`text-align:center` + `:placeholder-shown`）；
- 输入框高度随内容自动增长（40–160px），发送按钮 absolute right7/bottom7；
- 按钮 44px/r22 与 bugreport 完全一致，视觉边距 8px；
- 单行/多行均满足按钮圆心 = 输入框右侧/右下角圆角圆心（高度60/半径30体系）。
- 实测：单行 h62 gapR8 gapB8 cx0 cy0；三行 h110 gapR8 gapB8 cx0 cy0。


## 69. AI slogan 轮换/模型名替换（2026-10-30）

- AI 新对话 slogan 可点击切换（也支持 Enter/Space），文字格式与首页标题一致：
  黑色主文案 + `--tone-5` 模型名/关键词 + `--tone-6` 结尾强调；
- 选中模型后，模板里的 `AI` 自动替换为模型名（如 deepseek-chat）；
- `font-size: clamp(20px,3.1vw,30px)`、`max-width:22em`、`overflow-wrap:anywhere`、
  `text-wrap:balance`，长模型名自适应换行；
- 抽屉内字号自动缩小到 17px。


## 70. AI slogan 放大/抽屉居中/顶部未配置提示（2026-10-30）

- slogan 字号 `clamp(26px,4vw,40px)`，与输入框 gap=20px；
- 抽屉模式新对话：`.page` 去除上下 padding，`.ai-chat` `justify-content:center`，
  composer 中心与 iframe 中心实测均为 237（474px 高）；
- 未配置提示从工具栏移到页面/抽屉顶部：fixed top8、水平居中、红色 `#c0392b`，
  配置成功后自动隐藏，不再在工具栏重复。


## 71. AI 底部控制栏 + 加密文件上传（2026-10-30）

- AI composer footer：左下 📎 上传按钮，右下模型/effort/上下文统计；
- 上传接口：
  - `POST /api/files/upload`（base64，单文件≤16MB，按用户存储）
  - `GET /api/files` 当前用户文件
  - `GET /api/files/<id>` 服务端解密后下载
  - `POST /api/files/delete`
- 加密：`cryptography.Fernet`，密钥 `data/files/upload_key.bin`（0600），
  密文 `data/files/<user>/<id>.bin`，索引 `data/files/index.json` 只存元数据；
  下载/聊天时由服务端解密，其他用户不可访问；
- 发送聊天时 `files` 传入文件 id，服务端读取文本附件拼入 system context；
- 文件 chips 可下载/移除，发送成功后清空。


## 72. AI 右下 DSH 风格模型/上下文控件（2026-10-30）

- 模型 + effort 合并为一个 DSH 风格 trigger：`model · effort ⌄`，28px 高、透明底、hover 浅底；
- 点击弹出菜单：模型列表（自动搜索）+ Effort 低/中/高，选中打勾；
- 上下文用量改为 DSH 风格圆环 + 百分比 trigger，点击展开面板：
  `~used / window`、占用条；
- 左下 📎 上传文件，右下模型/上下文控件；
- 原生 select 仅作为数据源隐藏，不再显示。


## 73. AI 上下文面板统计/自适应弹出方向（2026-10-30）

- 圆环保持单段，不拆分；
- 上下文面板新增统计：输入、输出、总计、剩余、窗口，以及占用条；
- DSH 菜单/面板改为 fixed 定位，JS 优先向下弹出；下方空间不足且上方更大时向上；
- 实测新对话面板向下（top 451 > trigger bottom 443），历史对话底部面板向上（bottom 631 < trigger top 640）。


## 74. AI 发送/附件按钮缩到 2/3（2026-10-30）

- 发送按钮、附件按钮由 44px 改为 29.34px（约为原 2/3）；
- 发送按钮右边距/下边距 14.34px，保持与输入框右下角圆心重合；
- 实测 29.328px、ratio 0.6665，cx/cy≈0。


## 75. AI 输入框底部间距/发送按钮 margin（2026-10-30）

- 输入框与左下上传/右下控件间距从 20 缩到 **8px**（footer margin-top -12px）；
- 发送按钮与输入框边界 margin 统一为 **8px**（与抽屉一致）；
- 为同时保持同心圆：输入框圆角改为 **22.66px**（按钮 r14.67 + 8px margin），
  实测 gapR/gapB=8，cx/cy≈0.004。


## 76. AI 输入框有效区域 = 四角圆心矩形（2026-10-30）

- placeholder 取消居中，改为左对齐/上对齐；
- 输入框 padding=圆角半径（22.66px），textarea 实际边界正好落在四个倒角圆心的矩形上；
- 实测 textarea 四边 inset 均为 23.656px（含 1px 边框），四边相等；
- 输入框 min-height 76px，textarea min-height 30.68px，随内容自动增高；
- 发送按钮仍 29.34px、右下 margin 8px。


## 77. AI 附件 + 与文字上移（2026-10-30）

- 附件按钮图标由回形针改为「＋」，直径仍 29.34px；
- 输入框 padding-top 从 22.66 缩到 12px，textarea 顶部上移约 10.7px；
- 文字保持左对齐/上对齐，发送按钮仍右下 margin 8px。


## 78. 后端 AI 实际配置（2026-10-30）

- 已配置 DeepSeek 官方服务商：
  - base_url: https://api.deepseek.com/v1
  - model: deepseek-chat
  - context_window: 128000
  - 单 Key（第 1 个 provider，active）
- `/api/llm/test` 200 可达；`/api/llm/models` 返回 deepseek-flash / deepseek-v4-pro；
  `/api/llm/chat` 实测回复正常，kitten 用户同样可用。
- `llm.json` 改为 Fernet 加密存储（密钥 `data/llm_key.bin` 0600），接口只返回 Key 掩码；
  文件不以明文保存 Key。


## 79. 每用户 AI session / 导入导出 / 自定义工具（2026-10-30）

- Sessions：`data/ai_sessions/<user>/<id>.enc`，Fernet 加密，按用户隔离；
  API：`GET/POST /api/ai/sessions`、`/api/ai/sessions/<id>`、`save`、`delete`、`backup`、`import`。
- AI 页支持 session 下拉、新建、清空；发送后自动持久化。
- 会话管理：导出当前对话 .md（可读）；导入 .md/.json，支持覆盖当前或新 session；
  备份全部 session 为 JSON；从备份 JSON 恢复。
- 自定义工具：registry 支持 schedule / scratchpad；AI drawer 把 `module` 参数传入 AI 页，
  chat API 注入工具说明并解析 `{"tool","args"}`，执行后继续回答；工具带 dry-run。
- smoke test 全部改为只读/dry-run：附件上传 dry-run 加密往返、session dry-run 不写文件、
  工具 dry-run 不执行模块事务；smoke 36/36，verify 17/17。


## 80. AI 模块上下文强约束 + 操作观感（2026-10-31）

- 链路：shell app.current.id → iframe `module=` → AI 页 currentModule() → chat body module；
- 后端校验 module 项目存在且用户可访问；工具名必须属于当前 module 的 AI_TOOL_DEFS；
  system prompt 明确写“当前模块：标题（id）”；
- 工具结果可携带 `ui.actions`；AI 页 postMessage 给壳层，壳层显示 AI 光标、移动到 iframe 内目标、
  点击涟漪、短暂高亮，再向 iframe 发送 `kpAiAction`；
- scratchpad 监听 focus/refresh，schedule 监听 click/refresh，真实刷新对应模块；
- 当前工具仍由平台后端本地执行（schedule/scratchpad），未连接 DSH；
- 文件读取：chat 收到文件 id 后服务端解密；文本/代码附件内容注入 system context（最多6个/20k字符），
  图片/二进制仅提示元数据，不做视觉理解。


## 81. AI 模块走 DSH Bridge（路线 A，2026-10-31）

- `config/dsh.json` 启用；DSH Bridge 以 `dsh --profile headless --json --session-id ... -` 执行，
  stdin 传任务，解析 `session/text/final/status` NDJSON 事件；
- 平台 `POST /api/ai/dsh/chat`：校验用户/模块/平台 session，注入当前模块和用户上下文，
  调用 DSH；把 DSH session id 写回平台 session，后续轮次复用；
- AI 页检测 `/api/ai/dsh/status`：启用后隐藏平台模型/effort/context 控件，显示 DSH 徽标，
  对话直接走 DSH；DSH usage 显示 tokens；
- DSH 结果可返回通用 `ui.actions`（当前 schedule/scratchpad）驱动左侧模块光标/刷新；
- 注意：DSH headless 需要平台注入 `DEEPSEEK_API_KEY`（当前从加密 LLM 配置取），
  平台自身不再直接调用模型；DSH 的模块 API 工具桥仍未接，实际模块事务需 DSH 自身工具或后续 bridge。


## 82. DSH → 平台模块工具桥（2026-10-31）

- `_dsh_run` 生成一次性 bridge token，写入 `data/dsh_bridge/<token>.txt`，
  DSH 子进程通过 `KP_BRIDGE_TICKET` 读取（环境变量名不含 TOKEN/KEY，避免被 DSH 过滤）；
- 新增 `POST /api/dsh/tool`：校验一次性 token，执行当前 module 白名单工具；
- 新增 `tools/dsh_tool.py`：DSH shell 调用平台桥的客户端；
- 工具结果 ui 动作收集到 token，`/api/ai/dsh/chat` 返回 `ui_events`，AI 页转发壳层播放光标/刷新；
- 实测 DSH 能真正创建 scratchpad 便签并返回 ui_events，清理后无残留。


## 83. DSH 沙箱与模块工具桥安全改进（2026-10-31）

- DSH cwd 改为 `data/dsh_workspace/<user>` 隔离目录；`dsh_tool.py` 与一次性 ticket 复制到沙箱；
- ticket 不再放在固定 data/dsh_bridge，DSH 运行结束清理；
- 桥 token 绑定 user + module，`/api/dsh/tool` 拒绝跨模块；
- DSH prompt 明确“不要直接改 data/projects，必须走平台桥”；
- 实测 DSH 通过沙箱桥成功新增便签并返回 ui_events；平台可清理测试数据；
- 注意：仍是同一 OS 用户，absolute path 未被硬隔离；硬隔离需独立进程用户/容器。


## 84. AI 模块进一步优化（DSH/UI/session，2026-10-31）

- DSH 模式：隐藏平台模型/effort/context 控件，DSH 徽标展示 tokens；chat-hint 不再显示平台模型信息；
- DSH 消息展示“执行过程”（tool_call/tool_result 轨迹）；
- 消息内保存并显示附件 pill（可下载）；session 持久化保留 files；
- 历史面板新增删除当前 session；
- DSH 工具桥沙箱：cwd `data/dsh_workspace/<user>`，脚本/ticket 在沙箱内，token 运行后清理；
- DSH 通过 dsh_tool.py 实际创建便签并返回 ui_events，前端光标/刷新。


## 85. DSH 模型/effort/上下文与抽屉全高（2026-10-31）

- DSH 模式恢复模型/effort/上下文控件：
  - 模型/effort 来自 config/dsh.json（deepseek-flash/chat/v4-pro，low/medium/high）；
  - 请求带 model/effort，Bridge 为 DSH 生成 model_patch.yml；
  - 上下文环使用 DSH usage.totalTokens，窗口来自 DSH context_window；
  - 模型/effort 写入平台 session（dsh_model/dsh_effort），切换 session 恢复。
- AI 抽屉：iframe margin-bottom 190→0，消息区域占满整个抽屉内容高度；
  右侧为圆形按钮留 64px padding，按钮列只改变可显示宽度。
- 实测控件：models 3 / efforts 3，模型 deepseek-flash，effort 中，ctx 0% 可展开。


## 86. DSH 真实模型/effort、流式、ASK_USER、文件解析（2026-10-31）

- DSH 实际目录：deepseek-flash / deepseek-v4-pro；effort: off/low/high/max；默认 flash/high，context 1,000,000；
  移除不存在的 deepseek-chat。
- `/api/ai/dsh/stream` SSE：实时转发 thinking/tool_call/tool_result/text/final/done；
  AI 页实时更新回复气泡和“DSH 实时过程”轨迹。
- ASK_USER 协议：DSH 末尾输出 `ASK_USER {...}`；前端解析后在输入框下显示等宽问题面板，支持选项/自定义回答。
- 文件解析：text/PDF(pypdf)/DOCX(python-docx)/XLSX(openpyxl)；图片解密到沙箱 attachments，
  prompt 指向路径供 DSH `read_image` 使用；图片仍受 DSH 模型图像能力限制。
- AI 抽屉 iframe 全高（margin-bottom 0），右侧 64px 给圆形按钮列，消息区占满抽屉高度。


## 87. ASK_USER 单选/多选（2026-10-31）

- 协议增加 `multiple:false/true`；
- 前端按 multiple 渲染 radio（单选）或 checkbox（多选），不再是按钮；
- 单选提交选中项，多选可勾选多项；也支持自定义回答；
- 提示行显示“单选题/多选题 · 点击回答提交”。


## 88. AI Skill 管理正式支持（2026-10-31）

- AI 设置增加标签页：「AI 设置 / Skill 管理」，标签切换逻辑同调试窗口；
- 扫描 skill roots（platform/skills、DSH office-skills、~/.agents/skills、~/.dsh/skills、image-gen skills）；
- `/api/ai/skills` 列表、`toggle` 按用户启用、`import` 注册自定义 skill；
- 启用 skill 时复制到 DSH 沙箱 `.agents/skills`，prompt 声明可用 skill；
- 实测启用 office-xlsx 后，DSH 列出 `diagnose-windows-sandbox-acl` + `office-xlsx`。


## 89. 真流式 DSH / ASK_USER / 图像文件（2026-10-31）

- 自定义 DSH headless 插件 `@kittenpuppy/dsh-stream-delta`（platform/dsh_plugins/stream-delta）
  订阅 `agent/assistant-stream`，输出 `text_delta` / `reasoning_delta`；
- Bridge 每轮把插件插入 patch，SSE 转发 delta；AI 页边收边渲染，不再等完整思考；
- ASK_USER：`multiple:false/true` 分别渲染 radio/checkbox，非按钮；支持自定义答案；
- 文件解析：text/PDF/DOCX/XLSX；图片解密到沙箱 attachments，DSH 可 read_image；
- 模型/effort 已修正为 DSH 实际 deepseek-flash/v4-pro 与 off/low/high/max，context 1M。


## 90. 抽屉刀把型 + 工作中折叠块（2026-10-31）

- AI 抽屉页面取消全局右 padding；上方消息/工作区全宽，仅底部 `.ai-composer` 留 64px，
  形成按钮区域上方全宽的刀把型。
- 回复过程：工作块在正式回复上方，一级标题「工作中 · mm:ss」可收起；
  内部每个思考/工具调用是二级可收起项；最终回复完成时（final）自动收起工作块。
- 工作块使用灰色底、计时器、二级折叠；完成后标题变「工作完成」。


## 91. 工作中块去蓝色底纹（2026-10-31）

- `.ai-work` 背景改为中性灰 `rgba(120,120,120,.065)`，边框 `rgba(120,120,120,.16)`，虚线分隔同理；
- 标题/计时/二级项保持 muted 灰色小字，不使用主题蓝色。


## 92. 工作中块无底纹 & 回答归入工作（2026-10-31）

- `.ai-work` 背景/边框全部移除，只保留灰色小字标题、计时和折叠项；
- ASK_USER 的回答不再生成蓝色用户消息气泡：sendChat({answer}) 隐藏输入气泡，
  hist 记录 role=answer，回答作为工作块里的「你的回答」二级项；
- 会话渲染时 role=answer 显示为灰色「你的回答：…」注记，不是用户消息。


## 93. AI 消息 Markdown + KaTeX（2026-10-31）

- AI 页内置本地 vendor：marked、DOMPurify、KaTeX + auto-render（含字体），不依赖 CDN；
- AI 消息渲染 Markdown（标题/列表/表格/代码/引用/链接等），DOMPurify 清洗；
- 行内 `$...$` 与块级 `$$...$$`/`\[...\]` 公式渲染；
- 块级公式先占位再交给 KaTeX，支持多行 aligned/cases；
- 流式过程中逐 delta 重渲染，最终消息同样渲染。


## 94. AI 回复停止（2026-10-31）

- 发送中发送按钮变 ■，点击或按 Esc 调用 stopGeneration；
- `/api/ai/dsh/stop` 按 run_id 终止 DSH 进程；
- 前端 AbortController 中止 SSE，将已收到的部分内容保存为完整 assistant 回复（无内容则“已停止”）；
- 工作块标题显示「已停止」并自动收起；按钮恢复 ↑。


## 95. 抽屉新对话刀把型（2026-10-31）

- 修复 showPanel("chat") 在抽屉误设 panel-open 导致新对话空白；
- 新对话空态沿用刀把型：页面内容全宽，底部 composer 仅右侧留 64px 给按钮列。


## 96. 抽屉新对话真正全宽（2026-10-31）

- 修正：`.ai-composer` 的 64px 右留白仅在 `body.has-chat`（对话贴底时）生效；
- 新对话空态 composer 不使用右留白，输入区真正全宽；
- 对话开始后 composer 贴底，再收窄给按钮列。


## 97. 历史页改为会话列表（2026-10-31）

- 历史面板不再倒序列出当前会话全部消息；
- 改为按 updated 倒序显示 session 列表：标题、时间、模块、消息数、模型；
- 当前会话高亮，点击行加载该 session 并关闭面板；
- 打开历史面板时刷新 sessions。


## 98. 会话状态与中止标记（2026-10-31）

- 会话列表状态优先级：运行中转圈 > 需要用户回答黄点 > 新回复未读绿点；
- `/api/ai/sessions` 返回 running（DSH_RUNS 关联 platform_session_id）；
- session 保存 needs_response/unread；助手消息保存 stopped；
- Esc/停止后消息下显示红色「已中止」；
- 修复 session 消息保存：content 兼容 text 字段，role=answer 允许保存。


## 99. Session 消息 content 规范（2026-10-31）

- 保存规范使用 `content`；前端 sessionMessages() 将 hist.text 映射为 content；
- 兼容旧数据：后端 `_ai_session_save` 接受 content 或 text，`_ai_session_public` 补 content；
- 加载时前端优先 content，兼容 text；
- 完整恢复 role=answer、files、stopped（红色已中止）。


## 100. 工作内容恢复、上下文压缩、长会话窗口（2026-10-31）

- assistant 消息新增 work[]（thought/tool/answer 的 title/text/status），后端保存/返回；
  历史加载后渲染为可展开的「工作完成」块，content 只负责正式回复。
- DSH compaction-basic patch 改为 thresholdRatio 0.9、retainRatio 0.2，自动摘要压缩；
- 模型上下文按 model_contexts 自动切换（flash/v4-pro 均 1,000,000）；
- 长会话只渲染最近 30 条消息，顶部「加载更早」每次 +30，避免一次渲染全部 DOM。


## 101. 完整流事件持久化（2026-10-31）

- assistant 消息除 work[] 外新增 events[]，保存 SSE 原始事件（thinking/tool_call/tool_result/text/status/final/run 等）；
- 后端每事件字符串上限 8k、最多 600 条；前端恢复后工作块里出现「完整事件流 · N」可展开项；
- 搜索、抓取网页等表现为对应 tool_call 的 tool 名称、input、result 原样保留；
- 同时保留 work[] 便于快速展示，content 只存正式回复。


## 102. 删除 work 字段，统一由 events 派生（2026-10-31）

- session 消息只保存 content + events + stopped/files；work[] 不再写入；
- 工作块渲染由 workFromEvents(events) 派生：reasoning/thinking→思考，tool_call/result→工具，user_answer→你的回答；
- 旧 session 的 work 在读取/保存时自动迁移为等价 events，并移除 work；
- 事件流仍是完整 SSE 原始事件，可展开「完整事件流 · N」。


## 103. AI 抽屉首开加速（2026-10-31）

- shell 进入模块后 220ms 预加载隐藏 AI iframe（/p/ai/?drawer=1&preload=1&module=...），首开直接复用；
- AI 页启动改为：先 loadMe + 渲染 localStorage 缓存，再并行 loadDshStatus/loadStatus/initSessions；
- 静态 js/css/font 资源带 immutable 缓存和 gzip/ETag；
- 实测首开 0.2s 内可交互（预加载后）。


## 104. 回复完成后释放发送状态/终止提示外置（2026-10-31）

- final 事件到达即通过 Promise.race 结束 sendChat，发送按钮恢复↑，无需手动中止；
- 后台 SSE 由 AbortController 收尾，避免“说完了但还显示停止”；
- 初始等待不再写“思考中”，等待气泡为空并隐藏，只显示工作中块；
- “已终止”红色提示移到 AI 消息气泡外（ai-msgs 同级）。


## 105. 修复 AI 抽屉被误降级为低性能（2026-10-31）

- 原因：预加载隐藏 AI iframe 时，iframe 自身 FPS 检测把 data-perf 置 low，触发低性能 CSS（背景/阴影变化）；
- iframe 现在继承父页面 data-perf，并 MutationObserver 同步，不再自己跑 FPS 降级；
- 移除父页面 FPS<38 的自动低性能切换，仅保留 reduced-motion / save-data / 低硬件条件；
- 预加载期间设置 __KP_PRELOADING_AI 防止误判；打开抽屉时重新 applyThemeToFrame。


## 106. 实时 FPS 角标（2026-10-31）

- 页面左下角（调试按钮上方）显示 500ms 采样的实时 FPS；
- 绿色≥50、黄色30-49、红色<30；
- 只统计 shell 页面 rAF，不读取 iframe 内部。


## 107. 日程工具 update/delete + FPS 位置（2026-10-31）

- 日程 AI 工具新增 schedule_update（id 必填，可更新 title/date/endDate/start/end/startMin/endMin/tag/place/placeCode/note/reminders/mentions/participants）与 schedule_delete；
- 仅创建者可改删；更新做冲突检查并保留 creator/created_at，刷新日程 UI；
- FPS 角标从页面左下移到顶部右侧、用户信息左侧。


## 108. 用户菜顶层 + MinerU PDF 解析（2026-10-31）

- header.top z-index 5→110，user-menu 90→120；顶层下拉不再被 AI 抽屉/调试/FAB 遮挡；
- MinerU Standard API 集成：token 加密存 data/mineru.json.enc；
- PDF 先走 MinerU（batch 上传 → 轮询 → zip 下载 full.md），结果缓存 data/mineru_cache，失败回退 pypdf；
- 使用 requests 做 OSS 签名 PUT（urllib 会自动加 Content-Type 导致 SignatureDoesNotMatch）；
- 实测上传 PDF 后 DSH 回答出 MinerU 解析的关键词 HELLO_MINERU。


## 109. MinerU 默认链路 + 管理页 Token（2026-10-31）

- PDF 附件进入 AI 时默认先走 MinerU（配置 token 时），失败回退 pypdf；
- 管理 → AI 服务 新增「MinerU PDF 解析」区：状态显示掩码 token、输入框、保存/清除；
- GET /api/llm/admin 返回 mineru 状态；POST /api/llm/admin/mineru 管理员保存/清除，token 加密存储。


## 110. MinerU Token 输入/到期检查（2026-10-31）

- 管理页 MinerU Token 输入保存后保留在密码框中，可重复点击「检查到期」；
- POST /api/llm/admin/mineru/check 验证 Token（v4/application/status）并返回到期/剩余天数；
- MinerU Token 官方有效期 90 天，保存时记录 created_at/expires_at；已有 token 首次保存补记录；
- 到期天数为「按保存时间估算」，页面已标注。


## 111. MinerU 管理卡视觉升级（2026-10-31）

- 管理页 MinerU 区改为独立卡片：图标、标题、状态胶囊、Token 输入框（钥匙图标 + 显示/隐藏）、90 天进度条、保存/检查/清除按钮和状态消息；
- Token 输入框保存后保留内容；进度条按剩余天数显示；
- 状态胶囊区分已配置/即将到期/未配置。


## 112. 根壳按钮系统补齐（2026-10-31）

- 根壳 static/index.html 未加载 template.css，导致 .btn/.btn.primary/.soft/.ghost 全是原生按钮；
- 在根壳内补齐共享胶囊按钮样式（primary/soft/ghost/danger/sm、hover/active/disabled）；
- 管理页保存/检查/清除、添加服务商、保存全局配置等按钮统一为设计系统样式。


## 113. 设置/管理按钮统一走 .btn（2026-10-31）

- 个人设置与管理面板所有操作按钮统一使用 `.btn` 基类 + primary/soft/ghost/sm 变体；
- 左侧页签改为 `.btn.sm-item`，关闭按钮 `.btn.ghost.sm`，主题应用/保存 `.btn.primary.sm`；
- 主题色点、用户重置/删除、反馈回复/状态操作也统一走 `.btn`；
- 根壳补齐 `.btn` 基类（之前未加载 template.css，导致原生按钮）。


## 114. 日程地点 AI 工具（2026-10-31）

- 新增 schedule_place_list/create/update/delete；
- 地点存于 compat 全局 state.venues（code/name/short/address/note/lat/lng/custom）；
- update 可改 name/short/address/note/lat/lng，重命名同步更新日程 place/placeCode；
- delete 清理日程引用；
- UI action refresh_places：VenueStore.reloadVenues 从 /api/state 拉取并刷新地点列表。


## 115. AI 课程新增/修改/删除（2026-10-31）

- 新增 schedule_course_list/create/update/delete；
- 自定义课程存 data/schedule_courses.json，叠加到 schedule.json 静态课程后参与课程表/周网格派生；
- 字段：code/name/cn/module/credit/prof/prof_en/venues/schedule[{weeks,day,slot,span,venue,note}]/exams；
- 仅 AI 创建的自定义课程可改删，静态课程只读；页面通过 /api/schedule/courses 合并并 reload。


## 116. AI 抽屉关闭网页/关闭面板（2026-10-31）

- 抽屉头部新增「关闭网页」：调用 goHome() 关闭当前模块网页并返回工作台；
- 新增圆形 ×：只关闭 AI 抽屉，不离开模块；
- 与「打开模块」并排。


## 117. 链接内嵌关闭 + 课程单一数据源（2026-10-31）

- 修正「关闭网页」语义：AI 消息里的 http(s) 链接触发页面内 link viewer（iframe）；顶部「关闭网页」关闭预览，Esc 也可关闭；不再关闭模块或整页。
- schedule 改为单一可写 store `data/schedule_store.json`（version 2）：seed 自 schedule.json 一次，运行时课程/考试/特殊安排/节假日/slots 全部从 store 读取；前端不再请求/渲染 schedule.json 课程。
- 所有课程（含 seed）可 create/update/delete；source 仅标记 seed/ai。
- 课程事件 tag 改为课程缩写（code）；考试特殊安排保留 isExam。
- 新增 schedule_refresh / schedule_course_refresh，前端 refresh_courses 只重构课程表/周视图，不 reload 页面。


## 118. 考试/节假日单一数据源 + 课程 tag（2026-10-31）

- 考试、节假日统一存 schedule_store（exams/holidays），课程内嵌 exams 迁移到顶层并去重；
- 新增 exam/holiday 的 list/create/update/delete AI 工具；
- 前端只读 store：DATA.courses/exams/holidays 全部来自 /api/schedule/courses，不再请求 schedule.json；
- 课程事件 tag 改为课程 code；refresh_courses 同时刷新课程、考试、节假日，不 reload 页面。


## 119. 12/19 考试迁移 + 课程事件清理（2026-10-31）

- 个人日程里 tag=考试 的 12/19 研究生入学考试迁入 store exams（第4场）和 specials（EXAM，Week15 周六）；
- 删除 84 条 source=course 的重复课程事件，事件库只保留个人日程；
- 前端考试/特殊安排不再只按课程 code 过滤，EXAM 等非课程考试可显示；
- 课程事件 tag=课程 code，考试特殊安排 tag=EXAM。


## 120. 特殊安排 AI CRUD / 数据驱动结论（2026-10-31）

- 新增 schedule_special_list/create/update/delete，覆盖 CARE/考试等不对齐课节的安排；
- specials 增加稳定 id；页面刷新同 refresh_courses；
- 运行时课程/考试/节假日/特殊安排/个人日程全部来自可写数据；schedule.json 仅首次 seed，不再请求；
- slots/meta 属于学期配置，不是日程清单；地点仍走独立地点库。


## 121. AI 刷新权限扩大到抽屉之外（2026-10-31）

- AI UI action 新增 reload_host：只重载当前模块 iframe（AI 抽屉之外的页面/表格/图表/状态全部刷新），AI 抽屉 iframe 保留，对话不丢；
- schedule_refresh / schedule_course_refresh 与课程/考试/节假日/特殊安排/地点结构变更均返回 reload_host；
- 不再依赖局部 refresh_courses 补丁。


## 122. reload_host 清除旧缓存（2026-10-31）

- 项目 JS/CSS 不再使用 immutable 长缓存，改为 no-cache+ETag；只有 AI vendor 资源长缓存；
- reload_host 给模块 iframe URL 加 _kp_reload=timestamp，强制 HTML/资源重新请求；
- 只重载 host，AI 抽屉与 DSH 上下文保留。


## 123. 特殊安排标题（2026-10-31）

- 12/19 考试作为 special code=EXAM 迁移时最初没有 title，agenda/dayEntries 对非课程 code 回退成“日程”；
- 已给 EXAM special 补 title=研究生入学考试，deriveSchedule 透传 title；
- agenda/dayEntries fallback 不再直接写“日程”，优先 title/course/note/code；缓存 bust 后正确显示。


## 124. Special 原生模型（2026-10-31）

- special 升级为独立日程实体：id/title/tag/weeks/day/start/end/venue/note/isExam，code/course 可选；
- 渲染直接用 title/tag，不再回退“日程”或依赖课程 code；
- 迁移现有 specials 补 title/tag/course；EXAM=研究生入学考试；
- AI special 工具 create 要求 title（不再要求 code），支持非课程安排；删除/修改按 id/title/code。


## 125. 修复 AI 工具 UI action 丢失（2026-10-31）

- final 释放发送按钮后，流式后台继续到 done，由 streamDsh 在 done 时向父页面 postMessage(kpAiUi)；
- 不再在 sendChat 的 final race 分支重复/提前处理 ui_events；
- 实测 AI 真正调用 schedule_refresh 后，host 变为 /p/schedule/?_kp_reload=...，AI 抽屉保持打开。


## 126. 考试/特殊安排显示 title（2026-10-31）

- 考试面板行改为 title/cn 优先：研究生入学考试 · EXAM；
- 周信息考试 chip 改为 cn/title 优先；
- special 先补齐 title/tag；grid、详情、agenda 统一显示 title；
- 所有 special 不再依赖课程 code 查名称。


## 127. 课程 tag 旧缓存修复（2026-10-31）

- 课程 tag 已是课程 code，但浏览器仍可能执行旧 venues.js（此前 immutable 缓存）；
- project HTML 输出时给本地 assets JS/CSS 自动加 ?v=mtime，URL 变化强制拉新；
- 项目资源 no-cache+ETag，不再 immutable；只有 AI vendor 长缓存；
- kitten 新会话验证 tags = EAF/FAC/PFV/MIE...


## 128. 删除重复关闭键 + 清空 puppy 日程（2026-10-31）

- AI 抽屉右上角 × 与右下角返回功能重复，删除 ×；保留右下角返回/关闭；
- puppy 名下 3 条个人日程已删除（每周例会 11/02、11/09、11/16），事件库为空；操作前备份 schedule_events.json。


## 129. 课程/考试/特殊安排按用户私有，节假日共享（2026-10-31）

- store 的 courses/exams/specials 增加 owner/participants/mentions；
- seed 数据归 kitten；puppy 初始课程/考试/特殊安排为空；
- /api/schedule/courses 与 AI course/exam/special 工具均按当前用户过滤；
- holidays 仍为共享数据，所有用户可见；
- 页面课程/考试/special 均按当前用户过滤。


## 130. CARE 并入 course.schedule（2026-10-31）

- course.schedule 支持显式 start/end（无需 slot/span），用于不规律课程；
- CARE 5 次课合并为 3 条 schedule：W2 16:00-18:00、W6-7 18:45-20:45、W11-12 10:00-12:00；
- 删除 CARE specials；specials 只剩考试类 4 条；
- 页面 deriveSchedule 优先使用 entry.start/end。


## 131. AI 会话操作与工具扩展（2026-10-31）

- 消息级操作：用户/助手消息下方「复制」，助手消息「Fork」为分支会话；
- 历史面板：移除下拉/清空/当前删除；圆 + 新建；进行中/已归档双 toggle；置顶/归档/恢复；仅归档可删除（后端强制）；
- 会话字段 archived/pinned，新增 /api/ai/sessions/flags；
- 所有模块增加通用工具 workspace_overview / schedule_agenda / map_place_list / module_state / scratchpad_*；
- wishpool 模块增加 list/create/approve/reject；默认 reasoning effort 改为 high，DSH prompt 要求先查数据再行动。


## 132. AI UI 会话操作/工具摘要（2026-10-31）

- 消息：用户与助手下方复制；助手 Fork 生成分支会话；
- 历史：圆 + 新建，进行中/已归档 toggle，置顶/归档/恢复；仅归档可删除；
- 工具：全模块 workspace_overview/schedule_agenda/map_place_list/module_state/scratchpad_*；wishpool 专属 CRUD；默认 effort high；prompt 要求先查真实数据。


## 133. AI 消息复制按钮弱化（2026-10-31）

- 复制改为气泡外部的小剪贴板图标（默认 42% 透明度，hover 才明显）；
- Fork 作为同排小文字按钮，仅助手消息；
- 使用 ai-msg-wrap 包裹气泡与操作，停止提示/工作块仍挂在气泡外部。


## 134. AI 跨模块工具 + 自动上下文快照（2026-10-31）

- 通用工具扩展到跨模块日程读写、许愿池、便签、地点、module_state、workspace_overview；
- DSH 每轮 prompt 自动注入当前用户数据快照（未来14天日程、课程、考试、节假日、便签/许愿池计数），不再要求用户重复提供上下文；
- schedule 模块工具数 36；mock/wishpool 14，跨模块 schedule/wishpool 双向可用。


## 135. 后端数据统一与沙盒快照（2026-10-31）

- DSH 每轮在沙盒生成只读 kp_backend_data.json：当前用户 schedule store/events + 可访问项目 state + users/roles；
- 不新增 AI 工具，数据通过沙盒文件直接读取；
- 课程/考试/节假日/special/venue 统一 schedule_store；删除 legacy schedule_courses.json；schedule.json 仅首次 seed；
- 地点 AI 工具与页面改为 store 单源，页面本地仅缓存，POST /api/schedule/venues 写回 store；
- 密钥、密码、加密 AI session、上传文件内容不进入快照。


## 136. 日程权限统一：owner/participant/mention（2026-10-31）

- owner：读/写/删除；
- participants：读/写，不可删除；
- mentions：只读；
- 规则统一到事件 API、AI schedule 工具、课程/考试/special 工具和日程页 UI；
- 事件 partial update 会保留原 participants/mentions，不再被默认值清空。


## 137. 事件角色目录（owned/participated/mentioned）（2026-10-31）

- 事件 canonical 文件：data/schedule/events/<id>.json；
- 每个用户三个角色目录：data/schedule/users/<user>/{owned,participated,mentioned}；
- 同一事件通过 symlink/hardlink 出现在所有相关角色目录（可多份，同一内容）；
- 沙盒 backend/{owned,participated,mentioned} 直连这些真实目录；
- 权限：owner 读写删，participant 读写，mention 只读，API/AI/UI 一致。


## 138. 全部日程数据角色目录 + 沙盒直读（2026-10-31）

- 课程/考试/special canonical 文件拆到 data/schedule/items/<kind>/<id>.json；
- 每个用户 owned/participated/mentioned 用 symlink 链接对应项，可跨角色重复出现；
- shared.json 保存 meta/slots/holidays/venues；事件 canonical 在 data/schedule/events；
- 沙盒 backend/{owned,participated,mentioned,shared.json,projects} 直读真实文件，不再生成 kp_backend_data.json；
- store 由 item 文件组合，写操作同步 item/role links。


## 139. 地点搜索 + 绑定保护（2026-10-31）

- 新增 map_place_search：调用高德 place/text，返回名称/地址/WGS84 坐标/距离；
- schedule_create 支持 placeCode；地点删除前检查所有日程绑定，绑定中返回 409；
- AI 工作流提示：search → place_create → schedule_create/update bind → update → unbind → delete event → delete place。


## 140. 生日专题主题（2026-10-31）

- data/birthdays.json 存 MM-DD；生日当天 _theme_for 强制返回生日 monochrome palette，用户不可选；
- 5 个生日 palette（烛光/彩纸/薄荷气球/星夜/奶油蛋糕），按 user+date 哈希选一个；
- 背景 monochrome 动态生成 6 级色，叠加 cake/balloon/confetti/star 透明 PNG，左下角生日卡；
- /api/birthday 可设置/清除生日；/api/theme 保存时生日锁定；
- 主题设置里生日当天禁用色卡/保存。


## 141. ComfyUI 生日素材库（2026-10-31）

- tools/generate_birthday_assets.py 调本地 ComfyUI（NoobAI-XL，768，batch5）生成 cake/balloon/confetti/star 各 10 张；
- tools/cutout_birthday_assets.py 用边沿 flood-fill 去背景、裁边、512px；
- 输出 static/birthday/library/<category>/*_cut.png；后端优先随机返回 _cut 素材；
- 前端生日卡随机选 cake/balloon/star，测试后生日已清除。


## 142. Qwen 生日素材 + 全界面生日接管（2026-10-31）

- 生成器改用 Qwen-Image-2.1：UNET qwen_image_2.1_int8_convrot + qwen3vl 8b + qwen VAE，1024、euler/simple、CFG1；
- 每类 10 张，cutout 去白底/洋红点框；
- 生日当天 global CSS 接管：卡片虚线彩带边、标题栏 ribbon、卡片角落贴纸/🎉、按钮礼物纹理、chip/divider/用户 chip 等至少 9 处；iframe 同步 birthday-mode；
- Qwen 批量生成在 balloon 时 ComfyUI 崩溃，当前 cake 使用 Qwen 素材，balloon 回退内置透明 PNG；重新生成器已切 Qwen，可继续补齐。


## 143. 生日素材统一风格 + 多色彩带 + 分类贴图（2026-10-31）

- stylize_birthday_assets.py：闭孔、14px 奶油外描边、独立柔和阴影、512 画布留白，输出 *_styled.png，后端优先使用；
- 彩带改为 5 色（birthday.colors），header 用多色 border-image；
- 面板类（section/sm-box/modal/ai-drawer）四角各贴一张；module 卡片单角一张；只给 primary 按钮加小贴图，避免逐控件堆叠；
- template.css + shell inline 双份，iframe 继承 birthday-mode/素材变量。


## 144. 生日贴图随机化/全素材（2026-10-31）

- paintBirthdayStickers 为每个 panel 四角、card、primary 按钮、输入框独立随机选素材；
- 所有 *_styled.png 素材池随机，不使用固定 a/b/c/d；
- 贴图统一 style：闭孔、奶油外描边、独立阴影、留白；
- 清除测试生日，避免当前账号被误判。


## 145. 生日模式修复 AI 抽屉错位/移除左下提示（2026-10-31）

- birthday CSS 不再对 .ai-drawer/.ai-side-panel 设 position:relative，AI 抽屉恢复 fixed，不会在页面底部露出；
- 删除左下角生日卡 #birthday-deco，只保留 Hero 与分类贴图；
- 随机贴图改为每控件独立选择，使用全部 *_styled 素材。


## 146. 生日贴图：不漏孔、随机几何（2026-10-31）

- 透明处理改为“只补不删”：alpha 轮廓闭合，绝不删除已有前景像素；
- 细黑内边缘仅保留距轮廓 >8px 的内部边缘，避免外轮廓出现虚线；
- 薄洋红引导线用 inpaint 修复，不再打孔；
- JS 生成 .bd-sticker-el：每个控件随机素材、边缘位置、尺寸 14–54px、角度 -25..25°；
- 大 panel 2–4 张，card 1 张，primary button 1 张；不修改 fixed 的 AI 抽屉。


## 147. 生日贴图平涂化（2026-10-31）

- stylize 先 medianBlur(7) + k-means(K=8) 把素材压成平涂色块，消除微小色差；
- 再闭合 alpha 补孔（不删前景）、inpaint 薄洋红引导线、内部 Canny 细黑边；
- 白色外描边+外层细黑边+独立阴影保持不变；
- 每个控件随机素材/边缘位置/尺寸/角度，避免“统一四角固定图”的僵硬感。


## 148. 生日贴图 Pantone 直映射（2026-10-31）

- 去掉 medianBlur；前景每个像素直接映射到 12 色 Pantone-inspired 色卡（Lab 最近色）；
- 离散标签做邻域多数平滑，清理微小色差/噪点，不产生连续 RGB 渐变；
- 保留原图深色线稿作为内部细黑边，避免 Canny 在纹理上生成噪声线；
- 白色外描边+外层黑边+独立阴影/完全 opaque 保持不变。


## 149. 生日贴图去掉内部描边（2026-10-31）

- 先 inpaint 原图深色线稿，再 PANTONE 直映射，使内部只剩相邻平涂色块，无内部黑边；
- 只保留外轮廓：白色粗描边 + 外层细黑描边 + 独立阴影；
- 测试生日已清除。


## 150. 生日生成提示词只要求色块（2026-10-31）

- 正向统一：made only of flat solid colour blocks / no outlines / no strokes / no line art / no border / no frame / no white outline；
- 负向增加 outline/stroke/line art/white outline/black outline/die-cut outline；
- 所有描边、白边、黑边、阴影只在 stylize 后处理里生成。


## 151. 四类 raw 重生成（2026-11-01）

- 用修正提示词（只平涂色块，无 outline/stroke/frame）重生成 cake/balloon/confetti/star 各 10 张 raw；
- Qwen 512px、batch10、16 steps，40张；cutout + stylize 全部重跑；
- raw 移到 <cat>/raw/，为不透明 RGB；最终 UI 使用 *_styled.png。


## 152. 生日配色跟随用户 + 全随机 banner/sticker（2026-11-01）

- 删除固定“星空/薄荷气球”主题；birthday palette 直接取用户保存的 theme color/colormap，生成同色系 birthday 5 色；
- 贴图资产 alpha 只有 0/255（不透明），移除 baked shadow，阴影改由 CSS drop-shadow；
- Hero 改为 4–6 张随机素材的 scatter 布局（随机 left/top/size/angle）；
- sticker 仍按控件类别随机位置/尺寸/角度。


## 153. 生日线状彩带/CSS 礼花（2026-11-01）

- 不再使用 confetti 图片作为贴图；section-head/sm-head/hr 用 CSS gradient 彩带；
- 生日配色为 monochrome 用户色 + 4 个协调色（HSL 偏移），无固定主题名；
- 顶部 Hero 4–6 张随机 scatter；sticker 只用 cake/balloon/star；
- 新增 #birthday-confetti：34 片 CSS 动态礼花，reduced-motion / low-perf 自动关闭。


## 154. 生日抠图容差/同心描边（2026-11-01）

- cutout 去掉宽泛洋红判断，容差从 65 收紧到 24，仅删除与边界采样色非常接近的像素，避免误删不同洋红；
- 描边改为同心环：art → 2px 黑 → 10px 白 → 3px 黑（1.5x）→ 4px 白，最外圈为白色；
- 贴图 alpha 只有 0/255。


## 155. 生日贴图换 Emoji（2026-11-01）

- UI 不再使用 cake/balloon/star PNG 作为贴图，改为 46 种生日/派对 Emoji 随机池；
- Hero 5–7 个随机 Emoji scatter，控件贴图也用 Emoji，随机位置/尺寸/角度；
- 删除 body 固定 cake/balloon 图片装饰；生成图片仅保留为素材管线，不作为 UI 贴图；
- CSS 礼花/彩带继续使用。


## 156. Emoji 扁平 PNG 化（2026-11-01）

- 文本 Emoji 会因字体不同乱码/样式不一；改用 Twemoji 扁平 SVG，cairosvg 渲染为 512 PNG；
- 每个 Emoji 生成 <slug>.png（白色描边，无黑边）与 <slug>_shadow.png（独立阴影层）；
- 前端用两个 img 层叠，不再依赖系统 Emoji 字体；hero/控件都走 PNG；
- 44 个唯一 Emoji 类型；生成脚本 tools/render_emoji_assets.py。


## 157. Twemoji 生日池/相关性权重/CSS 阴影（2026-11-01）

- 删除独立 shadow PNG；阴影改由网页 CSS filter: drop-shadow 渲染；
- Emoji 池精简为 43 个生日相关元素（蛋糕/气球/礼物/蜡烛/彩带/花朵/香槟/乐器等），去掉星星/灯球/镜子；
- 每个 Emoji 带 relevance 1–10；所有 panel 从全池选择；
- 选择权重 = relevance^(0.35 + t*2.35)，t 为尺寸归一化，贴图越大越偏向高相关元素。


## 158. Twemoji 颜色变体（2026-11-01）

- 每个基础 Emoji 额外生成 3 个 hue-shift 变体（+38°/+150°/+238°），保留白描边；
- 28 个基础 Emoji → 112 个候选条目，全部进入同一个相关性加权池；
- 生成脚本 tools/render_emoji_assets.py；无 shadow PNG，网页 CSS drop-shadow。


## 159. Emoji 变体保护人脸/肤色（2026-11-01）

- hue 变体不再整体旋转：HSV 检测肤色/人脸范围（h 4–30, s≥35, v≥45），该区域只做 8% 微调；
- 黑白/低饱和色不参与旋转；其余装饰色正常 +38/+150/+238；
- 28 基础 Emoji × 4 = 112 候选。


## 160. Emoji 分区调色（2026-11-01）

- 人脸用肤色掩膜重上肉色（1f973 基础图即为 flesh tone），变体只做轻微明度/饱和度变化；
- 增加 REGION_RULES：按 emoji + HSV 范围独立调色，如蛋糕奶油、纸杯蛋糕糖霜；各区域可给不同 targets；
- 其余装饰色仍做局部变体，不整体旋转整图。


## 161. Emoji 手动 Mask 表（2026-11-01）

- 逐张检查 28 个基础 Emoji，在 render_emoji_assets.py 的 MANUAL_MASKS 中手写归一化 ellipse/rect/ring/poly mask；
- 每个 Emoji 至少一个可调 mask，每个 mask 独立 method：hue 或 recolor（target HSV）；
- 人脸脸部不参与 mask，1f973 先重上肉色；帽子单独 mask 调色；
- 蛋糕/纸杯蛋糕/蜡烛/帽子/玻璃杯/花/爱心等只改对应局部，不整体旋转。


## 162. Emoji 魔棒区域（2026-11-01）

- 取消几何预设 mask；MANUAL_MASKS 改为 MAGIC_WAND_MASKS：每个区域一个或多个手工 seed；
- magic_mask 从 seed 取色，用 RGB 容差 30 做连通区域选择；
- 每个 Emoji 至少一个 seed，method 仍为 hue / recolor；
- 1f973 人脸保持 Twemoji 原始黄色，不再重上肉色；只有帽子有 magic-wand seed。


## 163. Magic-wand 语义不连通区域（2026-11-01）

- magic_mask 支持每个 mask 多个 seed，union 多个连通块；
- `mode="semantic"`：选取所有与 seed 颜色匹配的像素（可跨多个不连通块），只作用于 alpha 内；
- 默认仍为 connected；1f382 蛋糕、1f495 双心已使用 semantic mode；
- 1f973 人脸保持 Twemoji 原始颜色。


## 164. Emoji 语义分割（2026-11-01）

- SEMANTIC_SEEDS：每个区域手工 seed；同一语义可有多个 seed；
- 先用 skimage watershed（Sobel 梯度）做分割，再用 seed 颜色候选约束，避免区域吞并邻近部件；
- 同语义的多个 seed 会在同一个 mask 内 union，支持不连通；mode=semantic 可直接取所有同色组件；
- 1f973 人脸不设 seed，保持 Twemoji 原始颜色。


## 165. 真正的 SAM 语义分割（2026-11-01）

- 安装 segment-anything，下载 SAM ViT-B 到 data/models/sam_vit_b_01ec64.pth；
- 每个 Emoji 只做一次 SamPredictor.set_image；SEMANTIC_SEEDS 的每个 seed 作为 positive point prompt，multimask 取最高分；
- 同一语义多 seed 的 mask union；无 seed 的人脸不参与，保持原始 Twemoji 颜色；
- SAM 不可用时回退 watershed；当前 28 基础 ×4=112 已用 SAM 重新生成。


## 166. Emoji 源文件（2026-11-01）

- 每个基础 Emoji 保存 Twemoji 原始 SVG 到 static/birthday/emoji/svg/<slug>.svg（XML 矢量）；
- 渲染产物为 512 PNG：原色 <slug>.png + 3 个变体 <slug>_v1..v3.png；
- 没有每个 Emoji 的单独源码，统一生成脚本 tools/render_emoji_assets.py；
- emoji.js/index.json 是前端索引，不是图形源。


## 167. SAM mask 后修正 + 语义 HSV 策略（2026-11-01）

- SAM mask 后处理：alpha 交集、5x5 close、3x3 open、小连通块 <40 去除；
- RULE_LABELS 给每个区域标语义：cake_icing/frosting/candle_wax/hat_band/crown/petals/liquid/bottle/heart 等；
- HSV_POLICIES 按语义限制可调色范围：蛋糕奶油只能暖色、皇冠只能金色小幅、蜡烛蜡只能浅奶油、植物不进入 mask、人脸无 mask 保持原色；
- 28 基础 ×4=112 已重新生成。


## 168. 五瓣花语义归组（2026-11-01）

- SAM 每次 prompt 只给一个 instance mask；五瓣花追加 5–6 个花瓣 seed 到同一 rule；
- 同 rule 的所有 SAM instance mask 取 union，得到“所有花瓣一个语义 mask”；
- 1f338/1f33a 使用 6 个花瓣 seed，1f33b 5 个，1f337/1f339 3 个，1f490 4 个花团 seed。


## 169. 按用户 28 条顺序细化（2026-11-01）

- Windows 文件名顺序：1f3a9,1f9c1,1f33a,1f33b,1f36b,1f36c,1f36d,1f37e,1f38a,1f49d,1f56f,1f337,1f338,1f339,1f369,1f370,1f380,1f381,1f382,1f388,1f389,1f451,1f490,1f495,1f496,1f942,1f973,1fa85；
- 多区域规则：hat body/band、cupcake frosting/sprinkles/liner、sunflower petals/core、bottle body/label、popper cone/other、crown gems、bouquet red/yellow flowers、whistle 等；
- 12/16/18/24/25/26 不生成变体（1f337/1f370/1f381/1f495/1f496/1f942）；共 94 个候选；
- SAM + seed 颜色候选 + mask 后处理 + 语义 HSV policy。


## 170. 24-26 无变体/六项修正（2026-11-01）

- NO_VARIANTS = {1f495,1f496,1f942}，旧 _v 文件已清理；1f337/1f370/1f381 恢复变体；
- 1f380 全 ribbon union 重着色；1f38a 增加 contents seeds；1f36d 增加 lollipop 三套 palette（红橙黄/红黄绿/红白粉）；1f36b wrapper 仅 seed 色容差18；1f382 cake body 多 seed；1f389 cone/other 多 seed；
- 当前 28 基础 → 103 候选。


## 171. 24-26 无变体 + 内侧/外侧归组（2026-11-01）

- NO_VARIANTS 仅 1f495/1f496/1f942，旧 _v 文件已清理；1f337/1f370/1f381 恢复变体；
- 1f370 增加 slice 多层 seed；1f380 bow 增加内侧/结/尾巴 seed；1f389 cone 增加内壁/开口 seed；1f388 增加收口 seed；1f381 增加盒身/丝带 seed；
- 1f36d 使用 lollipop 三套 palette；1f36b wrapper 容差 18；共 103 候选。


## 172. 942 液体变体/37e瓶身/49d蝴蝶结/973口哨（2026-11-01）

- 942 解除 no-variant，液体 recolor 棕/酒红/白；
- 37e 瓶身多 seed + recolor 棕绿，标签米白；
- 49d bow 增加右环 seed，全 bow union，heart 不变；
- 973 口哨多 seed + negative face 点，face 原色；hat 单独 hue；
- NO_VARIANTS 只剩 1f495/1f496；106 候选。


## 173. 942恢复/37e/49d/973/370/56f 修正（2026-11-01）

- 942 液体 recolor 棕/酒红/白；37e 瓶身多 seed recolor 棕绿、标签米白；
- 49d bow 增加横向扎带与右环 seed，整条 ribbon 一个 union，heart 不变；
- 973 hat 增加主/亮条纹有效 seed，全 hat union 统一 recolor；whistle 多 seed + negative face；
- 370 拆 cake_sponge（黄/棕）与 cake_trim（红黄相/明度）；56f 蜡烛体新增 seed + recolor 紫黄；
- NO_VARIANTS 仅 1f495/1f496；106 候选。


## 174. 49d护红/973帽子层次（2026-11-01）

- 49d 增加 protect_red：bow recolor 后恢复原红色像素，左半心保留红色；bow 含横向扎带/右环全 union；
- 973 hat 用多 seed 覆盖主色+亮条纹、dilate 3 去小边缘，改 hue 保留原有明暗层次；face 原色；whistle 多 seed；
- 942 变体、37e 瓶身、56f 蜡烛体、370 sponge/trim 已生效；106 候选。


## 175. 339/369/382 精修（2026-11-01）

- 339 花瓣改用 hue_keep：只换色相，保留原 S/V 明暗层次；叶子不 mask；
- 369 糖粒和果酱拆开：糖粒任意色，果酱 recolor 只走红/暖色，不出现蓝；
- 382 使用 cake_top/cake_body 两组，4 个变体：红丝绒+白奶油、巧克力+开心果奶油、白蛋糕+芒果奶油、浅紫蛋糕；蜡烛/盘子 protect_white 不变；
- 当前 107 候选。


## 176. 369面包胚/382三变体/339色相（2026-11-01）

- 369 jam seed 移到顶部糖霜，避开内侧下方面包胚；糖粒独立任意，jam 仅红/暖色；
- 382 只保留 3 变体；cake_cream_wave 用空间区分 cream/wave，union 同一 mask 但不同 target；pistachio 改橄榄绿；v3 白蛋糕+芒果奶油；
- 339 花瓣 hue_keep，色相范围紫→黄（150/175/25），保留明暗层次；
- 106 候选。


## 177. 382 侧面波浪/底部奶油 + 369 面包胚（2026-11-01）

- 382 拆 cake_top（顶层）与 cake_cream_wave；cream/wave 同一 mask 内按原始 V 分色：亮部奶油、暗部波浪；3变体；
- 369 果酱只用顶部糖霜 seed；糖粒 seed 移到真实糖粒位置；内侧下方面包胚不进入 jam/sprinkles mask；
- 当前 106 候选。


## 178. 382 三段侧面（2026-11-01）

- 382 cake_layers：顶层 / 侧上 / 侧下同一 union mask，按 y 分三段；
- 每段各自 targets：顶层主色、侧上浅一档、侧下奶油色，保证侧面与顶层有颜色差异；
- 3 个变体；106 候选。


## 179. 382 盘子保护/区域阴影（2026-11-01）

- cake_layers 增加 protect_plate：恢复原图蓝灰色盘子，盘子不再被蛋糕染色；
- 每层按 mask 内原始 S/V 中位数做相对缩放，保留同组内原有明暗色差，不压成纯色块；
- 仍为 3 个变体。


## 180. 382 四段无横线（2026-11-01）

- 382 取消 y-band cake_layers；改为 4 个 SAM mask：顶面、侧上、侧下、底部缝隙；
- 每段 shade 用区域内 S/V 中位数相对缩放，保留原图明暗；
- protect_plate 恢复盘子；3 变体；106 候选。


## 181. 36b 四口味/细线跟随（2026-11-01）

- 删除手工几何 line_zone；所有区域只用原图 seed/SAM/颜色选区，不新建区域；
- 36b 固定 4 变体：红=草莓白巧、黄=牛奶白巧、绿=黑巧、蓝=榛仁；
- 巧克力本体和包装都可变；细红线用原图暗红 seed 单独选为 wrapper_line，跟随包装目标色；
- 共 107 候选。


## 182. 生日页面概率/变体（2026-11-01）

- index.json/emoji.js 改为 28 组 {base, relevance, variants}；
- 选贴图：按 size 计算 exponent=0.35+2.35*t，base 概率权重=relevance^exponent，越大越偏高相关 emoji；
- 选中 base 后，在该 base 的 variants 中等概率选一个；
- 28 组，共 107 个候选；生日页已用新逻辑。


## 183. 生日贴图遮挡/flip（2026-11-01）

- 新增 bdTryPlace/bdRectOverlap：每个 sticker 最多与已有 sticker 重叠 50%（按较小面积）；
- 每个贴图最多 24 次位置尝试，失败则跳过；hero 延迟到布局完成后放置，避免 0 尺寸；
- 贴图按顺序交替 scaleX(-1) 做水平 flip；
- 实测 17 个 sticker 最大重叠 30.8%，≤50%。


## 184. 生日基础概率层级（2026-11-01）

- 权重：蛋糕 🎂40/🍰20/🧁20；庆祝 6×10；爱心 3×5；🎀4；其他 13×0.2；酒 2×0.1；总161.8；
- 类别总概率：蛋糕49.44% > 庆祝37.08% > 爱心9.27% > 蝴蝶结2.47% > 其他1.61% > 酒0.12%；
- size exponent 仍为0.35+2.35t；选中 base 后 variants 等概率；前端允许 <1 权重。


## 185. Banner 布局优化（2026-11-01）

- 原因：banner 左侧是标题/副标题，sticker 只能用右侧空间；
- 改为 2 行 stratified slots（4–6 个），slot 随机打乱+jitter，尺寸 40–84，保持碰撞 ≤50%；
- 仍按交替 flip；避免原来随机散点堆在右端。


## 186. 概率扁平化（2026-11-01）

- 权重：🎂14/🍰10/🧁10；庆祝6×5.5；爱心3×4；🎀8；其他13×0.5；酒2×0.4；总94.3；
- 类别概率：蛋糕36.06% > 庆祝34.99% > 爱心12.73% > 蝴蝶结8.48% > 其他6.89% > 酒0.85%；
- 极差从40–0.1改为14–0.4，小概率事件显著提升。


## 187. 生日 banner 文案切换 + 未登录 landing 提示（2026-11-01）

- 生日 hero 文案 5 组，点击 `.bh-copy` 循环切换；
- 新增公开 `/api/birthday/public`，只返回 active bool，不暴露用户名/生日；
- `/` landing 未登录时如有人过生日显示可点击生日提示条，并加生日背景纹理；无生日隐藏；
- 登录后的 `/home` 仍应用完整生日主题。


## 188. 登录态 landing 生日显示（2026-11-01）

- 未登录 `/` 不显示任何生日信息；
- 登录后访问 `/`：若本人今天生日，大标题（#tagline）切换为5组生日祝福，点击循环；不显示 banner；
- 若非本人但有其他人过生日，显示通用 banner，5条祝福，不写“许愿”类不实文案；
- 已登录生日态优先于 banner。


## 189. Landing 跟随登录用户主题（2026-11-01）

- 登录后访问 `/` 额外拉 `/api/theme`，把 bg/ink/soft/deep/accent/tone 写入 CSS 变量；
- kitten 粉色、puppy 蓝色已验证；未登录不拉 theme，保持默认；
- banner 仅在非寿星登录时显示，为通用文案；寿星本人改大标题。


## 190. 生日 banner 改为提示性文案（2026-11-01）

- 非寿星登录时的 banner 不写“有人过生日/主角/许愿”，改为“今天似乎有点特别/日历被圈了一下/适合说祝福”等提示性文案；
- 寿星本人仍显示明确大标题生日祝福；
- 未登录不显示。


## 191. kitten 1101 生日全页面观察（2026-11-01）

- kitten 生日设置为 11-01，当前 active；
- `/` landing 登录 kitten：大标题生日祝福 + 6 个 landing sticker，无 banner；
- `/home`：11 个 shell sticker + hero；module iframe 无 banner；
- `/dashboard`、`/mock`、`/wishpool`、`/ai`、`/courtyard`：shell sticker + iframe sticker 均有；iframe `.birthday-hero` = 0；
- module 内部只保留 sticker，不出现 banner。


## 192. module 巨大 sticker 修复（2026-11-01）

- 原因：iframe 的 template.css 只有 .bd-sticker-el，没有 .bd-emoji-face 的 width/height 100%，img 使用 512 原始尺寸；
- 修复：template.css 补 .bd-emoji-face absolute inset 0 width/height 100% object-fit contain；iframe sticker 恢复 30–54px；
- module 内仍无 banner。


## 193. 生日日期切换动画/6视频（2026-11-01）

- 进入生日：sticker scale 0→1.5→1、hero/banner 进入动画、线条突变；
- 离开生日：sticker 淡出缩小、hero/banner 上移淡出、线条 opacity 过渡，850ms 后恢复；
- iframe 用 setFrameBirthday 同步 enter/leave；
- shell 每60秒对比 /api/theme birthday.active，日期翻转自动 applyPalette；
- 生成 6 个 webm：landing enter/leave、home enter/leave、module enter/leave。


## 194. Panel/背景/大字动画（2026-11-01）

- `animatePanels`：主题切换时 card/section/sm-box 从 translateY(10px)+opacity .72 过渡回来；
- html/body 与 card/section/sm-box 加 background-color/border/box-shadow 过渡；iframe template.css 同步；
- 生日 Hero 文案点击时先 bh-fading（opacity/translateY）再换字；
- landing #tagline 点击改文案走 tag-fade 淡出→更新→淡入；
- kitten 生日仍 11-01 active。


## 195. 6视频重渲染（2026-11-01）

- 用最终动画重录 6 段，文件名不变：01-landing-enter / 02-landing-leave / 03-home-enter / 04-home-leave / 05-module-enter / 06-module-leave；
- 包含 panel 位移过渡、背景/panel 颜色过渡、hero/tagline 淡入淡出、日期切换 sticker/banner 动画；
- kitten 生日仍 11-01 active。


## 196. Panel 重排动画/大字对称淡入淡出（2026-11-01）

- 新增 capturePanelPositions/playPanelReflow（FLIP）：banner 插入/移除导致 card/section 位置变化时，先反位移再 .45s 过渡；
- landing `__landingSetBirthday`/`__landingLeaveBirthday` 都走 `fadeSwap`，大字进入/退出都是淡出→换字→淡入；
- 重录6视频，文件名不变。


## 197. Banner 高度渐变/panel 平滑让位（2026-11-01）

- .birthday-hero 改为 max-height 0→320 + padding/margin/border/opacity 过渡，panel 随高度连续移动；
- 进入先 collapsed → 强制 reflow → expanded；离开 collapsed，850ms 后移除；
- landing 大字进入/退出统一 fadeSwap；
- 重录6视频，文件名不变。


## 198. 基本信息/年龄/贴图摆动（2026-11-01）

- 个人设置新增“基本信息”选项卡，只含生日（date，含年份）；主题页生日设置移除；
- 后端支持 YYYY-MM-DD，GET /api/birthday 与 birthday palette 返回 age；
- 生日 Hero 第2/4/5组大字、landing 第3/4/5组大字显示年龄（有年份时）；
- .bd-emoji-face/landing-sticker 做中心固定摆动：rotate -15°~15°、scale .9~1.1，5.2–7.8s 周期随机；reduced-motion/low-perf 关闭。


## 199. Banner sticker 裁剪修复（2026-11-01）

- 原因：高度动画给 .birthday-hero 设了 overflow:hidden，顶部/边缘 sticker 被裁；
- 修复：.birthday-hero overflow:visible，靠 max-height + opacity 控制高度动画；copy 在 opacity 0 时不露；
- 卡片本身 birthday mode 已有 overflow:visible；module host 也 visible。


## 200. 时光漂流瓶 module（2026-11-01）

- 新模块 `bottle`，路径 `/bottle/`，manifest + project.py + web/index.html；
- 数据 `{bottles:[{id,from,to,message,openAt,createdAt,opened,openedAt,color}]}`；
- 服务端 `/api/p/bottle/state` 按当前用户过滤：所有人看到公共元数据，正文只给 from 或已打开的 to；
- action create/open：open 仅 to、已到 openAt、未打开时可执行；open 后从池子移到已打开；
- 生日 Hero 增加快捷链接“在漂流瓶里许一个生日愿望”，跳转后默认收件人自己、openAt 下一年生日；
- 不同用户按 from 哈希分配不同小船颜色；打开有船上/信纸动画。


## 201. 漂流瓶去掉公共信息 panel（2026-11-01）

- 删除顶层“时光漂流瓶”说明/统计 section，只保留“小船池”“已打开”两个 section；
- compose/refresh/chips/rev 并入“小船池”section-head，与其他模块一致；
- 删除 #who 引用。


## 202. 漂流瓶 UI 优化/示例数据（2026-11-01）

- 卡片改为海面场景 + 内联 SVG 小船（船体/双帆/桅杆/波浪/小旗/太阳，按 from 颜色着色）；
- 增加可开启/等待/不是给你的/你写的状态徽章，卡片 hover 轻抬；
- 已打开信纸样式优化；打开弹层使用同一 SVG 船动画；
- 以 puppy 视角放入 5 个示例瓶（1 个已打开、4 个未打开，含给 kitten 的未到期瓶）。


## 203. 小船池海面改造（2026-11-01）

- 小船池改为海面场景：波光/水纹动画、漂浮小船、悬停才出现信息气泡；
- 船为内联 SVG（船体/双帆/桅杆/旗/阳光/倒影/波浪），按 from 用户主题色着色；
- 船色来自 /api/users/public 的 theme color，创建时也写入主题色；旧瓶子前端覆盖显示；
- 以 puppy 视角放 9 个未打开 + 3 个已打开示例。


## 204. 漂流瓶 WebGL 3D 海面（2026-11-01）

- 引入本地 `static/bottle-three.min.js`；小船池改为 Three.js canvas；
- 水面 ShaderMaterial：波纹顶点位移 + 碎光/高光片元；无 panel 边框，CSS radial mask 软化边缘；
- 纸船为真实 BufferGeometry：左右船体/船底/船头船尾/甲板/双帆/桅杆/阴影；随机位置、缩放、朝向；
- 相机右键拖动 orbit（azimuth/polar），双击复位；悬停用屏幕投影选最近船，fixed 气泡显示；
- 船色按写信人主题色；puppy 示例 8 未打开 + 4 已打开。


## 205. 漂流瓶海面天空/固定光/光追阴影（2026-11-01）

- 海面分为天空穹顶和圆形水盘两个 mesh，能看见地平线；
- 水盘 CircleGeometry 半径 13，边缘 alpha 淡出；整个 canvas 用 radial mask + 页面色 fade overlay，四周淡出无边框；
- 固定 DirectionalLight（位置/方向固定），水面 shader 使用 uLightDir 做高光，并对最多 12 条船做 ray-sphere 遮挡计算生成阴影；
- 船 mesh castShadow，renderer PCFSoftShadowMap；
- 水 shader 使用径向均匀波纹 + 小型 hash 闪光点。


## 206. 漂流瓶水面模型/船物理（2026-11-01）

- 水面换成 3 组 Gerstner 波：Shader 顶点位移/法线 + CPU `waveAt()` 同参数采样；
- 船物理：按波高调整 y、按波斜率做 pitch/roll，波推 + 阻尼漂移、缓慢转向、边界反弹、船间软排斥；
- 天空穹顶/圆形水盘分离；固定平行光 + 水面 ray-sphere 船影 + PCFSoft 阴影；
- canvas 四周 mask + 页面色 fade；Three.js WebGL 视口。


## 207. 漂流瓶玻璃瓶/Cannon 物理（2026-11-01）

- vendored `static/cannon-es.js`；动态 import；
- 小船池对象改为透明玻璃瓶：瓶身/瓶肩/瓶颈/软木塞/标签带/瓶中纸卷/玻璃边缘高光；
- 每个瓶 Cannon Body（圆柱 mass .58），6 个沿瓶轴采样点按波高施加浮力，作用点产生力矩；
- 阻尼/波推/边界/船间碰撞；阻尼回正约束保持瓶口向上，波面斜率驱动 ±0.2rad 摇摆；
- 位置 y 稳定在水面附近，瓶体约半浮；打开弹层使用 SVG 玻璃瓶。


## 208. 漂流瓶玻璃材质/厚度光照（2026-11-01）

- 瓶身用 MeshPhysicalMaterial：transmission .22、thickness .12、ior 1.48、attenuation、clearcoat、specular、envMapIntensity；
- 程序化等距柱状天空贴图 → PMREM 环境贴图，给玻璃提供反射/高光；
- 额外 glassTint 薄壳 + 玻璃边缘线 + 标签/软木塞/纸卷，保证透明瓶在深色水面上仍可读；
- Cannon 刚体继续负责浮力/碰撞；打开弹层用玻璃瓶 SVG。


## 209. 海面透明/光感/渲染半径（2026-11-01）

- 水面材质改为透明 alpha（0.74+fresnel*.2），depthWrite false；可见水下瓶体；
- 水盘半径 13→22，alpha 边缘 fade 从 14→21；CSS mask/fade overlay 同步放宽，避免半径附近过快消失；
- 曝光 1.25、固定平行光 2.7、hemisphere 1.35；水面增加 Fresnel 天空反射、两次高光采样、sun-path 反射；
- 当前不是多级路径追踪：每片元 1 次视线着色、最多 12 条指向固定平行光的 ray-sphere 船影遮挡射线、2 个高光采样；玻璃为 PBR 近似。


## 210. 漂流瓶 WebGL2 真实光线追踪（2026-11-01）

- 新增 `static/bottle-raytrace.js`，全屏 WebGL2 fragment shader 光线追踪器；
- 每像素 primary ray，trace loop 3 次 bounce（性能预算），每命中玻璃/水面额外 1 次反射；
- 玻璃为薄壁 SDF：`max(outer, -inner)`，IOR 1.5，进入/离开界面折射，Fresnel 反射；refract 为零时全反射 TIR；
- 水面 IOR 1.33，反射/折射；天空解析渐变；
- 最多 12 个瓶子 + 每瓶 paper rigid body 的 uniform；
- 固定 MAX_T=24、0.5 分辨率；原 Three canvas 隐藏，保留相机/物理/Cannon；ray canvas 接收鼠标。


## 211. 光追反射/固定渲染半径（2026-11-01）

- 玻璃/水面 Fresnel 反射改为 traceOne 一次真实反射采样，可看到瓶影/天空/水面；
- 玻璃高光增加太阳 glint；TIR 分支继续反射；
- 主 trace loop 仍为 5 bounces；每命中玻璃/水面额外 1 次反射采样；
- 固定 MAX_T=24 渲染距离、最多 12 瓶、0.62 分辨率，保持性能。


## 212. 漂流瓶 2D 上线（2026-11-01）

- `projects/bottle/web/index.html` 已换成 2D 圆环池；3D/Cannon 页面代码移入 `projects/bottle/archive/3d-index.html`，不在 module 路由输出；
- 圆面积 = 持续天数 * 22；圆环厚度 = 半径 * 25%（时间进度带）；每个圆用 canvas shadow 投阴影；
- 质量 = 圆面积；拖动有惯性；固定动摩擦 26 px/s²；圆圆/圆墙碰撞 restitution .9；
- 悬停显示 from/to/开启日/持续天数/进度；主题色来自 from 用户；
- 2D 页面实际由 `/bottle/`、`/p/bottle/` 提供。


## 213. 2D 漂流瓶补回写瓶/已打开（2026-11-01）

- 顶部“写一个漂流瓶”按钮 + 刷新；
- 底部“已打开”区域恢复，显示 from→to、开启日、正文；
- 双击已到期的圆环可打开，弹层显示信件；
- 写入/打开后重新 seed 圆环并刷新 archive；
- 3D 页面仍在 `archive/3d-index.html`，不路由。


## 214. 2D 漂流瓶动画/透明视口（2026-11-01）

- `.stage` 去背景色和阴影，视口透明；
- 点击空白处打开写瓶弹窗并在该处插入；顶部按钮新建则随机位置；
- 新建动画：内圈瓶子出现 → 外侧灰色进度环绕一圈 → scale 1→1.5→1 落地 → 开始碰撞；
- 打开动画：点击到期圆环，中心瓶变打开态，绿色进度环 0→100%，随后进度环立即消失，内圈放大到 1.5 倍并淡出；
- 打开后移除圆环、更新已打开列表并弹层；动画期间不参与碰撞。


## 215. 2D 透明视口/深色进度环/打开动画验证（2026-11-01）

- `/api/users/public` 增加 `deep`，2D 圆环进度色使用写瓶人最深的主题色；
- 2D 的 html/body/stage 都改为 transparent，直接透出父页面背景；
- 新增 demo-ring-progress（37% 深红环）和 demo-open-1/2（到期大圆）验证；
- 打开：点击圆环 → 绿环顺时针 0→100% → 环立即消失 → 内圈 1.5x 淡出 → 移除并弹层；
- 录制 `bottle-2d-videos/open.webm`（大圆、绿环可见）和 spawn.webm。


## 216. 2D 瓶塞/打开分阶段（2026-11-01）

- 默认瓶形改为带软木塞的封口瓶；塞子有高光；
- 打开动画分段：绿环 0→100%（塞子仍在）→ 环消失 → 塞子淡出（0.62–0.78）→ 内圈放大 1.5x 并淡出（0.78–1）；
- html/body/stage 透明；进度环使用用户最深主题色（/api/users/public deep）；
- 重录 open.webm（大圆、瓶塞淡出、内圈消失）和 spawn.webm。


## 217. 瓶塞拔出/弹窗后入列表（2026-11-01）

- 默认瓶带软木塞；
- 打开动画 OPEN_DUR=2s：0–1.0s 绿环 0→100%；1.0–1.3s 塞子淡出并上拔；1.3–1.68s 停顿（约0.38s）；1.68–2.0s 内圈 1→1.5x 并整体淡出；
- 淡出后弹窗展示信件；弹窗关闭前 `pendingArchiveId` 排除列表，关闭后才进入已打开列表；
- 验证：弹窗显示时 archive 10 封，关闭后 11 封。


## 218. 生日漂流瓶锁定（2026-11-01）

- 生日 Hero 的 `.bh-bottle-link` 正常进入 2D `/bottle/` 并打开 compose；
- `birthdayCompose` 时收件人=自己、开启日=下个生日，两个控件 disabled；保存时强制这两个值；
- 普通“写一个漂流瓶”不受锁定；取消/关闭后重置。


## 219. 生日漂流瓶就地弹窗投放（2026-11-01）

- `.bh-bottle-link` 不再 goPath 到 `/bottle/`；在 shell 当前页直接打开固定收件人=自己、openAt=下个生日的浮动弹窗；
- 弹窗固定在顶部水平居中（top 72px），显示收件人/开启日（不可改）；
- 点击投放后：表单隐藏，5条“正在…”提示每520ms轮播，最少2.6s，同时 POST create 到 `/api/p/bottle/action`；
- 成功文案只保留“已经投放”（去掉容易被字体渲染成方块的 emoji），不跳转；关闭后留在当前生日页。


## 220. 漂流瓶文本框样式统一（2026-11-01）

- 生日弹窗 `#bb-message`、2D 写瓶弹窗 `#c-message` 均加 `.input`；
- 统一 11–12px 圆角、浅色背景、1.65 行高、focus 蓝色描边和柔光；
- goPath 切页时自动 bbClose，避免生日弹窗跨页残留。


## 221. 漂流瓶 AI 抽屉/我的漂流瓶抽屉（2026-11-01）

- 文本框 focus 描边/柔光改为 var(--accent)（随主题色，不再固定蓝）；
- 漂流瓶模块内 AI 抽屉按钮可见，iframe 以 module=bottle 打开；
- AI 按钮上方新增🍾“我的漂流瓶”按钮，打开同 AI 抽屉样式的右侧抽屉；
- 抽屉追踪所有 from=当前用户的瓶子：未打开显示“漂流中 + 三点动画”，已打开显示“已打开”；每5秒刷新。


## 222. 2D 悬停弹窗下方/位置持久化（2026-11-01）

- 悬停信息弹窗优先放在圆下方 8px，避免遮住进度环导致无法点击；空间不足才翻到上方，tip 仍 pointer-events:none；
- 拖拽后位置以归一化坐标写入 localStorage `kp_bottle_positions:<user>`，刷新/退出重进按 per-user 恢复；
- 保存时机：拖拽释放、延迟 260ms、新增/打开、pagehide；不同用户互不影响；
- 顶部“刷新”按钮从软 boot 改为真正 `location.reload()`；浏览器 F5 实测 `/bottle/` 保持模块、重载数据并恢复已保存位置。


## 223. GitHub Pages /bottle/ 路径壳（2026-11-01）

- 公网 `https://stjwls.github.io/kitten/KittenPuppy4Ever/bottle/` 之前没有静态路径壳，刷新直出 404；
- `tools/publish_frames.py` PATHS 增加 `bottle/index.html`，并修复缺失的 HERE；
- 已通过 GitHub API 发布 iframe 承载页（地址栏保持 github.io，内部 iframe 指向隧道 `/bottle/`），Pages 构建后返回 200；
- 以后新增路径只需加入 PATHS 后运行 `python tools/publish_frames.py`。


## 224. 未收件人瓶子提示/状态抽屉底边（2026-11-01）

- 点击进度100%但 to≠当前用户的瓶子：不打开，弹出 5 条提示轮播（“不是给你的瓶子哦！”等），每620ms切换、约3.4s收起；
- 新增 demo-locked-1（kitten→puppy、100%）用于验证；
- “我的漂流瓶”抽屉底部增加30px padding和18px渐变遮罩，避免滚动列表被圆角下边缘硬切。


## 225. 未收件人提示交互/抽屉底边（2026-11-01）

- 提示气泡默认不自动切换；点击气泡才切下一条，切换后重新计时 3s；3s 后消失；
- 气泡按自身宽度居中在瓶子上方；
- “我的漂流瓶”抽屉 bottom=122px：外圆角半径30与内部22px状态按钮同心（间距8px），状态 FAB 在抽屉内，AI FAB 在抽屉外；打开时不隐藏 FAB。


## 226. 抽屉按钮常显/位置服务端同步（2026-11-01）

- “我的漂流瓶”抽屉 bottom=122px，状态按钮落在抽屉内部底部；外圆角半径30、内按钮半径22、间距8，二者圆心均为 (1396,748)，满足同心；AI按钮在抽屉外下方；两个按钮都始终可见；
- bottle project 增加 `layouts[user][bottleId]={x,y}`；state present 只下发当前用户 layout；
- 新 action `save_positions`（或 `layout`）校验并保存归一化坐标；merge 保留 layouts；
- 2D 端从服务端 layout 恢复（localStorage 仅作离线/即时缓存），拖拽后 320ms debounce 推服务端，pagehide keepalive 推送；跨浏览器/设备同用户可恢复。


## 227. 生日 sticker 立即加载/漂流瓶透明背景（2026-11-01）

- 所有生日 emoji 资源改为 WebP（3.7MB → 0.8MB），并保留原 PNG；
- `preloadBirthdayAssets()` 在生日主题应用前注入全部 `<link rel=preload as=image fetchpriority=high>`（约152条），图片 `loading=eager`、`decoding=sync`；
- `/static/birthday/**` 返回 `Cache-Control: public, max-age=86400`，二次进入直接缓存；
- 2D 页面改为 body[data-project] 直接使用当前用户 `var(--bg)`；shell head 和 2D head 都先应用缓存主题并异步补拉 `/api/public-theme`；host iframe allowtransparency 保留。


## 228. 位置/主题持久化回退修复（2026-11-01）

- 之前服务端 layout 覆盖 localStorage，服务端保存稍慢时刷新会回退旧位置；现同浏览器 local 优先，新设备才用服务端 layout；
- shell `<head>` 增加缓存主题 bootstrap：读取 `kp_pubtheme_<lastUser>` 先设置 CSS 变量，避免闪烁米色默认背景；
- 2D 页面 boot 时也先应用缓存主题变量，再拉 API；
- 位置保存仍 debounce + pagehide keepalive 推服务端。


## 229. 始终使用用户背景色（2026-11-01）

- 漂流瓶 body[data-project] 不再透明，直接用 `var(--bg)`，避免白/米色透出；
- 2D head 和 shell head 都从 `kp_pubtheme_<user>` 先设置主题变量，并异步请求 `/api/public-theme` 校正；
- applyFrameTheme 在 userTheme 尚未加载时用 cachedPublicTheme 兜底；
- 同浏览器位置 localStorage 优先，新设备才用服务端 layout。


## 230. 全站用户背景色（2026-11-01）

- shell body 改为 `background: var(--bg) !important`，去掉硬编码渐变；登录层/boot splash 同样使用 var(--bg)；
- applyFrameTheme 给每个项目 iframe 的 html/body 强制写 `background-color: theme.bg !important` 和 `background-image:none`；
- shell/2D head 缓存主题 + 异步 public-theme 校正；所有页面背景统一为当前用户背景色。


## 231. 移动端适配/测试数据清理（2026-11-01）

- <=760px：header 压缩，隐藏 FPS/副标题，用户 chip 缩小；
- AI/我的漂流瓶抽屉统一 left/right 8px、全宽、覆盖页面，不再挤窄 host；
- 漂流瓶圆按 `min(1,W/980,H/620)` 缩放，移动端不再重叠；2D header 精简；
- 状态/AI FAB 提高 z-index，移动端可点击；
- 清空 `data/bottle/doc.json` 的 bottles/layouts（测试内容），rev 65；备份文件已删除。


## 232. 用户生日/年龄验证（2026-11-01）

- `data/birthdays.json`：kitten=2003-11-02，puppy=1999-04-02（完整年月日，年龄功能生效）；
- 模拟生日当天验证：kitten 23 岁、puppy 27 岁（按模拟日期），年龄随年份正确；
- 生日 Hero 点击切换到年龄文案："生日快乐，你 23 岁啦" / "今天，你 23 岁" / "你已经 23 岁了，继续闪闪发光"；
- 测试后已恢复正式生日。


## 233. 修改生日后刷新主题（2026-11-01）

- 个人设置保存生日后调用 refreshThemeAfterBirthdayChange()；
- 重新 GET /api/theme，写入用户主题缓存，applyPaletteAnimated，并强制 applyFrameTheme 当前 iframe；
- 进入生日：立即切到生日主题/Hero/贴纸；离开生日：按 bd-leaving 动画退出并回到普通主题；
- 已用 UI 从 2003-11-02 改到 2003-11-01 再改回验证。


## 234. Home 卡片自适应列数（2026-11-01）

- `.cards` 改为 `repeat(auto-fit, minmax(min(100%, 240px), 1fr))`，去掉 1060px 上限；
- `.home-tools` 同步满宽；
- 实测 1440px=5列、1024px=3列、390px=1列。


## 235. 顶栏大字页按钮/Safari 登录保持（2026-11-01）

- 用户 chip 左侧新增“🏠 大字页”按钮；
- 点击不修改 token/cookie/sessionStorage；iframe 内先向 GitHub Pages shim 发送 kpLanding，并保留 260ms 的 github.io 根路径兜底（绝不回退隧道域名）；
- landing 首屏从 kp_pubtheme 缓存立即上色，session/theme/birthday 并行请求；不再先闪未登录配色；
- 登录 token 写入仅保留在密码通过后的 doLogin；清除仅在退出/切换账号。


## 236. 移动端所有抽屉全宽（2026-11-01）

- <=760px：shell 的 `.ai-drawer`、`#bottle-status-drawer`、`.sched-drawer`、`aside.debug` 统一 left/right:0、width:100%、border-radius:0；`body.debug-open` 时 host/home-wrap 也不再让位；
- 只改宽度，不覆盖各抽屉原有 top/bottom（高度设置与叠放/z-index 保持）；
- AI 模块内 `.ai-side-panel` 同样全宽，top/bottom 与 panel-open margin 保持逻辑。


## 237. 设置/管理左侧目录可收起（2026-11-01）

- 两个 `.sm-box` 动态插入 `.sm-collapse-tab`；
- 点击后 `.sm-side` width/flex-basis 动画到 0，`.sm-main` padding-left 38px 避免按钮压标题；
- 状态存 `localStorage.kp_sm_side_collapsed`，两个弹窗共享；
- 收起按钮固定在弹窗左上，展开态 `‹`、收起态 `☰`。


## 238. 使用统计图表看板（2026-11-01）

- `data/activity.json` 记录 open/use/heartbeat 事件（最多 30000 条）；
- 打开模块由 shell renderProject 上报 `/api/activity`；功能操作由项目 action 自动记录；每分钟心跳；
- GET `/api/admin/activity?user=&days=365` 汇总：365 天热力图、24 小时时段、模块 opens/uses、用户分布；
- 管理·统计 pane 改为 dashboard：用户筛选、四张汇总卡、GitHub 风格热力图、24小时柱状图、模块双色条形图。


## 239. 页面布局模板：按钮集群 + 抽屉基类（2026-11-01）

- 顶栏=大标题，项目 pbar=模块标题；左右浮动按钮统一进 `.kp-fab-cluster`，`flex-direction:column-reverse`、gap10 从下往上等距；
- 抽屉统一 `.kp-drawer`，绑定 `data-button`、`data-side`、`data-scope`；
- 上边界：global=header.top 底部+12，module=#view-project .pbar 底部+12；
- 下/侧边界：按键中心 ± 30px（外圆角R30），保证按钮圆(r22)与外圆角同心；宽度固定360px；
- 当前 AI 抽屉=global/right，我的漂流瓶=module/right，调试=module/left；移动端仍全宽、top/bottom由基类计算。


## 240. 标题模板适配圆形按钮（2026-11-01）

- 大标题右上：大字页/用户设置改为 44px 圆形按钮（大字页仅🏠、用户显示 emoji 头像，名称进 title/menu）；FPS 保持为状态胶囊，不按钮化；
- 模块标题：返回按钮改为 44px 圆形「←」，与浮动按钮同尺寸/圆角语言；
- 所有圆按钮绑定 `.kp-round-btn` 模板（header/module/fab 变体），改模板变量即可批量换外观；路径 chip 等非动作信息保留胶囊。


## 241. 漂流瓶圆环最小尺寸修复（2026-11-01）

- 原因：生产数据只剩一个 1 天持续时间的真实瓶子，面积公式得到 r≈4.3px，25% 环宽≈1px，视觉上像坏掉的点；
- 修复：2D 圆半径加视觉下限 18px，area 按最终 r 回算（质量同步）；长持续时间仍保持面积与时间成正比；
- 桌面/移动端圆环恢复可见、可点击，同心/进度环样式不变。


## 242. 统计·模块分用户堆叠（2026-11-01）

- `/api/admin/activity` 的 modules 增加 `by_user[user]={opens,uses}`；
- 统计看板“全部用户”时：模块使用区显示用户颜色图例，每个模块两条堆叠柱（打开/功能），段按用户着色；
- 选择单个用户时恢复原来的打开/功能双色条。


## 243. Popup 基类/统一关闭按钮（2026-11-01）

- JS `KpPopup` 为弹出窗口基类，`KpDrawer extends KpPopup`；`.kp-popup` 统一 `--kp-popup-radius:30px`，四角一致；
- 仅非抽屉 popup 自动插入一个 `.kp-popup-close`（同时绑定 `.kp-round-btn--close` 模板）；原有 `.drawer-close/[data-close]/#bb-close/#bug-close` 隐藏避免重复；
- 抽屉不新增关闭按钮，收起由已绑定的集群按钮负责；
- 非抽屉关闭按钮尺寸44px（r22），top/right = R30 - 22 = 8px，与外圆角同心；
- 抽屉仍保持 `.kp-drawer` 定位/叠放逻辑，移动端全宽。


## 244. Popup 统一视觉/抽屉 scope（2026-11-01）

- `.kp-popup` 与 `.kp-round-btn` 一样模板化：根变量 `--kp-popup-bg/border-color/shadow/radius` + `--kp-popup--modal/--drawer` 变体；所有 shell popup（sm-box/modal-box/生日弹窗/抽屉）共享；
- 抽屉 scope：AI=module、漂流瓶=module、调试=global；
- module 抽屉 top = pbar 底部+12（完整在模块标题下），global = header 底部+12；
- 移动端抽屉仍全宽、圆角30、遮住 host，不改变 top/bottom 参考逻辑；
- `.modal` 层级提升到 300（header 110），修复移动端设置/管理弹窗被大标题/模块标题分割线压住的绘制次序问题。


## 245. Popup 样式嵌套/嵌套抽屉（2026-11-01）

- `.kp-popup` 结构化模板变量（bg/border/shadow/radius/layer），modal/drawer 变体；modal 层300高于header110；
- `.kp-fab-cluster--inset.left/right` 可用于 popup 内部按钮集群；
- `.kp-drawer--nested` 以父 `.kp-popup` 为移动视口：absolute inset0、宽高100%、圆角30，覆盖父内容；绑定按钮切换 open；
- 设置 popup 右下增加一个 inset 按钮与“界面说明”嵌套抽屉作为示例；全局/模块抽屉仍走原 base 定位。


## 246. 仅抽屉可收起/嵌套 mobile 视口规则（2026-11-01）

- 设置/管理侧目录本身改为左侧抽屉：`.sm-side` 滑入滑出，绑定 popup 内左下按钮；不再使用独立 collapse tab；
- 设置弹窗右侧保留“界面说明”嵌套抽屉，它是 modal 内的普通 360px 右侧抽屉，非移动端全屏视口；
- 嵌套抽屉仅在父级 `.kp-popup--drawer` 下使用 mobile 视口规则（absolute inset0/100%）；父级为 modal 时使用普通右侧 360px 抽屉；
- 所有“可收起”交互均使用抽屉语义（侧目录 / 嵌套说明 / 全局与模块抽屉）。


## 247. 同心圆 margin 规则 & AI 抽屉按钮归属（2026-11-01）

- m = popup 外圆角 R30 - 按钮半径 r22 = 8px；
- 非抽屉 popup 的左/右按钮集群 margin = 2m = 16px（含边框精确测量 16）；抽屉 popup margin = m = 8px；
- Popup 关闭按钮偏移 = R-r-border =7px，保证外沿同心；
- AI 抽屉的“历史记录/设置”属于 AI 抽屉的**右下按钮集群**（44px、margin m=8）；抽屉打开时 AI 开关也临时移入该集群，原全局位置用不可见占位保持其他按钮位置；
- KittenPuppy 网站本身不依赖 ComfyUI；代码库无 comfy/8188 引用。


## 248. AI 抽屉右下按钮/嵌套移动抽屉/滚动锁定（2026-11-01）

- 不存在“右上按钮集群”；AI 历史/设置与 AI 收起按钮都在 AI 抽屉右下集群；
- 历史/设置点击后打开 AI 抽屉内部的 `.kp-drawer--nested`，按移动端抽屉规则铺满 AI 抽屉；内容 iframe 用 `/p/ai/?drawer=1&panel=history|settings`，AI 模块支持初始 panel；
- 抽屉打开时 `body.ai-open { overflow:hidden; }`，锁住背景页面滚动，避免滚动条位置跳变；
- AI 抽屉底部预留 108px 给右下按钮，避免遮挡输入框发送键。


## 249. 移除自定义格式抽屉/统一同心圆（2026-11-01）

- 设置/管理左侧目录不再使用 172px、单侧圆角的自定义抽屉；改为标准 `.kp-drawer--nested`：宽360、四角R30、父 popup 内缩 2m=16；
- 所有抽屉走同一 popup 模板；侧目录只保留普通 padding/布局，不再覆写宽度/背景/单侧边框/圆角；
- 所有圆按钮走 `.kp-round-btn`；非抽屉 popup 左右按钮 margin=2m=16，抽屉按钮 margin=m=8，关闭按钮按 R-r-border 精确同心；
- AI 历史/设置/AI收起在 AI 抽屉右下集群，历史/设置打开移动端嵌套抽屉。


## 250. Popup宽度1/4窗口 & 同心margin（2026-11-01）

- `--kp-drawer-w: 25vw`；所有顶层/嵌套抽屉宽度统一为窗口 1/4（移动端仍全宽）；
- `--kp-ring-margin:8px=m`：抽屉与窗口/父 popup 边缘 margin=m；抽屉绑定按钮 margin=2m=16；嵌套 modal 抽屉 inset=m；
- 因此外层圆角 R30 的圆心与按钮 r22 圆心重合：m + R = 2m + r；
- 滚动锁定改为模板级：任一抽屉打开时 `html` 和 `body` 均 `overflow:hidden`，页面滚动条不再被抽屉覆盖，抽屉内部 iframe 滚动不受影响；
- 设置左目录为普通 `.kp-drawer--nested`，宽度、圆角、背景、边框全部来自模板，无自定义宽度/单侧圆角。


## 251. Popup 静态树/嵌套宽度1/4/半径逐层+m（2026-11-01）

- JS 静态树 `KP_POPUP_TREE` 声明窗口→抽屉/弹窗→嵌套抽屉关系，`kpPopupDepth` 一次性计算深度；
- 抽屉是 mobile popup 锚点：顶层抽屉圆角 r+m=30；非抽屉 Popup 包含抽屉时半径=38；
- **抽屉内部的嵌套抽屉按移动端原则：宽高100%、inset0、border-radius0**，不再按父级25%宽；
- 非抽屉 Popup 内的嵌套抽屉仍为父 Popup 的25%宽、圆角30；
- 抽屉边缘 margin=m（内边距扣除border），Popup 内部按钮 inset=R-r-border，使按钮圆与 Popup 外圆角同心；
- 滚动锁定对 html/body 全抽屉模板生效，页面滚动条不覆盖；
- AI 历史/设置抽屉此时为 AI 抽屉的25%宽（1440下约90px），这是要求的父级1/4规则。


## 252. 抽屉开启按钮绑定（2026-11-01）

- 每个 `.kp-drawer` 都有 `data-button` 指向开启它的圆按钮，静态树节点也记录 `button`；
- 设置/管理左右侧抽屉在 setup 时生成 `settings-side-toggle` / `manage-side-toggle`，并写回 `data-button`、`aria-controls`、`aria-expanded`；
- AI 抽屉绑定 ai-edge；AI 历史/设置绑定 ai-history / ai-drawer-settings；漂流瓶绑定 bottle-status-btn；调试绑定 dbg-toggle；设置说明绑定 settings-help-btn；
- 所有开启按钮保持 44px、右下/左下集群规则；点击切换对应抽屉，移动端内部抽屉仍全宽、无额外圆角。


## 253. 抽屉底边绑定开启按钮/同对象返回按钮（2026-11-01）

- 顶层抽屉底边 = 开启按钮中心 + 当前抽屉半径；AI 抽屉因按钮移入内部，使用其全局锚点位置计算，打开后保持不变；
- 非抽屉 popup 内嵌套抽屉（设置侧/说明）底边同样按开启按钮中心 + 半径计算（相对父 Popup）；
- 抽屉内移动端全宽嵌套抽屉仍 top/bottom 0，占满父级，不受底边计算影响；
- 所有开启按钮通过 MutationObserver 同步：打开时同一按钮对象文本变为 ←，关闭时恢复原图标；aria-expanded/aria-controls 同步，不新建返回按钮。


## 254. Popup-only 树/关闭键让位/AI右按钮模板化（2026-11-01）

- `KP_POPUP_TREE` 只含 Popup，不记录按钮；抽屉是叶子，抽屉内部的移动端全宽抽屉不进树；
- 抽屉锚点 R=r+m=30；非抽屉 Popup 若含抽屉子节点则 R=38（设置/管理）；AI 抽屉无树子节点保持30；
- 非抽屉 Popup 关闭按钮 z-index 70 始终最上；右侧嵌套抽屉 top = 关闭按钮底部 + m，实测8px，bottom仍按开启按钮计算；
- AI 抽屉右按钮（AI/历史/设置）是标准 inset cluster，始终显示，不再依赖 body.ai-open display，行为由统一 data-button/返回箭头模板驱动。


## 255. AI 抽屉按钮/返回主题/嵌套内容修复（2026-11-01）

- AI 右按钮固定 flex-basis/尺寸，禁用 hover transform，只在背景/边框/文字上过渡，消除悬停圆形漂移；
- 开启状态统一加 `.kp-trigger-open` 主题色，关闭移除；不再用 `.back` 类混用（避免详情返回与抽屉状态互相污染）；
- AI 历史/设置 iframe 父容器补 `display:flex; flex-direction:column`，iframe `height:100%`，解决 iframe 默认150px导致只显示顶部/设置空白；
- 关闭键 z70 最上；非抽屉 Popup 右侧嵌套抽屉 top=关闭键底部+m=8。


## 256. AI 修复回归为模板规则（2026-11-01）

- 撤回 AI 专属 hover/尺寸/显示/iframe CSS；
- hover 稳定、颜色过渡统一到 `.kp-round-btn`；
- 开启返回主题色统一到 `.kp-trigger-open`；
- 抽屉 iframe 高度统一由 `.kp-drawer` flex + `.kp-drawer > iframe` 规则控制；
- 抽屉右按钮空间由 `.kp-popup--drawer:has(> .kp-fab-cluster--inset)` 统一预留；
- AI 历史/设置按钮使用标准 inset cluster，不再有 body.ai-open 专属 display 或固定定位。


## 257. 移动端视口上下文/按钮margin=m（2026-11-01）

- `html/body` 在 ≤760px 加 `.kp-mobile-viewport`；每个 `.kp-drawer` 也加该 class（抽屉即移动视口）；
- 移动视口直接子级左右按钮集群 margin 从2m降到m（实测右边8）；
- `.kp-mobile-viewport` 下所有 `.kp-drawer--nested` 全部为移动端内部抽屉：inset0、宽高100%、border-radius0、不按父级1/4；
- 桌面设置/管理内部抽屉仍是父级25%、R30；移动端设置侧/说明抽屉也变成全宽无额外圆角；
- 规则只加在上下文 class 上，无 AI 专属分支。


## 258. AI 抽屉面板锁定/开启按钮同对象（2026-11-01）

- AI 抽屉 opener 不再移入抽屉：`#ai-edge` 保持全局右下集群同一 DOM 对象，打开只换图标/主题色，位置不弹跳；
- 移除 `body.ai-open .fab-bottle-status{display:none}`，其他按钮不再因 AI 打开重排；
- 抽屉内动作集群用 `data-trigger-external="1"` 通用规则上移 44+m+gap，位于外部 opener 上方；
- AI 模块 `/p/ai/?panel=history|settings` 增加 initial panel pin 1.8s，防止 init/newSession 的 showPanel("chat") 竞态把面板跳回聊天。


## 259. 移动视口子 popup margin=m（2026-11-01）

- `.kp-mobile-viewport` 下所有非抽屉子 popup（sm-box/modal-box/生日弹窗）宽度改为 `calc(100% - 2m)`，左右 margin=m（实测8）；
- 不再使用 92vw/94vw 产生的约2m侧边距；
- 抽屉内部移动端全宽抽屉仍占满父级（移动端规则）；非抽屉popup内部的嵌套抽屉仍 inset=m；
- 桌面端非抽屉popup尺寸不受影响。


## 260. 移动端子 popup 全宽偏移修复（2026-11-01）

- 移动视口下嵌套抽屉强制 `inset:0; width/height:100%; box-sizing:border-box; border-radius:0`，并提高选择器权重覆盖 data-side 的 m inset；
- 移动端 JS 不再为右抽屉计算 close-button top / opener bottom 的内联 !important，避免内联偏移盖过移动端全宽规则；
- 非抽屉 popup 宽度 calc(100%-2m)，左右各 m；设置侧/说明抽屉实测 x=9、width=372，与 popup 内部边界对齐；
- 桌面端仍保留嵌套抽屉 25%/m inset 逻辑。


## 261. Popup 内容与嵌套抽屉绑定动画（2026-11-01）

- 非抽屉 Popup 内容加 `.kp-popup-content`；使用 `:has(> .kp-drawer--nested.open[data-side])` 自动绑定左右抽屉。
- 内容 padding-left/right 与抽屉 transform 同步 `.24s cubic-bezier(.22,1,.36,1)`；
- 左抽屉展开 -> 内容 padding-left=25%+2m；右抽屉展开 -> padding-right 同步；关闭自动回收；
- 移动视口下内容 padding 固定18，抽屉全宽覆盖，不参与位移；桌面保留25%内容让位。
- 删除 settings/manage 自定义 `.sm-main` padding/side-drawer-closed 特例。


## 262. Popup 内容 padding 至少2m/初始位置修复（2026-11-01）

- `.kp-popup-content` 默认 padding=2m=16（四边）；左/右抽屉展开时内容 padding = 25% + innerMargin + 2m，与抽屉边界至少2m；关闭回到16；
- 移动视口内容 padding 固定2m，不参与抽屉位移；
- 嵌套抽屉定位跳过隐藏父级（矩形0）并监听 `.modal` class 变化，在 popup 显示时重新计算，修复首次/重开设置时侧抽屉位置错误。


## 263. AI 嵌套面板首帧/预加载/同对象返回（2026-11-01）

- `/p/ai/?panel=...` 在脚本初始化前直接给 body 加 panel-open、给目标 pane 加 open，先画出历史/设置骨架，不再先闪聊天；
- initial panel pin 防止 initSessions 的 showPanel("chat") 覆盖；
- AI 抽屉打开 320ms 后后台预加载 history/settings iframe，点击时直接显示；
- AI opener 保持全局同一 DOM 对象/位置，不随抽屉移动；移除 AI 打开时隐藏漂流瓶按钮导致的重排；
- 抽屉内动作按钮通过 data-trigger-external 上移，避免与外部 opener 重叠。


## 264. 右侧按钮顺序/内容段落间距（2026-11-01）

- 全局右下集群自下而上改为 bugreport 在底部、漂流瓶在其上（DOM 顺序 bug→bottle→ai）；
- `.kp-popup-content .sm-pane > * + *` 等块级段落间距至少 m=8；sm-head 与首个 pane、label、嵌套 ai section 都应用；
- 设置/管理多行段落、隐形模块之间保持至少m间距，实测 hint→label=11.5px。


## 265. 生日贴纸/输入框灰块修复（2026-11-01）

- 移除 birthday-mode 给 input/select/textarea 加 `--bd-sticker-d` 背景的规则；此前日期输入框后的灰块就是该 22px 装饰图；
- 生日 hero 增加 `ensureHeroLargeSticker`：若 scatter 中没有 >=64px 的大贴纸，强制补一个 68–86px 贴纸，并在 80ms/520ms 二次确认；
- 测试把 kitten 生日临时改为 2026-11-01 验证后已恢复 2003-11-02。


## 266. 生日 Hero 大贴纸原生修复（2026-11-01）

- 根因：`paintHeroEmojis` 清空 scatter 后，`_bdRects` 仍保留旧 `.bh-emoji` 的碰撞矩形；重绘时大贴纸被已删除元素挡住；
- 原生修复：重绘前用当前页面 `.bd-sticker-el` 重建碰撞集，不把旧 hero emoji 算进去；
- 原生生成时预留一个 largeSlot，尺寸固定 68–86px；其余仍 40–84px；不再添加独立 ensure/兜底函数；
- 输入框灰块仍保持已修复：birthday-mode 不再给 input/select/textarea 加背景 sticker。


## 267. 大字页行尾标点悬挂居中（2026-11-01）

- 大字页 `#tagline` 渲染后按 `<br>` 分行，找到每行最后一个文本节点；
- 行尾中文/英文标点拆成 `.hanging-punct`（inline-block、width:0、overflow:visible），标点仍显示但宽度不参与居中；
- 左半部分 centering 后标点自然悬挂在右侧；保留原 `<em>/<span>` 样式；
- 生日模式与随机 tagline 切换均重新应用。


## 268. 站内信系统（2026-11-02）

- 后端 `kernel/notifications.py`：per-user 文件存储、最多500条/人；
- API：`GET /api/notifications`（items/unread/modules）、`POST /api/notifications/read`（ids/module/all）；
- 顶栏按钮在“大字页”和“用户”之间，`.kp-round-btn` 模板，红色数字 badge；
- 弹窗 `.sm-box.kp-popup` 继承 Popup 模板，左侧模块索引为 `.sm-side.kp-drawer--nested` 抽屉模板；桌面宽25%，移动端全宽；
- 通知来源：日程提到/参与（新增时比较旧集合）、漂流瓶创建、愿望创建/通过/驳回；其他业务可直接调用 `notify()`（当前无独立砍价后端动作）；
- 支持筛选模块、标为已读、全部已读、打开模块、30秒轮询；测试数据已清理，保留真实漂流瓶。


## 269. 站内信窗口与设置窗口对齐（2026-11-02）

- 根因：mail popup 未加入静态树，圆角回退30，内部按钮 inset=m；设置popup树深度2为38，按钮inset=2m；
- 修复：静态树新增 mail-popup（child mail-side-drawer），mail 外层38、模块索引抽屉30；
- 桌面/移动端实测：设置和站内信 `.sm-box` 完全同尺寸/坐标，侧抽屉同尺寸，toggle 同坐标；移动端 x=8/374、侧抽屉 x=9/372、toggle x=24/y=672。


## 270. 消息中心/私信/导出（2026-11-02）

- UI 站内信改名“消息”；左索引新增“私信”，支持选择其他用户、对话气泡、发送；
- 后端 `kernel/messages.py` 使用 SQLite `data/messages.db`（WAL）存 direct_messages：id/sender/recipient/body/created/read_at/meta；
- API：GET `/api/messages/threads` `/api/messages/thread?peer=`；POST `/api/messages/send` `/api/messages/read`；
- 导出 `GET /api/messages/export?format=json|csv|txt&gzip=1`，合并事件通知与私信，默认 gzip；UI“导出”下载 messages.json.gz；
- 消息 badge 合并通知未读+私信未读，30秒轮询；读私信/全部已读同步；
- 测试私信、通知、测试日程/愿望/漂流瓶均已清理；真实漂流瓶保留2个。


## 271. 私信社交式双栏 UI（2026-11-02）

- 私信页改为常见社交软件布局：左侧会话列表（头像/名称/最后消息/时间/未读），右侧聊天窗（对方标题、气泡、输入框）；
- 不再使用右侧下拉框选择对象；所有其他用户都在会话列表，没聊过的显示“开始聊天”；
- 移动端会话列表改为横向滚动、聊天窗在下方；
- SQLite 查询用 `created DESC, rowid DESC` 保证同秒消息顺序稳定；
- 导出、通知 badge、已读/全部已读保持不变；测试消息已清空。


## 272. 消息左侧层级/私信上收（2026-11-02）

- 私信不再三栏：移除右侧内容里的会话列表列；角色/用户列表放入左侧模块抽屉；
- 左侧层级：消息总标题 → 全部/私信（一级）→ 私信用户列表（二级缩进）；其它通知 module 为一级；
- 私信行右侧有折叠按钮 ⌃/⌄，可向上收起用户列表；折叠状态仅影响左侧；
- 右侧仅保留单一聊天窗（对方标题、气泡、输入框）；
- 测试私信/通知已清空；真实漂流瓶保留。


## 273. 私信输入框仿 AI/主题气泡/已读标记（2026-11-02）

- 私信输入区改为 AI 风格圆角 `.dm-input-wrap` + 右下圆形 ↑ `.dm-send-round`，固定聊天窗底部；
- `.dm-chat` / `#mail-list` 在消息弹窗内 flex 填充，输入框贴底；
- 自己发送的消息气泡背景=`var(--accent)`、白字，左侧显示“已读/未读”（来自 direct_messages.read_at）；
- 测试消息已清空。
