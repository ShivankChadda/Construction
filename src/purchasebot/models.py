"""Plain data objects passed between the workflow, renderers and sync."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

# Slip statuses
DRAFT = "DRAFT"
PENDING = "PENDING"
APPROVED = "APPROVED"
PARTIAL = "PARTIAL"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"
DECIDED = (APPROVED, PARTIAL, REJECTED)

# Requisition statuses
SUBMITTED = "SUBMITTED"
CLOSED = "CLOSED"


@dataclass
class Flag:
    code: str  # PRICE_UP, NOT_REQUESTED, QTY_OVER, NEW_VENDOR, RECENT_PURCHASE, ENTERED_BY_LOGISTICS, QTY_MISSING
    text: str

    def to_dict(self) -> dict:
        return {"code": self.code, "text": self.text}


@dataclass
class ReqItem:
    id: int
    line_no: int
    ref: str | None
    name: str
    item_key: str
    qty: float
    unit: str
    spec: str = ""
    status: str = "OPEN"


@dataclass
class Requisition:
    id: int
    req_no: str | None
    site_code: str
    engineer_name: str
    engineer_phone: str
    entered_by_phone: str
    status: str
    source: str
    raw_text: str
    needed_by: str
    urgent: bool
    created_at: str
    submitted_at: str | None
    items: list[ReqItem] = field(default_factory=list)

    @property
    def entered_by_logistics(self) -> bool:
        return self.entered_by_phone != self.engineer_phone


@dataclass
class SlipLine:
    id: int
    line_no: int
    site_code: str
    req_item_id: int | None
    ref: str | None
    req_no: str | None
    name: str
    item_key: str
    qty: float
    unit: str
    vendor: str
    rate: float
    amount: float
    requested_qty: float | None
    last_rate: float | None
    last_rate_date: str | None
    last_vendor: str | None
    flags: list[Flag]
    status: str
    dispatched_at: str | None = None
    dispatch_note: str | None = None
    received_qty: float | None = None
    received_at: str | None = None

    def flag_codes(self) -> set[str]:
        return {f.code for f in self.flags}


@dataclass
class DispatchItem:
    id: int
    line_no: int
    name: str
    item_key: str
    qty: float
    unit: str
    slip_line_id: int | None
    slip_no: str | None
    stock_item: bool
    received_qty: float | None


@dataclass
class Dispatch:
    id: int
    dispatch_no: str
    site_code: str
    carrier: str
    note: str
    created_by: str
    created_at: str
    status: str
    received_at: str | None
    received_by: str | None
    items: list[DispatchItem] = field(default_factory=list)


@dataclass
class Slip:
    id: int
    slip_no: str
    version: int
    status: str
    prepared_by_name: str
    prepared_by_phone: str
    created_at: str
    submitted_at: str | None
    decided_at: str | None
    decided_by_name: str | None
    decided_by_phone: str | None
    decision_ref: str | None
    decision_text: str | None
    signature: str | None
    verify_code: str | None
    pdf_path: str | None
    drive_link: str | None
    lines: list[SlipLine] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(sum(l.amount for l in self.lines), 2)

    @property
    def approved_total(self) -> float:
        return round(sum(l.amount for l in self.lines if l.status == "APPROVED"), 2)

    def sites(self) -> list[str]:
        return list(OrderedDict.fromkeys(l.site_code for l in self.lines))

    def lines_for_site(self, site_code: str) -> list[SlipLine]:
        return [l for l in self.lines if l.site_code == site_code]

    def vendor_totals(self, approved_only: bool = False) -> list[tuple[str, int, float]]:
        totals: OrderedDict[str, list] = OrderedDict()
        for l in self.lines:
            if approved_only and l.status != "APPROVED":
                continue
            t = totals.setdefault(l.vendor, [0, 0.0])
            t[0] += 1
            t[1] += l.amount
        return [(v, n, round(a, 2)) for v, (n, a) in totals.items()]

    def flagged_lines(self) -> list[SlipLine]:
        return [l for l in self.lines if l.flags]
