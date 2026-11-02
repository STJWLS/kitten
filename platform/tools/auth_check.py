# -*- coding: utf-8 -*-
"""严格鉴权检查：验证 401、登录接口、会话 cookie、受保护接口。

用法：
    python platform/tools/auth_check.py --base http://127.0.0.1:8774
    python platform/tools/auth_check.py --password 你的口令      # 额外验证真实登录
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else "  " + detail))


def call(base, method, path, body=None, cookie=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8")), r.headers
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8")), e.headers
        except Exception:
            return e.code, {}, e.headers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8771")
    ap.add_argument("--user", default="kitten")
    ap.add_argument("--password", default="")
    args = ap.parse_args()
    b = args.base.rstrip("/")

    st, body, _ = call(b, "GET", "/api/tree")
    check("未登录访问 /api/tree -> 401", st == 401 and body.get("error", {}).get("code") == "unauthorized")

    st, body, _ = call(b, "POST", "/api/login", {"user": args.user, "password": "wrong"})
    check("错误口令 -> 401", st == 401)

    if args.password:
        st, body, hdrs = call(b, "POST", "/api/login",
                              {"user": args.user, "password": args.password})
        cookie = (hdrs.get("Set-Cookie") or "").split(";")[0]
        check("正确口令登录成功并下发 HttpOnly cookie",
              st == 200 and bool(cookie) and "HttpOnly" in (hdrs.get("Set-Cookie") or ""))
    else:
        from _session import make_cookie
        cookie = make_cookie(args.user)
        check("签发测试会话（不依赖明文口令）", bool(cookie))

    st, body, _ = call(b, "GET", "/api/tree", cookie=cookie)
    check("带会话读到树，身份正确",
          st == 200 and (body.get("session") or {}).get("user") == args.user)

    st, body, _ = call(b, "GET", "/api/p/schedule/state", cookie=cookie)
    check("带会话读到项目 state", st == 200 and "rev" in body)

    st, hdrs, _ = call(b, "POST", "/api/logout", {}, cookie=cookie)
    check("登出下发清除 cookie（Max-Age=0）", st == 200 and "Max-Age=0" in (hdrs.get("Set-Cookie") or ""))

    print("\n结果：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
