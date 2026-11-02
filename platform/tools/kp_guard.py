# -*- coding: utf-8 -*-
"""KittenPuppy4Ever 新引擎 · 自愈守护（替代旧的 tunnel_supervisor + public_dash）。

每 20 秒巡检：
  1) 8772 引擎不响应        -> 拉起 platform/run.py（正式模式，dev 关闭）
  2) Mock 后端已并入引擎进程（不再有 8768）
  3) cloudflared 不存在/隧道探测失败 -> 重启隧道，拿到新 URL
  4) 隧道 URL 变化          -> 写 data/tunnel_url.txt + 更新 GitHub 的
                              kitten/KittenPuppy4Ever/entry.json
日志：platform/data/_migration/guard.log
用法：pythonw platform/tools/kp_guard.py   或  python platform/tools/kp_guard.py
"""

import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.dirname(HERE)
LOCALDATA = os.path.join(DASH, "localdata")
CONF_DIR = os.path.join(os.path.expanduser("~"), ".dashboard_config")
DATA = os.path.join(HERE, "data", "_migration")
LOG_FILE = os.path.join(DATA, "guard.log")
URL_FILE = os.path.join(HERE, "data", "tunnel_url.txt")
STATE_FILE = os.path.join(DATA, "guard_state.json")

ENGINE_PORT = 8772
MOCK_PORT = 8768
MOCK_DIR = os.path.normpath(os.path.join(DASH, "..", "..", "MockInterview"))
MOCK_PY = os.path.join(MOCK_DIR, ".venv", "Scripts", "python.exe")
CLOUDFLARED = os.path.join(LOCALDATA, "cloudflared.exe")
if not os.path.exists(CLOUDFLARED):
    CLOUDFLARED = r"D:\Seafile\pytorch-unet-road\cloudflared.exe"
REPO = "kitten"
REPO_PATH = "KittenPuppy4Ever/entry.json"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
TUNNEL_CONF = os.path.join(HERE, "config", "tunnel.json")
TAILSCALE = r"C:\Program Files\Tailscale\tailscale.exe"


def load_tunnel_conf():
    try:
        with open(TUNNEL_CONF, encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


TUNNEL_CFG = load_tunnel_conf()
TUNNEL_MODE = (TUNNEL_CFG.get("mode") or "quick").lower()
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CURL = shutil.which("curl") or r"C:\Windows\System32\curl.exe"
PY = sys.executable
ENGINE_PY = os.path.join(r"D:\KittenLisaWork\MockInterview", ".venv", "Scripts", "python.exe")
if not os.path.isfile(ENGINE_PY):
    ENGINE_PY = PY
INTERVAL = 20
ISSUE_URL = "https://raw.githubusercontent.com/%s/%s/main/%s"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_engine_proc = None
_mock_proc = None
_tunnel_proc = None
_engine_log = None
_tunnel_url = ""
_tunnel_started = 0.0
_fail_count = 0
_entry_synced = ""


def log(msg):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def port_open(port, timeout=1.2):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def http_json(url, timeout=8):
    """用 curl 探测：Windows 上 urllib 的 TLS 偶发 SSL EOF，会把活隧道误判成死的。"""
    try:
        p = subprocess.run([CURL, "-sS", "--max-time", str(int(timeout)), url],
                           capture_output=True, timeout=int(timeout) + 5,
                           creationflags=NO_WINDOW)
        if p.returncode != 0 or not (p.stdout or b"").startswith(b"{"):
            return None
        return json.loads(p.stdout.decode("utf-8", "replace"))
    except Exception:
        return None

def load_github():
    owner = open(os.path.join(CONF_DIR, "github_user.txt"), encoding="utf-8").read().strip()
    token = open(os.path.join(CONF_DIR, "github_token.txt"), encoding="utf-8").read().strip()
    return owner, token


def curl_json(url, method="GET", headers=None, data=None, timeout=20):
    """GitHub 偶尔 SSL EOF（本机 Python SSL 栈问题），用系统 curl 兜底。"""
    args = [CURL, "-sS", "-L", "--max-time", str(timeout), "-X", method]
    for k, v in (headers or {}).items():
        args += ["-H", "%s: %s" % (k, v)]
    args.append(url)
    if data is not None:
        args += ["--data-binary", "@-"]
    p = subprocess.run(args, input=data, capture_output=True, timeout=timeout + 5,
                       creationflags=NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or b"").decode("utf-8", "replace")[:300])
    raw = (p.stdout or b"").decode("utf-8", "replace").strip()
    return json.loads(raw) if raw else {}


