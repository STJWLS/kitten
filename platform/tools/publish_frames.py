# -*- coding: utf-8 -*-
"""把 GitHub Pages 入口改成"地址栏保持 github.io"的 iframe 承载页。

之前入口页是 302/JS 跳到 trycloudflare，地址栏变成 cloudflare 域名。
现在：入口页用全屏 iframe 承载隧道里的工作台，并用 postMessage + replaceState
把地址栏保持在 /kitten/KittenPuppy4Ever/... 的原路径。

覆盖路径：
    /                                -> 隧道 /
    /dashboard/                      -> 隧道 /dashboard/
    /dashboard/map/                  -> 隧道 /dashboard/map/
    /wishpool/                       -> 隧道 /wishpool/
    /mock/                           -> 隧道 /mock/
    /courtyard/                      -> 隧道 /courtyard/

用法：python platform/tools/publish_frames.py [--dry-run]
"""

import argparse
import base64
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(os.path.expanduser("~"), ".dashboard_config")
OWNER_FILE = os.path.join(CONF, "github_user.txt")
TOKEN_FILE = os.path.join(CONF, "github_token.txt")
REPO = "kitten"

PREFIX = "/kitten/KittenPuppy4Ever"

SHIM = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KittenPuppy4Ever</title>
<style>
  html, body { height: 100%; margin: 0; background: #f8f4ec; }
  #frame { position: fixed; inset: 0; width: 100%; height: 100%; border: 0; background: #f8f4ec; }
  #msg {
    position: fixed; inset: 0; display: flex; align-items: center; justify-content: center;
    font: 13px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; color: #8a7f6d;
    background: linear-gradient(160deg, #fbf7f0, #eee1d6);
  }
  #msg.hidden { display: none; }
  #msg b { color: #42392b; display: block; margin-bottom: 6px; font-size: 15px; }
</style>
</head>
<body>
<iframe id="frame" allow="microphone; camera; autoplay; fullscreen" title="KittenPuppy4Ever"></iframe>
<div id="msg"><div><b>🐱🐶 KittenPuppy4Ever</b>正在连接工作台…</div></div>
<script>
(function () {
  var PREFIX = "/kitten/KittenPuppy4Ever";
  var path = location.pathname.indexOf(PREFIX) === 0
    ? (location.pathname.slice(PREFIX.length) || "/")
    : "/";
  if (path.charAt(0) !== "/") path = "/" + path;
  var base = "";

  function fail(text) {
    document.getElementById("msg").classList.remove("hidden");
    document.querySelector("#msg b").textContent = "🐱🐶 KittenPuppy4Ever";
    document.querySelector("#msg div").innerHTML = "<b>🐱🐶 KittenPuppy4Ever</b>" + text;
  }

  // 先读 raw（缓存 5 分钟、带 CORS），Pages 的 entry.json 往往被 CDN 缓存 10 分钟
  var rawEntry = "https://raw.githubusercontent.com/STJWLS/kitten/main/KittenPuppy4Ever/entry.json?ts=" + Date.now();
  var pagesEntry = PREFIX + "/entry.json?ts=" + Date.now();
  fetch(rawEntry, { cache: "no-store" })
    .then(function (r) { if (!r.ok) throw new Error("raw " + r.status); return r.json(); })
    .catch(function () { return fetch(pagesEntry, { cache: "no-store" }).then(function (r) { return r.json(); }); })
    .then(function (r) { return r; })
    .then(function (d) {
      if (!d || !d.url) { fail("工作台入口未配置（entry.json 为空）"); return; }
      base = d.url.replace(/\\/+$/, "");
      var f = document.getElementById("frame");
      var loaded = false, tries = 0;
      f.onload = function () { loaded = true; document.getElementById("msg").classList.add("hidden"); };
      function load() {
        tries++;
        f.src = base + path + (path.indexOf("?") >= 0 ? "&" : "?") + "kp_frame=" + tries;
      }
      load();
      // 首次跨域加载慢时显示"重试/直接打开"，不自动重置（避免打断正在进行的加载）
      setTimeout(function () {
        if (loaded) return;
        document.getElementById("msg").classList.remove("hidden");
        document.querySelector("#msg div").innerHTML =
          "<b>🐱🐶 KittenPuppy4Ever</b>工作台加载较慢…" +
          '<div style="margin-top:10px"><button id="retry" style="border:1px solid #d9cdb9;background:#fff;border-radius:999px;padding:6px 14px;cursor:pointer">重试</button> ' +
          '<a href="' + base + path + '" style="margin-left:8px">直接打开</a></div>';
        var btn = document.getElementById("retry");
        if (btn) btn.onclick = function () {
          document.querySelector("#msg div").innerHTML = "<b>🐱🐶 KittenPuppy4Ever</b>正在重试…";
          load();
        };
      }, 20000);
    })
    .catch(function (e) { fail("无法读取入口配置：" + e.message); });

  // 子页面（隧道内的工作台）把路径同步回来，地址栏保持在 github.io 原格式
  window.addEventListener("message", function (e) {
    if (!base || e.origin !== new URL(base).origin) return;
    if (e.data && e.data.kpLanding) {
      location.href = PREFIX + "/";
      return;
    }
    var p = e.data && e.data.kpPath;
    if (typeof p !== "string" || p.charAt(0) !== "/") return;
    var want = PREFIX + p;
    if (location.pathname + location.search !== want) {
      history.replaceState(null, "", want);
    }
  });
})();
</script>
</body>
</html>
"""

PATHS = [
    "index.html",
    "dashboard/index.html",
    "dashboard/map/index.html",
    "wishpool/index.html",
    "mock/index.html",
    "courtyard/index.html",
    "home/index.html",
    "login/index.html",
    "ai/index.html",
    "schedule-debug/index.html",
    "bottle/index.html",
]


def creds():
    owner = open(OWNER_FILE, encoding="utf-8").read().strip()
    token = open(TOKEN_FILE, encoding="utf-8").read().strip()
    return owner, token


def api(owner, token, method, path, data=None):
    url = "https://api.github.com/repos/%s/%s/contents/%s" % (owner, REPO, path)
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/vnd.github+json",
               "Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="rewrite existing iframe shims")
    args = ap.parse_args()
    owner, token = creds()
    shim_file = os.path.join(HERE, "..", "data", "shim.html")
    shim_src = open(shim_file, encoding="utf-8").read() if os.path.exists(shim_file) else SHIM
    content = base64.b64encode(shim_src.encode("utf-8")).decode("utf-8")

    for rel in PATHS:
        path = "KittenPuppy4Ever/" + rel
        try:
            sha = api(owner, token, "GET", path).get("sha")
        except Exception as e:
            print("  %-32s 读取失败（%s），将新建" % (rel, e))
            sha = None
        # 已经是 iframe 承载页则跳过
        try:
            cur = base64.b64decode(api(owner, token, "GET", path)["content"]).decode("utf-8", "replace")
            if (not args.force) and "id=\"frame\"" in cur and "kpPath" in cur and "kp_frame" in cur and "加载较慢" in cur:
                print("  %-32s 已是 iframe 承载页，跳过" % rel)
                continue
        except Exception:
            pass
        if args.dry_run:
            print("  PUT %s (%s)" % (path, "update" if sha else "create"))
            continue
        payload = {"message": "entry: keep github.io URL (iframe shell)", "content": content}
        if sha:
            payload["sha"] = sha
        api(owner, token, "PUT", path, payload)
        print("  PUT %s ok" % rel)
    print("完成。GitHub Pages 约 1~10 分钟生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
