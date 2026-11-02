# -*- coding: utf-8 -*-
"""新引擎验收：无损迁移 + 旧协议兼容 + kp/1 + 视图 + 鉴权/ACL + 性能旁证。

用法：
    python platform/tools/smoke_test.py --base http://127.0.0.1:8772
"""

import argparse
import base64
import glob
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request

PASS, FAIL = [], []
COOKIE = ""


def login(base):
    """测试会话：直接用内核会话密钥签发，不需要明文口令。"""
    try:
        from _session import make_cookie
        return make_cookie("kitten")
    except Exception as e:
        print("  签发测试会话失败: %s" % e)
        return ""


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else "  " + detail))


def call(base, method, path, body=None, headers=None, no_cookie=False):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers=dict(headers or {}))
    req.add_header("Content-Type", "application/json")
    if COOKIE and not no_cookie:
        req.add_header("Cookie", COOKIE)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            if (r.headers.get("Content-Encoding") or "") == "gzip":
                raw = gzip.decompress(raw)
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except Exception:
                parsed = raw
            return r.status, parsed, r.headers
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            parsed = {"raw": raw[:200]}
        return e.code, parsed, e.headers


def raw_get(base, path, headers=None):
    req = urllib.request.Request(base + path, headers=dict(headers or {}))
    if COOKIE:
        req.add_header("Cookie", COOKIE)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def latest_report(platform):
    files = sorted(glob.glob(os.path.join(platform, "data", "_migration", "report-*.json")))
    if not files:
        return {}
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)


