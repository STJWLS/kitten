# KittenPuppy4Ever · Android 原生客户端（Phase 1）

这是一个 **不使用 WebView** 的 Android 原生客户端骨架。

## 已实现

- 原生登录页（服务器地址、账号、口令）
- Bearer token 会话
- 原生工作台头部与项目卡片
- 原生项目路由页（读取 `/api/p/<id>/state`）
- 原生消息页：
  - 通知列表
  - 私信会话列表
  - 原生私信聊天气泡与发送
  - 标记已读 / 全部已读
- 原生设置页：账号、主题信息、服务器地址、退出登录
- 服务端主题色应用到原生界面
- 无 WebView、无 Capacitor/Cordova、无 Gradle 依赖

## 构建

本地工具链沿用 `app/toolchain/`：

```bash
python android/build_apk.py
```

输出：

```text
releases/KittenPuppy4Ever-0.1.0.apk
```

CI 构建使用 `JAVA_HOME` + `ANDROID_SDK_ROOT`，不需要本地 toolchain。

## 服务器地址

默认指向 Tailscale Funnel 公网入口：

```text
https://02f5c6734009.tail4ba04e.ts.net
```

GitHub Pages 只是静态入口，实际后端运行在本机 `127.0.0.1:8772`，由 Tailscale Funnel 暴露。Android 模拟器也可改为 `http://10.0.2.2:8772`。

## 安装

```bash
adb install -r releases/KittenPuppy4Ever-0.1.0.apk
```

## GitHub Actions

`.github/workflows/android-apk.yml` 支持：

- 手动触发；
- `android-v*` tag 触发；
- 上传 APK artifact，tag 构建时创建 GitHub Release。

签名：

- 本地构建会自动生成 `android/KittenPuppy/kp.keystore`（不提交）；
- CI 可通过 `KP_KEYSTORE_BASE64` / `KP_KS_PASS` secrets 使用固定签名密钥；
- 没有固定 keystore 时 CI 会生成临时签名，APK 之间无法覆盖安装升级。

## 下一阶段

Phase 1 只完成原生壳、路由、消息、设置和主题。下一阶段实现：

- 漂流瓶原生 Canvas
- 日程/许愿池/便签原生界面
- AI 原生 SSE 聊天
- 面试 Mock 录音
- 造院/地图
