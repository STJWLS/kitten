# -*- coding: utf-8 -*-
"""内核数据引擎：每个项目一份 JSON 文档，内存缓存 + 原子写 + 版本 + 指标。

相比旧实现（local_store.py 每次请求都 read/parse 整份 store.json，每次保存都
整份重写 34KB），这一层提供：

  1. 分片写：一个项目一个 doc.json，保存只写被改动的那一份（写放大从 34KB
     降到 1~8KB）
  2. 读缓存：按 mtime_ns + size 失效，未变化时直接命中内存（省掉 JSON 解析）
  3. 全局版本号：任何写都会推进 engine.version，用于 HTTP ETag / 304
  4. 指标：reads / cache_hits / writes / bytes_read / bytes_written / saves /
     etag_304，供 /api/metrics 与 bench 使用
  5. 原子写：tmp + os.replace，读永远不会看到半份文件
"""

import json
import os
import threading
import time

from .protocol import ProjectError


class DataEngine:
    def __init__(self, root: str):
        self.root = root
        self.data_dir = os.path.join(root, "data")
        self.version = 0
        self.started_at = time.time()
        self.metrics = {
            "reads": 0, "cache_hits": 0, "cache_misses": 0,
            "writes": 0, "saves": 0, "bytes_read": 0, "bytes_written": 0,
            "etag_304": 0,
        }
        self._cache = {}
        self._locks = {}
        self._meta_lock = threading.Lock()

    # ---------------- 路径与锁 ----------------
    def doc_path(self, pid: str) -> str:
        return os.path.join(self.data_dir, pid, "doc.json")

    def _lock(self, pid: str):
        with self._meta_lock:
            lock = self._locks.get(pid)
            if lock is None:
                lock = threading.RLock()
                self._locks[pid] = lock
            return lock

    # ---------------- 读 ----------------
    def read(self, pid: str):
        """返回 (rev, data, audit)。未落盘时返回默认空文档。"""
        path = self.doc_path(pid)
        try:
            st = os.stat(path)
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            return 0, {}, []

        with self._lock(pid):
            self.metrics["reads"] += 1
            cached = self._cache.get(pid)
            if cached and cached["sig"] == sig:
                self.metrics["cache_hits"] += 1
                return cached["rev"], cached["data"], []

            self.metrics["cache_misses"] += 1
            try:
                with open(path, "rb") as f:
                    raw = f.read()
                doc = json.loads(raw.decode("utf-8"))
            except Exception:
                return 0, {}, []
            data = doc.get("data") if isinstance(doc.get("data"), dict) else {}
            rev = int(doc.get("_rev") or 0)
            self.metrics["bytes_read"] += len(raw)
            self._cache[pid] = {"sig": sig, "rev": rev, "data": data}
            return rev, data, []

    # ---------------- 审计（独立 jsonl，不塞进 doc 免得放大写） ----------------
    def _audit_path(self, pid: str) -> str:
        return os.path.join(self.data_dir, pid, "audit.jsonl")

    def _append_audit(self, pid: str, entries):
        if not entries:
            return
        path = self._audit_path(pid)
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        mode = "a"
        if size > 512 * 1024:          # 简单轮转，避免无限增长
            try:
                os.replace(path, path + ".1")
            except OSError:
                pass
            mode = "w"
        try:
            with open(path, mode, encoding="utf-8") as f:
                for e in entries:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ---------------- 写 ----------------
    def write(self, pid: str, data: dict, rev=None, audit=None):
        if not isinstance(data, dict):
            raise ProjectError("bad_request", "项目状态必须是 JSON 对象")
        path = self.doc_path(pid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with self._lock(pid):
            if rev is None:
                cur_rev, _, _ = self.read(pid)
                new_rev = int(cur_rev) + 1
            else:
                # 调用方（项目 dispatch）已经算好新版本号，这里只负责落盘
                new_rev = int(rev)
            body = json.dumps({"_rev": new_rev, "data": data},
                              ensure_ascii=False, indent=1).encode("utf-8")
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(body)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            st = os.stat(path)
            self._cache[pid] = {"sig": (st.st_mtime_ns, st.st_size), "rev": new_rev, "data": data}
            self.metrics["writes"] += 1
            self.metrics["saves"] += 1
            self.metrics["bytes_written"] += len(body)
            with self._meta_lock:
                self.version += 1
            self._append_audit(pid, audit)
            return new_rev

    # ---------------- 版本与指标 ----------------
    def state_version(self) -> int:
        return self.version

    def stats(self) -> dict:
        m = dict(self.metrics)
        total = m["reads"]
        m["cache_hit_rate"] = round(m["cache_hits"] / total, 4) if total else 0.0
        m["uptime_s"] = round(time.time() - self.started_at, 1)
        sizes = {}
        for pid in sorted(self._cache):
            try:
                sizes[pid] = os.path.getsize(self.doc_path(pid))
            except OSError:
                pass
        m["doc_bytes"] = sizes
        m["doc_bytes_total"] = sum(sizes.values())
        audit_bytes = {}
        for pid in sorted(self._cache):
            try:
                audit_bytes[pid] = os.path.getsize(self._audit_path(pid))
            except OSError:
                pass
        m["audit_bytes"] = audit_bytes
        return m
