# -*- coding: utf-8 -*-
"""清理公开仓库里的旧静态页，换成"路径保留"的跳转壳。

背景：旧版把 dashboard/wishpool/mock 的整站静态文件（含明文口令的 auth.js）
发布到了公开仓库。切流后这些页面不再需要，但文件仍能被公网访问。

本脚本：
  1) 删除 KittenPuppy4Ever/{dashboard,wishpool,mock} 下的旧静态文件（含 assets/auth.js）
  2) 为这 4 个旧 URL 路径创建跳转壳（保留路径，跳当前隧道）：
       /kitten/KittenPuppy4Ever/dashboard/      -> 隧道 /dashboard/
       /kitten/KittenPuppy4Ever/dashboard/map/  -> 隧道 /dashboard/map/
       /kitten/KittenPuppy4Ever/wishpool/       -> 隧道 /wishpool/
       /kitten/KittenPuppy4Ever/mock/           -> 隧道 /mock/
  3) 根入口 index.html 已经是跳转壳，不动

用法：
    python platform/tools/publish_paths.py --dry-run
    python platform/tools/publish_paths.py
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

CONF = os.path.join(os.path.expanduser("~"), ".dashboard_config")
OWNER_FILE = os.path.join(CONF, "github_user.txt")
TOKEN_FILE = os.path.join(CONF, "github_token.txt")
REPO = "kitten"
ROOT = "KittenPuppy4Ever"

TARGETS = {
    "dashboard": "/dashboard/",
    "dashboard/map": "/dashboard/map/",
    "wishpool": "/wishpool/",
    "mock": "/mock/",
}

STUB = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KittenPuppy4Ever</title>
<style>
  html,body{height:100%;margin:0}
  body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
    display:flex;align-items:center;justify-content:center;
    background:linear-gradient(160deg,#fbf7f0,#f4eadf 55%,#eee1d6);color:#42392b}
  .c{background:#fffdf8;border:1px solid #e8dfd2;border-radius:18px;padding:26px 34px;
    text-align:center;box-shadow:0 16px 50px rgba(66,57,43,.14)}
  .l{font-size:26px} h1{margin:6px 0 2px;font-size:17px;font-family:monospace}
  p{font-size:12px;color:#8a7f6d;margin:8px 0 0;font-family:monospace}
  a{color:#2f6fb5}
</style></head>
<body><div class="c"><div class="l">🐱🐶</div><h1>KittenPuppy4Ever</h1>
<p id="s">正在连接工作台…</p>
<p><a href="__DEPTH__entry.json">查看入口配置</a></p></div>
<script>
fetch("__DEPTH__entry.json?ts=" + Date.now(), {cache: "no-store"})
  .then(function(r){ return r.json(); })
  .then(function(d){
    if (d && d.url) {
      document.getElementById("s").textContent = "已连接，正在进入…";
      location.replace(d.url.replace(/\\/+$/, "") + "__PATH__");
    } else {
      document.getElementById("s").textContent = "工作台入口未配置";
    }
  })
  .catch(function(e){ document.getElementById("s").textContent = "无法读取入口：" + e.message; });
</script></body></html>
"""


def creds():
    with open(OWNER_FILE, encoding="utf-8") as f:
        owner = f.read().strip()
    with open(TOKEN_FILE, encoding="utf-8") as f:
        token = f.read().strip()
    return owner, token


def api(owner, token, method, path, data=None, base="contents"):
    if base == "contents":
        url = "https://api.github.com/repos/%s/%s/contents/%s" % (owner, REPO, path)
    else:
        url = "https://api.github.com/repos/%s/%s/%s" % (owner, REPO, path)
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/vnd.github+json",
               "Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    owner, token = creds()

    tree = api(owner, token, "GET", "git/trees/main?recursive=1", base="git")
    blobs = [t for t in tree.get("tree", []) if t.get("type") == "blob"]
    old = []
    for t in blobs:
        p = t["path"]
        for prefix in TARGETS:
            if p.startswith(ROOT + "/" + prefix + "/"):
                old.append(p)
    old = sorted(set(old))
    print("旧静态文件 %d 个，将删除；并重建 %d 个跳转壳" % (len(old), len(TARGETS)))
    if args.dry_run:
        for p in old:
            print("  DELETE", p)
        for p, path in TARGETS.items():
            print("  PUT   %s/%s/index.html -> %s" % (ROOT, p, path))
        return 0

    deleted = 0
    for p in old:
        try:
            sha = [t["sha"] for t in blobs if t["path"] == p][0]
            api(owner, token, "DELETE", p,
                {"message": "security: remove legacy static page (plaintext creds)",
                 "sha": sha})
            deleted += 1
            if deleted % 10 == 0:
                print("  已删除 %d/%d" % (deleted, len(old)))
            time.sleep(0.15)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            print("  删除失败 %s: %s" % (p, e))
    print("删除完成：%d 个" % deleted)

    for sub, path in TARGETS.items():
        depth = "../../" if sub == "dashboard/map" else "../"
        html = STUB.replace("__DEPTH__", depth).replace("__PATH__", path)
        try:
            api(owner, token, "PUT", "%s/%s/index.html" % (ROOT, sub),
                {"message": "entry: path-preserving redirect for /%s/" % sub,
                 "content": base64.b64encode(html.encode("utf-8")).decode("utf-8")})
            print("  PUT %s/%s/index.html -> %s" % (ROOT, sub, path))
        except urllib.error.HTTPError as e:
            print("  写入失败 %s: %s" % (sub, e))
    print("完成。GitHub Pages 约 1~10 分钟生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
