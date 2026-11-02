# -*- coding: utf-8 -*-
"""旧客户端兼容层：把 store.json 的全局协议映射到新引擎的分片文档。

旧页面（课表/许愿池/工作台）只认两个端点：
    GET  /api/state   -> {events, venues, wishes, coins, t, reminders_sent, wish_notified}
    POST /api/save    -> 旧语义（t 单调、空数据保护、愿望并集、余额保护）

这层保证"页面模板可以改，但数据协议不丢行为"：旧页面一行不改也能跑在新引擎上，
所有合并/保护逻辑从 local_store.py 原样搬过来，测试见 tools/migrate.py 的往返校验。
"""

import json
import os

from .protocol import ProjectError

SCHEDULE = "schedule"
WISHPOOL = "wishpool"
META = "meta"

DEFAULT_SCHEDULE = {"events": [], "venues": [], "reminders_sent": []}
DEFAULT_WISHPOOL = {"wishes": [], "coins": {}, "wish_notified": []}
DEFAULT_META = {"t": 0, "extras": {}}


# ==================== 旧版合并语义（逐行对照 local_store.py / venues.js） ====================

def wish_stamp(w):
    s = (w.get("createdAt") or "") if isinstance(w, dict) else ""
    for h in ((w.get("history") or []) if isinstance(w, dict) else []):
        if isinstance(h, dict) and (h.get("at") or "") > s:
            s = h.get("at")
    return s


def wish_richness(w):
    r = 0
    for k in ("wantDate", "wantTime", "venue", "detail"):
        if w.get(k):
            r += 1
    r += len(w.get("history") or [])
    return r


def merge_wishes(old, new):
    """愿望只增不删：按 id 求并集，同一 id 保留流程日志更新的一份。"""
    by, order = {}, []
    for w in list(old or []) + list(new or []):
        if not isinstance(w, dict) or not w.get("id"):
            continue
        i = w["id"]
        if i not in by:
            by[i] = w
            order.append(i)
        else:
            p = by[i]
            if (wish_stamp(w) > wish_stamp(p) or
                    (wish_stamp(w) == wish_stamp(p) and wish_richness(w) > wish_richness(p))):
                by[i] = w
    return [by[i] for i in order]


def looks_fresh_coins(c):
    """是否像「全新浏览器从开户日空算出来」的余额：没有任何经济行为。"""
    if not isinstance(c, dict) or not c:
        return True
    for k in ("kittenSpent", "kittenSent", "kittenGift", "kittenWon", "puppyEarned"):
        try:
            if float(c.get(k) or 0) != 0:
                return False
        except Exception:
            return False
    for e in (c.get("coinLog") or []):
        if isinstance(e, dict) and e.get("kind") not in ("grant", "interest", None):
            return False
    return True


# ==================== 状态读写 ====================

def _sorted_list(v):
    return v if isinstance(v, list) else []


def read_state(engine):
    """把三个分片文档拼回旧版全局 state（含未知字段，保证无损）。"""
    _, s, _ = engine.read(SCHEDULE)
    _, w, _ = engine.read(WISHPOOL)
    _, m, _ = engine.read(META)

    state = dict(m.get("extras") or {})      # 迁移时保留的未知顶层字段
    state.update({
        "t": int(m.get("t") or 0),
        "events": _sorted_list(s.get("events")),
        "venues": _sorted_list(s.get("venues")),
        "reminders_sent": _sorted_list(s.get("reminders_sent")),
        "wishes": _sorted_list(w.get("wishes")),
        "coins": w.get("coins") if isinstance(w.get("coins"), dict) else {},
        "wish_notified": _sorted_list(w.get("wish_notified")),
    })
    return state


def _audit_append(engine, pid, action, role, payload):
    from .project import now_iso, _clip
    rev, data, audit = engine.read(pid)
    audit = list(audit)
    audit.append({"at": now_iso(), "rev": rev + 1, "action": action,
                  "role": role, "payload": _clip(payload)})
    return audit


def save_state(engine, payload, role=None):
    """旧版 /api/save 的等价实现；返回 {"saved", "stale", "protected"}。"""
    if not isinstance(payload, dict):
        raise ProjectError("bad_request", "请求体必须是 JSON 对象")

    cur = read_state(engine)
    new_t = payload.get("t", 0)
    try:
        new_t = int(new_t)
    except Exception:
        new_t = 0
    if new_t < cur["t"]:
        return {"saved": False, "stale": True, "protected": False}

    def _list(v):
        return v if isinstance(v, list) else []

    incoming = {
        "events": _list(payload.get("events")),
        "venues": _list(payload.get("venues")),
        "wishes": _list(payload.get("wishes")),
        "coins": payload.get("coins") if isinstance(payload.get("coins"), dict) else {},
    }

    patched = False
    fresh_client = (not incoming["events"] and not incoming["venues"]
                    and not incoming["wishes"] and looks_fresh_coins(incoming["coins"]))
    if fresh_client:
        if cur["events"]:
            incoming["events"] = cur["events"]
            patched = True
        if cur["venues"]:
            incoming["venues"] = cur["venues"]
            patched = True
    if looks_fresh_coins(incoming["coins"]) and not looks_fresh_coins(cur["coins"]):
        incoming["coins"] = cur["coins"]
        patched = True

    merged_wishes = merge_wishes(cur["wishes"], incoming["wishes"])
    server_ids = {(w.get("id"), wish_stamp(w)) for w in incoming["wishes"] if isinstance(w, dict)}
    merged_ids = {(w.get("id"), wish_stamp(w)) for w in merged_wishes if isinstance(w, dict)}
    if merged_ids != server_ids:
        patched = True

    t_out = new_t + (1 if patched else 0)
    changed = 0

    # 只写真正变化的文档：纯心跳式 push（数据没变）只推进 meta.t
    if (incoming["events"] != cur["events"] or incoming["venues"] != cur["venues"]
            or cur["reminders_sent"] != (engine.read(SCHEDULE)[1].get("reminders_sent") or [])):
        engine.write(SCHEDULE, {
            "events": incoming["events"], "venues": incoming["venues"],
            "reminders_sent": cur["reminders_sent"],
        }, audit=_audit_append(engine, SCHEDULE, "legacy_save", role, payload))
        changed += 1
    if incoming["coins"] != cur["coins"] or merged_wishes != cur["wishes"]:
        engine.write(WISHPOOL, {
            "wishes": merged_wishes, "coins": incoming["coins"],
            "wish_notified": cur["wish_notified"],
        }, audit=_audit_append(engine, WISHPOOL, "legacy_save", role, payload))
        changed += 1
    if t_out != cur["t"]:
        engine.write(META, {"t": t_out, "extras": (engine.read(META)[1].get("extras") or {})},
                     audit=_audit_append(engine, META, "legacy_save", role, payload))
        changed += 1

    return {"saved": True, "stale": False, "protected": patched, "docs_written": changed,
            "t": t_out}


# ==================== 无损往返校验 ====================

def reconstruct_store(engine):
    """按旧 store.json 的字段顺序重建，用于和原件做结构级比对。"""
    state = read_state(engine)
    known = ["events", "venues", "wishes", "coins", "t", "reminders_sent", "wish_notified"]
    ordered = {k: state[k] for k in known}
    for k, v in state.items():
        if k not in ordered:
            ordered[k] = v           # 迁移时保留的未知顶层字段
    return ordered
