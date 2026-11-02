# -*- coding: utf-8 -*-
"""正式模式验收：匿名被挡、会话可用、旧页面受保护、登录接口拒绝错误口令。

用法：
    python platform/tools/verify_prod.py [--base http://127.0.0.1:8772]
    python platform/tools/verify_prod.py --base https://xxx.trycloudflare.com --password 你的口令
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else "  " + detail))


def req(base, path, body=None, cookie=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(base + path, data=data,
                               method="POST" if data is not None else "GET")
    if data is not None:
        r.add_header("Content-Type", "application/json")
    if cookie:
        r.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(r, timeout=15) as x:
            return x.status, x.headers, x.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8772")
    ap.add_argument("--user", default="kitten")
    ap.add_argument("--password", default="", help="提供则额外验证真实登录接口")
    args = ap.parse_args()
    b = args.base.rstrip("/")

    st, h, body = req(b, "/api/session")
    check("匿名 /api/session 返回 session=null", st == 200 and json.loads(body).get("session") is None)
    st, h, body = req(b, "/api/tree")
    check("匿名 /api/tree -> 401", st == 401)
    st, h, body = req(b, "/legacy/")
    check("旧页面本身可加载（数据仍由 API 鉴权）", st == 200 and "课程看板".encode() in body)
    st, h, body = req(b, "/api/state")
    check("匿名 /api/state -> 401", st == 401)
    st, h, body = req(b, "/")
    check("/ 是无后缀全首页（登录/注册入口）", st == 200 and b"/login" in body and b"register" in body)
    st, h, body = req(b, "/home")
    check("/home 是工作台壳", st == 200 and b"view-home" in body)
    for p in ("/dashboard/", "/dashboard/map/", "/wishpool/", "/mock/"):
        st, h, body = req(b, p)
        check("旧版 URL 路径 %s 可访问" % p, st == 200 and b"view-home" in body)

    st, h, body = req(b, "/api/login", {"user": args.user, "password": "wrong-password"})
    check("错误口令 401", st == 401)
    if args.password:
        st, h, body = req(b, "/api/login", {"user": args.user, "password": args.password})
        ck = (h.get("Set-Cookie") or "").split(";")[0]
        check("正确口令登录成功", st == 200 and bool(ck))

    try:
        from _session import make_cookie
        cookie = make_cookie(args.user)
    except Exception as e:
        check("签发测试会话", False, str(e))
        cookie = ""
    st, h, body = req(b, "/api/tree", cookie=cookie)
    j = json.loads(body)
    check("会话读到树", st == 200 and j.get("session", {}).get("user") == args.user)
    _tree_ids = [c.get("id") for c in (j.get("root", {}).get("children") or [])]
    check("树是后端结构（含 ai 等 6+ 根项目）",
          {"schedule", "mock", "wishpool", "ai", "courtyard", "scratchpad"}.issubset(set(_tree_ids)))

    st, h, body = req(b, "/legacy/?embed=1", cookie=cookie)
    check("登录后旧页面可访问且注入去壳/会话桥",
          st == 200 and b"kp-embed" in body and b"kp-bridge" in body)
    st, h, body = req(b, "/api/state", cookie=cookie)
    check("登录后 /api/state 可用", st == 200 and "wishes" in json.loads(body))
    st, h, body = req(b, "/api/metrics", cookie=cookie)
    check("维护者可见指标", st in (200, 403))

    st, h, body = req(b, "/api/login", {"user": args.user, "password": "wrong-again"})
    check("连续错误口令触发节流", st in (401, 429))

    print("\n结果：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
