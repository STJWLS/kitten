# -*- coding: utf-8 -*-
"""无损迁移：把 localdata/store.json 拆进新引擎的分片文档，并做往返校验。

迁移映射（字段级、原样搬运，不做任何形状改写）：
    store.json                  ->  data/<project>/doc.json
    ├─ events / venues           ->  schedule（events / venues）
    ├─ reminders_sent            ->  schedule（reminders_sent，提醒去重）
    ├─ wishes / coins            ->  wishpool（wishes / coins）
    ├─ wish_notified             ->  wishpool（wish_notified，审批通知去重）
    ├─ t                         ->  meta（t）
    └─ 未知顶层字段               ->  meta（extras，逐字段保留）

校验：
    1) 原始 store.json 备份一份（data/_migration/backup/）
    2) 迁移后从引擎重建 store，与原件做 json.dumps(sort_keys) 全等比较
    3) 统计每个字段的条数/键数，写报告 data/_migration/report-*.json
    4) 源文件只读；本工具不修改 localdata/

用法：
    python platform/tools/migrate.py [--dry-run]
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PLATFORM = os.path.dirname(HERE)
DASH = os.path.dirname(PLATFORM)
sys.path.insert(0, PLATFORM)

from kernel import compat                      # noqa: E402
from kernel.engine import DataEngine            # noqa: E402

SOURCE = os.path.join(DASH, "localdata", "store.json")
SCHEDULE_JSON = os.path.join(DASH, "emf-schedule", "schedule.json")
MAIL_CFG = os.path.join(DASH, "localdata", "mail_config.json")
BACKUP_DIR = os.path.join(PLATFORM, "data", "_migration", "backup")
REPORT_DIR = os.path.join(PLATFORM, "data", "_migration")

KNOWN = {"events", "venues", "wishes", "coins", "t", "reminders_sent", "wish_notified"}


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def counts(store):
    coins = store.get("coins") if isinstance(store.get("coins"), dict) else {}
    return {
        "events": len(store.get("events") or []),
        "venues": len(store.get("venues") or []),
        "wishes": len(store.get("wishes") or []),
        "coins_keys": sorted(coins.keys()),
        "coinLog": len(coins.get("coinLog") or []),
        "reminders_sent": len(store.get("reminders_sent") or []),
        "wish_notified": len(store.get("wish_notified") or []),
        "t": store.get("t"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=SOURCE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.source):
        print("找不到源文件：%s" % args.source)
        return 2

    with open(args.source, "rb") as f:
        raw = f.read()
    original = json.loads(raw.decode("utf-8"))

    unknown = {k: v for k, v in original.items() if k not in KNOWN}
    schedule_doc = {
        "events": original.get("events") or [],
        "venues": original.get("venues") or [],
        "reminders_sent": original.get("reminders_sent") or [],
    }
    wishpool_doc = {
        "wishes": original.get("wishes") or [],
        "coins": original.get("coins") if isinstance(original.get("coins"), dict) else {},
        "wish_notified": original.get("wish_notified") or [],
    }
    meta_doc = {"t": int(original.get("t") or 0), "extras": unknown}

    stamp = time.strftime("%Y%m%d-%H%M%S")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup = os.path.join(BACKUP_DIR, "store-%s.json" % stamp)
    shutil.copy2(args.source, backup)
    print("[备份] %s" % backup)

    engine = DataEngine(PLATFORM)
    if not args.dry_run:
        engine.write("schedule", schedule_doc, rev=1)
        engine.write("wishpool", wishpool_doc, rev=1)
        engine.write("meta", meta_doc, rev=1)
        print("[写入] schedule / wishpool / meta 三份分片文档")
        reconstructed = compat.reconstruct_store(engine)
    else:
        reconstructed = dict(unknown)
        reconstructed.update({
            "t": meta_doc["t"],
            "events": schedule_doc["events"],
            "venues": schedule_doc["venues"],
            "reminders_sent": schedule_doc["reminders_sent"],
            "wishes": wishpool_doc["wishes"],
            "coins": wishpool_doc["coins"],
            "wish_notified": wishpool_doc["wish_notified"],
        })

    same = canonical(original) == canonical(reconstructed)
    report = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": args.source,
        "source_sha256": sha256_bytes(raw),
        "source_mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(args.source))),
        "backup": backup,
        "dry_run": args.dry_run,
        "lossless": same,
        "counts_original": counts(original),
        "counts_reconstructed": counts(reconstructed),
        "unknown_top_level_keys": sorted(unknown.keys()),
        "schedule_json_sha256": sha256_bytes(open(SCHEDULE_JSON, "rb").read()) if os.path.isfile(SCHEDULE_JSON) else None,
        "mail_config_sha256": sha256_bytes(open(MAIL_CFG, "rb").read()) if os.path.isfile(MAIL_CFG) else None,
    }
    os.makedirs(REPORT_DIR, exist_ok=True)
    report_path = os.path.join(REPORT_DIR, "report-%s.json" % stamp)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("[校验] 字段条数：")
    for k, v in report["counts_original"].items():
        mark = "OK" if report["counts_reconstructed"].get(k) == v else "FAIL"
        print("   %-4s %-14s %s" % (mark, k, v))
    print("[校验] 未知顶层字段：%s" % (report["unknown_top_level_keys"] or "无"))
    print("[校验] 往返全等：%s" % ("是（无损）" if same else "否（有差异，见报告）"))
    print("[报告] %s" % report_path)
    if not same:
        o, r = canonical(original), canonical(reconstructed)
        for i in range(min(len(o), len(r))):
            if o[i] != r[i]:
                print("   首个差异位置 %d：" % i)
                print("     原始: ...%s..." % o[max(0, i - 80):i + 80])
                print("     重建: ...%s..." % r[max(0, i - 80):i + 80])
                break
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
