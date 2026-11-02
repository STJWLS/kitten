# -*- coding: utf-8 -*-
"""修改某个角色的登录口令（只写 PBKDF2 哈希，不保存明文）。

用法：
    python platform/tools/set_password.py kitten
    （运行后按提示输入两次新口令；输入内容不会回显）

也可以非交互：
    python platform/tools/set_password.py kitten --stdin   （从 stdin 读一行）
"""

import argparse
import getpass
import hashlib
import json
import os
import secrets
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLATFORM = os.path.dirname(HERE)
USERS = os.path.join(PLATFORM, "config", "users.json")
ITER = 200_000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("user", choices=["kitten", "puppy"])
    ap.add_argument("--stdin", action="store_true", help="从标准输入读口令（脚本用）")
    args = ap.parse_args()

    if args.stdin:
        pwd = sys.stdin.readline().rstrip("\r\n")
    else:
        pwd = getpass.getpass("新口令（不回显）：")
        again = getpass.getpass("再输一次：")
        if pwd != again:
            print("两次输入不一致，未修改。")
            return 1
    if len(pwd) < 6:
        print("口令太短（至少 6 位），未修改。")
        return 1

    with open(USERS, encoding="utf-8") as f:
        users = json.load(f)
    rec = users.get(args.user)
    if not rec:
        print("没有这个角色：%s" % args.user)
        return 1

    salt = secrets.token_hex(16)
    rec["salt"] = salt
    rec["iterations"] = ITER
    rec["hash"] = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"),
                                     bytes.fromhex(salt), ITER).hex()
    users[args.user] = rec
    with open(USERS, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=1)
    print("已更新 %s 的口令（只保存哈希）。如需立即生效，重启 8772 引擎即可（守护会自动拉起）。" % args.user)
    return 0


if __name__ == "__main__":
    sys.exit(main())
