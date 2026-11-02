# -*- coding: utf-8 -*-
"""Structured direct-message store (SQLite) for the in-site message center."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone

_LOCK = threading.RLock()
_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "messages.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB), exist_ok=True)
    con = sqlite3.connect(_DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("""
        CREATE TABLE IF NOT EXISTS direct_messages (
            id TEXT PRIMARY KEY,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            body TEXT NOT NULL,
            created TEXT NOT NULL,
            read_at TEXT,
            meta TEXT
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS dm_sender ON direct_messages(sender, created)")
    con.execute("CREATE INDEX IF NOT EXISTS dm_recipient ON direct_messages(recipient, created)")
    return con


def _row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "from": r["sender"],
        "to": r["recipient"],
        "body": r["body"],
        "created": r["created"],
        "read": bool(r["read_at"]),
        "read_at": r["read_at"] or "",
        "meta": json.loads(r["meta"] or "{}") if r["meta"] else {},
    }


def send(sender: str, recipient: str, body: str, meta=None) -> dict | None:
    sender = str(sender or "").strip()
    recipient = str(recipient or "").strip()
    body = str(body or "").strip()
    if not sender or not recipient or not body:
        return None
    item_id = "m" + str(int(time.time() * 1000)) + uuid.uuid4().hex[:5]
    created = _now()
    with _LOCK, _connect() as con:
        con.execute(
            "INSERT INTO direct_messages(id,sender,recipient,body,created,read_at,meta) VALUES(?,?,?,?,?,NULL,?)",
            (item_id, sender, recipient, body[:8000], created, json.dumps(meta) if isinstance(meta, dict) else "{}"),
        )
    return {"id": item_id, "from": sender, "to": recipient, "body": body[:8000], "created": created, "read": False, "read_at": "", "meta": meta or {}}


def conversation(user: str, peer: str, limit: int = 300) -> list[dict]:
    with _LOCK, _connect() as con:
        rows = con.execute(
            "SELECT * FROM direct_messages WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?) ORDER BY created DESC, rowid DESC LIMIT ?",
            (user, peer, peer, user, max(1, min(1000, int(limit or 300)))),
        ).fetchall()
    return [_row(r) for r in reversed(rows)]


def threads(user: str, known_users=None) -> dict:
    with _LOCK, _connect() as con:
        rows = con.execute(
            "SELECT * FROM direct_messages WHERE sender=? OR recipient=? ORDER BY created DESC, rowid DESC",
            (user, user),
        ).fetchall()
    by_peer = {}
    for r in rows:
        peer = r["sender"] if r["recipient"] == user else r["recipient"]
        if not peer or peer == user:
            continue
        rec = by_peer.get(peer)
        if rec is None:
            rec = {"peer": peer, "last": _row(r), "unread": 0, "total": 0}
            by_peer[peer] = rec
        rec["total"] += 1
        if r["recipient"] == user and not r["read_at"]:
            rec["unread"] += 1
    items = sorted(by_peer.values(), key=lambda x: x["last"]["created"], reverse=True)
    users = sorted(set(known_users or []) | set(by_peer.keys()))
    return {"threads": items, "users": users}


def unread(user: str) -> int:
    with _LOCK, _connect() as con:
        row = con.execute(
            "SELECT COUNT(*) AS n FROM direct_messages WHERE recipient=? AND read_at IS NULL",
            (user,),
        ).fetchone()
    return int(row["n"] if row else 0)


def mark_read(user: str, peer: str = "", all_peers: bool = False) -> int:
    with _LOCK, _connect() as con:
        if all_peers:
            cur = con.execute(
                "UPDATE direct_messages SET read_at=? WHERE recipient=? AND read_at IS NULL",
                (_now(), user),
            )
        elif peer:
            cur = con.execute(
                "UPDATE direct_messages SET read_at=? WHERE recipient=? AND sender=? AND read_at IS NULL",
                (_now(), user, peer),
            )
        else:
            return 0
        return cur.rowcount


def all_for(user: str, limit: int = 10000) -> list[dict]:
    with _LOCK, _connect() as con:
        rows = con.execute(
            "SELECT * FROM direct_messages WHERE sender=? OR recipient=? ORDER BY created DESC, rowid DESC LIMIT ?",
            (user, user, max(1, min(20000, int(limit or 10000)))),
        ).fetchall()
    return [_row(r) for r in rows]