def update_entry(url):
    global _entry_synced
    owner, token = load_github()
    api = "https://api.github.com/repos/%s/%s/contents/%s" % (owner, REPO, REPO_PATH)
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/vnd.github+json",
               "Content-Type": "application/json"}
    sha = None
    for attempt in (1, 2, 3):
        try:
            req = urllib.request.Request(api, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=20) as r:
                sha = json.loads(r.read().decode("utf-8")).get("sha")
            break
        except Exception as e:
            log("[entry] 读取 sha 失败(%d/3): %s" % (attempt, e))
            try:
                sha = curl_json(api, headers=headers).get("sha")
                break
            except Exception as e2:
                log("[entry] curl 读取也失败(%d/3): %s" % (attempt, e2))
                time.sleep(3 * attempt)
    doc = {"url": url, "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    payload = json.dumps({
        "message": "update dash tunnel url",
        "content": base64.b64encode(json.dumps(doc, ensure_ascii=False).encode("utf-8")).decode("utf-8"),
        **({"sha": sha} if sha else {}),
    }).encode("utf-8")
    for attempt in (1, 2, 3):
        try:
            req = urllib.request.Request(api, data=payload, headers=headers, method="PUT")
            with urllib.request.urlopen(req, timeout=20) as r:
                r.read()
            log("[entry] 已更新 entry.json -> %s" % url)
            _entry_synced = url
            return True
        except Exception as e:
            log("[entry] urllib 写入失败(%d/3): %s" % (attempt, e))
            try:
                curl_json(api, method="PUT", headers=headers, data=payload)
                log("[entry] 已更新 entry.json (curl) -> %s" % url)
                _entry_synced = url
                return True
            except Exception as e2:
                log("[entry] curl 写入也失败(%d/3): %s" % (attempt, e2))
                time.sleep(3 * attempt)
    return False


def ensure_entry():
    """每轮核对 GitHub 上的 entry.json 是否指向当前隧道（修正失败/漏更新）。"""
    global _entry_synced
    if not _tunnel_url or _entry_synced == _tunnel_url:
        return
    owner, _ = load_github()
    url = ISSUE_URL % (owner, REPO, REPO_PATH)
    try:
        remote = curl_json(url).get("url")
    except Exception as e:
        log("[entry] 远端核对失败: %s" % e)
        return
    if remote == _tunnel_url:
        _entry_synced = _tunnel_url
        return
    log("[entry] 远端仍是 %r，重推 %r" % (remote, _tunnel_url))
    update_entry(_tunnel_url)


