# -*- coding: utf-8 -*-
"""身份与会话：服务器侧校验（替代现在 auth.js 里把口令写进前端的那套）。

- users.json 存 PBKDF2-SHA256(200k) 的口令哈希，不存明文
- 会话 = HMAC-SHA256 签名的 cookie（HttpOnly，7 天）
- dev_mode 下（config/platform.json）未登录请求自动以 puppy 身份进入，
  只为本地原型演示方便；正式迁移时关掉即可。
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

SESSION_TTL = 7 * 24 * 3600
COOKIE = "kp_session"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


ROLE_SUPER = "superadmin"
ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_LABEL = {ROLE_SUPER: "超级管理员", ROLE_ADMIN: "管理员", ROLE_USER: "成员"}


class Auth:
    def __init__(self, root: str):
        self.root = root
        self.config = self._read_json(os.path.join(root, "config", "platform.json"), {})
        self.users = self._read_json(os.path.join(root, "config", "users.json"), {})
        self._secret = self._load_secret()
        self._lock = threading.RLock()
        self._dirty = False
        self._last_save = 0.0
        self._migrate()

    # ---------------- 用户模型迁移 / 持久化 ----------------
    def _users_path(self):
        return os.path.join(self.root, "config", "users.json")

    def _migrate(self):
        old = {"主要维护者": ROLE_SUPER, "主要使用者": ROLE_ADMIN}
        changed = False
        for name, rec in self.users.items():
            if not isinstance(rec, dict):
                continue
            role = rec.get("role")
            if role in old:
                rec["role"] = old[role]; changed = True
            elif role not in (ROLE_SUPER, ROLE_ADMIN, ROLE_USER):
                rec["role"] = ROLE_USER; changed = True
            if name == "kitten" and rec.get("role") != ROLE_ADMIN:
                rec["role"] = ROLE_ADMIN; changed = True
            if name == "puppy" and rec.get("role") != ROLE_SUPER:
                rec["role"] = ROLE_SUPER; changed = True
            if not isinstance(rec.get("modules"), dict):
                rec["modules"] = {}; changed = True
            if not isinstance(rec.get("maintain"), dict):
                rec["maintain"] = {}; changed = True
            rec.setdefault("active_seconds", 0)
            rec.setdefault("last_seen", 0)
            rec.setdefault("created_at", int(time.time()))
        if changed:
            self.save_users()

    def save_users(self):
        with self._lock:
            path = self._users_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.users, f, ensure_ascii=False, indent=1, sort_keys=True)
            os.replace(tmp, path)
            self._dirty = False
            self._last_save = time.time()

    def _flush_later(self):
        if time.time() - self._last_save > 20:
            self.save_users()

    # ---------------- 角色与权限 ----------------
    def role_of(self, user):
        rec = self.users.get(user) or {}
        role = rec.get("role")
        return role if role in (ROLE_SUPER, ROLE_ADMIN, ROLE_USER) else ROLE_USER

    def is_super(self, user):
        return self.role_of(user) == ROLE_SUPER

    def is_admin(self, user):
        return self.role_of(user) in (ROLE_SUPER, ROLE_ADMIN)

    def can_access(self, user, module):
        if not user or user not in self.users:
            return False
        if self.is_admin(user):
            return True
        return bool((self.users[user].get("modules") or {}).get(module))

    def can_maintain(self, user, module):
        if not user or user not in self.users:
            return False
        if self.is_super(user):
            return True
        if not self.is_admin(user):
            return False
        return bool((self.users[user].get("maintain") or {}).get(module))

    def modules_of(self, user):
        rec = self.users.get(user) or {}
        return dict(rec.get("modules") or {}), dict(rec.get("maintain") or {})

    def record_activity(self, user, gap_limit=300):
        if not user or user not in self.users:
            return
        now = time.time()
        with self._lock:
            rec = self.users[user]
            last = float(rec.get("last_seen") or 0)
            if last:
                delta = min(max(0, now - last), gap_limit)
                rec["active_seconds"] = int(rec.get("active_seconds") or 0) + int(delta)
            rec["last_seen"] = int(now)
            self._dirty = True
        self._flush_later()

    # ---------------- 管理操作 ----------------
    def _valid_name(self, user):
        return bool(user) and all(c.isalnum() or c in "_-" for c in user) and len(user) <= 32

    def create_user(self, user, password, role=ROLE_USER):
        if not self._valid_name(user):
            return False, "用户名只能包含字母/数字/下划线，最长 32"
        if user in self.users:
            return False, "用户已存在"
        if role not in (ROLE_SUPER, ROLE_ADMIN, ROLE_USER):
            return False, "角色不合法"
        salt = secrets.token_hex(16)
        rec = {"role": role, "name": user, "emoji": "🐱" if role != ROLE_ADMIN else "🛠️",
               "salt": salt, "iterations": 200_000,
               "hash": self.hash_password(password, salt),
               "modules": {}, "maintain": {}, "active_seconds": 0,
               "last_seen": 0, "created_at": int(time.time())}
        with self._lock:
            self.users[user] = rec
            self.save_users()
        return True, "ok"

    def reset_password(self, user, password):
        rec = self.users.get(user)
        if not rec:
            return False, "用户不存在"
        salt = secrets.token_hex(16)
        with self._lock:
            rec["salt"] = salt
            rec["iterations"] = 200_000
            rec["hash"] = self.hash_password(password, salt)
            self.save_users()
        return True, "ok"

    def delete_user(self, user):
        if user not in self.users:
            return False, "用户不存在"
        supers = [u for u, r in self.users.items() if r.get("role") == ROLE_SUPER]
        if self.role_of(user) == ROLE_SUPER and len(supers) <= 1:
            return False, "至少保留一个超级管理员"
        with self._lock:
            del self.users[user]
            self.save_users()
        return True, "ok"

    def set_role(self, user, role):
        if user not in self.users:
            return False, "用户不存在"
        if role not in (ROLE_SUPER, ROLE_ADMIN, ROLE_USER):
            return False, "角色不合法"
        with self._lock:
            self.users[user]["role"] = role
            self.save_users()
        return True, "ok"

    def set_module(self, user, module, allow, kind="modules"):
        if user not in self.users:
            return False, "用户不存在"
        with self._lock:
            rec = self.users[user]
            rec.setdefault(kind, {})[module] = bool(allow)
            self.save_users()
        return True, "ok"

    def public_users(self, viewer):
        """admin 只看 user；superadmin 看全部。"""
        out = []
        seen = time.time()
        for name, rec in sorted(self.users.items()):
            role = rec.get("role") or ROLE_USER
            mods, maint = self.modules_of(name)
            can_manage = False
            if name != viewer:
                if self.is_super(viewer):
                    can_manage = role in (ROLE_USER, ROLE_ADMIN)
                elif self.is_admin(viewer):
                    can_manage = role == ROLE_USER
            out.append({
                "user": name, "name": rec.get("name", name), "emoji": rec.get("emoji", "🐱"),
                "role": role, "role_label": ROLE_LABEL.get(role, role),
                "modules": mods, "maintain": maint, "can_manage": can_manage,
                "active_seconds": int(rec.get("active_seconds") or 0),
                "last_seen": int(rec.get("last_seen") or 0),
                "active": (seen - float(rec.get("last_seen") or 0)) < 300,
                "created_at": int(rec.get("created_at") or 0),
            })
        return out

    def usage_summary(self, viewer):
        users = self.public_users(viewer)
        return {
            "users": users,
            "total": len(users),
            "active_users": sum(1 for x in users if x["active"]),
            "total_active_seconds": sum(x["active_seconds"] for x in users),
        }

    # ---------------- 基础 ----------------
    @staticmethod
    def _read_json(path, default):
        try:
            with open(path, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            return default

    def _load_secret(self):
        path = os.path.join(self.root, "config", "session.key")
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception:
            key = secrets.token_bytes(32)
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(key)
            except Exception:
                pass
            return key

    @property
    def dev_mode(self):
        return bool(self.config.get("dev_mode"))

    # ---------------- 口令 ----------------
    @staticmethod
    def hash_password(password: str, salt_hex: str, iterations: int = 200_000) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex),
            iterations).hex()

    def verify(self, user: str, password: str) -> bool:
        rec = self.users.get(user)
        if not rec:
            return False
        try:
            calc = self.hash_password(password, rec["salt"], int(rec.get("iterations", 200_000)))
        except Exception:
            return False
        return hmac.compare_digest(calc, rec.get("hash", ""))

    def profile(self, user: str) -> dict:
        rec = dict(self.users.get(user) or {})
        rec.pop("salt", None)
        rec.pop("hash", None)
        role = rec.get("role") if rec.get("role") in (ROLE_SUPER, ROLE_ADMIN, ROLE_USER) else ROLE_USER
        mods, maint = self.modules_of(user)
        return {"user": user, "role": role, "role_label": ROLE_LABEL.get(role, role),
                "emoji": rec.get("emoji", "🐱"), "name": rec.get("name", user),
                "is_admin": role in (ROLE_SUPER, ROLE_ADMIN),
                "is_super": role == ROLE_SUPER,
                "modules": mods, "maintain": maint}

    # ---------------- 会话 ----------------
    def issue(self, user: str) -> str:
        payload = _b64e(json.dumps({"u": user, "exp": int(time.time()) + SESSION_TTL},
                                   separators=(",", ":")).encode())
        sig = _b64e(hmac.new(self._secret, payload.encode(), hashlib.sha256).digest())
        return payload + "." + sig

    def read(self, raw: str):
        """校验 cookie，返回用户名或 None。"""
        try:
            payload, sig = raw.rsplit(".", 1)
            expect = _b64e(hmac.new(self._secret, payload.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(sig, expect):
                return None
            data = json.loads(_b64d(payload))
            if int(data.get("exp", 0)) < int(time.time()):
                return None
            return data.get("u")
        except Exception:
            return None

    @staticmethod
    def cookie_header(value: str, max_age: int = SESSION_TTL, secure: bool = False) -> str:
        """secure=True 时使用适合第三方 iframe 的 cookie：
        SameSite=None; Secure; Partitioned（CHIPS），否则浏览器会在 GitHub Pages 的 iframe 里丢弃它。"""
        if secure:
            return ("%s=%s; Path=/; HttpOnly; Secure; SameSite=None; Partitioned; Max-Age=%d"
                    % (COOKIE, value, max_age))
        return "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d" % (COOKIE, value, max_age)

    @staticmethod
    def clear_cookie(secure: bool = False) -> str:
        if secure:
            return ("%s=; Path=/; HttpOnly; Secure; SameSite=None; Partitioned; Max-Age=0" % COOKIE)
        return "%s=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" % COOKIE
