# -*- coding: utf-8 -*-
"""Mock 后端网关：把 MockInterview 的 FastAPI 应用直接挂进看板引擎进程。

- 不再启动 8768、不再需要独立 HTTP 后端；
- 首次请求时才导入 FastAPI 应用并起一个后台事件循环（冷启动约几秒）；
- 其余请求通过 ASGI 直接调用（进程内，无网络回环、无代理超时）；
- 跳过原应用的 startup 预热（流式 ASR 改为按需懒加载），避免引擎启动变慢。
"""

import asyncio
import os
import sys
import threading
import time
import traceback


class MockGateway:
    def __init__(self, mock_dir: str):
        self.mock_dir = os.path.abspath(mock_dir)
        self._lock = threading.Lock()
        self._app = None
        self._loop = None
        self._ready = False
        self._error = None
        self.started_at = None

    def prewarm(self):
        """引擎启动后在后台导入 Mock 后端，避免第一次请求等 19 秒。"""
        if self._ready:
            return
        threading.Thread(target=self._ensure, daemon=True, name="mock-prewarm").start()

    # ---------------- 初始化（懒加载） ----------------
    def _ensure(self):
        if self._ready:
            if self._error:
                raise RuntimeError(self._error)
            return self._app, self._loop

        with self._lock:
            if self._ready:
                if self._error:
                    raise RuntimeError(self._error)
                return self._app, self._loop
            t0 = time.time()
            try:
                if self.mock_dir not in sys.path:
                    sys.path.insert(0, self.mock_dir)
                import mock_web  # noqa: E402  延迟到首次请求再导入

                self._app = mock_web.app
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, daemon=True,
                                 name="mock-asgi-loop").start()
                self._loop = loop
                self._ready = True
                self.started_at = time.time()
                print("[mock] in-process backend ready in %.1fs" % (time.time() - t0))
            except Exception as e:
                self._error = "Mock 后端导入失败：%s" % e
                self._ready = True
                traceback.print_exc()
            return self._app, self._loop

    # ---------------- 请求分发 ----------------
    async def _dispatch(self, method, path, query_string, headers, body):
        app = self._app
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "path": path,
            "raw_path": path.encode("utf-8", "replace"),
            "query_string": query_string.encode("utf-8", "replace"),
            "root_path": "",
            "scheme": "http",
            "headers": headers,
            "server": ("127.0.0.1", 8772),
            "client": ("127.0.0.1", 0),
        }
        sent = {"body": False}

        async def receive():
            if not sent["body"]:
                sent["body"] = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        out = {"status": 500, "headers": [], "body": b""}

        async def send(message):
            if message["type"] == "http.response.start":
                out["status"] = message["status"]
                out["headers"] = message.get("headers") or []
            elif message["type"] == "http.response.body":
                out["body"] += message.get("body") or b""

        await app(scope, receive, send)
        return out["status"], out["headers"], out["body"]

    def handle(self, method, full_path, headers_dict, body, timeout=300):
        """full_path 形如 /mock/api/health；内部路由是 /api/health。"""
        parsed = full_path
        path = parsed
        query = ""
        if "?" in parsed:
            path, query = parsed.split("?", 1)
        if path.startswith("/mock"):
            path = path[len("/mock"):] or "/"

        app, loop = self._ensure()
        hdrs = []
        for k, v in (headers_dict or {}).items():
            if k.lower() in ("host", "connection", "content-length", "transfer-encoding",
                             "accept-encoding"):
                continue
            hdrs.append((k.lower().encode("latin-1", "replace"),
                         str(v).encode("latin-1", "replace")))
        fut = asyncio.run_coroutine_threadsafe(
            self._dispatch(method.upper(), path, query, hdrs, body or b""), loop)
        return fut.result(timeout=timeout)

    def stats(self):
        return {
            "ready": self._ready,
            "error": self._error,
            "cold_start_s": round(self.started_at, 1) if self.started_at else None,
        }
