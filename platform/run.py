# -*- coding: utf-8 -*-
"""KittenPuppy4Ever 平台原型：树状项目库 + 抽象项目机制。

运行：
    python platform/run.py --port 8770
"""

import argparse
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from kernel.server import PlatformServer  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--dev", action="store_true", help="开发模式：未登录自动以 puppy 身份进入")
    ap.add_argument("--no-dev", action="store_true", help="强制关闭 dev 自动登录（正式部署）")
    args = ap.parse_args()

    srv = PlatformServer((args.host, args.port), HERE)
    if args.dev:
        srv.auth.config["dev_mode"] = True
    elif args.no_dev:
        srv.auth.config["dev_mode"] = False
    print("KittenPuppy4Ever 平台内核已启动: http://%s:%d" % (args.host, args.port))
    print("  项目树: %s" % ", ".join(srv.registry.order) if srv.registry.order else "  (空)")
    if srv.registry.errors:
        print("  注册错误: %s" % srv.registry.errors)
    # 绑定端口后，再在后台预热 Mock 后端，避免拖慢启动/被守护判定为失败
    try:
        threading.Timer(2.0, srv.mock_gateway.prewarm).start()
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("已停止")


if __name__ == "__main__":
    main()