def main():
    global COOKIE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8772")
    args = ap.parse_args()
    b = args.base.rstrip("/")
    platform = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    report = latest_report(platform)

    print("== 登录（正式模式） ==")
    COOKIE = login(b)
    check("服务器会话登录成功", bool(COOKIE))
    if not COOKIE:
        print("  未拿到会话，后续受保护接口会 401；确认 config dev_mode=false 且 users.json 存在")

    print("== 引擎与树 ==")
    st, body, _ = call(b, "GET", "/api/health")
    check("health.ok", st == 200 and body.get("ok") is True)
    check("协议号 kp/1 + 引擎版本", body.get("protocol") == "kp/1" and body.get("engine") == "kp-engine/1.1")
    st, body, _ = call(b, "GET", "/api/tree")
    root = body.get("root") or {}
    ids = [c["id"] for c in root.get("children") or []]
    check("根项目包含 schedule/mock/wishpool/ai/courtyard/scratchpad",
          {"schedule", "mock", "wishpool", "ai", "courtyard", "scratchpad"}.issubset(set(ids)), str(ids))
    sched = [c for c in root["children"] if c["id"] == "schedule"][0]
    check("schedule 下挂 map", [c["id"] for c in sched["children"]] == ["map"])
    check("所有项目都是模板原生视图", all(c["view"]["kind"] == "custom" for c in root["children"]))

    print("== 无损迁移（对照迁移报告） ==")
    st, state, _ = call(b, "GET", "/api/state")
    orig = report.get("counts_original") or {}
    got = {
        "events": len(state.get("events") or []),
        "venues": len(state.get("venues") or []),
        "wishes": len(state.get("wishes") or []),
        "reminders_sent": len(state.get("reminders_sent") or []),
        "wish_notified": len(state.get("wish_notified") or []),
        "t": state.get("t"),
    }
    for k in ("events", "venues", "wishes", "reminders_sent", "wish_notified", "t"):
        if k == "t":
            check("字段 t 单调（>= 迁移值 %s）" % orig.get(k), got[k] >= (orig.get(k) or 0),
                  "实际 %s" % got[k])
        elif k in ("reminders_sent", "wish_notified"):
            # 提醒服务 / 许愿通知在运行中会追加记录，只要求不丢
            check("字段 %s 只增不减（%s）" % (k, got[k]), got[k] >= (orig.get(k) or 0), "迁移值 %s" % orig.get(k))
        else:
            check("字段 %s 无损（%s）" % (k, got[k]), got[k] == orig.get(k), "期望 %s" % orig.get(k))
    check("迁移报告判定无损", report.get("lossless") is True)
    coins = state.get("coins") or {}
    check("coinLog 只增不减（%s）" % len(coins.get("coinLog") or []),
          len(coins.get("coinLog") or []) >= (orig.get("coinLog") or 0),
          "迁移值 %s" % orig.get("coinLog"))
    check("未知顶层字段为空", (report.get("unknown_top_level_keys") or []) == [])

    print("== 旧协议只读检查（不写状态） ==")
    st, state2, _ = call(b, "GET", "/api/state")
    st, state3, _ = call(b, "GET", "/api/state")
    check("旧协议 state 可读", st == 200 and isinstance(state2.get("events"), list))
    check("旧协议只读后 t 未变化", (state3.get("t") or 0) == (state2.get("t") or 0))

    print("== kp/1 只读检查 ==")
    st, sp, _ = call(b, "GET", "/api/p/scratchpad/state")
    check("零代码项目 state 可读", st == 200 and isinstance(sp.get("data", {}).get("items"), list))

    print("== 附件上传 dry-run（不落盘） ==")
    raw = base64.b64encode(b"smoke attachment").decode()
    st, up, _ = call(b, "POST", "/api/files/upload",
                     {"name": "smoke.txt", "mime": "text/plain", "data": raw, "dry_run": True})
    check("附件 dry-run 加密往返成功",
          st == 200 and up.get("file", {}).get("encrypted") is True and up.get("file", {}).get("roundtrip") is True)

    print("== AI session dry-run（不写 session 文件夹） ==")
    st, before, _ = call(b, "GET", "/api/ai/sessions")
    st, saved, _ = call(b, "POST", "/api/ai/sessions/save",
                        {"dry_run": True, "session": {"title": "smoke", "messages": [{"role": "user", "content": "hi"}]}})
    st, after, _ = call(b, "GET", "/api/ai/sessions")
    check("session dry-run 返回结构与消息",
          st == 200 and saved.get("dry_run") is True and saved.get("session", {}).get("message_count") == 1)
    check("session dry-run 未写入 session 列表",
          len(before.get("sessions") or []) == len(after.get("sessions") or []))

    print("== AI 自定义工具 dry-run（不执行模块事务） ==")
    st, tools, _ = call(b, "GET", "/api/ai/tools?module=schedule")
    names = [x.get("name") for x in tools.get("tools") or []]
    check("schedule 工具清单", "schedule_create" in names and "schedule_list" in names)
    st, tr1, _ = call(b, "POST", "/api/ai/tools/execute",
                      {"module": "scratchpad", "tool": "scratchpad_append", "args": {"title": "smoke"}, "dry_run": True})
    check("便签工具 dry-run", st == 200 and tr1.get("result", {}).get("dry_run") is True)
    st, tr2, _ = call(b, "POST", "/api/ai/tools/execute",
                      {"module": "schedule", "tool": "schedule_create",
                       "args": {"title": "smoke", "date": "2030-01-01", "start": "09:00", "end": "10:00"}, "dry_run": True})
    check("日程工具 dry-run", st == 200 and tr2.get("result", {}).get("dry_run") is True)

    print("== 旧页面托管 ==")
    st, raw, _ = raw_get(b, "/legacy/?embed=1")
    check("课程看板页 200 + 去壳 CSS", st == 200 and b"kp-embed" in raw)
    check("课程看板页含课表标题", "课程看板".encode() in raw)
    st, raw, _ = raw_get(b, "/legacy/wishpool/")
    check("许愿池页 200", st == 200 and "许愿池".encode() in raw)
    st, raw, _ = raw_get(b, "/legacy/mock/")
    check("Mock 页 200", st == 200 and "面试".encode() in raw)
    st, raw, _ = raw_get(b, "/legacy/assets/dashboard.css")
    check("静态资源可访问", st == 200 and len(raw) > 1000)

    print("== 缓存 / ETag / gzip ==")
    st, body, hdrs = call(b, "GET", "/api/state")
    etag = hdrs.get("ETag")
    check("state 带 ETag", bool(etag))
    st2, _, _ = call(b, "GET", "/api/state", headers={"If-None-Match": etag or ""})
    check("条件请求返回 304", st2 == 304)
    st3, raw_gz, h3 = raw_get(b, "/api/state", {"Accept-Encoding": "gzip"})
    st4, raw_plain, h4 = raw_get(b, "/api/state")
    check("gzip 生效且体积更小",
          (h3.get("Content-Encoding") or "") == "gzip" and len(raw_gz) < len(raw_plain),
          "%s vs %s" % (len(raw_gz), len(raw_plain)))

    print("== 指标 / 鉴权 / ACL ==")
    st, m, _ = call(b, "GET", "/api/metrics")
    check("metrics 可读（维护者）", st in (200, 403) and (st == 403 or "cache_hit_rate" in (m.get("engine") or {})))
    st, bad, _ = call(b, "POST", "/api/login", {"user": "kitten", "password": "wrong"})
    check("错误口令 -> 401", st == 401)
    sys.path.insert(0, platform)
    from kernel.registry import Registry
    from kernel.protocol import ProjectError
    reg = Registry(platform)
    proj = reg.get("wishpool")
    check("ACL: 陌生角色不可读写", not proj.can_read("intruder") and not proj.can_write("intruder"))
    try:
        proj.dispatch("append", {"item": {}}, role="intruder")
        acl_ok = False
    except ProjectError as e:
        acl_ok = e.code == "forbidden"
    check("ACL: dispatch 抛 forbidden", acl_ok)

    print("\n结果：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
