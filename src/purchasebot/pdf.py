"""PDF documents: the purchase list (draft / approved / rejected), the signed challan for each shop,
and the open requirement list.

Built-in PDF fonts have no rupee glyph, so amounts print as "Rs.".
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from . import clock
from .fmt import inr, qty
from .models import APPROVED, CANCELLED, DROP, PARTIAL, PENDING_STOCK, REJECTED, SENT, Challan, Slip
from .roster import Roster

INK = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#6B7280")
RULE = colors.HexColor("#D1D5DB")
ZEBRA = colors.HexColor("#F7F7F5")
GREEN = colors.HexColor("#15803D")
AMBER = colors.HexColor("#B45309")
RED = colors.HexColor("#B91C1C")
GREY = colors.HexColor("#6B7280")
STAMP_BLUE = colors.HexColor("#1E3A8A")

_ss = getSampleStyleSheet()
S = {
    "body": ParagraphStyle("body", parent=_ss["Normal"], fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK),
    "small": ParagraphStyle("small", parent=_ss["Normal"], fontName="Helvetica", fontSize=7, leading=9, textColor=MUTED),
    "cell": ParagraphStyle("cell", parent=_ss["Normal"], fontName="Helvetica", fontSize=8, leading=10, textColor=INK),
    "cellr": ParagraphStyle("cellr", parent=_ss["Normal"], fontName="Helvetica", fontSize=8, leading=10, textColor=INK, alignment=TA_RIGHT),
    "h1": ParagraphStyle("h1", parent=_ss["Normal"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=INK),
    "h2": ParagraphStyle("h2", parent=_ss["Normal"], fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=INK, spaceBefore=7, spaceAfter=2),
    "title": ParagraphStyle("title", parent=_ss["Normal"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=INK, alignment=TA_RIGHT),
    "right": ParagraphStyle("right", parent=_ss["Normal"], fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK, alignment=TA_RIGHT),
    "banner": ParagraphStyle("banner", parent=_ss["Normal"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.white, alignment=TA_CENTER),
    "sig": ParagraphStyle("sig", parent=_ss["Normal"], fontName="Times-BoldItalic", fontSize=22, leading=26, textColor=STAMP_BLUE),
    "label": ParagraphStyle("label", parent=_ss["Normal"], fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=MUTED),
}


def rs(amount: float) -> str:
    return inr(amount, symbol="Rs. ")


def _p(text: str, style: str = "cell") -> Paragraph:
    return Paragraph(text, S[style])


def _e(text: str | None) -> str:
    # Built-in PDF fonts have no rupee glyph.
    return escape((text or "").replace("₹", "Rs. "))


class Stamp(Flowable):
    """Round approval stamp with the approver's initials and date."""

    def __init__(self, initials: str, date_text: str, size: float = 30 * mm):
        super().__init__()
        self.initials = initials
        self.date_text = date_text
        self.size = size
        self.width = self.height = size

    def draw(self):
        c = self.canv
        r = self.size / 2
        c.saveState()
        c.translate(r, r)
        c.rotate(-12)
        c.setStrokeColor(STAMP_BLUE)
        c.setFillColor(STAMP_BLUE)
        c.setLineWidth(1.6)
        c.circle(0, 0, r - 1, stroke=1, fill=0)
        c.setLineWidth(0.6)
        c.circle(0, 0, r - 4, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 6.5)
        c.drawCentredString(0, r * 0.48, "APPROVED")
        c.setFont("Times-BoldItalic", r * 0.62)
        c.drawCentredString(0, -r * 0.18, self.initials)
        c.setFont("Helvetica", 5.5)
        c.drawCentredString(0, -r * 0.55, self.date_text)
        c.restoreState()


def _qr(url: str, size: float = 26 * mm) -> Drawing:
    w = QrCodeWidget(url)
    x1, y1, x2, y2 = w.getBounds()
    d = Drawing(size, size, transform=[size / (x2 - x1), 0, 0, size / (y2 - y1), 0, 0])
    d.add(w)
    return d


