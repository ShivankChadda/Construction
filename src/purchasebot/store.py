"""Queries that turn database rows into model objects."""

from __future__ import annotations

import json
from datetime import timedelta

from . import clock
from .db import DB
from .models import Flag, ReqItem, Requisition, Slip, SlipLine


def load_requisition(db: DB, req_id: int) -> Requisition | None:
    r = db.one("SELECT * FROM requisitions WHERE id = ?", (req_id,))
    if not r:
        return None
    items = [
        ReqItem(
            id=i["id"], line_no=i["line_no"], ref=i["ref"], name=i["name"], item_key=i["item_key"],
            qty=i["qty"], unit=i["unit"], spec=i["spec"], status=i["status"],
        )
        for i in db.q("SELECT * FROM req_items WHERE requisition_id = ? ORDER BY line_no", (req_id,))
    ]
    return Requisition(
        id=r["id"], req_no=r["req_no"], site_code=r["site_code"], engineer_name=r["engineer_name"],
        engineer_phone=r["engineer_phone"], entered_by_phone=r["entered_by_phone"], status=r["status"],
        source=r["source"], raw_text=r["raw_text"], needed_by=r["needed_by"], urgent=bool(r["urgent"]),
        created_at=r["created_at"], submitted_at=r["submitted_at"], items=items,
    )


def draft_requisition_id(db: DB, engineer_phone: str, entered_by: str) -> int | None:
    row = db.one(
        "SELECT id FROM requisitions WHERE engineer_phone = ? AND entered_by_phone = ? AND status = 'DRAFT' "
        "ORDER BY id DESC LIMIT 1",
        (engineer_phone, entered_by),
    )
    return row["id"] if row else None


def load_slip(db: DB, slip_id: int) -> Slip | None:
    s = db.one("SELECT * FROM slips WHERE id = ?", (slip_id,))
    if not s:
        return None
    rows = db.q(
        "SELECT sl.*, ri.ref AS ref, r.req_no AS req_no FROM slip_lines sl "
        "LEFT JOIN req_items ri ON ri.id = sl.req_item_id "
        "LEFT JOIN requisitions r ON r.id = ri.requisition_id "
        "WHERE sl.slip_id = ? ORDER BY sl.line_no",
        (slip_id,),
    )
    lines = [
        SlipLine(
            id=l["id"], line_no=l["line_no"], site_code=l["site_code"], req_item_id=l["req_item_id"],
            ref=l["ref"], req_no=l["req_no"], name=l["name"], item_key=l["item_key"], qty=l["qty"],
            unit=l["unit"], vendor=l["vendor"], rate=l["rate"], amount=l["amount"],
            requested_qty=l["requested_qty"], last_rate=l["last_rate"], last_rate_date=l["last_rate_date"],
            last_vendor=l["last_vendor"], flags=[Flag(**f) for f in json.loads(l["flags"])],
            status=l["status"], dispatched_at=l["dispatched_at"], dispatch_note=l["dispatch_note"],
            received_qty=l["received_qty"], received_at=l["received_at"],
        )
        for l in rows
    ]
    return Slip(
        id=s["id"], slip_no=s["slip_no"], version=s["version"], status=s["status"],
        prepared_by_name=s["prepared_by_name"], prepared_by_phone=s["prepared_by_phone"],
        created_at=s["created_at"], submitted_at=s["submitted_at"], decided_at=s["decided_at"],
        decided_by_name=s["decided_by_name"], decided_by_phone=s["decided_by_phone"],
        decision_ref=s["decision_ref"], decision_text=s["decision_text"], signature=s["signature"],
        verify_code=s["verify_code"], pdf_path=s["pdf_path"], drive_link=s["drive_link"], lines=lines,
    )


def slip_by_number(db: DB, number: int) -> Slip | None:
    row = db.one("SELECT id FROM slips WHERE slip_no = ?", (slip_no(number),))
    return load_slip(db, row["id"]) if row else None


def slip_no(number: int) -> str:
    return f"PS-{number:04d}"


def draft_slip_id(db: DB, phone: str) -> int | None:
    row = db.one(
        "SELECT id FROM slips WHERE prepared_by_phone = ? AND status = 'DRAFT' ORDER BY id DESC LIMIT 1", (phone,)
    )
    return row["id"] if row else None


