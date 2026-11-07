# -*- coding: utf-8 -*-
"""Generate/update GitHub Pages path shells for every navigable module.

Each module path gets KittenPuppy4Ever/<path>/index.html. The shell reads
entry.json at runtime (so the tunnel URL can change without rebuilding the
shell), embeds the backend at the same path, and mirrors inner kpPath updates
back into the GitHub Pages address bar. That keeps subpages refreshable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

PREFIX = "/kitten/KittenPuppy4Ever"
SHELL = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KittenPuppy4Ever</title>
<style>
  html, body { height: 100%; margin: 0; background: #f8f4ec; }
  #frame { position: fixed; inset: 0; width: 100%; height: 100%; border: 0; background: #f8f4ec; }
  #msg { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center;
    font: 13px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; color: #8a7f6d;
    background: linear-gradient(160deg, #fbf7f0, #eee1d6); transition: opacity .25s; }
  #msg.hidden { opacity: 0; pointer-events: none; }
  #msg b { color: #42392b; display: block; margin-bottom: 6px; font-size: 15px; }
</style>
</head>
<body>
<iframe id="frame" allow="microphone; camera; autoplay; fullscreen" title="KittenPuppy4Ever"></iframe>
<div id="msg"><div><b>🐱🐶 KittenPuppy4Ever</b>正在连接工作台…</div></div>
<script>
(function () {
  var PREFIX = "__PREFIX__";
  var path = location.pathname.indexOf(PREFIX) === 0
    ? (location.pathname.slice(PREFIX.length) || "/")
    : "/";
  if (path.charAt(0) !== "/") path = "/" + path;
  var f = document.getElementById("frame");
  var msg = document.getElementById("msg");
  var loaded = false;
  function showError(text) {
    msg.classList.remove("hidden");
    msg.innerHTML = "<div><b>🐱🐶 KittenPuppy4Ever</b>" + text +
      '<div style="margin-top:10px"><a href="__PREFIX__/entry.json">查看 entry.json</a></div></div>';
  }
  fetch(PREFIX + "/entry.json?ts=" + Date.now(), {cache: "no-store"})
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d || !d.url) throw new Error("entry.json 未配置 url");
      var base = d.url.replace(/\\/+$/, "");
      var target = base + path + (path.indexOf("?") >= 0 ? "&" : "?") + "kp_frame=1";
      f.src = target;
      f.onload = function () { loaded = true; msg.classList.add("hidden"); };
      setTimeout(function () {
        if (!loaded) showError("工作台加载较慢…");
      }, 15000);
    })
    .catch(function (e) { showError("无法读取入口：" + e.message); });

  window.addEventListener("message", function (e) {
    try { if (e.origin !== new URL(PREFIX + "/entry.json", location.href).origin) return; } catch (err) { return; }
    if (e.data && e.data.kpLanding) { location.href = PREFIX + "/"; return; }
    var p = e.data && e.data.kpPath;
    if (typeof p !== "string" || p.charAt(0) !== "/") return;
    var want = PREFIX + p;
    if (location.pathname + location.search !== want) history.replaceState(null, "", want);
  });
})();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pages-root", default="")
    args = ap.parse_args()
    platform = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo = os.path.dirname(platform)
    pages = args.pages_root or os.path.join(repo, "KittenPuppy4Ever")
    if not os.path.isdir(pages):
        print("pages root not found: %s" % pages, file=sys.stderr)
        return 2
    projects = os.path.join(platform, "projects")
    changed = 0
    missing = []
    for name in sorted(os.listdir(projects)):
        pdir = os.path.join(projects, name)
        mf = os.path.join(pdir, "project.json")
        if not os.path.isdir(pdir) or not os.path.isfile(mf):
            continue
        try:
            doc = json.load(open(mf, encoding="utf-8"))
        except Exception as exc:
            print("SKIP %s (bad json: %s)" % (name, exc)); continue
        path = doc.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            if not doc.get("hidden"):
                missing.append(name)
            continue
        rel = path.strip("/")
        if not rel or rel.startswith("../") or "/../" in rel:
            print("SKIP %s (unsafe path %r)" % (name, path)); continue
        out = os.path.join(pages, *rel.split("/"), "index.html")
        html = SHELL.replace("__PREFIX__", PREFIX)
        if args.dry_run:
            print("PUT %s" % out); continue
        os.makedirs(os.path.dirname(out), exist_ok=True)
        old = ""
        if os.path.isfile(out):
            try: old = open(out, encoding="utf-8").read()
            except Exception: old = ""
        if old != html:
            open(out, "w", encoding="utf-8", newline="\n").write(html)
            changed += 1
            print("UPDATED %s" % out)
        else:
            print("OK %s" % out)
    if missing:
        print("MISSING PATH for visible modules: %s" % ", ".join(missing), file=sys.stderr)
        return 1
    print("done; changed=%d" % changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