def ensure_engine():
    global _engine_proc, _engine_log
    if port_open(ENGINE_PORT):
        return
    log("[engine] 8772 无响应 -> 启动 platform/run.py")
    os.makedirs(DATA, exist_ok=True)
    _engine_log = open(os.path.join(DATA, "engine.log"), "ab")
    _engine_proc = subprocess.Popen(
        [ENGINE_PY, "-u", os.path.join(HERE, "run.py"), "--port", str(ENGINE_PORT)],
        cwd=HERE, stdout=_engine_log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    for _ in range(20):
        time.sleep(0.5)
        if port_open(ENGINE_PORT):
            log("[engine] 已启动 pid=%s" % _engine_proc.pid)
            return
    log("[engine] 启动后 10 秒内仍不通，稍后重试")


def ensure_mock():
    global _mock_proc
    if port_open(MOCK_PORT):
        return
    if not os.path.isfile(MOCK_PY):
        log("[mock] 找不到 %s" % MOCK_PY)
        return
    log("[mock] 8768 无响应 -> 启动 mock_web.py")
    os.makedirs(DATA, exist_ok=True)
    out = open(os.path.join(DATA, "mock.log"), "ab")
    _mock_proc = subprocess.Popen([MOCK_PY, "-u", "mock_web.py"], cwd=MOCK_DIR,
                                  stdout=out, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)


def ensure_tailscale_funnel():
    """确保 tailscale funnel 仍然把 443 反代到本地引擎。"""
    try:
        p = subprocess.run([TAILSCALE, "funnel", "status"], capture_output=True,
                           timeout=20, creationflags=NO_WINDOW)
        out = (p.stdout or b"").decode("utf-8", "replace")
        if "proxy http://127.0.0.1:%d" % ENGINE_PORT in out:
            return True
    except Exception:
        pass
    try:
        p = subprocess.run([TAILSCALE, "funnel", "--bg", "--yes", str(ENGINE_PORT)],
                           capture_output=True, timeout=60, creationflags=NO_WINDOW)
        out = ((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", "replace").strip()
        log("[tailscale] 尝试启动 funnel: %s" % out.splitlines()[-1:])
        return True
    except Exception as e:
        log("[tailscale] funnel 启动失败: %s" % e)
        return False


def start_tunnel():
    global _tunnel_proc, _tunnel_url, _tunnel_started, _fail_count
    if TUNNEL_MODE == "tailscale":
        _tunnel_url = (TUNNEL_CFG.get("public_url") or "").rstrip("/")
        _fail_count = 0
        try:
            with open(URL_FILE, "w", encoding="utf-8") as f:
                f.write(_tunnel_url)
        except Exception:
            pass
        ensure_tailscale_funnel()
        log("[tunnel] Tailscale 固定地址: %s" % _tunnel_url)
        if _tunnel_url:
            update_entry(_tunnel_url)
        return True
    log("[tunnel] 启动 cloudflared -> 127.0.0.1:%d" % ENGINE_PORT)
    _tunnel_started = time.time()
    _fail_count = 0
    _tunnel_proc = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--protocol", "http2",
         "--url", "http://127.0.0.1:%d" % ENGINE_PORT],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, text=True,
        encoding="utf-8", errors="replace")
    got = threading.Event()
    tail = []

    def reader():
        global _tunnel_url, _tunnel_started, _entry_synced
        for line in _tunnel_proc.stderr:
            tail.append(line.rstrip())
            del tail[:-5]
            m = URL_RE.search(line)
            if m and "api.trycloudflare" not in line:
                url = m.group(0)
                _tunnel_url = url
                _tunnel_started = time.time()
                _entry_synced = ""
                try:
                    with open(URL_FILE, "w", encoding="utf-8") as f:
                        f.write(url)
                except Exception:
                    pass
                log("[tunnel] 新地址: %s" % url)
                got.set()

                # 等边缘节点真正可达再写 GitHub entry，避免把死链推给用户
                def publish(u=url):
                    for _ in range(20):
                        if http_json(u + "/api/session", timeout=4) is not None:
                            update_entry(u)
                            log("[tunnel] 边缘可达，entry 已更新")
                            return
                        time.sleep(2)
                    update_entry(u)
                    log("[tunnel] 20 次探测仍未恢复，先写入 entry 供稍后重试")

                threading.Thread(target=publish, daemon=True, name="kp-tunnel-publish").start()
                # 注意：不能 return，必须继续排空 stderr，否则管道写满后 cloudflared 会阻塞/退出

    threading.Thread(target=reader, daemon=True, name="kp-tunnel-reader").start()
    if got.wait(45):
        return True
    log("[tunnel] 45 秒内没拿到地址；最近输出: %s" % " / ".join(tail))
    return False


def internet_ok():
    """区分"隧道坏了"和"整机断网"：整机断网时不要重启隧道。"""
    try:
        p = subprocess.run([CURL, "-sS", "--max-time", "6",
                            "https://www.cloudflare.com/cdn-cgi/trace"],
                           capture_output=True, timeout=12, creationflags=NO_WINDOW)
        return p.returncode == 0 and b"colo=" in (p.stdout or b"")
    except Exception:
        return False


def tunnel_alive():
    """返回 True 表示"当前隧道可用，不要重启"。

    quick tunnel 刚建立时 DNS/边缘节点需要几秒~几十秒才可达，所以前 30 秒视为正常；
    探测失败时先判断是不是整机断网（断网不背锅），连续 5 次失败才判定隧道故障。
    """
    global _fail_count
    if TUNNEL_MODE == "tailscale":
        if not _tunnel_url:
            return False
        ok = http_json(_tunnel_url + "/api/session", timeout=20) is not None
        if ok:
            return True
        ensure_tailscale_funnel()
        return http_json(_tunnel_url + "/api/session", timeout=20) is not None
    if _tunnel_proc is None or _tunnel_proc.poll() is not None:
        return False
    if not _tunnel_url:
        return False
    if time.time() - _tunnel_started < 30:
        return True
    got = http_json(_tunnel_url + "/api/session", timeout=8)
    if got is not None and "session" in got:
        if _fail_count:
            log("[tunnel] 探测恢复（之前失败 %d 次）" % _fail_count)
        _fail_count = 0
        return True
    if not internet_ok():
        log("[tunnel] 探测失败但整机网络不通，暂不重启隧道")
        return True
    # 引擎正在重启/无响应时，隧道失败是果不是因：保留当前隧道，等引擎回来
    local = http_json("http://127.0.0.1:%d/api/health" % ENGINE_PORT, timeout=4)
    if local is None:
        log("[tunnel] 本地引擎无响应，暂不重启隧道（等引擎恢复）")
        return True
    _fail_count += 1
    log("[tunnel] 探测失败 %d/10: %s" % (_fail_count, _tunnel_url))
    return _fail_count < 10


def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "engine_port": ENGINE_PORT, "tunnel": _tunnel_url}, f, ensure_ascii=False)
    except Exception:
        pass


