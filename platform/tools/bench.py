# -*- coding: utf-8 -*-
"""性能对照：旧引擎（实时 8767）vs 新引擎（8772）。

- 只读旧服务（不发写请求），避免动线上数据
- 写基准只打新引擎（数据目录是迁移副本）
- 用持久连接测新引擎（HTTP/1.1 keep-alive）；旧服务是 HTTP/1.0，每请求都要重连，
  这对浏览器之外的高频轮询/同步是真实成本，因此分开标注

用法：
    python platform/tools/bench.py [--rounds 200]
"""

import argparse
import http.client
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

OLD_HOST, OLD_PORT = "127.0.0.1", 8767
NEW_HOST, NEW_PORT = "127.0.0.1", 8772
COOKIE = ""

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None


def login_new():
    """测试会话：直接用内核会话密钥签发（不需要明文口令）。"""
    try:
        from _session import make_cookie
        return make_cookie("puppy")
    except Exception:
        return ""


class Client:
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.conn = None

    def _ensure(self):
        if self.conn is None:
            self.conn = http.client.HTTPConnection(self.host, self.port, timeout=30)
        return self.conn

    def get(self, path, headers=None):
        headers = dict(headers or {})
        if COOKIE:
            headers["Cookie"] = COOKIE
        for attempt in (1, 2):
            try:
                c = self._ensure()
                c.request("GET", path, headers=headers)
                r = c.getresponse()
                body = r.read()
                return r.status, len(body), r.getheader("Content-Encoding"), r.getheader("ETag")
            except (http.client.HTTPException, OSError):
                self.close()
                if attempt == 2:
                    raise
        raise RuntimeError("unreachable")

    def post(self, path, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if COOKIE:
            headers["Cookie"] = COOKIE
        for attempt in (1, 2):
            try:
                c = self._ensure()
                c.request("POST", path, body=body, headers=headers)
                r = c.getresponse()
                data = r.read()
                return r.status, len(data), len(body)
            except (http.client.HTTPException, OSError):
                self.close()
                if attempt == 2:
                    raise
        raise RuntimeError("unreachable")

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None


def pct(lat, p):
    lat = sorted(lat)
    idx = min(len(lat) - 1, max(0, int(len(lat) * p) - 1))
    return lat[idx]


def summarize(name, lat, sizes):
    mean = statistics.mean(lat) if lat else 0
    return {
        "name": name, "n": len(lat),
        "p50_ms": round(pct(lat, 0.5), 2), "p95_ms": round(pct(lat, 0.95), 2),
        "mean_ms": round(mean, 2),
        "avg_bytes": round(statistics.mean(sizes), 1) if sizes else 0,
        "rps": round(1000.0 / mean, 2) if mean else 0,
    }


def bench_client(host, port, path, name, rounds, headers=None):
    c = Client(host, port)
    lat, sizes = [], []
    for _ in range(rounds):
        t0 = time.perf_counter()
        code, n, enc, etag = c.get(path, headers)
        if code in (200, 304):
            lat.append((time.perf_counter() - t0) * 1000.0)
            sizes.append(n)
    c.close()
    return summarize(name, lat, sizes)


def bench_concurrent(host, port, path, name, threads=8, per_thread=40):
    lat, sizes, lock = [], [], threading.Lock()

    def worker():
        c = Client(host, port)
        local_lat, local_sizes = [], []
        for _ in range(per_thread):
            t0 = time.perf_counter()
            code, n, _, _ = c.get(path)
            local_lat.append((time.perf_counter() - t0) * 1000.0)
            local_sizes.append(n)
        c.close()
        with lock:
            lat.extend(local_lat)
            sizes.extend(local_sizes)

    t0 = time.perf_counter()
    ts = [threading.Thread(target=worker) for _ in range(threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    wall = time.perf_counter() - t0
    s = summarize(name, lat, sizes)
    s["throughput_rps"] = round(len(lat) / wall, 1)
    s["concurrency"] = threads
    return s


def metrics(engine_url):
    with urllib.request.urlopen(engine_url + "/api/metrics", timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    global COOKIE
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=200)
    args = ap.parse_args()
    results = []

    COOKIE = login_new()
    print("新引擎会话：%s" % ("已登录" if COOKIE else "未登录（受保护接口会 401）"))

    old_online = True
    try:
        urllib.request.urlopen("http://%s:%d/api/health" % (OLD_HOST, OLD_PORT), timeout=3)
    except Exception:
        old_online = False
    print("旧引擎 %s:%d : %s" % (OLD_HOST, OLD_PORT, "在线" if old_online else "不可达"))

    # 1) 兼容层读取
    results.append(bench_client(NEW_HOST, NEW_PORT, "/api/state", "新引擎 GET /api/state（兼容）", args.rounds))
    if old_online:
        results.append(bench_client(OLD_HOST, OLD_PORT, "/api/state", "旧引擎 GET /api/state（8767）", args.rounds))

    # 2) 分片读取
    results.append(bench_client(NEW_HOST, NEW_PORT, "/api/p/schedule/state", "新引擎 GET /api/p/schedule/state", args.rounds))
    results.append(bench_client(NEW_HOST, NEW_PORT, "/api/p/wishpool/state", "新引擎 GET /api/p/wishpool/state", args.rounds))

    # 3) gzip
    gz = bench_client(NEW_HOST, NEW_PORT, "/api/state", "新引擎 /api/state + gzip", 60,
                      {"Accept-Encoding": "gzip"})
    results.append(gz)

    # 4) 304
    c = Client(NEW_HOST, NEW_PORT)
    _, _, _, etag = c.get("/api/state")
    lat, sizes = [], []
    for _ in range(60):
        t0 = time.perf_counter()
        code, n, _, _ = c.get("/api/state", {"If-None-Match": etag or ""})
        lat.append((time.perf_counter() - t0) * 1000.0)
        sizes.append(n)
    c.close()
    results.append(summarize("新引擎 /api/state 条件请求(304)", lat, sizes))

    # 5) 并发
    results.append(bench_concurrent(NEW_HOST, NEW_PORT, "/api/state", "新引擎 并发 8×40 GET /api/state"))
    if old_online:
        results.append(bench_concurrent(OLD_HOST, OLD_PORT, "/api/state", "旧引擎 并发 8×40 GET /api/state"))

    # 6) 写入：只打新引擎，用 /api/metrics 统计实际落盘字节
    payload = json.loads(urllib.request.urlopen("http://%s:%d/api/state" % (NEW_HOST, NEW_PORT)).read())
    m0 = metrics("http://%s:%d" % (NEW_HOST, NEW_PORT))
    c = Client(NEW_HOST, NEW_PORT)
    lat, rows = [], 0
    rounds = 30
    for i in range(rounds):
        p = dict(payload)
        p["t"] = int(time.time() * 1000) + i
        t0 = time.perf_counter()
        c.post("/api/save", p)
        lat.append((time.perf_counter() - t0) * 1000.0)
        rows += 1
    c.close()
    m1 = metrics("http://%s:%d" % (NEW_HOST, NEW_PORT))
    write_bytes = (m1["engine"]["bytes_written"] - m0["engine"]["bytes_written"]) / max(1, rows)
    save_stat = summarize("新引擎 POST /api/save", lat, [write_bytes])
    save_stat["avg_bytes"] = round(write_bytes, 1)
    results.append(save_stat)

    # 7) 写放大对照
    dash = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    store_path = os.path.join(dash, "localdata", "store.json")
    old_store = os.path.getsize(store_path) if os.path.isfile(store_path) else None
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    docs = {}
    for pid in ("schedule", "wishpool", "meta"):
        p = os.path.join(data_dir, pid, "doc.json")
        if os.path.isfile(p):
            docs[pid] = os.path.getsize(p)

    report = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "old_online": old_online,
        "rounds": args.rounds,
        "results": results,
        "old_store_bytes": old_store,
        "new_doc_bytes": docs,
        "avg_write_bytes_per_save_new": round(write_bytes, 1),
    }
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "_migration")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "bench-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n%-46s %7s %7s %7s %9s %8s" % ("场景", "p50", "p95", "mean", "bytes", "rps"))
    print("-" * 100)
    for r in results:
        print("%-46s %7s %7s %7s %9s %8s%s" % (
            r["name"], r["p50_ms"], r["p95_ms"], r["mean_ms"], r["avg_bytes"], r["rps"],
            ("  (并发 %s 吞吐 %s/s)" % (r["concurrency"], r["throughput_rps"])) if "throughput_rps" in r else ""))
    print("\n写放大：旧 store.json %s B（每次整份重写）；新引擎实测 %s B/次（只写变化的项目分片）"
          % (old_store, round(write_bytes, 1)))
    print("分片大小：%s" % docs)
    print("报告：%s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
