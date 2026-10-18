"""SQLite storage. This is the source of truth; Google Sheets is a mirror.

All workflow handling is serialized by Bot's lock, so a single connection is
enough at this scale (a few hundred messages a day).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from . import clock

SCHEMA = """
CREATE TABLE IF NOT EXISTS counters (
  name TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS requisitions (
  id INTEGER PRIMARY KEY,
  req_no TEXT UNIQUE,
  site_code TEXT NOT NULL,
  engineer_phone TEXT NOT NULL,
  engineer_name TEXT NOT NULL,
  entered_by_phone TEXT NOT NULL,
  status TEXT NOT NULL,              -- DRAFT, SUBMITTED, CLOSED, CANCELLED
  source TEXT NOT NULL,              -- text, voice, image
  raw_text TEXT NOT NULL DEFAULT '',
  needed_by TEXT NOT NULL DEFAULT '',
  urgent INTEGER NOT NULL DEFAULT 0,
  media_link TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  submitted_at TEXT,
  reminded_at TEXT
);

CREATE TABLE IF NOT EXISTS req_items (
  id INTEGER PRIMARY KEY,
  requisition_id INTEGER NOT NULL REFERENCES requisitions(id),
  line_no INTEGER NOT NULL,
  ref TEXT,                          -- N17 / K4 / D9, assigned when submitted
  name TEXT NOT NULL,
  item_key TEXT NOT NULL,
  qty REAL NOT NULL,
  unit TEXT NOT NULL,
  spec TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'OPEN'  -- OPEN, IN_SLIP, ORDERED, REJECTED, CANCELLED
);
CREATE INDEX IF NOT EXISTS ix_req_items_ref ON req_items(ref);

CREATE TABLE IF NOT EXISTS slips (
  id INTEGER PRIMARY KEY,
  slip_no TEXT UNIQUE,
  version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL,              -- DRAFT, PENDING, APPROVED, PARTIAL, REJECTED, CANCELLED
  prepared_by_phone TEXT NOT NULL,
  prepared_by_name TEXT NOT NULL,
  raw_text TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  submitted_at TEXT,
  reminded_at TEXT,
  reminder_count INTEGER NOT NULL DEFAULT 0,
  decided_at TEXT,
  decided_by_phone TEXT,
  decided_by_name TEXT,
  decision_ref TEXT,                 -- WhatsApp message id of the approval
  decision_text TEXT,
  signature TEXT,
  verify_code TEXT,
  pdf_path TEXT,
  drive_link TEXT
);

CREATE TABLE IF NOT EXISTS slip_lines (
  id INTEGER PRIMARY KEY,
  slip_id INTEGER NOT NULL REFERENCES slips(id),
  line_no INTEGER NOT NULL,
  site_code TEXT NOT NULL,
  req_item_id INTEGER REFERENCES req_items(id),
  name TEXT NOT NULL,
  item_key TEXT NOT NULL,
  qty REAL NOT NULL,
  unit TEXT NOT NULL,
  vendor TEXT NOT NULL,
  rate REAL NOT NULL,
  amount REAL NOT NULL,
  requested_qty REAL,
  last_rate REAL,
  last_rate_date TEXT,
  last_vendor TEXT,
  flags TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING, APPROVED, REJECTED
  dispatched_at TEXT,
  dispatch_note TEXT,
  received_qty REAL,
  received_at TEXT,
  received_by TEXT
);

CREATE TABLE IF NOT EXISTS outbound (
  wamid TEXT PRIMARY KEY,
  to_phone TEXT NOT NULL,
  kind TEXT NOT NULL,
  entity TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processed (
  wamid TEXT PRIMARY KEY,
  at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conv_state (
  phone TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stock_ledger (
  id INTEGER PRIMARY KEY,
  site_code TEXT NOT NULL,
  item_key TEXT NOT NULL,
  name TEXT NOT NULL,
  unit TEXT NOT NULL,
  qty REAL NOT NULL,                 -- + received, - used
  kind TEXT NOT NULL,                -- RECEIVED, USED, ADJUST
  ref TEXT NOT NULL DEFAULT '',
  by_phone TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  entity TEXT NOT NULL DEFAULT '',
  details TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS sync_queue (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  key TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  UNIQUE(kind, key)
);

CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
"""


class DB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self.lock = threading.RLock()

    # ---- basics ----
    def q(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchone()

    def run(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, tuple(params))
            return cur.lastrowid or cur.rowcount

    def transaction(self):
        return _Tx(self)

    def next_counter(self, name: str) -> int:
        with self.lock:
            self.conn.execute(
                "INSERT INTO counters(name, value) VALUES (?, 1) "
                "ON CONFLICT(name) DO UPDATE SET value = value + 1",
                (name,),
            )
            return self.conn.execute("SELECT value FROM counters WHERE name = ?", (name,)).fetchone()[0]

    # ---- message bookkeeping ----
    def mark_processed(self, wamid: str) -> bool:
        """Return False when this WhatsApp message was already handled (Meta retries)."""
        with self.lock:
            try:
                self.conn.execute("INSERT INTO processed(wamid, at) VALUES (?, ?)", (wamid, clock.now_iso()))
                return True
            except sqlite3.IntegrityError:
                return False

    def record_outbound(self, wamid: str, to_phone: str, kind: str, entity: str = "") -> None:
        if not wamid:
            return
        self.run(
            "INSERT OR REPLACE INTO outbound(wamid, to_phone, kind, entity, created_at) VALUES (?,?,?,?,?)",
            (wamid, to_phone, kind, entity, clock.now_iso()),
        )

    def outbound(self, wamid: str) -> sqlite3.Row | None:
        return self.one("SELECT * FROM outbound WHERE wamid = ?", (wamid,))

    # ---- conversation state ----
    def get_state(self, phone: str) -> tuple[str, dict]:
        row = self.one("SELECT state, data FROM conv_state WHERE phone = ?", (phone,))
        return (row["state"], json.loads(row["data"])) if row else ("", {})

    def set_state(self, phone: str, state: str, data: dict | None = None) -> None:
        if not state:
            self.run("DELETE FROM conv_state WHERE phone = ?", (phone,))
            return
        self.run(
            "INSERT OR REPLACE INTO conv_state(phone, state, data, updated_at) VALUES (?,?,?,?)",
            (phone, state, json.dumps(data or {}), clock.now_iso()),
        )

    # ---- audit ----
    def audit(self, actor: str, action: str, entity: str = "", **details: Any) -> int:
        return self.run(
            "INSERT INTO audit(at, actor, action, entity, details) VALUES (?,?,?,?,?)",
            (clock.now_iso(), actor, action, entity, json.dumps(details, ensure_ascii=False, default=str)),
        )

    # ---- key/value ----
    def kv_get(self, k: str, default: str = "") -> str:
        row = self.one("SELECT v FROM kv WHERE k = ?", (k,))
        return row["v"] if row else default

    def kv_set(self, k: str, v: str) -> None:
        self.run("INSERT OR REPLACE INTO kv(k, v) VALUES (?, ?)", (k, v))

    def backup_to(self, dest: str | Path) -> None:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            target = sqlite3.connect(str(dest))
            try:
                self.conn.backup(target)
            finally:
                target.close()


class _Tx:
    def __init__(self, db: DB):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        self.db.conn.execute("BEGIN")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            self.db.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db.lock.release()
        return False