def pending_slips(db: DB) -> list[Slip]:
    return [load_slip(db, r["id"]) for r in db.q("SELECT id FROM slips WHERE status = 'PENDING' ORDER BY id")]


def open_items(db: DB) -> list[dict]:
    """Requisition items still waiting to be bought, oldest first."""
    return [
        dict(r)
        for r in db.q(
            "SELECT ri.id, ri.ref, ri.name, ri.item_key, ri.qty, ri.unit, ri.spec, r.site_code, r.req_no, "
            "r.engineer_name, r.urgent, r.needed_by, r.submitted_at, "
            "CASE WHEN r.entered_by_phone != r.engineer_phone THEN 1 ELSE 0 END AS by_logistics "
            "FROM req_items ri JOIN requisitions r ON r.id = ri.requisition_id "
            "WHERE ri.status = 'OPEN' AND r.status = 'SUBMITTED' ORDER BY r.site_code, ri.id"
        )
    ]


def item_by_ref(db: DB, ref: str) -> dict | None:
    r = db.one(
        "SELECT ri.*, r.site_code, r.req_no, r.status AS req_status, "
        "CASE WHEN r.entered_by_phone != r.engineer_phone THEN 1 ELSE 0 END AS by_logistics "
        "FROM req_items ri JOIN requisitions r ON r.id = ri.requisition_id WHERE UPPER(ri.ref) = UPPER(?)",
        (ref,),
    )
    return dict(r) if r else None


def known_item_keys(db: DB, limit: int = 150) -> list[str]:
    rows = db.q(
        "SELECT item_key, COUNT(*) AS n FROM (SELECT item_key FROM req_items UNION ALL SELECT item_key FROM slip_lines) "
        "GROUP BY item_key ORDER BY n DESC LIMIT ?",
        (limit,),
    )
    return [r["item_key"] for r in rows]


def known_vendor_names(db: DB) -> set[str]:
    return {r["vendor"].lower() for r in db.q("SELECT DISTINCT vendor FROM slip_lines sl JOIN slips s ON s.id = sl.slip_id WHERE s.status IN ('APPROVED','PARTIAL')")}


def last_approved_rate(db: DB, item_key: str, unit: str, exclude_slip: int | None = None) -> dict | None:
    r = db.one(
        "SELECT sl.rate, sl.vendor, s.decided_at, s.slip_no FROM slip_lines sl JOIN slips s ON s.id = sl.slip_id "
        "WHERE sl.item_key = ? AND LOWER(sl.unit) = LOWER(?) AND sl.status = 'APPROVED' AND s.id != ? "
        "ORDER BY s.decided_at DESC LIMIT 1",
        (item_key, unit, exclude_slip or -1),
    )
    return dict(r) if r else None


def recent_purchase(db: DB, item_key: str, site_code: str, days: int, exclude_slip: int | None = None) -> dict | None:
    since = (clock.now() - timedelta(days=days)).isoformat(timespec="seconds")
    r = db.one(
        "SELECT sl.qty, sl.unit, s.slip_no, s.decided_at FROM slip_lines sl JOIN slips s ON s.id = sl.slip_id "
        "WHERE sl.item_key = ? AND sl.site_code = ? AND sl.status = 'APPROVED' AND s.decided_at >= ? AND s.id != ? "
        "ORDER BY s.decided_at DESC LIMIT 1",
        (item_key, site_code, since, exclude_slip or -1),
    )
    return dict(r) if r else None


def stock_summary(db: DB, site_code: str | None = None) -> list[dict]:
    sql = (
        "SELECT site_code, item_key, MAX(name) AS name, unit, ROUND(SUM(qty), 3) AS qty, MAX(created_at) AS last_at "
        "FROM stock_ledger {where} GROUP BY site_code, item_key, unit HAVING ABS(SUM(qty)) > 0.0001 "
        "ORDER BY site_code, name"
    )
    if site_code:
        return [dict(r) for r in db.q(sql.format(where="WHERE site_code = ?"), (site_code,))]
    return [dict(r) for r in db.q(sql.format(where=""))]
