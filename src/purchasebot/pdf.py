"""PDF documents: the purchase slip (draft / approved / rejected) and the open requirement list.

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
from .models import APPROVED, CANCELLED, PARTIAL, REJECTED, Slip
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
        title=f"Purchase Slip {slip.slip_no}", author=roster.company.name,
    )
    story: list = []

    when = slip.submitted_at or slip.created_at
    story.append(_header(roster, "PURCHASE SLIP", [
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
    col_w = [8 * mm, 62 * mm, 16 * mm, 18 * mm, 20 * mm, 22 * mm, 34 * mm]
    for site_code in slip.sites():
        lines = slip.lines_for_site(site_code)
        engineers = ", ".join(p.name for p in roster.engineers_for(site_code)) or "-"
        reqs = sorted({l.req_no for l in lines if l.req_no})
        sub = f"Engineer: {_e(engineers)}" + (f"  ·  Requisitions: {_e(', '.join(reqs))}" if reqs else "")
        story.append(_p(f"{_e(roster.site_name(site_code).upper())}&nbsp;&nbsp;<font name='Helvetica' size=7 color='#6B7280'>{sub}</font>", "h2"))
        rows = [[_p("<b>#</b>"), _p("<b>Item</b>"), _p("<b>Qty</b>", "cellr"), _p("<b>Rate</b>", "cellr"),
                 _p("<b>Amount</b>", "cellr"), _p("<b>Vendor</b>"), _p("<b>Status</b>")]]
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
            sub = f"<br/><font size=6.5 color='#6B7280'>{' · '.join(detail)}</font>" if detail else ""
            flags = "".join(f"<br/><font size=6.5 color='#B45309'>[!] {_e(f.text)}</font>" for f in l.flags)
            status_text = {"APPROVED": "<font color='#15803D'><b>APPROVED</b></font>",
                           "REJECTED": "<font color='#B91C1C'><b>NOT APPROVED</b></font>"}.get(l.status, "Pending")
            rows.append([
                _p(str(l.line_no)),
                _p(strike(_e(l.name)) + sub + flags),
                _p(strike(f"{qty(l.qty)} {_e(l.unit)}"), "cellr"),
                _p(strike(rs(l.rate)), "cellr"),
                _p(strike(rs(l.amount)), "cellr"),
                _p(strike(_e(l.vendor))),
                _p(status_text),
            ])
            if not rejected:
                subtotal += l.amount
            if rejected:
                styles.append(("TEXTCOLOR", (0, i), (-1, i), MUTED))
            if i % 2 == 0:
                styles.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
        rows.append(["", _p("<b>Site total" + (" (excl. not approved)" if decided else "") + "</b>"), "", "",
                     _p(f"<b>{rs(subtotal)}</b>", "cellr"), "", ""])
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

    # ---- vendor summary and totals ----
    story.append(_p("VENDOR SUMMARY", "h2"))
    vt = slip.vendor_totals(approved_only=decided)
    vrows = [[_p("<b>Vendor</b>"), _p("<b>Lines</b>", "cellr"), _p("<b>Amount</b>", "cellr")]]
    vrows += [[_p(_e(v)), _p(str(n), "cellr"), _p(rs(a), "cellr")] for v, n, a in vt]
    if not vt:
        vrows.append([_p("No lines approved"), "", ""])
    vrows.append([_p("Total of all lines"), "", _p(rs(slip.total), "cellr")])
    if decided:
        vrows.append([_p("<b>Approved for purchase</b>"), "", _p(f"<b>{rs(slip.approved_total)}</b>", "cellr")])
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
    story.append(Spacer(1, 6))

    # ---- checks ----
    n_flags = sum(len(l.flags) for l in slip.lines)
    if n_flags:
        seen = "were shown to the approver before the decision" if decided else "are shown to the approver with this slip"
        story.append(_p(f"<b>Checks:</b> {n_flags} alert{'s' if n_flags != 1 else ''} (marked [!] above) {seen}.", "body"))
    else:
        story.append(_p("<b>Checks:</b> no price, quantity, vendor or repeat-purchase alerts on this slip.", "body"))
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
            _p("Scan the QR code to check this slip against the original record. "
               "Any change to items, quantities, rates or vendors makes the check fail.", "small"),
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
