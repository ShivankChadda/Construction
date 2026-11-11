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

# What logistics decided for a requested item. Only BUY lines go to the approver for a decision;
# the rest are listed on the slip as "not buying now".
BUY = "BUY"
PENDING_STOCK = "PENDING"   # not available in the market now; stays on the open list
SENT = "SENT"               # already sent to site earlier; closed without a purchase
DROP = "DROP"               # not needed; closed
NOTE_ACTIONS = (PENDING_STOCK, SENT, DROP)

# Challan statuses
OPEN = "OPEN"
PART_BILLED = "PART_BILLED"
BILLED = "BILLED"


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
    note: str = ""


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
    action: str = BUY
    remark: str = ""
    last_rate_name: str | None = None
    challan_id: int | None = None

    def flag_codes(self) -> set[str]:
        return {f.code for f in self.flags}

    @property
    def est_rate(self) -> float:
        """The quoted rate if logistics gave one, else the last rate paid (0 when neither is known)."""
        return self.rate if self.rate > 0 else (self.last_rate or 0.0)

    @property
    def est_amount(self) -> float:
        return round(self.qty * self.est_rate, 2)


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
    lines: list[SlipLine] = field(default_factory=list)   # BUY lines: what the approver decides on
    notes: list[SlipLine] = field(default_factory=list)   # pending / already sent / not needed

    @property
    def total(self) -> float:
        """Estimated value: quoted rates where given, else last rates paid."""
        return round(sum(l.est_amount for l in self.lines), 2)

    @property
    def approved_total(self) -> float:
        return round(sum(l.est_amount for l in self.lines if l.status == "APPROVED"), 2)

    @property
    def unpriced(self) -> int:
        """Lines with neither a quoted rate nor a past rate, so they're missing from the estimate."""
        return sum(1 for l in self.lines if l.est_rate <= 0)

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
            t[1] += l.est_amount
        return [(v, n, round(a, 2)) for v, (n, a) in totals.items()]

    def flagged_lines(self) -> list[SlipLine]:
        return [l for l in self.lines if l.flags]


@dataclass
class Challan:
    id: int
    challan_no: str
    slip_id: int
    slip_no: str
    vendor: str
    status: str
    verify_code: str | None
    signature: str | None
    pdf_path: str | None
    valid_until: str | None
    created_at: str
    billed_at: str | None
    decided_by_name: str | None
    decided_by_phone: str | None
    decided_at: str | None
    lines: list[SlipLine] = field(default_factory=list)


@dataclass
class BillLine:
    id: int
    line_no: int
    name: str
    item_key: str
    qty: float
    unit: str
    rate: float
    amount: float
    slip_line_id: int | None
    flags: list[Flag]


@dataclass
class Bill:
    id: int
    bill_ref: str
    challan_id: int | None
    challan_no: str | None
    vendor: str
    printed_vendor: str
    vendor_bill_no: str
    bill_date: str
    status: str
    tax_total: float
    grand_total: float
    media: list[str]
    unclear: list[str]
    submitted_by: str
    created_at: str
    recorded_at: str | None
    lines: list[BillLine] = field(default_factory=list)

    @property
    def lines_total(self) -> float:
        return round(sum(l.amount for l in self.lines), 2)
