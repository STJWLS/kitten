# -*- coding: utf-8 -*-
"""AI module-local API：技能、DSH 状态/流、工具、会话。"""
import base64
import hashlib
import json
import os
import re
import secrets
import time
from datetime import datetime
from urllib.parse import parse_qs, quote, urlparse

from kernel.project import TZ
from kernel.protocol import ProjectError, ok

PREFIXES = ["/api/ai/", "/api/files", "/api/llm/"]


def handle(handler, method, path, parsed):
    # 文件服务与 AI 上传/会话共用，先处理 /api/files
    if method == "GET" and path == "/api/files":
        user = handler._require_user()
        idx = handler._files_index()
        files = [handler._files_public(x) for x in idx.get("files") or [] if x.get("owner") == user]
        files.sort(key=lambda x: x.get("created") or "", reverse=True)
        handler._json(ok(files=files))
        return True
    fm = re.match(r"^/api/files/([^/]+)$", path)
    if method == "GET" and fm:
        user = handler._require_user()
        fid = fm.group(1)
        idx = handler._files_index()
        item = next((x for x in idx.get("files") or [] if x.get("id") == fid and x.get("owner") == user), None)
        if not item:
            raise ProjectError("not_found", "文件不存在", 404)
        path_enc = os.path.join(handler._files_root(), item.get("stored") or "")
        try:
            with open(path_enc, "rb") as f:
                token = f.read()
            data = handler._files_fernet().decrypt(token)
        except Exception:
            raise ProjectError("internal", "文件解密失败", 500)
        name = item.get("name") or "file"
        ascii_name = re.sub(r'[^A-Za-z0-9._-]', "_", name)[:80] or "file"
        disp = "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (ascii_name, quote(name))
        handler._send(data, 200, item.get("mime") or "application/octet-stream", cache="no-store",
                      extra={"Content-Disposition": disp})
        return True
    if method == "POST" and path == "/api/files/upload":
        user = handler._require_user()
        body = handler._read_json()
        name = os.path.basename(str(body.get("name") or "file")).strip()[:180] or "file"
        mime = str(body.get("mime") or "application/octet-stream")[:120]
        raw = str(body.get("data") or "")
        if "," in raw and raw.lstrip().startswith("data:"):
            raw = raw.split(",", 1)[1]
        try:
            data = base64.b64decode(raw, validate=True)
        except Exception:
            raise ProjectError("bad_request", "文件内容不是合法 base64", 400)
        if not data:
            raise ProjectError("bad_request", "文件为空", 400)
        if len(data) > 16 * 1024 * 1024:
            raise ProjectError("bad_request", "文件不能超过 16MB", 413)
        if body.get("dry_run"):
            token = handler._files_fernet().encrypt(data)
            dec = handler._files_fernet().decrypt(token)
            handler._json(ok(dry_run=True, file={"name": name, "mime": mime, "size": len(data),
                                                 "sha256": hashlib.sha256(data).hexdigest(),
                                                 "encrypted": len(token) > 0, "roundtrip": dec == data}))
            return True
        fid = secrets.token_hex(12)
        safe_user = re.sub(r"[^A-Za-z0-9_.-]", "_", user)[:60] or "user"
        rel = os.path.join(safe_user, fid + ".bin")
        full = os.path.join(handler._files_root(), rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        token = handler._files_fernet().encrypt(data)
        with open(full, "wb") as f:
            f.write(token)
        item = {"id": fid, "owner": user, "name": name, "mime": mime,
                "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "created": datetime.now(TZ).isoformat(timespec="seconds"),
                "stored": rel, "enc": "fernet"}
        idx = handler._files_index()
        idx.setdefault("files", []).append(item)
        handler._files_save_locked(idx)
        handler._json(ok(file=handler._files_public(item)))
        return True
    if method == "POST" and path == "/api/files/delete":
        user = handler._require_user()
        body = handler._read_json()
        fid = str(body.get("id") or "")
        idx = handler._files_index()
        item = next((x for x in idx.get("files") or [] if x.get("id") == fid and x.get("owner") == user), None)
        if not item:
            raise ProjectError("not_found", "文件不存在", 404)
        idx["files"] = [x for x in idx.get("files") or [] if not (x.get("id") == fid and x.get("owner") == user)]
        handler._files_save_locked(idx)
        try:
            os.remove(os.path.join(handler._files_root(), item.get("stored") or ""))
        except Exception:
            pass
        handler._json(ok(deleted=fid))
        return True

    if method == "GET":
        if path == "/api/ai/skills":
            user = handler._require_user()
            return handler._json(ok(skills=handler._ai_skill_catalog(user), enabled=handler._ai_skills_enabled(user),
                                 roots=handler._ai_skill_roots()))

        if path == "/api/ai/dsh/status":
            user = handler._require_user()
            return handler._json(ok(dsh=handler._dsh_status()))

        if path == "/api/ai/tools":
            user = handler._require_user()
            q = parse_qs(urlparse(handler.path).query)
            module = str((q.get("module") or [""])[0])[:40]
            return handler._json(ok(module=module, tools=handler._ai_tool_defs(module)))

        if path == "/api/ai/sessions":
            user = handler._require_user()
            return handler._json(ok(sessions=handler._ai_session_list(user)))

        if path == "/api/ai/sessions/backup":
            user = handler._require_user()
            sessions = handler._ai_session_list(user, full=True)
            return handler._json(ok(version=1, exported=datetime.now(TZ).isoformat(timespec="seconds"),
                                 user=user, sessions=sessions))

        sm = re.match(r"^/api/ai/sessions/([A-Za-z0-9_-]{4,64})$", path)
        if sm:
            user = handler._require_user()
            d = handler._ai_session_load(user, sm.group(1))
            if not d:
                raise ProjectError("not_found", "会话不存在", 404)
            return handler._json(ok(session=handler._ai_session_public(d, full=True)))

    if method == "POST":
        if path == "/api/ai/dsh/stream":
            user = handler._require_user()
            body = handler._read_json()
            handler._dsh_stream(user, body)
            return

        if path == "/api/ai/skills/toggle":
            user = handler._require_user()
            body = handler._read_json()
            name = str(body.get("name") or "").strip()[:120]
            if not name:
                raise ProjectError("bad_request", "缺少 skill 名称", 400)
            enabled = handler._ai_skill_toggle(user, name, bool(body.get("enabled")))
            return handler._json(ok(enabled=enabled))

        if path == "/api/ai/skills/import":
            user = handler._require_user()
            body = handler._read_json()
            name = str(body.get("name") or "").strip()[:80]
            desc = str(body.get("description") or "").strip()[:500]
            content = str(body.get("content") or "").strip()
            if not name or not content:
                raise ProjectError("bad_request", "需要 name 与 content", 400)
            slug = re.sub(r"[^A-Za-z0-9_.-]", "-", name).strip("-") or ("skill-" + secrets.token_hex(3))
            d = os.path.join(handler.server.root, "skills", slug)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("---\nname: %s\ndescription: %s\n---\n\n%s\n" % (name, desc or name, content))
            handler._ai_skill_toggle(user, name, True)
            return handler._json(ok(skill={"name": name, "path": os.path.join(d, "SKILL.md")}))

        if path == "/api/ai/dsh/stop":
            user = handler._require_user()
            body = handler._read_json()
            rid = str(body.get("run_id") or "").strip()
            stopped = False
            with DSH_RUNS_LOCK:
                run = DSH_RUNS.get(rid)
                if run and run.get("user") == user:
                    try:
                        run["proc"].kill(); stopped = True
                    except Exception:
                        pass
                    run["stopped"] = True
            return handler._json(ok(stopped=stopped))

        if path == "/api/ai/dsh/chat":
            user = handler._require_user()
            body = handler._read_json()
            module = str(body.get("module") or "")[:40]
            text = str(body.get("text") or "").strip()
            if not text:
                raise ProjectError("bad_request", "消息为空", 400)
            if module:
                proj = handler.registry.get(module)
                if not proj or not handler._can_access(user, module):
                    raise ProjectError("forbidden", "当前模块不可访问：" + module, 403)
            psid = str(body.get("platform_session_id") or "")
            session = handler._ai_session_load(user, psid) if psid else None
            dsh_id = str(body.get("dsh_session_id") or (session or {}).get("dsh_session_id") or "")
            transcript = ""
            if session and not dsh_id:
                msgs = (session.get("messages") or [])[-20:]
                if msgs:
                    transcript = "\n\n".join(("用户回答：" if m.get("role") == "answer" else "用户：" if m.get("role") == "user" else "AI：") + str(m.get("content") or "") for m in msgs)
            file_notes = handler._dsh_file_notes(user, body.get("files") or [])
            proj = handler.registry.get(module) if module else None
            module_title = (proj.manifest().get("title") if proj else module) or "工作台"
            prompt = "你是 KittenPuppy4Ever 工作台内的 AI 助手。\n"
            prompt += "当前用户：%s\n当前模块：%s（%s）\n" % (user, module_title, module or "无")
            prompt += "请在该模块上下文中帮助用户；需要操作模块时使用可用工具，并说明实际执行结果。\n"
            if transcript:
                prompt += "\n之前的对话：\n" + transcript + "\n"
            if file_notes:
                prompt += "\n" + "\n\n".join(file_notes) + "\n"
            prompt += "\n用户消息：\n" + text
            result = handler._dsh_run(user, module, prompt, dsh_id,
                                   model=str(body.get("model") or "")[:120],
                                   effort=str(body.get("effort") or "")[:20])
            new_dsh = result.get("dsh_session_id") or dsh_id
            if session and new_dsh and session.get("dsh_session_id") != new_dsh:
                session["dsh_session_id"] = new_dsh
                try: handler._ai_session_save(user, session)
                except Exception: pass
            ui = None
            if module == "scratchpad":
                ui = {"module": module, "actions": [{"type": "focus", "selector": "#new-text"},
                                                    {"type": "refresh", "selector": "#list"}]}
            elif module == "schedule":
                ui = {"module": module, "actions": [{"type": "click", "selector": "#gridwrap"},
                                                    {"type": "refresh", "selector": "#mylist"}]}
            return handler._json(ok(reply=result.get("reply") or "", dsh_session_id=new_dsh,
                                 usage=result.get("usage") or {}, events=result.get("events") or [],
                                 module=module, ui=ui, ui_events=result.get("ui_events") or [],
                                 model=result.get("model") or "", effort=result.get("effort") or "",
                                 context_window=result.get("context_window") or 0))

        if path == "/api/dsh/tool":
            token = (handler.headers.get("X-KP-Bridge") or "").strip()
            with DSH_TOKENS_LOCK:
                rec = DSH_TOKENS.get(token)
                if not rec or rec.get("expires", 0) < time.time():
                    raise ProjectError("unauthorized", "DSH Bridge token 无效或已过期", 401)
                user, module = rec.get("user"), rec.get("module")
            body = handler._read_json()
            mod = str(body.get("module") or module or "")[:40]
            if mod != (module or ""):
                raise ProjectError("forbidden", "Bridge token 不允许跨模块", 403)
            tool = str(body.get("tool") or "")[:80]
            result = handler._ai_tool_execute(user, mod, tool, body.get("args") or {}, dry_run=bool(body.get("dry_run")))
            ui = result.get("ui") if isinstance(result, dict) else None
            if ui:
                with DSH_TOKENS_LOCK:
                    if token in DSH_TOKENS:
                        DSH_TOKENS[token].setdefault("ui", []).append(ui)
            return handler._json(ok(result=result, module=mod, tool=tool))

        if path == "/api/ai/tools/execute":
            user = handler._require_user()
            body = handler._read_json()
            module = str(body.get("module") or "")[:40]
            name = str(body.get("tool") or "")[:80]
            result = handler._ai_tool_execute(user, module, name, body.get("args") or {}, dry_run=bool(body.get("dry_run")))
            return handler._json(ok(dry_run=bool(body.get("dry_run")), result=result))

        if path == "/api/ai/sessions/save":
            user = handler._require_user()
            body = handler._read_json()
            session = body.get("session") if isinstance(body.get("session"), dict) else body
            sid = handler._ai_session_id(session.get("id"))
            session["id"] = sid
            if body.get("dry_run"):
                # Validate/shape in memory, do not write any server state.
                preview = {"id": sid, "title": str(session.get("title") or "新对话")[:120],
                           "module": str(session.get("module") or "")[:40],
                           "messages": session.get("messages") or [], "usage": session.get("usage") or {},
                           "context_window": session.get("context_window") or 0}
                return handler._json(ok(dry_run=True, session=handler._ai_session_public(preview, full=True)))
            data = handler._ai_session_save(user, session)
            return handler._json(ok(session=handler._ai_session_public(data, full=True)))

        if path == "/api/ai/sessions/flags":
            user = handler._require_user()
            body = handler._read_json()
            d = handler._ai_session_flags(user, body.get("id"),
                                       body.get("archived") if "archived" in body else None,
                                       body.get("pinned") if "pinned" in body else None)
            return handler._json(ok(session=handler._ai_session_public(d, full=False)))

        if path == "/api/ai/sessions/delete":
            user = handler._require_user()
            body = handler._read_json()
            okdel = handler._ai_session_delete(user, body.get("id"))
            return handler._json(ok(deleted=bool(okdel)))

        if path == "/api/ai/sessions/import":
            user = handler._require_user()
            body = handler._read_json()
            mode = str(body.get("mode") or "new")
            if mode not in ("overwrite", "new"):
                raise ProjectError("bad_request", "导入模式不合法", 400)
            items = body.get("sessions") if isinstance(body.get("sessions"), list) else ([body.get("session")] if isinstance(body.get("session"), dict) else [])
            items = [x for x in items if isinstance(x, dict)]
            if not items:
                raise ProjectError("bad_request", "导入内容为空", 400)
            if body.get("dry_run"):
                return handler._json(ok(dry_run=True, imported=len(items), mode=mode,
                                     sessions=[handler._ai_session_public(x, full=True) for x in items[:20]]))
            saved = []
            for item in items[:500]:
                item = dict(item)
                if mode == "overwrite" and item.get("id"):
                    item["id"] = handler._ai_session_id(item["id"])
                else:
                    item["id"] = handler._ai_session_id("")
                saved.append(handler._ai_session_public(handler._ai_session_save(user, item), full=True))
            return handler._json(ok(imported=len(saved), mode=mode, sessions=saved))

    if method == "GET":
        if path == "/api/llm/models":
            user = handler._require_user()
            q = parse_qs(urlparse(handler.path).query)
            body = {k: (v[0] if v else "") for k, v in q.items()}
            cfg = handler._llm_load()
            g = cfg.get("global") or {}
            provider_id = str(body.get("provider_id") or body.get("provider") or "")
            p = next((x for x in handler._llm_providers(g) if x.get("id") == provider_id), None) if provider_id else None
            if p:
                base, key, provider = p.get("base_url") or "", (p.get("keys") or [""])[0], p.get("provider") or ""
            else:
                eff = handler._llm_effective(user)
                if not eff:
                    raise ProjectError("bad_request", "尚未配置 AI 服务", 400)
                base, key, provider = eff.get("base_url") or "", eff.get("api_key") or "", eff.get("provider") or ""
            base = str(base).strip().rstrip("/")
            if not base:
                raise ProjectError("bad_request", "Base URL 为空", 400)
            headers = {"Authorization": "Bearer " + key} if key else {}
            if provider == "dsh":
                url = base + "/api/models"
            elif base.endswith("/models"):
                url = base
            else:
                url = base + "/models"
            status, data = handler._llm_http(url, headers)
            if status == 0 and provider == "dsh":
                status, data = handler._llm_http(base + "/v1/models", headers)
            ids = []
            if isinstance(data, dict):
                items = data.get("data") if isinstance(data.get("data"), list) else data.get("models")
                for it in items or []:
                    if isinstance(it, str):
                        ids.append(it)
                    elif isinstance(it, dict):
                        mid = it.get("id") or it.get("name") or it.get("model")
                        if mid:
                            ids.append(str(mid))
            seen = []
            for x in ids:
                if x not in seen:
                    seen.append(x)
            return handler._json(ok(models=seen, provider=provider, provider_id=(p or {}).get("id") or "",
                                 status=status, context_window=(p or {}).get("context_window") or 0))

        if path == "/api/llm/status":
            user = handler._require_user()
            cfg = handler._llm_load()
            g = cfg.get("global") or {}
            me = (cfg.get("users") or {}).get(user) or {"mode": "server"}
            eff = handler._llm_effective(user)
            ps = handler._llm_providers(g)
            active = handler._llm_active_provider(g)
            return handler._json(ok(
                server=handler._llm_public(g, "server"),
                me={"mode": me.get("mode") or "server", **handler._llm_public(me, me.get("mode") or "server")},
                effective=handler._llm_public(eff, eff.get("source") if eff else None),
                providers=[handler._llm_provider_public(p, p.get("id") == (active or {}).get("id")) for p in ps],
                message=("未配置服务端 AI，请联系管理员" if not ps else ""),
            ))

        if path == "/api/llm/admin":
            user = handler._require_user()
            if not handler.auth.is_admin(user):
                raise ProjectError("forbidden", "仅管理员可查看全局 AI 配置", 403)
            cfg = handler._llm_load()
            g = cfg.get("global") or {}
            active = handler._llm_active_provider(g)
            return handler._json(ok(global_=handler._llm_public(g, "server"),
                                 providers=[handler._llm_provider_public(p, p.get("id") == (active or {}).get("id")) for p in handler._llm_providers(g)],
                                 mineru=handler._mineru_public(),
                                 kinds=["deepseek", "openai", "anthropic", "openrouter", "moonshot",
                                        "zhipu", "qwen", "groq", "mistral", "ollama", "dsh", "local", "custom"]))

    if method == "POST":
        if path == "/api/llm/admin/mineru":
            user = handler._require_user()
            if not handler.auth.is_admin(user):
                raise ProjectError("forbidden", "仅管理员可设置 MinerU", 403)
            body = handler._read_json()
            handler._mineru_save(token=body.get("token"), clear=bool(body.get("clear")))
            return handler._json(ok(mineru=handler._mineru_public()))

        if path == "/api/llm/admin/mineru/check":
            user = handler._require_user()
            if not handler.auth.is_admin(user):
                raise ProjectError("forbidden", "仅管理员可检查 MinerU", 403)
            body = handler._read_json()
            return handler._json(ok(check=handler._mineru_check(body.get("token"))))

        if path == "/api/llm/admin":
            user = handler._require_user()
            if not handler.auth.is_admin(user):
                raise ProjectError("forbidden", "仅管理员可设置全局 AI", 403)
            body = handler._read_json()
            cfg = handler._llm_load()
            old_g = cfg.get("global") or {}
            old_ps = {p.get("id"): p for p in handler._llm_providers(old_g)}
            if isinstance(body.get("providers"), list):
                out, first = [], None
                for idx, p in enumerate(body.get("providers") or []):
                    if not isinstance(p, dict):
                        continue
                    base = str(p.get("base_url") or "").strip()[:500]
                    if not base:
                        continue
                    provider = str(p.get("provider") or "").strip()[:40] or handler._llm_detect(base)
                    pid = str(p.get("id") or provider or ("p%d" % idx)).strip()[:60]
                    oldp = old_ps.get(pid) or {}
                    keys = handler._llm_keys(oldp.get("keys"))
                    text = p.get("keys_text")
                    if text is not None:
                        text = str(text).strip()
                        if text in ("__CLEAR__", "CLEAR"):
                            keys = []
                        elif text:
                            keys = handler._llm_keys(text.splitlines())
                    elif isinstance(p.get("keys"), list):
                        keys = handler._llm_keys(p.get("keys"))
                    item = {"id": pid, "name": str(p.get("name") or pid)[:80],
                            "provider": provider, "base_url": base,
                            "model": str(p.get("model") or "").strip()[:120],
                            "context_window": int(p.get("context_window") or 0),
                            "keys": keys, "enabled": bool(p.get("enabled", True))}
                    out.append(item)
                    if p.get("active"):
                        first = item
                if not out:
                    raise ProjectError("bad_request", "至少配置一个可用的服务商", 400)
                first = first or out[0]
                clean = {"provider": first["provider"], "base_url": first["base_url"],
                         "api_key": (first["keys"] or [""])[0], "model": first["model"],
                         "context_window": first["context_window"],
                         "enabled": first["enabled"]}
                cfg["global"] = {**clean, "providers": out, "active_provider": first["id"],
                                 "effort": str(body.get("effort") or old_g.get("effort") or "medium")[:20]}
            else:
                clean = handler._llm_clean(body)
                if body.get("api_key") is None and old_g.get("api_key"):
                    clean["api_key"] = old_g["api_key"]
                if str(body.get("api_key") or "").strip() in ("__CLEAR__", "CLEAR"):
                    clean["api_key"] = ""
                cfg["global"] = clean
            handler._llm_save(cfg)
            g = cfg.get("global") or {}
            active = handler._llm_active_provider(g)
            return handler._json(ok(global_=handler._llm_public(g, "server"),
                                 providers=[handler._llm_provider_public(p, p.get("id") == (active or {}).get("id")) for p in handler._llm_providers(g)]))

        if path == "/api/llm/me":
            user = handler._require_user()
            body = handler._read_json()
            cfg = handler._llm_load()
            users = cfg.setdefault("users", {})
            cur = users.get(user) or {}
            mode = str(body.get("mode") or cur.get("mode") or "server")
            if mode not in ("server", "override"):
                raise ProjectError("bad_request", "模式不合法", 400)
            clean = handler._llm_clean(body)
            if not body.get("api_key") and cur.get("api_key"):
                clean["api_key"] = cur["api_key"]
            if str(body.get("api_key") or "").strip() in ("__CLEAR__", "CLEAR"):
                clean["api_key"] = ""
            clean["mode"] = mode
            if mode == "server":
                g = cfg.get("global") or {}
                if not (g.get("base_url") and g.get("enabled", True)):
                    raise ProjectError("bad_request", "服务端尚未配置 AI，请联系管理员", 400)
            users[user] = clean
            handler._llm_save(cfg)
            return handler._json(ok(me={"mode": mode, **handler._llm_public(clean, mode)}))

        if path == "/api/llm/test":
            user = handler._require_user()
            body = handler._read_json()
            cfg = handler._llm_effective(user)
            if body.get("scope") == "global":
                if not handler.auth.is_admin(user):
                    raise ProjectError("forbidden", "仅管理员可测试全局配置", 403)
                cfg = handler._llm_load().get("global") or {}
            if not cfg or not cfg.get("base_url"):
                raise ProjectError("bad_request", "尚未配置 AI 服务", 400)
            base = cfg["base_url"].rstrip("/")
            provider = cfg.get("provider") or handler._llm_detect(base)
            if provider == "dsh":
                status, data = handler._llm_http(base + "/api/health", {"Authorization": "Bearer " + (cfg.get("api_key") or "")})
                return handler._json(ok(reachable=status in (200, 401), status=status,
                                     message=("本机 DSH 可达" if status in (200, 401) else "本机 DSH 不可达"),
                                     data=data))
            url = base if base.endswith("/models") else base + "/models"
            headers = {"Authorization": "Bearer " + cfg.get("api_key", "")} if cfg.get("api_key") else {}
            status, data = handler._llm_http(url, headers)
            return handler._json(ok(reachable=200 <= status < 300, status=status, provider=provider, data=data))

        if path == "/api/llm/models":
            user = handler._require_user()
            body = {}
            if handler.command == "POST":
                body = handler._read_json()
            else:
                q = parse_qs(urlparse(handler.path).query)
                body = {k: (v[0] if v else "") for k, v in q.items()}
            cfg = handler._llm_load()
            g = cfg.get("global") or {}
            provider_id = str(body.get("provider_id") or body.get("provider") or "")
            p = next((x for x in handler._llm_providers(g) if x.get("id") == provider_id), None) if provider_id else None
            if p:
                base, key, provider = p.get("base_url") or "", (p.get("keys") or [""])[0], p.get("provider") or ""
            else:
                eff = handler._llm_effective(user)
                if not eff:
                    raise ProjectError("bad_request", "尚未配置 AI 服务", 400)
                base, key, provider = eff.get("base_url") or "", eff.get("api_key") or "", eff.get("provider") or ""
            base = str(body.get("base_url") or base).strip().rstrip("/")
            key = str(body.get("api_key") or key)
            provider = str(body.get("provider") or provider or handler._llm_detect(base))
            if not base:
                raise ProjectError("bad_request", "Base URL 为空", 400)
            headers = {"Authorization": "Bearer " + key} if key else {}
            if provider == "dsh":
                url = base + "/api/models"
            elif base.endswith("/models"):
                url = base
            else:
                url = base + "/models"
            status, data = handler._llm_http(url, headers)
            if status == 0 and provider == "dsh":
                status, data = handler._llm_http(base + "/v1/models", headers)
            ids = []
            if isinstance(data, dict):
                items = data.get("data") if isinstance(data.get("data"), list) else data.get("models")
                for it in items or []:
                    if isinstance(it, str):
                        ids.append(it)
                    elif isinstance(it, dict):
                        mid = it.get("id") or it.get("name") or it.get("model")
                        if mid:
                            ids.append(str(mid))
            seen = []
            for x in ids:
                if x not in seen:
                    seen.append(x)
            return handler._json(ok(models=seen, provider=provider, provider_id=(p or {}).get("id") or "",
                                 status=status, context_window=(p or {}).get("context_window") or 0))

        if path == "/api/llm/chat":
            user = handler._require_user()
            body = handler._read_json()
            provider_id = str(body.get("provider_id") or "")
            cfg = handler._llm_effective(user, provider_id or None)
            if not cfg or not cfg.get("base_url"):
                raise ProjectError("bad_request", "未配置 AI 服务，请联系管理员", 400)
            messages = body.get("messages") or []
            if not isinstance(messages, list) or not messages:
                raise ProjectError("bad_request", "messages 不能为空", 400)
            module = str(body.get("module") or "")[:40]
            if module:
                proj = handler.registry.get(module)
                if not proj or not handler._can_access(user, module):
                    raise ProjectError("forbidden", "当前模块不可访问：" + module, 403)
            dry_run = bool(body.get("dry_run"))
            file_notes = handler._dsh_file_notes(user, body.get("files") or [])
            if file_notes:
                messages = [{"role": "system", "content": "用户上传了以下文件：\n\n" + "\n\n".join(file_notes)}] + messages
            tool_prompt = handler._ai_tool_prompt(module, user) if module else ""
            if tool_prompt:
                messages = [{"role": "system", "content": tool_prompt}] + messages
            model = str(body.get("model") or cfg.get("model") or "deepseek-chat")[:160]
            effort = str(body.get("effort") or cfg.get("effort") or "medium")[:20]
            base = cfg["base_url"].rstrip("/")
            if base.endswith("/chat/completions"):
                url = base
            elif base.endswith("/v1"):
                url = base + "/chat/completions"
            else:
                url = base + "/v1/chat/completions"
            headers = {"Content-Type": "application/json"}
            if cfg.get("api_key"):
                headers["Authorization"] = "Bearer " + cfg["api_key"]
            tool_results = []
            reply = ""
            data = {}
            for round_no in range(3):
                payload = {"model": model, "messages": messages, "stream": False}
                if effort and effort != "medium":
                    payload["reasoning_effort"] = effort
                status, data = handler._llm_http(url, headers, payload, timeout=int(body.get("timeout") or 60))
                if not (200 <= status < 300):
                    raise ProjectError("upstream_error", "AI 服务返回 %s：%s" % (status, str(data)[:300]), 502)
                try:
                    reply = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
                except Exception:
                    reply = ""
                parsed = None
                txt = str(reply or "").strip()
                if txt.startswith("```"):
                    txt = re.sub(r"^```[a-zA-Z]*\s*", "", txt)
                    txt = re.sub(r"\s*```$", "", txt)
                try:
                    cand = json.loads(txt)
                    if isinstance(cand, dict) and cand.get("tool"):
                        parsed = cand
                except Exception:
                    parsed = None
                if not parsed or round_no >= 2:
                    break
                name = str(parsed.get("tool") or "")
                args = parsed.get("args") if isinstance(parsed.get("args"), dict) else {}
                try:
                    result = handler._ai_tool_execute(user, module, name, args, dry_run=dry_run)
                except Exception as e:
                    result = {"error": str(getattr(e, "message", e))}
                tool_results.append({"tool": name, "args": args, "result": result})
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "system", "content": "工具 %s 执行结果：%s" % (name, json.dumps(result, ensure_ascii=False)[:4000])})
            usage = (data.get("usage") if isinstance(data, dict) else None) or {}
            def rough_tokens(text):
                return max(1, int(len(text or "") / 3))
            pt = usage.get("prompt_tokens") or sum(rough_tokens(m.get("content") if isinstance(m, dict) else "") for m in messages)
            ct = usage.get("completion_tokens") or rough_tokens(reply)
            total = usage.get("total_tokens") or (pt + ct)
            return handler._json(ok(reply=reply, raw=data, provider=cfg.get("provider"), model=model,
                                 effort=effort, tool_results=tool_results,
                                 usage={"prompt_tokens": int(pt), "completion_tokens": int(ct),
                                        "total_tokens": int(total),
                                        "context_window": int(cfg.get("context_window") or 0)}))

    return False
