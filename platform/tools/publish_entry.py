# -*- coding: utf-8 -*-
"""把 GitHub Pages 入口页从「iframe 套壳」改成「顶层跳转」到当前隧道。

旧入口页 iframe 隧道的 / 路径，而新内核的 / 本身就是根工作台（内部还有内容 iframe），
会变成 iframe 套 iframe、地址栏同步失效。这里改成：读 entry.json → location.replace。

用法：python platform/tools/publish_entry.py [--dry-run]
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
REPO = "kitten"
PATH = "KittenPuppy4Ever/index.html"

NEW_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KittenPuppy4Ever</title>
<style>
  html,body{height:100%;margin:0;}
  body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
    display:flex;align-items:center;justify-content:center;overflow:hidden;
    background:linear-gradient(160deg,#fbf7f0,#f4eadf 55%,#eee1d6);color:#42392b;}
  .orb{position:fixed;border-radius:50%;pointer-events:none;}
  .o1{width:460px;height:460px;top:-130px;left:-110px;
    background:radial-gradient(circle,rgba(246,184,207,.6),rgba(246,184,207,0) 70%);}
  .o2{width:430px;height:430px;bottom:-120px;right:-100px;
    background:radial-gradient(circle,rgba(168,196,239,.6),rgba(168,196,239,0) 70%);}
  .card{position:relative;background:rgba(255,255,255,.94);border:1px solid rgba(255,255,255,.8);
    border-radius:20px;padding:30px 40px;max-width:440px;text-align:center;
    box-shadow:0 18px 60px rgba(66,57,43,.16);}
  .logo{font-size:30px;line-height:1;}
  h1{margin:8px 0 2px;font-size:19px;font-family:monospace;}
  #s{font-size:12.5px;color:#8a7f6d;margin:12px 0 4px;font-family:monospace;}
  .hint{font-size:10.5px;color:#b5a88f;line-height:1.7;margin-top:12px;}
  a{color:#2f6fb5;}
</style>
</head>
<body>
<div class="orb o1"></div><div class="orb o2"></div>
<div class="card">
  <div class="logo">🐱🐶</div>
  <h1>KittenPuppy4Ever</h1>
  <div id="s">正在连接工作台…</div>
  <div class="hint">
    工作台由本机服务交付。若长时间停留：确认本机守护进程在跑<br>
    （<code>platform/tools/kp_guard.py</code>），或直接访问
    <a id="local" href="http://127.0.0.1:8772/">127.0.0.1:8772</a>
  </div>
</div>
<script>
(function(){
  // 入口页只做一件事：读 entry.json，顶层跳到当前隧道（不再 iframe 套 iframe）
  fetch("entry.json?ts=" + Date.now(), {cache: "no-store"})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if (d && d.url){
        document.getElementById("s").textContent = "已连接，正在进入…";
        location.replace(d.url.replace(/\\/+$/, "") + "/");
      } else {
        document.getElementById("s").textContent = "工作台入口未配置（entry.json 为空）";
      }
    })
    .catch(function(e){
      document.getElementById("s").textContent = "无法读取入口配置：" + e.message;
    });
})();
</script>
</body>
</html>
"""


def creds():
    token = open(os.path.join(CONF, "github_token.txt"), encoding="utf-8").read().strip()
    owner = open(os.path.join(CONF, "github_user.txt"), encoding="utf-8").read().strip()
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
    args = ap.parse_args()
    owner, token = creds()

    cur = api(owner, token, "GET", PATH)
    old = base64.b64decode(cur["content"]).decode("utf-8", "replace")
    print("当前入口页 %d 字节，sha=%s" % (len(old), cur["sha"][:10]))
    if "location.replace" in old and "entry.json" in old:
        print("入口页已经是跳转版，无需再推。")
        return 0
    if args.dry_run:
        print("dry-run：将替换为 %d 字节跳转页" % len(NEW_HTML))
        return 0

    payload = {
        "message": "entry: redirect to tunnel instead of iframe",
        "content": base64.b64encode(NEW_HTML.encode("utf-8")).decode("utf-8"),
        "sha": cur["sha"],
    }
    api(owner, token, "PUT", PATH, payload)
    print("已推送新入口页（GitHub Pages 约 1~10 分钟生效）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
