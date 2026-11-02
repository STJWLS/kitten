# -*- coding: utf-8 -*-
"""提醒服务：从 local_store.py 迁移的课程/日程邮件提醒 + 许愿池审批通知。

数据来源改为新引擎：
  - 课程/考试：仍读 emf-schedule/schedule.json（静态真相，不动）
  - 个人日程：engine 里 schedule 项目文档的 events
  - 去重记录：写回 schedule 项目 reminders_sent / wishpool 项目 wish_notified
"""

import json
import os
import threading
import traceback
from datetime import datetime, timedelta, timezone

from ..compat import read_state
from .mail import send_mail

TZ = timezone(timedelta(hours=8))
DAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _fmt_min(m):
    return "%02d:%02d" % (m // 60, m % 60)


def schedule_json_path(platform_root):
    return os.path.normpath(os.path.join(os.path.dirname(platform_root), "emf-schedule", "schedule.json"))


def build_items(platform_root, engine):
    items = []
    try:
        with open(schedule_json_path(platform_root), encoding="utf-8") as f:
            D = json.load(f)
        meta = D.get("meta", {})
        term = datetime.strptime(meta["termStart"], "%Y-%m-%d").date()
        slots = D.get("slots", [])
        by_code = {c["code"]: c for c in D.get("courses", [])}
        for c in D.get("courses", []):
            for e in c.get("schedule", []):
                s0 = slots[e["slot"] - 1]
                s1 = slots[e["slot"] - 1 + e.get("span", 1) - 1]
                for wk in e["weeks"]:
                    day = term + timedelta(days=(wk - 1) * 7 + e["day"])
                    start = datetime.combine(day, datetime.min.time()) + timedelta(minutes=s0["start"])
                    end = datetime.combine(day, datetime.min.time()) + timedelta(minutes=s1["end"])
                    items.append({
                        "key": "c%s|%d|%d|%d" % (c["code"], wk, e["day"], s0["start"]),
                        "title": c.get("cn") or c.get("name") or c["code"],
                        "venue": e.get("venue", ""), "note": e.get("note", ""),
                        "date": day.isoformat(), "start": start, "end": end,
                        "offsets": [60, 30, 15], "kind": "course",
                    })
        for sp in D.get("specials", []):
            c = by_code.get(sp["code"], {})
            title = (c.get("cn") or c.get("name") or sp["code"]) + (
                "（考试）" if "Exam" in sp.get("note", "") else "")
            for wk in sp["weeks"]:
                day = term + timedelta(days=(wk - 1) * 7 + sp["day"])
                start = datetime.combine(day, datetime.min.time()) + timedelta(minutes=sp["start"])
                end = datetime.combine(day, datetime.min.time()) + timedelta(minutes=sp["end"])
                items.append({
                    "key": "s%s|%d|%d|%d" % (sp["code"], wk, sp["day"], sp["start"]),
                    "title": title, "venue": sp.get("venue", ""), "note": sp.get("note", ""),
                    "date": day.isoformat(), "start": start, "end": end,
                    "offsets": [60, 30, 15], "kind": "course",
                })
    except Exception:
        traceback.print_exc()

    state = read_state(engine)
    for e in state.get("events") or []:
        try:
            day = datetime.strptime(e["date"], "%Y-%m-%d").date()
            start = datetime.combine(day, datetime.min.time()) + timedelta(minutes=int(e.get("startMin", 0)))
            end = datetime.combine(day, datetime.min.time()) + timedelta(minutes=int(e.get("endMin", 0)))
            rem = e.get("reminders")
            offsets = [int(x) for x in rem] if isinstance(rem, list) and rem else [30]
            items.append({
                "key": "e%s|%s|%d" % (e.get("id", ""), e["date"], int(e.get("startMin", 0))),
                "title": e.get("title", "个人日程"), "venue": e.get("place", ""),
                "note": e.get("note", ""), "date": e["date"], "start": start, "end": end,
                "offsets": offsets, "kind": "event",
                "creator": e.get("creator", "kitten"), "mentions": e.get("mentions", []),
            })
        except Exception:
            continue
    return items


def _mail_body(item, offset):
    d = item["start"]
    lines = [
        "【日程提醒】%s即将开始" % item["title"], "",
        "日程：%s" % item["title"],
        "时间：%s（%s）%s ~ %s" % (item["date"], DAY_CN[d.weekday()],
                                  _fmt_min(item["start"].hour * 60 + item["start"].minute),
                                  _fmt_min(item["end"].hour * 60 + item["end"].minute)),
    ]
    if item["venue"]:
        lines.append("地点：%s" % item["venue"])
    if item["note"]:
        lines.append("备注：%s" % item["note"])
    if item.get("creator"):
        lines.append("创建者：%s" % item["creator"] + (
            "（提到 %s）" % "、".join(item["mentions"]) if item.get("mentions") else ""))
    lines += ["", "距开始还有约 %d 分钟（提前 %d 分钟提醒）。" % (offset, offset),
              "—— EMF 26R 课表看板自动发送"]
    return "\n".join(lines)


def _mail_subject(item, offset):
    return "⏰ 日程提醒（提前%d分钟）：%s %s" % (
        offset, item["title"], _fmt_min(item["start"].hour * 60 + item["start"].minute))


def check_reminders(platform_root, engine, projects):
    now = datetime.now(TZ).replace(tzinfo=None)
    project = projects.get("schedule")
    if project is None:
        return
    _, sdata, _ = engine.read("schedule")
    sent = set(sdata.get("reminders_sent") or [])
    new_sent = []
    for item in build_items(platform_root, engine):
        if item["start"] <= now:
            continue
        for off in item["offsets"]:
            target = item["start"] - timedelta(minutes=off)
            key = "%s|%d" % (item["key"], off)
            if key in sent:
                continue
            delta = (now - target).total_seconds()
            if 0 <= delta < 1800:
                ok, msg = send_mail(platform_root, _mail_subject(item, off), _mail_body(item, off))
                print("[提醒] %s 提前%d分钟 -> %s" % (item["title"], off, msg))
                if ok:
                    new_sent.append(key)
    if new_sent:
        project.merge_list_field("reminders_sent", new_sent, limit=500)


def check_wish_notify(platform_root, engine, projects, mail_status):
    from .mail import load_mail_config
    project = projects.get("wishpool")
    if project is None:
        return
    _, wdata, _ = engine.read("wishpool")
    notified = set(wdata.get("wish_notified") or [])
    new_notified = []
    now = datetime.now(TZ).replace(tzinfo=None)
    tomorrow_s = (now.date() + timedelta(days=1)).isoformat()
    puppy = load_mail_config(platform_root).get("puppy_addr") or ""
    if not puppy:
        return
    for w in wdata.get("wishes") or []:
        if w.get("status") != "pending" or not w.get("dueDate"):
            continue
        key_c, key_d = "create|" + w.get("id", ""), "ddl|" + w.get("id", "")
        if key_c not in notified:
            body = "\n".join([
                "【新的愿望待审批】", "", "愿望：" + w.get("title", ""),
                "投入许愿币：%s 枚" % w.get("coins", 0),
                "审批 DDL：%s（按整天计）" % w.get("dueDate", ""), "",
                "（用 🐶 puppy 角色登录 → 猫猫许愿池 → 审批队列）", "",
                "请尽快审批：投币越多，kitten 的期待越优先。",
                "—— KittenPuppy4Ever 许愿池自动发送",
            ])
            ok, _ = send_mail(platform_root,
                              "⏰ 新愿望待审批：%s（投入 %s 枚）" % (w.get("title", ""), w.get("coins", 0)),
                              body, [puppy])
            if ok:
                new_notified.append(key_c)
        elif w["dueDate"] == tomorrow_s and key_d not in notified:
            body = "\n".join([
                "【愿望审批 DDL 明日到期】", "", "愿望：" + w.get("title", ""),
                "投入许愿币：%s 枚" % w.get("coins", 0),
                "到期日：%s（按整天计）" % w.get("dueDate", ""), "",
                "若未实现，kitten 可判定「未实现」：不获报酬并被倒扣。",
                "—— KittenPuppy4Ever 许愿池自动发送",
            ])
            ok, _ = send_mail(platform_root,
                              "⏰ 审批 DDL 明日到期：%s" % w.get("title", ""), body, [puppy])
            if ok:
                new_notified.append(key_d)
    if new_notified:
        project.merge_list_field("wish_notified", new_notified, limit=1000)


def loop(platform_root, engine, projects, stop_event, interval=20):
    while not stop_event.is_set():
        try:
            check_reminders(platform_root, engine, projects)
        except Exception:
            traceback.print_exc()
        try:
            check_wish_notify(platform_root, engine, projects, None)
        except Exception:
            traceback.print_exc()
        stop_event.wait(interval)


def start(platform_root, engine, projects):
    stop_event = threading.Event()
    t = threading.Thread(target=loop, args=(platform_root, engine, projects, stop_event),
                         daemon=True, name="kp-reminders")
    t.start()
    return t, stop_event