def acquire_lock():
    """单实例：防止计划任务重复拉起多个 guard。"""
    try:
        import msvcrt
    except ImportError:
        return True
    os.makedirs(DATA, exist_ok=True)
    f = open(os.path.join(DATA, "guard.lock"), "a+b")
    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        return f
    except Exception:
        f.close()
        return None


def main():
    global _tunnel_url
    lock = acquire_lock()
    if not lock:
        log("另一个 guard 已在运行，本实例退出")
        return
    log("=== KittenPuppy4Ever guard 启动（engine %d · Mock 进程内） ===" % ENGINE_PORT)
    if TUNNEL_MODE == "tailscale":
        _tunnel_url = (TUNNEL_CFG.get("public_url") or "").rstrip("/")
    else:
        try:
            with open(URL_FILE, encoding="utf-8") as f:
                _tunnel_url = f.read().strip()
        except Exception:
            _tunnel_url = ""
    ensure_engine()
    start_tunnel()
    save_state()
    while True:
        try:
            ensure_engine()
            ensure_entry()
            if not tunnel_alive():
                if TUNNEL_MODE != "tailscale":
                    if _tunnel_proc is not None and _tunnel_proc.poll() is None:
                        log("[tunnel] 探测失败 -> 结束旧隧道进程")
                        try:
                            _tunnel_proc.kill()
                        except Exception:
                            pass
                start_tunnel()
                save_state()
        except Exception as e:
            log("[guard] 巡检异常: %s" % e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
