"""WhatsApp message text. WhatsApp formatting: *bold*, _italic_, ~strike~."""

from __future__ import annotations

from . import clock
from .fmt import inr, qty
from .models import DROP, PENDING_STOCK, SENT, Requisition, Slip, SlipLine
from .roster import Person, Roster

NOTE_WORDS = {PENDING_STOCK: "not available", SENT: "already sent", DROP: "not needed"}
NOTE_ICONS = {PENDING_STOCK: "⏳", SENT: "📦", DROP: "✖️"}


def _n(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def n_items(n: int) -> str:
    return _n(n, "item")


def note_line(n: SlipLine) -> str:
    """'⏳ N2 PPR metal bend — not available: dispatch pending (stays pending)'."""
    ref = f"{n.ref} " if n.ref else ""
    tail = {PENDING_STOCK: " _(stays pending)_", SENT: "", DROP: ""}[n.action]
    remark = f": {n.remark}" if n.remark else ""
    return f"{NOTE_ICONS[n.action]} {ref}{n.name} — {NOTE_WORDS[n.action]}{remark}{tail}"


def notes_summary(notes: list[SlipLine]) -> str:
    counts = {a: sum(1 for n in notes if n.action == a) for a in (PENDING_STOCK, SENT, DROP)}
    return ", ".join(f"{c} {NOTE_WORDS[a]}" for a, c in counts.items() if c) or "nothing"


def last_rate_text(l: SlipLine) -> str:
    if not l.last_rate:
        return "no past rate"
    when = clock.fmt(l.last_rate_date, with_time=False) if l.last_rate_date else "Zoho item rate"
    shop = f"{l.last_vendor}, " if l.last_vendor else ""
    same = l.last_rate_name and l.last_rate_name.lower() not in (l.name.lower(), l.item_key)
    return f"last {inr(l.last_rate)} ({shop}{when})" + (f" for \"{l.last_rate_name}\"" if same else "")


def req_card(req: Requisition, roster: Roster, heard: str = "", unclear: list[str] | None = None, note: str = "") -> str:
    site = roster.site_name(req.site_code)
    head = f"📋 *Requirement – {site}*"
    head += f" ({req.req_no})" if req.req_no else " (draft, not sent yet)"
    lines = [head]
    if req.source == "group":
        lines.append("_From the group, forwarded by logistics_")
    elif req.entered_by_logistics:
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
    ref = f" ({l.ref})" if l.ref else ""
    out = [f"*{l.line_no}.* {name}{ref} — {qty(l.qty)} {l.unit}{status}"]
    meta = [f"🏪 {l.vendor}"]
    if l.rate > 0:
        meta.append(f"quoted {inr(l.rate)} = {inr(l.amount)}")
    if "PRICE_UP" not in l.flag_codes():
        meta.append(last_rate_text(l))
    out.append("    " + " · ".join(meta))
    if l.remark:
        out.append(f"    _{l.remark}_")
    for f in l.flags:
        out.append(f"    ⚠️ {f.text}")
    return out


def _estimate(slip: Slip, approved_only: bool = False) -> str:
    lines = [l for l in slip.lines if l.status == "APPROVED"] if approved_only else slip.lines
    total = sum(l.est_amount for l in lines)
    missing = sum(1 for l in lines if l.est_rate <= 0)
    if not total:
        return "_No past rates for these items yet — prices come from the shop bills._"
    text = f"*Est. value: {inr(total)}*"
    if missing:
        text += f" _(+{n_items(missing)} with no past rate)_"
    return text


def slip_text(slip: Slip, roster: Roster, title: str, show_status: bool = False) -> str:
    sites = list(dict.fromkeys(slip.sites() + [n.site_code for n in slip.notes]))
    head = f"🧾 *{slip.slip_no}* — {title}"
    sub = f"_{n_items(len(slip.lines))} to buy · {_n(len(sites), 'site')} · by {slip.prepared_by_name}_"
    lines = [head, sub]
    for site in sites:
        lines += ["", f"📍 *{roster.site_name(site).upper()}*"]
        for l in slip.lines_for_site(site):
            lines += _line_text(l, roster, show_status)
        for n in slip.notes:
            if n.site_code == site:
                lines.append(note_line(n))
    if slip.lines:
        approved_only = show_status and slip.status in ("APPROVED", "PARTIAL")
        vt = slip.vendor_totals(approved_only=approved_only)
        if vt:
            lines += ["", "*Shops:* " + " · ".join(f"{v} ({n})" for v, n, _ in vt)]
        lines.append(_estimate(slip, approved_only))
    if slip.notes:
        lines.append(f"_Not buying now: {notes_summary(slip.notes)}_")
    return "\n".join(lines)


def slip_short(slip: Slip) -> str:
    n_flags = sum(len(l.flags) for l in slip.lines)
    s = f"*{slip.slip_no}* · {n_items(len(slip.lines))}"
    if slip.total:
        s += f" · est. {inr(slip.total)}"
    if slip.notes:
        s += f" · {notes_summary(slip.notes)}"
    if n_flags:
        s += f"\n⚠️ {n_flags} alert{'s' if n_flags != 1 else ''} — see the list above"
    return s


def bill_text(bill, challan, warnings: list[str], roster: Roster, recorded_by: str = "") -> str:
    """A shop bill checked against its challan: what Abbas confirms, and what the office receives."""
    head = f"🧾 *Bill {bill.bill_ref}* — {bill.vendor or 'shop'}"
    meta = [x for x in (f"bill no {bill.vendor_bill_no}" if bill.vendor_bill_no else "",
                        clock.fmt(bill.bill_date, with_time=False) if bill.bill_date else "") if x]
    lines = [head + (f" ({', '.join(meta)})" if meta else "")]
    if challan:
        lines.append(f"Against challan *{challan.challan_no}* ({challan.vendor}, approved by "
                     f"{challan.decided_by_name or '-'} on {clock.fmt(challan.decided_at, with_time=False)})")
    if recorded_by:
        lines.append(f"_Recorded by {recorded_by}_")
    lines.append("")
    for l in bill.lines:
        ok = " ✅" if l.slip_line_id and not l.flags else ""
        lines.append(f"{l.line_no}. {l.name} — {qty(l.qty)} {l.unit} × {inr(l.rate)} = *{inr(l.amount)}*{ok}")
        lines += [f"    ⚠️ {f.text}" for f in l.flags]
    tot = [f"Lines {inr(bill.lines_total)}"]
    if bill.tax_total:
        tot.append(f"GST {inr(bill.tax_total)}")
    tot.append(f"*Total {inr(bill.grand_total or bill.lines_total + bill.tax_total)}*")
    lines += ["", " · ".join(tot)]
    if challan:
        billed = {l.slip_line_id for l in bill.lines if l.slip_line_id}
        missing = [l for l in challan.lines if l.id not in billed]
        if missing:
            lines.append("_Not on this bill: " + ", ".join(f"{l.name} {qty(l.qty)} {l.unit}" for l in missing) + "_")
    n_flags = sum(len(l.flags) for l in bill.lines) + len(warnings)
    lines += [""] + [f"⚠️ {w}" for w in warnings]
    if not n_flags:
        lines.append("✔ Matches the approved challan.")
    return "\n".join(lines).rstrip()


def approval_prompt(slip: Slip) -> str:
    return (
        f"{slip_short(slip)}\n\n"
        "Reply *yes* / *haan* to approve all, *no* to reject.\n"
        "To drop a line: *3 nahi*. To approve some: *only 1 2*.\n"
        "Once approved, each shop gets its own signed challan; the bill is checked against it.\n"
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
            if it.get("note"):
                lines.append(f"    ⏳ _{it['note']}_")
    first = items[0]["ref"]
    lines += ["", "Say where to buy each item (voice note is fine, prices optional):", f"_{first} Om Traders_",
              "_N2 to N5 Hira Metals_", "_N6 not available_ · _N7 already sent by MV Campbell Bay_ · _N8 not needed_"]
    return "\n".join(lines)


def dispatch_text(d, roster: Roster) -> str:
    out = [f"🚚 *{d.dispatch_no} → {roster.site_name(d.site_code)}*"]
    meta = [x for x in (f"via {d.carrier}" if d.carrier else "", d.note) if x]
    if meta:
        out.append("_" + " · ".join(meta) + "_")
    out.append("")
    for i in d.items:
        q = f"{qty(i.qty)} {i.unit}" if i.qty else "qty ?"
        out.append(f"{i.line_no}. {i.name} — {q}" + (f" ({i.slip_no})" if i.slip_no else ""))
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
            "• *Forward* site requirements from the group to me (text, photo or voice) — I log them by site\n"
            "• *Forward* your dispatch post (photo + caption) — the site confirms what arrives\n"
            "• *list* — open requirements from all sites (with PDF)\n"
            "• Say which shop for each item, by voice or text: _N17 N18 Om Traders_, _N19 nahi mila_,\n"
            "  _N20 already sent_, _N21 not needed_. Prices are optional.\n"
            "• Then tap 📤 *Send for approval*. After approval you get one signed challan per shop\n"
            "• After buying, send a 📷 *photo of the shop's bill* — I check it against the challan\n"
            "• *edit PS-42* — pull back a slip to change it\n"
            "• *dispatch PS-42 Nicobar MV Campbell Bay* — send a slip's items to a site\n"
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
    if p.role == "accounts":
        return (f"🙏 Namaste {p.name}. You receive approved purchase lists and every shop bill logistics records, "
                "checked against the signed challan.\n• *report* — this month's spend and credit by shop\n"
                "• *pending* — lists waiting for approval")
    return f"🙏 Namaste {p.name}. You receive copies of approved purchase lists.\n• *report* — this month's spend\n• *pending* — lists waiting for approval"


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
