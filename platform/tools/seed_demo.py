# -*- coding: utf-8 -*-
"""把现有真实数据灌进原型项目的 data/<id>/doc.json（只读源文件，不改动线上）。

来源：
    ../emf-schedule/schedule.json   课程表
    ../localdata/store.json         个人日程 / 愿望 / 硬币
用法：
    python platform/tools/seed_demo.py
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PLATFORM = os.path.dirname(HERE)
DASH = os.path.dirname(PLATFORM)

SCHED = os.path.join(DASH, "emf-schedule", "schedule.json")
STORE = os.path.join(DASH, "localdata", "store.json")

DAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
STATUS_MAP = {"done": "approved", "reviewing": "pending", "pending": "pending",
              "approved": "approved", "rejected": "rejected"}


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("读取失败 %s: %s" % (path, e))
        return default


def write_doc(pid, data, rev=1):
    d = os.path.join(PLATFORM, "data", pid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "doc.json"), "w", encoding="utf-8") as f:
        json.dump({"_rev": rev, "data": data, "_audit": []}, f, ensure_ascii=False, indent=1)
    print("[seed] %-10s -> data/%s/doc.json" % (pid, pid))


def seed_schedule():
    D = read_json(SCHED, {})
    store = read_json(STORE, {})
    items = []
    slots = D.get("slots") or []
    courses = D.get("courses") or []

    def hhmm(m):
        return "%02d:%02d" % (m // 60, m % 60)

    seq = 0
    for c in courses:
        for e in c.get("schedule") or []:
            seq += 1
            try:
                s0 = slots[e["slot"] - 1]
                s1 = slots[e["slot"] - 1 + e.get("span", 1) - 1]
            except Exception:
                continue
            day = DAY[(e.get("day", 1) - 1) % 7]
            # 主键必须唯一：同一门课一周可能排多次
            items.append({
                "key": "%s|%s|%s|%d" % (c.get("code", "?"), day, e.get("slot"), seq),
                "title": c.get("cn") or c.get("name") or c.get("code"),
                "day": day,
                "time": "%s-%s" % (hhmm(s0.get("start", 0)), hhmm(s1.get("end", 0))),
                "venue": e.get("venue") or "",
                "weeks": e.get("weeks") or [],
                "kind": "course",
                "done": False,
            })
    for ev in store.get("events") or []:
        if not isinstance(ev, dict):
            continue
        items.append({
            "key": "e" + str(ev.get("id") or "")[:8],
            "title": ev.get("title") or "个人日程",
            "day": "未分组",
            "time": "%02d:%02d" % (int(ev.get("startMin") or 0) // 60,
                                   int(ev.get("startMin") or 0) % 60),
            "venue": ev.get("place") or "",
            "note": ev.get("date") or "",
            "kind": "event",
            "done": False,
        })
    if not items:
        items = [{"key": "demo|周一|1", "title": "示例课程", "day": "周一",
                  "time": "08:30-11:30", "venue": "FISF310", "kind": "course", "done": False}]
    write_doc("schedule", {
        "items": items,
        "term": (D.get("meta") or {}).get("term") or "Fall 2026",
        "note": "由平台内核托管（原型种子数据）",
    })
    return len(items)


def seed_wishpool():
    store = read_json(STORE, {})
    wishes = []
    for w in store.get("wishes") or []:
        if not isinstance(w, dict):
            continue
        raw = w.get("status") or "pending"
        wishes.append({
            "id": w.get("id") or ("w" + str(len(wishes))),
            "title": w.get("title") or "",
            "coins": w.get("coins") or 0,
            "status": STATUS_MAP.get(raw, raw),
            "dueDate": w.get("dueDate") or "",
            "createdAt": w.get("createdAt") or "",
        })
    coins = store.get("coins") or {}
    balance = 0
    for entry in coins.get("coinLog") or []:
        try:
            balance += float(entry.get("amount") or 0)
        except Exception:
            pass
    stats = {
        "pending": len([w for w in wishes if w["status"] == "pending"]),
        "approved": len([w for w in wishes if w["status"] == "approved"]),
        "rejected": len([w for w in wishes if w["status"] == "rejected"]),
    }
    write_doc("wishpool", {
        "items": wishes, "coins": int(balance),
        "log": [{"at": "", "delta": int(balance), "reason": "seed（来自 store.json coinLog 求和）",
                 "by": "kitten"}],
        "stats": stats,
    })
    return len(wishes)


def main():
    n1 = seed_schedule()
    n2 = seed_wishpool()
    write_doc("scratchpad", {"items": [], "note": "零代码项目，内核默认 CRUD"})
    write_doc("map", {"items": [], "note": "课程看板子节点，多层级树演示"})
    print("完成：schedule %d 条 · wishpool %d 条" % (n1, n2))


if __name__ == "__main__":
    main()
