# -*- coding: utf-8 -*-
"""生成 config/users.json：从现有前端 auth.js 迁移两个角色的口令，存 PBKDF2 哈希。

出于安全考虑：脚本只写哈希，不回显明文。迁移完成后 auth.js 里那段明文应当删除，
改由本文件 + 服务器侧 /api/login 校验。
"""

import json
import os
import re
import secrets

HERE = os.path.dirname(os.path.abspath(__file__))
PLATFORM = os.path.dirname(HERE)
DASH = os.path.dirname(PLATFORM)
AUTH_JS = os.path.join(DASH, "emf-schedule", "assets", "auth.js")
OUT = os.path.join(PLATFORM, "config", "users.json")

USERS = {
    "kitten": {"emoji": "🐱", "role": "主要使用者", "name": "kitten"},
    "puppy": {"emoji": "🐶", "role": "主要维护者", "name": "puppy"},
}


def main():
    try:
        with open(AUTH_JS, encoding="utf-8") as f:
            src = f.read()
    except Exception as e:
        print("读不到 auth.js：%s" % e)
        return 1

    # saveCreds({kitten:"...", puppy:"..."}) 里的两个口令
    found = dict(re.findall(r'(kitten|puppy)\s*:\s*"([^"]*)"', src))
    out = {}
    for user, meta in USERS.items():
        pwd = found.get(user)
        if not pwd:
            print("auth.js 里没有找到 %s 的口令，跳过" % user)
            continue
        salt = secrets.token_hex(16)
        out[user] = dict(meta)
        out[user].update({
            "salt": salt,
            "iterations": 200_000,
            "hash": __import__("hashlib").pbkdf2_hmac(
                "sha256", pwd.encode("utf-8"), bytes.fromhex(salt), 200_000).hex(),
        })
        print("[users] %s -> PBKDF2 哈希已写入（明文未回显）" % user)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("已写入 %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
