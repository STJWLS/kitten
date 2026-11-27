# -*- coding: utf-8 -*-
"""AI module-local API：技能、DSH 状态/流、工具、会话。"""
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from kernel.project import TZ
from kernel.protocol import ProjectError, ok

PREFIXES = ["/api/ai/"]


def handle(handler, method, path, parsed):
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

    return False