def _page_decorator(slip_no: str, footer: str, watermark: str | None):
    def draw(canvas, doc):
        canvas.saveState()
        if watermark:
            canvas.setFillColor(colors.HexColor("#E5E7EB"))
            canvas.setFont("Helvetica-Bold", 46)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, watermark)
            canvas.rotate(-35)
            canvas.translate(-A4[0] / 2, -A4[1] / 2)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(15 * mm, 9 * mm, f"{slip_no}  ·  {footer}")
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def _header(roster: Roster, title: str, right_lines: list[str]) -> Table:
    co = roster.company
    left = [_p(_e(co.name), "h1")]
    if co.address:
        left.append(_p(_e(co.address), "small"))
    if co.gstin:
        left.append(_p(f"GSTIN: {_e(co.gstin)}", "small"))
    right = [_p(title, "title")] + [_p(t, "right") for t in right_lines]
    t = Table([[left, right]], colWidths=[105 * mm, 75 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, INK),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _banner(text: str, color) -> Table:
    t = Table([[_p(text, "banner")]], colWidths=[180 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _status_banner(slip: Slip) -> Table:
    if slip.status == APPROVED:
        return _banner("APPROVED FOR PURCHASE", GREEN)
    if slip.status == PARTIAL:
        return _banner("PARTIALLY APPROVED - BUY ONLY THE LINES MARKED APPROVED", GREEN)
    if slip.status == REJECTED:
        return _banner("REJECTED - DO NOT PURCHASE", RED)
    if slip.status == CANCELLED:
        return _banner("CANCELLED", GREY)
    return _banner("PENDING APPROVAL - NOT VALID FOR PURCHASE", AMBER)


def render_slip_pdf(slip: Slip, roster: Roster, out_path: str | Path, verify_url: str = "") -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    decided = slip.status in (APPROVED, PARTIAL, REJECTED)
    watermark = None if decided else ("CANCELLED" if slip.status == CANCELLED else "PENDING APPROVAL")
    footer = "Generated by the purchase approval bot"
    if slip.verify_code:
        footer += f"  ·  Verification code {slip.verify_code}"
    doc = SimpleDocTemplate(
        str(out), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
        title=f"Purchase List {slip.slip_no}", author=roster.company.name,
    )
    story: list = []

    when = slip.submitted_at or slip.created_at
    story.append(_header(roster, "PURCHASE LIST", [
        f"<b>{slip.slip_no}</b>" + (f"  (revision {slip.version})" if slip.version > 1 else ""),
        f"Date: {clock.fmt(when, with_time=False)}",
    ]))
    story.append(Spacer(1, 6))
    story.append(_status_banner(slip))
    story.append(Spacer(1, 6))

    site_names = ", ".join(roster.site_name(s) for s in slip.sites())
    story.append(_p(
        f"Prepared by <b>{_e(slip.prepared_by_name)}</b> (Logistics)  ·  Submitted {clock.fmt(when)}  ·  "
        f"Sites: <b>{_e(site_names)}</b>", "body"))

    # ---- lines grouped by site ----
    col_w = [8 * mm, 54 * mm, 16 * mm, 27 * mm, 31 * mm, 19 * mm, 25 * mm]
    for site_code in slip.sites():
        lines = slip.lines_for_site(site_code)
        engineers = ", ".join(p.name for p in roster.engineers_for(site_code)) or "-"
        reqs = sorted({l.req_no for l in lines if l.req_no})
        sub = f"Engineer: {_e(engineers)}" + (f"  ·  Requisitions: {_e(', '.join(reqs))}" if reqs else "")
        story.append(_p(f"{_e(roster.site_name(site_code).upper())}&nbsp;&nbsp;<font name='Helvetica' size=7 color='#6B7280'>{sub}</font>", "h2"))
        rows = [[_p("<b>#</b>"), _p("<b>Item</b>"), _p("<b>Qty</b>", "cellr"), _p("<b>Shop</b>"),
                 _p("<b>Last rate</b>"), _p("<b>Est. value</b>", "cellr"), _p("<b>Status</b>")]]
        styles = []
        subtotal = 0.0
        for i, l in enumerate(lines, start=1):
            rejected = l.status == REJECTED
            strike = (lambda s: f"<strike>{s}</strike>") if rejected else (lambda s: s)
            detail = []
            if l.ref:
                detail.append(f"Ref {l.ref}")
            if l.requested_qty is not None and l.requested_qty != l.qty:
                detail.append(f"site asked {qty(l.requested_qty)} {_e(l.unit)}")
            if l.rate > 0:
                detail.append(f"quoted {rs(l.rate)}/{_e(l.unit)}")
            if l.remark:
                detail.append(_e(l.remark))
            sub = f"<br/><font size=6.5 color='#6B7280'>{' · '.join(detail)}</font>" if detail else ""
            flags = "".join(f"<br/><font size=6.5 color='#B45309'>[!] {_e(f.text)}</font>" for f in l.flags)
            status_text = {"APPROVED": "<font color='#15803D'><b>APPROVED</b></font>",
                           "REJECTED": "<font color='#B91C1C'><b>NOT APPROVED</b></font>"}.get(l.status, "Pending")
            if l.last_rate:
                when_ = clock.fmt(l.last_rate_date, with_time=False) if l.last_rate_date else "Zoho item rate"
                last = f"{rs(l.last_rate)}<br/><font size=6.5 color='#6B7280'>{_e(l.last_vendor or '')} {when_}"
                if l.last_rate_name and l.last_rate_name.lower() not in (l.name.lower(), l.item_key):
                    last += f"<br/>as \"{_e(l.last_rate_name[:40])}\""
                last += "</font>"
            else:
                last = "<font color='#6B7280'>no past rate</font>"
            rows.append([
                _p(str(l.line_no)),
                _p(strike(_e(l.name)) + sub + flags),
                _p(strike(f"{qty(l.qty)} {_e(l.unit)}"), "cellr"),
                _p(strike(_e(l.vendor))),
                _p(last),
                _p(strike(rs(l.est_amount)) if l.est_amount else "-", "cellr"),
                _p(status_text),
            ])
            if not rejected:
                subtotal += l.est_amount
            if rejected:
                styles.append(("TEXTCOLOR", (0, i), (-1, i), MUTED))
            if i % 2 == 0:
                styles.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
        rows.append(["", _p("<b>Site est." + (" (excl. not approved)" if decided else "") + "</b>"), "", "", "",
                     _p(f"<b>{rs(subtotal)}</b>", "cellr"), ""])
        t = Table(rows, colWidths=col_w, repeatRows=1)
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
            ("LINEABOVE", (0, -1), (-1, -1), 0.6, RULE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            *styles,
        ]))
        story.append(t)

    # ---- items not being bought now ----
    if slip.notes:
        story.append(_p("NOT BUYING NOW", "h2"))
        label = {PENDING_STOCK: "<font color='#B45309'><b>Not available</b></font> - stays pending",
                 SENT: "<b>Already sent</b> - not purchased", DROP: "<b>Not needed</b> - closed"}
        nrows = [[_p("<b>Ref</b>"), _p("<b>Item</b>"), _p("<b>Site</b>"), _p("<b>Status</b>"), _p("<b>Remark</b>")]]
        for n in slip.notes:
            nrows.append([_p(_e(n.ref or "")), _p(f"{_e(n.name)} - {qty(n.qty)} {_e(n.unit)}"),
                          _p(_e(roster.site_name(n.site_code))), _p(label[n.action]), _p(_e(n.remark) or "-")])
        nt = Table(nrows, colWidths=[14 * mm, 66 * mm, 24 * mm, 36 * mm, 40 * mm], repeatRows=1)
        nt.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(nt)

    # ---- shop summary and estimate ----
    if slip.lines:
        story.append(_p("BY SHOP", "h2"))
        vt = slip.vendor_totals(approved_only=decided)
        vrows = [[_p("<b>Shop</b>"), _p("<b>Items</b>", "cellr"), _p("<b>Est. value</b>", "cellr")]]
        vrows += [[_p(_e(v)), _p(str(n), "cellr"), _p(rs(a) if a else "-", "cellr")] for v, n, a in vt]
        if not vt:
            vrows.append([_p("No lines approved"), "", ""])
        missing = slip.unpriced
        vrows.append([_p("Estimated value of all lines" + (f" ({missing} without a past rate)" if missing else "")),
                      "", _p(rs(slip.total), "cellr")])
        if decided:
            vrows.append([_p("<b>Approved (estimated)</b>"), "", _p(f"<b>{rs(slip.approved_total)}</b>", "cellr")])
        n_tot = 2 if decided else 1
        vtable = Table(vrows, colWidths=[110 * mm, 25 * mm, 45 * mm])
        vtable.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
            ("LINEABOVE", (0, -n_tot), (-1, -n_tot), 0.6, RULE),
            ("LINEABOVE", (0, -1), (-1, -1), 1 if decided else 0.6, INK if decided else RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(vtable)
        story.append(_p("Estimates use the last rate paid for each item. Actual prices come from the shop bills, "
                        "which are checked against the signed challans.", "small"))
    story.append(Spacer(1, 6))

    # ---- checks ----
    n_flags = sum(len(l.flags) for l in slip.lines)
    if n_flags:
        seen = "were shown to the approver before the decision" if decided else "are shown to the approver with this list"
        story.append(_p(f"<b>Checks:</b> {n_flags} alert{'s' if n_flags != 1 else ''} (marked [!] above) {seen}.", "body"))
    else:
        story.append(_p("<b>Checks:</b> no price, quantity, shop or repeat-purchase alerts on this list.", "body"))
    story.append(Spacer(1, 8))

    story.append(KeepTogether(_approval_block(slip, roster, verify_url)))

    doc.build(story, onFirstPage=_page_decorator(slip.slip_no, footer, watermark),
              onLaterPages=_page_decorator(slip.slip_no, footer, watermark))
    return out


def _approval_block(slip: Slip, roster: Roster, verify_url: str) -> list:
    if slip.status in (APPROVED, PARTIAL):
        approver = next((p for p in roster.people if p.phone == slip.decided_by_phone), None)
        initials = approver.initials if approver else "".join(w[0] for w in (slip.decided_by_name or "?").split()[:3])
        title = approver.title if approver else ""
        phone = approver.short_phone if approver else ""
        left = [
            _p("APPROVED AND DIGITALLY SIGNED BY", "label"),
            Paragraph(_e(slip.decided_by_name), S["sig"]),
            _p(_e(title), "small"),
            Spacer(1, 4),
            _p(f"Approved on WhatsApp {('from ' + phone) if phone else ''} on <b>{clock.fmt(slip.decided_at)}</b>", "body"),
            _p(f"Reply recorded: “{_e((slip.decision_text or '')[:80])}”", "small"),
            Spacer(1, 4),
            _p(f"Verification code: <b>{_e(slip.verify_code)}</b>", "body"),
            _p("Scan the QR code to check this list against the original record. "
               "Any change to items, quantities or shops makes the check fail. Each shop gets its own signed challan.",
               "small"),
        ]
        right_cells = [Stamp(initials, clock.fmt(slip.decided_at, with_time=False), size=26 * mm)]
        if verify_url:
            right_cells.append(_qr(verify_url, size=24 * mm))
        right = Table([right_cells], colWidths=[30 * mm] * len(right_cells))
        right.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
        box = Table([[left, right]], colWidths=[180 * mm - 30 * mm * len(right_cells) - 4 * mm, 30 * mm * len(right_cells) + 4 * mm])
        box.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1, STAMP_BLUE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (0, 0), 10),
        ]))
        return [box]
    if slip.status == REJECTED:
        t = Table([[[
            _p("REJECTED BY", "label"),
            _p(f"<b>{_e(slip.decided_by_name)}</b> on {clock.fmt(slip.decided_at)}", "body"),
            _p(f"Reply recorded: “{_e((slip.decision_text or '')[:120])}”", "small"),
        ]]], colWidths=[180 * mm])
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1, RED), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                               ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        return [t]
    approvers = ", ".join(p.name for p in roster.by_role("approver"))
    t = Table([[[
        _p("AWAITING APPROVAL", "label"),
        _p(f"Sent to {_e(approvers)} on WhatsApp. This document is <b>not valid for purchase</b> until it is "
           "re-issued with a signature and verification code.", "body"),
    ]]], colWidths=[180 * mm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1, AMBER), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return [t]


def render_challan_pdf(ch: Challan, roster: Roster, out_path: str | Path, verify_url: str = "",
                       buyer: str = "") -> Path:
    """The signed purchase order a shop supplies against. No prices: the shop bills at its rate, and the
    bill is checked against this challan."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    footer = f"Generated by the purchase approval bot  ·  Verification code {ch.verify_code}"
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=f"Purchase Challan {ch.challan_no}", author=roster.company.name)
    right = [f"<b>{ch.challan_no}</b>", f"Date: {clock.fmt(ch.decided_at or ch.created_at, with_time=False)}"]
    if ch.valid_until:
        right.append(f"Valid until: <b>{clock.fmt(ch.valid_until, with_time=False)}</b>")
    story: list = [_header(roster, "PURCHASE CHALLAN", right), Spacer(1, 6),
                   _banner("APPROVED PURCHASE ORDER - SUPPLY ON CREDIT", GREEN), Spacer(1, 8)]
    co = roster.company
    story.append(_p("TO", "label"))
    story.append(_p(f"<b>{_e(ch.vendor)}</b>", "h1"))
    story.append(Spacer(1, 4))
    who = f"our representative <b>{_e(buyer)}</b> (Logistics)" if buyer else "our representative"
    story.append(_p(f"Please supply the items below to {who} on credit, against this challan. "
                    f"Bill to <b>{_e(co.name)}</b>" + (f", {_e(co.address)}" if co.address else "") +
                    (f", GSTIN {_e(co.gstin)}" if co.gstin else "") +
                    f". Please write <b>{ch.challan_no}</b> on your bill.", "body"))
    story.append(Spacer(1, 6))
    rows = [[_p("<b>#</b>"), _p("<b>Item</b>"), _p("<b>Qty</b>", "cellr"), _p("<b>Unit</b>"), _p("<b>For site</b>")]]
    for i, l in enumerate(ch.lines, start=1):
        sub = f"<br/><font size=6.5 color='#6B7280'>{_e(l.remark)}</font>" if l.remark else ""
        rows.append([_p(str(i)), _p(_e(l.name) + sub), _p(qty(l.qty), "cellr"), _p(_e(l.unit)),
                     _p(_e(roster.site_name(l.site_code)))])
    t = Table(rows, colWidths=[10 * mm, 98 * mm, 22 * mm, 20 * mm, 30 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(Spacer(1, 6))
    story.append(_p("<b>Supply only these items and quantities.</b> Anything not on this challan needs a new approval "
                    "and will not be paid against it. Scan the QR code to check that the challan is genuine and has not "
                    "already been billed.", "body"))
    story.append(Spacer(1, 8))
    approver = next((p for p in roster.people if p.phone == ch.decided_by_phone), None)
    initials = approver.initials if approver else "".join(w[0] for w in (ch.decided_by_name or "?").split()[:3])
    left = [
        _p("APPROVED AND DIGITALLY SIGNED BY", "label"),
        Paragraph(_e(ch.decided_by_name), S["sig"]),
        _p(_e(approver.title if approver else ""), "small"),
        Spacer(1, 4),
        _p(f"Approved on WhatsApp on <b>{clock.fmt(ch.decided_at)}</b> (purchase list {ch.slip_no})", "body"),
        _p(f"Verification code: <b>{_e(ch.verify_code)}</b>", "body"),
    ]
    cells = [Stamp(initials, clock.fmt(ch.decided_at, with_time=False), size=26 * mm)]
    if verify_url:
        cells.append(_qr(verify_url, size=24 * mm))
    right_t = Table([cells], colWidths=[30 * mm] * len(cells))
    right_t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
    box = Table([[left, right_t]], colWidths=[180 * mm - 30 * mm * len(cells) - 4 * mm, 30 * mm * len(cells) + 4 * mm])
    box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, STAMP_BLUE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (0, 0), 10),
    ]))
    story.append(KeepTogether([box]))
    watermark = "CANCELLED" if ch.status == CANCELLED else None
    doc.build(story, onFirstPage=_page_decorator(ch.challan_no, footer, watermark),
              onLaterPages=_page_decorator(ch.challan_no, footer, watermark))
    return out


def render_requirements_pdf(items: list[dict], roster: Roster, out_path: str | Path) -> Path:
    """Open site requirements grouped by site — what logistics takes to the market."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=16 * mm, title="Material Requirement List")
    story: list = [
        _header(roster, "MATERIAL REQUIREMENT LIST", [f"Open items as of {clock.fmt(clock.now_iso())}"]),
        Spacer(1, 6),
    ]
    by_site: dict[str, list[dict]] = {}
    for it in items:
        by_site.setdefault(it["site_code"], []).append(it)
    if not by_site:
        story.append(_p("No open requirements.", "body"))
    for site in roster.sites:
        rows_in = by_site.get(site.code)
        if not rows_in:
            continue
        story.append(_p(f"{_e(site.name.upper())}  ({len(rows_in)} items)", "h2"))
        rows = [[_p("<b>Ref</b>"), _p("<b>Item</b>"), _p("<b>Qty</b>", "cellr"), _p("<b>Requisition</b>"), _p("<b>Asked on</b>")]]
        for it in rows_in:
            name = _e(it["name"]) + (f"<br/><font size=6.5 color='#6B7280'>{_e(it['spec'])}</font>" if it.get("spec") else "")
            if it.get("urgent"):
                name += " <font color='#B91C1C'><b>URGENT</b></font>"
            rows.append([_p(f"<b>{_e(it['ref'])}</b>"), _p(name), _p(f"{qty(it['qty'])} {_e(it['unit'])}", "cellr"),
                         _p(_e(it["req_no"])), _p(clock.fmt(it["submitted_at"], with_time=False))])
        t = Table(rows, colWidths=[16 * mm, 84 * mm, 26 * mm, 28 * mm, 26 * mm], repeatRows=1)
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t)
    doc.build(story, onFirstPage=_page_decorator("Requirement list", "Generated by the purchase approval bot", None),
              onLaterPages=_page_decorator("Requirement list", "Generated by the purchase approval bot", None))
    return out
