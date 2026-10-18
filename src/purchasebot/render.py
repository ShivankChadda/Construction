"""WhatsApp message text. WhatsApp formatting: *bold*, _italic_, ~strike~."""

from __future__ import annotations

from . import clock
from .fmt import inr, qty
from .models import Requisition, Slip, SlipLine
from .roster import Person, Roster



def _n(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def req_card(req: Requisition, roster: Roster, heard: str = "", unclear: list[str] | None = None, note: str = "") -> str:
    site = roster.site_name(req.site_code)
    head = f"📋 *Requirement – {site}*"
    head += f" ({req.req_no})" if req.req_no else " (draft, not sent yet)"
    lines = [head]
    if req.entered_by_logistics:
        lines.append(f"_Entered by logistics for {req.engineer_name}_")
    if note:
        lines.append(f"_{note}_")
    lines.append("")
    missing = 0
    for it in req.items:
        q = f"{qty(it.qty)} {it.unit}" if it.qty else "*qty ?*"
        missing += 0 if it.qty else 1
        ref = f"{it.ref} " if it.ref else f"{it.line_no}. "
        spec = f" ({it.spec})" if it.spec else ""
        lines.append(f"{ref}{it.name}{spec} — {q}")
    extra = []
    if req.urgent:
        extra.append("🔴 *URGENT*")
    if req.needed_by:
        extra.append(f"🗓 Needed: {req.needed_by}")
    if extra:
        lines += ["", "  ".join(extra)]
    if missing:
        lines += ["", f"⚠️ {missing} item(s) have no quantity. Send e.g. \"{req.items[0].name} 20 bag\" to fix."]
    if unclear:
        lines += ["", "❓ Not understood: " + "; ".join(f"\"{u}\"" for u in unclear[:5])]
    if heard:
        lines += ["", f"🎙 _I heard:_ \"{heard[:300]}\""]
    return "\n".join(lines)


def _line_text(l: SlipLine, roster: Roster, show_status: bool = False) -> list[str]:
    status = ""
    if show_status and l.status == "REJECTED":
        status = " ❌"
    elif show_status and l.status == "APPROVED":
        status = " ✅"
    name = f"~{l.name}~" if show_status and l.status == "REJECTED" else l.name
    out = [f"{l.line_no}. {name} — {qty(l.qty)} {l.unit} × {inr(l.rate)} = *{inr(l.amount)}*{status}"]
    meta = [l.vendor]
    if l.ref:
        meta.append(l.ref)
    if l.last_rate and "PRICE_UP" not in l.flag_codes():
        meta.append(f"last {inr(l.last_rate)}")
    out.append("    " + " · ".join(meta))
    for f in l.flags:
        out.append(f"    ⚠️ {f.text}")
    return out


def slip_text(slip: Slip, roster: Roster, title: str, show_status: bool = False) -> str:
    sites = slip.sites()
    lines = [f"🧾 *{slip.slip_no}* — {title}",
             f"_{_n(len(slip.lines), 'line')} · {_n(len(sites), 'site')} · by {slip.prepared_by_name}_"]
    for site in sites:
        lines += ["", f"📍 *{roster.site_name(site).upper()}*"]
        for l in slip.lines_for_site(site):
            lines += _line_text(l, roster, show_status)
    approved_only = show_status and slip.status in ("APPROVED", "PARTIAL")
    vt = slip.vendor_totals(approved_only=approved_only)
    lines += ["", "*By vendor:* " + " · ".join(f"{v} {inr(a)}" for v, _, a in vt)] if vt else [""]
    if approved_only and slip.status == "PARTIAL":
        lines.append(f"*Approved: {inr(slip.approved_total)}* (of {inr(slip.total)})")
    else:
        lines.append(f"*Total: {inr(slip.total)}*")
    return "\n".join(lines)


def slip_short(slip: Slip) -> str:
    n_flags = sum(len(l.flags) for l in slip.lines)
    s = f"*{slip.slip_no}* · {inr(slip.total)} · {_n(len(slip.lines), 'line')}"
    if n_flags:
        s += f"\n⚠️ {n_flags} alert{'s' if n_flags != 1 else ''} — see the list above"
    return s


def approval_prompt(slip: Slip) -> str:
    return (
        f"{slip_short(slip)}\n\n"
        "Reply *yes* / *haan* to approve all, *no* to reject.\n"
        "To drop a line: *3 nahi*. To approve some: *only 1 2*.\n"
        "Anything else you type goes to logistics as a question."
    )


def open_list(items: list[dict], roster: Roster) -> str:
    if not items:
        return "✅ No open requirements. Everything requested has been put on a slip."
    lines = [f"📋 *Open requirements* ({len(items)} items)"]
    by_site: dict[str, list[dict]] = {}
    for it in items:
        by_site.setdefault(it["site_code"], []).append(it)
    for site in roster.sites:
        rows = by_site.get(site.code)
        if not rows:
            continue
        eng = ", ".join(p.name for p in roster.engineers_for(site.code))
        lines += ["", f"📍 *{site.name.upper()}*" + (f" — {eng}" if eng else "")]
        for it in rows:
            age = (clock.now() - clock.parse(it["submitted_at"])).days if it["submitted_at"] else 0
            tag = " 🔴" if it["urgent"] else ""
            tag += " _(entered by you)_" if it.get("by_logistics") else ""
            lines.append(f"*{it['ref']}* {it['name']} — {qty(it['qty'])} {it['unit']}{tag}" + (f" · {age}d" if age else ""))
    first = items[0]["ref"]
    lines += ["", "To make a purchase slip, reply like:", f"_{first} Om Traders 420_",
              "_N2 N3 Hira Metals 62 per kg_", "_freight Nicobar 4500 lump sum MV Swaraj Dweep_"]
    return "\n".join(lines)


def grn_text(slip: Slip, site_code: str, lines: list[SlipLine], roster: Roster, note: str = "") -> str:
    out = [f"🚚 *Material for {roster.site_name(site_code)} – {slip.slip_no}*"]
    if note:
        out.append(f"_{note}_")
    out.append("")
    for i, l in enumerate(lines, start=1):
        out.append(f"{i}. {l.name} — {qty(l.qty)} {l.unit} ({l.vendor})")
    out += ["", "When it reaches site, tap *All received*, or *Short/damaged* to tell what actually came."]
    return "\n".join(out)


def stock_text(rows: list[dict], roster: Roster, site_code: str | None = None) -> str:
    title = f"📦 *Stock – {roster.site_name(site_code)}*" if site_code else "📦 *Stock – all sites*"
    if not rows:
        return title + "\nNo stock recorded yet. Stock is added when deliveries are confirmed."
    out = [title]
    current = None
    for r in rows:
        if not site_code and r["site_code"] != current:
            current = r["site_code"]
            out += ["", f"📍 *{roster.site_name(current)}*"]
        warn = " ⚠️ negative" if r["qty"] < 0 else ""
        out.append(f"{r['name']} — {qty(r['qty'])} {r['unit']}{warn}")
    return "\n".join(out)


def help_text(p: Person, roster: Roster) -> str:
    if p.role == "engineer":
        return (
            f"🙏 Namaste {p.name}. Site: *{roster.site_name(p.site)}*\n\n"
            "• Send your material list — type it, send a 🎙 *voice note*, or a 📷 *photo* of the list.\n"
            "  _Saaman ki list bhejiye — likh kar, bol kar ya photo khinch kar._\n"
            "• I'll show it back; tap ✅ *Confirm* to send it to logistics.\n"
            "• When material arrives, tap *All received* on the dispatch message.\n"
            "• *stock* — site stock   • *used 10 bag cement* — record usage\n"
            "• *status* — your open requirements   • *received* — deliveries due"
        )
    if p.role == "logistics":
        return (
            f"🙏 Namaste {p.name}.\n\n"
            "• *list* — open requirements from all sites (with PDF)\n"
            "• Make a slip: _N17 N18 Om Traders 420_ (one line per vendor/rate)\n"
            "• Then tap 📤 *Send for approval*\n"
            "• *edit PS-42* — pull back a slip to change it\n"
            "• *dispatch PS-42 Nicobar MV Campbell Bay* — tell the site it's on the way\n"
            "• *Nicobar: cement 50 bag* — enter a requirement for a site\n"
            "• *slips* — recent slips   • *stock* — all-site stock"
        )
    if p.role == "approver":
        return (
            f"🙏 Namaste {p.name}.\n\n"
            "Purchase slips come to you here with a PDF. Reply to the slip:\n"
            "• *yes* / *haan* / 👍 — approve everything\n"
            "• *no* / *nahi* — reject\n"
            "• *3 nahi* — approve all except line 3\n"
            "• *only 1 2* — approve only lines 1 and 2\n"
            "• anything else — sent to logistics as your question\n\n"
            "• *pending* — slips waiting for you   • *report* — this month's spend"
        )
    return f"🙏 Namaste {p.name}. You receive copies of approved purchase slips.\n• *report* — this month's spend\n• *pending* — slips waiting for approval"


def split_text(text: str, limit: int = 3800) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts
