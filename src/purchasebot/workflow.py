"""The purchase workflow, driven by WhatsApp messages.

    Engineer ──list/voice/photo──▶ draft requisition ──✅──▶ REQ-NIC-0012 (items N17, N18…)
    Abbas ──"N17 Om Traders 420"──▶ draft slip PS-0042 (price/qty/vendor checks) ──📤──▶
    Approver ──"yes" / "3 nahi" / button──▶ signed PDF ──▶ Abbas, observers, Drive, Sheets
    Abbas ──"dispatch PS-42"──▶ engineer ──"All received" / shortage──▶ site stock

Every handler runs under one lock: messages are processed one at a time.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from . import approval, clock, render, store
from .approval import Decision
from .config import Settings
from .db import DB
from .fmt import inr, lakh, qty
from .google_sync import GoogleSync, enqueue, process_queue
from .llm import ParsedItem, ParsedSlipLine, ParseError, Parser, norm_key, norm_unit
from .models import APPROVED, DRAFT, PARTIAL, PENDING, REJECTED, Flag, Slip
from .pdf import render_requirements_pdf, render_slip_pdf
from .roster import Person, Roster
from .signing import Signer, canonical, verify_code
from .speech import Speech, SpeechError
from .whatsapp import REENGAGEMENT_ERROR, Incoming, WhatsApp, WhatsAppError

log = logging.getLogger(__name__)

HELP_WORDS = {"help", "menu", "start", "hi", "hello", "namaste", "madad", "?"}


class UserError(Exception):
    """A problem the sender can fix; the message is shown to them as-is."""


@dataclass
class Content:
    text: str
    attachments: list[tuple[bytes, str]]
    source: str
    heard: str = ""
    saved_path: str = ""


class Bot:
    def __init__(self, settings: Settings, db: DB, roster: Roster, wa: WhatsApp, parser: Parser,
                 speech: Speech, signer: Signer, gsync: GoogleSync | None = None):
        self.s = settings
        self.db = db
        self.roster = roster
        self.wa = wa
        self.parser = parser
        self.speech = speech
        self.signer = signer
        self.gsync = gsync
        self.lock = threading.RLock()
        self._sync_lock = threading.Lock()
        clock.set_timezone(settings.timezone)

    # ================================================================ entry

    def handle(self, msg: Incoming) -> None:
        with self.lock:
            if not msg.wamid or not self.db.mark_processed(msg.wamid):
                return
            person = self.roster.person(msg.phone)
            if person is None:
                self._unknown_sender(msg)
                return
            self.wa.mark_read(msg.wamid)
            try:
                self._route(person, msg)
            except UserError as e:
                self._text(person, str(e))
            except (ParseError, SpeechError) as e:
                log.warning("Could not read message from %s: %s", person.name, e)
                self._text(person, f"⚠️ Sorry, I couldn't read that ({e}). Please try again, or type it as text.")
            except Exception:
                log.exception("Failed handling %s from %s", msg.wamid, person.name)
                self._text(person, "⚠️ Something went wrong on my side. Please try again in a minute.")
        self.sync_soon()

    def sync_soon(self) -> None:
        if self.gsync is None or not self._sync_lock.acquire(blocking=False):
            return

        def run():
            try:
                process_queue(self.db, self.gsync, self.roster)
            finally:
                self._sync_lock.release()

        threading.Thread(target=run, daemon=True).start()

    def _route(self, p: Person, msg: Incoming) -> None:
        if msg.kind == "button":
            return self._button(p, msg)
        if msg.kind == "reaction":
            # A 👍 on a slip may just mean "seen", so it only ever leads to a confirm tap.
            ob = self.db.outbound(msg.context_id) if msg.context_id and msg.text else None
            if p.role == "approver" and ob and (ob["entity"] or "").startswith("slip:"):
                _, sid, ver = ob["entity"].split(":")
                slip = store.load_slip(self.db, int(sid))
                d = approval.read_decision(msg.text, len(slip.lines))
                if d.kind in (approval.APPROVE_ALL, approval.REJECT_ALL) and slip.status == PENDING and slip.version == int(ver):
                    self._ask_confirm(p, slip, int(ver), d, f"{msg.text} (reaction)", msg.wamid)
            return
        text = msg.text.strip()
        if text.lower() in HELP_WORDS and msg.kind == "text":
            self._db_state_clear_if(p, ("QUERY", "PARTIAL_CONFIRM", "VOICE_CONFIRM", "GRN_DETAIL"))
            return self._text(p, render.help_text(p, self.roster))
        if msg.context_id:
            ob = self.db.outbound(msg.context_id)
            if ob and self._on_quote(p, msg, ob):
                return
        handler = {"engineer": self._as_engineer, "logistics": self._as_logistics,
                   "approver": self._as_approver, "observer": self._as_observer}[p.role]
        handler(p, msg)

    def _db_state_clear_if(self, p: Person, states: tuple[str, ...]) -> None:
        state, _ = self.db.get_state(p.phone)
        if state in states:
            self.db.set_state(p.phone, "")

    def _unknown_sender(self, msg: Incoming) -> None:
        today = clock.now().date().isoformat()
        key = f"unknown:{msg.phone}"
        self.db.audit(msg.phone, "unknown_sender", "", name=msg.profile_name, text=msg.text[:200])
        if self.db.kv_get(key) != today:
            self.db.kv_set(key, today)
            self.wa.send_text(msg.phone, "This number is not registered with the purchase system. "
                                         "Please ask the office to add you.")

    # ================================================================ sending

    def _text(self, to: Person | str, text: str, kind: str = "info", entity: str = "", reply_to: str = "") -> str:
        phone = to.phone if isinstance(to, Person) else to
        wamid = ""
        for part in render.split_text(text):
            wamid = self.wa.send_text(phone, part, reply_to=reply_to)
            self.db.record_outbound(wamid, phone, kind, entity)
        return wamid

    def _buttons(self, to: Person, body: str, buttons: list[tuple[str, str]], kind: str = "info", entity: str = "") -> str:
        wamid = self.wa.send_buttons(to.phone, body, buttons)
        self.db.record_outbound(wamid, to.phone, kind, entity)
        return wamid

    def _doc(self, to: Person, path: str, caption: str, kind: str = "info", entity: str = "") -> str:
        wamid = self.wa.send_document(to.phone, path, caption=caption)
        self.db.record_outbound(wamid, to.phone, kind, entity)
        return wamid

    def _notify(self, to: Person, summary: str, send) -> bool:
        """Run `send()`; if the person is outside WhatsApp's 24h window, send the
        approved template instead. Tapping its button re-sends what's pending."""
        try:
            send()
            return True
        except WhatsAppError as e:
            if e.code != REENGAGEMENT_ERROR:
                log.error("WhatsApp send to %s failed: %s", to.name, e)
                return False
            try:
                wamid = self.wa.send_template(to.phone, self.s.wa_template_name, self.s.wa_template_lang,
                                              [summary], button_payload="SHOW_PENDING")
                self.db.record_outbound(wamid, to.phone, "template")
            except WhatsAppError as e2:
                log.error("Template to %s failed: %s", to.name, e2)
            return False

    # ================================================================ buttons & quotes

    def _button(self, p: Person, msg: Incoming) -> None:
        action, *args = msg.button_id.split(":")
        if action == "SHOW_PENDING":
            return self._show_pending(p)
        role_actions = {
            "engineer": {"RQ_OK", "RQ_EDIT", "RQ_X", "GR_ALL", "GR_SHORT"},
            "logistics": {"RQ_OK", "RQ_EDIT", "RQ_X", "SL_SEND", "SL_EDIT", "SL_X"},
            "approver": {"AP_YES", "AP_NO", "AP_ASK", "AP_PYES", "AP_PNO"},
        }.get(p.role, set())
        if action not in role_actions:
            return self._text(p, "That button isn't for you.")
        if action.startswith("RQ_"):
            return self._req_button(p, action, int(args[0]))
        if action.startswith("SL_"):
            return self._slip_button(p, action, int(args[0]))
        if action.startswith("GR_"):
            return self._grn_button(p, action, int(args[0]), args[1])
        slip_id, version = int(args[0]), int(args[1])
        if action == "AP_YES":
            return self._approver_decides(p, slip_id, version, Decision(approval.APPROVE_ALL), "✅ Approve all (button)", msg.wamid)
        if action == "AP_NO":
            return self._approver_decides(p, slip_id, version, Decision(approval.REJECT_ALL), "❌ Reject (button)", msg.wamid)
        if action == "AP_ASK":
            self.db.set_state(p.phone, "QUERY", {"slip_id": slip_id, "version": version})
            slip = store.load_slip(self.db, slip_id)
            return self._text(p, f"Type your question about {slip.slip_no} — I'll send it to logistics.")
        if action in ("AP_PYES", "AP_PNO"):
            return self._confirm_pending_decision(p, action == "AP_PYES", msg.wamid)

    def _on_quote(self, p: Person, msg: Incoming, ob) -> bool:
        entity = ob["entity"] or ""
        if p.role == "approver" and entity.startswith("slip:"):
            _, sid, ver = entity.split(":")
            content = self._content(msg) if msg.kind == "audio" else None
            text = content.heard if content else msg.text
            self._approver_text(p, int(sid), int(ver), text, msg.wamid, voice=content is not None)
            return True
        if p.role == "logistics" and ob["kind"] == "query" and entity.startswith("slip:"):
            _, sid, ver = entity.split(":")
            slip = store.load_slip(self.db, int(sid))
            text = self._content(msg).text if msg.kind == "audio" else msg.text
            for a in self.roster.by_role("approver"):
                self._notify(a, f"{p.name} replied about {slip.slip_no}", lambda a=a: self._text(
                    a, f"💬 *{p.name} replied about {slip.slip_no}:*\n{text}\n\n_Reply to this message to answer, "
                       f"or say yes / no to decide._", kind="reply", entity=entity))
            self.db.audit(p.phone, "query_reply", slip.slip_no, text=text)
            self._text(p, f"Sent to {', '.join(a.name for a in self.roster.by_role('approver'))}.")
            return True
        if p.role == "engineer" and ob["kind"] == "grn" and entity.startswith("grn:"):
            _, sid, site = entity.split(":")
            if site == p.site:
                self._grn_detail(p, msg, {"slip_id": int(sid), "site": site})
                return True
        return False

    # ================================================================ content

    def _content(self, msg: Incoming) -> Content:
        if msg.kind == "text":
            return Content(msg.text, [], "text")
        if msg.kind in ("audio", "image", "document"):
            data, mime = self.wa.download_media(msg.media_id)
            mime = (msg.mime or mime or "").split(";")[0]
            ext = {"audio/ogg": "ogg", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
                   "application/pdf": "pdf", "audio/mpeg": "mp3", "audio/mp4": "m4a"}.get(mime, "bin")
            path = Path(self.s.pdf_dir).parent / "media" / f"{re.sub(r'[^A-Za-z0-9]', '_', msg.wamid)[-40:]}.{ext}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            if msg.kind == "audio":
                heard = self.speech.transcribe(data, mime)
                if not heard:
                    raise UserError("🎙 I couldn't hear anything in that voice note. Please try again closer to the phone.")
                return Content(heard, [], "voice", heard=heard, saved_path=str(path))
            if mime.startswith("image/") or mime == "application/pdf":
                return Content(msg.text, [(data, mime)], "image", saved_path=str(path))
            raise UserError("I can read text, voice notes, photos and PDFs. Please send the list in one of those.")
        raise UserError("I can read text, voice notes, photos and PDFs.")

    # ================================================================ engineer

    def _as_engineer(self, p: Person, msg: Incoming) -> None:
        state, data = self.db.get_state(p.phone)
        if state == "GRN_DETAIL":
            return self._grn_detail(p, msg, data)
        t = msg.text.strip().lower()
        if msg.kind == "text":
            if re.fullmatch(r"(stock|stok|maal|inventory)", t):
                return self._text(p, render.stock_text(store.stock_summary(self.db, p.site), self.roster, p.site))
            if re.match(r"^(used|use|consumed|kharch|lagaya|lag gaya)\b", t):
                return self._usage(p, msg.text)
            if re.fullmatch(r"(status|my requests|pending|requests)", t):
                return self._engineer_status(p)
            if re.fullmatch(r"(receive|received|deliveries|delivery|mila|aa gaya|aagaya)", t):
                return self._deliveries_due(p)
        self._requisition_input(p, msg, p.site, p)

    def _requisition_input(self, sender: Person, msg: Incoming, site_code: str, engineer: Person | None,
                           content: Content | None = None) -> None:
        content = content or self._content(msg)
        eng_phone = engineer.phone if engineer else f"site:{site_code}"
        eng_name = engineer.name if engineer else f"{self.roster.site_name(site_code)} site"
        draft_id = store.draft_requisition_id(self.db, eng_phone, sender.phone)
        if draft_id:
            draft = store.load_requisition(self.db, draft_id)
            if draft.site_code != site_code:
                self.db.run("UPDATE requisitions SET status = 'CANCELLED' WHERE id = ?", (draft_id,))
                draft_id, draft = None, None
        else:
            draft = None
        current = [ParsedItem(i.name, i.item_key, i.qty, i.unit, i.spec) for i in draft.items] if draft else None
        parsed = self.parser.parse_requisition(content.text, self.roster.site_name(site_code),
                                               store.known_item_keys(self.db), current, content.attachments)
        if not parsed.items:
            if draft:
                return self._text(sender, "I couldn't see any change to your list in that. Send e.g. \"cement 60 bag\" "
                                          "or \"remove sand\", or tap ✅ Confirm on the list above.")
            hint = ("\n\nNot understood: " + "; ".join(f"\"{u}\"" for u in parsed.unclear[:3])) if parsed.unclear else ""
            return self._text(sender, "I couldn't find any materials in that message.\n"
                                      "Send like:\n_Cement 50 bag_\n_Sariya 12mm 2 ton_\n_Balu 3 truck_"
                                      "\nOr send a voice note / photo of the list." + hint)
        now = clock.now_iso()
        with self.db.transaction():
            if draft_id is None:
                draft_id = self.db.run(
                    "INSERT INTO requisitions(site_code, engineer_phone, engineer_name, entered_by_phone, status, source, "
                    "raw_text, needed_by, urgent, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (site_code, eng_phone, eng_name, sender.phone, DRAFT, content.source, content.text,
                     parsed.needed_by, int(parsed.urgent), now, now),
                )
            else:
                self.db.run(
                    "UPDATE requisitions SET raw_text = raw_text || char(10) || '---' || char(10) || ?, "
                    "needed_by = CASE WHEN ? != '' THEN ? ELSE needed_by END, urgent = MAX(urgent, ?), "
                    "updated_at = ?, reminded_at = NULL WHERE id = ?",
                    (content.text, parsed.needed_by, parsed.needed_by, int(parsed.urgent), now, draft_id),
                )
                self.db.run("DELETE FROM req_items WHERE requisition_id = ?", (draft_id,))
            for n, it in enumerate(parsed.items, start=1):
                self.db.run(
                    "INSERT INTO req_items(requisition_id, line_no, name, item_key, qty, unit, spec) VALUES (?,?,?,?,?,?,?)",
                    (draft_id, n, it.name, it.item_key or norm_key(it.name), it.qty, norm_unit(it.unit), it.spec),
                )
            if content.saved_path:
                self.db.run("UPDATE requisitions SET media_link = ? WHERE id = ?", (content.saved_path, draft_id))
        if content.saved_path and self.gsync:
            month = clock.now().strftime("%Y-%m")
            enqueue(self.db, "file", f"{content.saved_path}|Originals/{self.roster.site_name(site_code)}/{month}")
        req = store.load_requisition(self.db, draft_id)
        self.db.audit(sender.phone, "req_draft", f"req:{draft_id}", source=content.source, items=len(req.items))
        card = render.req_card(req, self.roster, heard=content.heard, unclear=parsed.unclear, note=parsed.note)
        self._text(sender, card, kind="req", entity=f"req:{draft_id}")
        self._buttons(sender, "Is this list correct? You can also just send changes, e.g. \"cement 60 bag\" or \"remove sand\".",
                      [(f"RQ_OK:{draft_id}", "✅ Confirm"), (f"RQ_EDIT:{draft_id}", "✏️ Change"), (f"RQ_X:{draft_id}", "❌ Cancel")],
                      kind="req", entity=f"req:{draft_id}")

    def _req_button(self, p: Person, action: str, req_id: int) -> None:
        req = store.load_requisition(self.db, req_id)
        if req is None or p.phone not in (req.engineer_phone, req.entered_by_phone):
            return self._text(p, "That list isn't yours.")
        if req.status != DRAFT:
            return self._text(p, f"This list was already {'sent as ' + req.req_no if req.req_no else req.status.lower()}.")
        if action == "RQ_EDIT":
            return self._text(p, "OK — send the changes, e.g. \"cement 60 bag\", \"remove sand\", or the full list again.")
        if action == "RQ_X":
            self.db.run("UPDATE requisitions SET status = 'CANCELLED', updated_at = ? WHERE id = ?", (clock.now_iso(), req_id))
            self.db.audit(p.phone, "req_cancel", f"req:{req_id}")
            return self._text(p, "❌ List cancelled. Send a new one any time.")
        self._submit_requisition(p, req)

    def _submit_requisition(self, p: Person, req) -> None:
        site = self.roster.site(req.site_code)
        now = clock.now_iso()
        with self.db.transaction():
            req_no = f"REQ-{site.code}-{self.db.next_counter(f'req:{site.code}'):04d}"
            for it in req.items:
                ref = f"{site.letter}{self.db.next_counter(f'ref:{site.code}')}"
                self.db.run("UPDATE req_items SET ref = ? WHERE id = ?", (ref, it.id))
            self.db.run("UPDATE requisitions SET req_no = ?, status = 'SUBMITTED', submitted_at = ?, updated_at = ? WHERE id = ?",
                        (req_no, now, now, req.id))
        req = store.load_requisition(self.db, req.id)
        self.db.audit(p.phone, "req_submit", req_no, items=len(req.items))
        enqueue(self.db, "req", req.id)
        logistics = self.roster.by_role("logistics")
        self._text(p, f"✅ Sent to {', '.join(l.name for l in logistics) or 'logistics'} as *{req_no}*.\n"
                      "You'll get a message when the material is dispatched.")
        card = render.req_card(req, self.roster)
        who = f"from {req.engineer_name}" + (" (entered by you)" if req.entered_by_logistics else "")
        for l in logistics:
            if l.phone == p.phone:
                continue
            self._notify(l, f"New requirement {req_no} from {self.roster.site_name(req.site_code)}",
                         lambda l=l: self._text(l, f"📥 *New requirement {who}*\n\n{card}\n\nReply *list* to see all open items.",
                                                kind="req", entity=f"req:{req.id}"))
        if req.entered_by_logistics:
            for e in self.roster.engineers_for(req.site_code):
                self._notify(e, f"Requirement {req_no} entered for your site",
                             lambda e=e: self._text(e, f"ℹ️ {p.name} entered this requirement for your site:\n\n{card}"))

    def _engineer_status(self, p: Person) -> None:
        rows = self.db.q(
            "SELECT ri.ref, ri.name, ri.qty, ri.unit, ri.status, r.req_no FROM req_items ri "
            "JOIN requisitions r ON r.id = ri.requisition_id WHERE r.site_code = ? AND r.status = 'SUBMITTED' "
            "ORDER BY ri.id DESC LIMIT 40", (p.site,))
        if not rows:
            return self._text(p, "No open requirements for your site.")
        label = {"OPEN": "⏳ waiting for slip", "IN_SLIP": "🧾 waiting for approval", "ORDERED": "✅ approved",
                 "REJECTED": "❌ not approved", "CANCELLED": "cancelled"}
        lines = [f"📋 *{self.roster.site_name(p.site)} – open requirements*"]
        lines += [f"{r['ref']} {r['name']} {qty(r['qty'])} {r['unit']} — {label.get(r['status'], r['status'])}" for r in rows]
        self._text(p, "\n".join(lines))

    # ================================================================ logistics

    def _as_logistics(self, p: Person, msg: Incoming) -> None:
        content = self._content(msg) if msg.kind != "text" else None
        text = (content.text if content else msg.text).strip()
        t = text.lower()
        m = re.match(r"^\s*([a-z ]{3,20})\s*:\s*(.+)$", text, re.IGNORECASE | re.DOTALL)
        site = self.roster.find_site(m.group(1)) if m else None
        if site:
            engineers = self.roster.engineers_for(site.code)
            body = Content(m.group(2), content.attachments if content else [], content.source if content else "text",
                           heard=content.heard if content else "", saved_path=content.saved_path if content else "")
            return self._requisition_input(p, msg, site.code, engineers[0] if engineers else None, content=body)
        if content and content.source == "image" and not store.draft_slip_id(self.db, p.phone):
            raise UserError("Is this a site's requirement list? Send the photo again with a caption like *Nicobar:*")
        if re.fullmatch(r"(list|open|pending|items|requirements?)( pdf)?", t):
            return self._open_list(p)
        if re.match(r"^(dispatch|dispatched|shipped|sent|loaded)\b", t):
            return self._dispatch(p, text)
        if re.match(r"^(edit|change|revise|withdraw)\b", t) and approval.find_slip_number(t):
            return self._withdraw_slip(p, approval.find_slip_number(t))
        if re.fullmatch(r"(slips|status)", t):
            return self._slip_status(p)
        if re.fullmatch(r"(stock|stok)", t):
            return self._text(p, render.stock_text(store.stock_summary(self.db), self.roster))
        self._slip_input(p, text)

    def _open_list(self, p: Person) -> None:
        items = store.open_items(self.db)
        self._text(p, render.open_list(items, self.roster))
        if items:
            path = Path(self.s.pdf_dir) / "lists" / f"requirements-{clock.now().strftime('%Y%m%d-%H%M')}.pdf"
            render_requirements_pdf(items, self.roster, path)
            self._doc(p, str(path), "Open requirements by site — for the market")

    def _slip_input(self, p: Person, text: str) -> None:
        draft_id = store.draft_slip_id(self.db, p.phone)
        draft = store.load_slip(self.db, draft_id) if draft_id else None
        open_items = store.open_items(self.db)
        current = None
        if draft:
            current = [ParsedSlipLine(l.ref or "", l.site_code, l.name, l.item_key, l.qty, l.unit, l.vendor, l.rate)
                       for l in draft.lines]
            # items already on this draft are still "open" for the parser's purposes
            open_refs = {it["ref"] for it in open_items}
            for l in draft.lines:
                if l.ref and l.ref not in open_refs:
                    it = store.item_by_ref(self.db, l.ref)
                    if it:
                        open_items.append({**it, "by_logistics": it["by_logistics"]})
        if not open_items and not current and not re.search(r"\d", text):
            return self._text(p, "There are no open requirements right now, and that didn't look like a purchase line.\n"
                                 "Send *help* to see what I can do.")
        vendors = [v.name for v in self.roster.vendors] + sorted(store.known_vendor_names(self.db))
        parsed = self.parser.parse_slip(text, open_items, vendors, [(s.code, s.name) for s in self.roster.sites],
                                        store.known_item_keys(self.db), current)
        lines, problems = self._validate_slip_lines(parsed.lines, draft_id)
        problems += [f"Not understood: \"{u}\"" for u in parsed.unclear[:5]]
        if not lines:
            msg = "I couldn't build a purchase slip from that."
            if problems:
                msg += "\n\n" + "\n".join(f"• {x}" for x in problems)
            msg += "\n\nFormat: _N17 N18 Om Traders 420_ (refs from *list*, vendor, rate per unit)"
            return self._text(p, msg)
        now = clock.now_iso()
        with self.db.transaction():
            if draft_id is None:
                no = store.slip_no(self.db.next_counter("slip"))
                draft_id = self.db.run(
                    "INSERT INTO slips(slip_no, status, prepared_by_phone, prepared_by_name, raw_text, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?)", (no, DRAFT, p.phone, p.name, text, now, now))
            else:
                self.db.run("UPDATE slips SET raw_text = raw_text || char(10) || '---' || char(10) || ?, updated_at = ? "
                            "WHERE id = ?", (text, now, draft_id))
                self.db.run("DELETE FROM slip_lines WHERE slip_id = ?", (draft_id,))
            for n, l in enumerate(lines, start=1):
                self.db.run(
                    "INSERT INTO slip_lines(slip_id, line_no, site_code, req_item_id, name, item_key, qty, unit, vendor, rate, "
                    "amount, requested_qty, last_rate, last_rate_date, last_vendor, flags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (draft_id, n, l["site_code"], l["req_item_id"], l["name"], l["item_key"], l["qty"], l["unit"],
                     l["vendor"], l["rate"], l["amount"], l["requested_qty"], l["last_rate"], l["last_rate_date"],
                     l["last_vendor"], l["flags"]),
                )
        slip = store.load_slip(self.db, draft_id)
        self.db.audit(p.phone, "slip_draft", slip.slip_no, lines=len(slip.lines), total=slip.total)
        body = render.slip_text(slip, self.roster, "draft")
        if parsed.note:
            body = f"_{parsed.note}_\n\n" + body
        if problems:
            body += "\n\n❓ " + "\n❓ ".join(problems)
        self._text(p, body, kind="slip", entity=f"slip:{slip.id}:{slip.version}")
        self._buttons(p, render.slip_short(slip) + "\n\nSend more lines or changes, or send it for approval.",
                      [(f"SL_SEND:{slip.id}", "📤 Send for approval"), (f"SL_EDIT:{slip.id}", "✏️ Change"),
                       (f"SL_X:{slip.id}", "🗑 Discard")], kind="slip", entity=f"slip:{slip.id}:{slip.version}")

    def _validate_slip_lines(self, parsed: list[ParsedSlipLine], slip_id: int | None) -> tuple[list[dict], list[str]]:
        out: list[dict] = []
        problems: list[str] = []
        seen_refs: set[str] = set()
        known_vendors = store.known_vendor_names(self.db)
        for pl in parsed:
            item = None
            if pl.ref:
                item = store.item_by_ref(self.db, pl.ref)
                in_this_draft = item and slip_id and self.db.one(
                    "SELECT 1 FROM slip_lines WHERE slip_id = ? AND req_item_id = ?", (slip_id, item["id"]))
                if not item or item["req_status"] != "SUBMITTED" or (item["status"] != "OPEN" and not in_this_draft):
                    problems.append(f"{pl.ref} is not an open requirement (see *list*)")
                    continue
                if pl.ref in seen_refs:
                    problems.append(f"{pl.ref} appears twice — kept the first")
                    continue
                seen_refs.add(pl.ref)
            site_code = item["site_code"] if item else pl.site_code
            if not self.roster.site(site_code):
                problems.append(f"Which site is \"{pl.name}\" for? Add the site name, e.g. \"{pl.name} Nicobar ...\"")
                continue
            name = pl.name or (item["name"] if item else "")
            unit = norm_unit(pl.unit or (item["unit"] if item else "nos"))
            key = (item["item_key"] if item and (not pl.item_key or pl.item_key == item["item_key"]) else pl.item_key) or norm_key(name)
            q = pl.qty or (item["qty"] if item else 0)
            if q <= 0:
                problems.append(f"Quantity missing for \"{name}\"")
                continue
            rate = pl.rate if pl.rate > 0 else (pl.lump_sum / q if pl.lump_sum > 0 else 0)
            if rate <= 0:
                problems.append(f"Rate missing for \"{name}\"")
                continue
            if not pl.vendor.strip():
                problems.append(f"Vendor missing for \"{name}\"")
                continue
            vendor_match = self.roster.match_vendor(pl.vendor)
            vendor = vendor_match.name if vendor_match else pl.vendor.strip().title()
            flags: list[Flag] = []
            last = store.last_approved_rate(self.db, key, unit, exclude_slip=slip_id)
            if last and rate > last["rate"] * (1 + self.s.price_alert_pct / 100):
                pct = (rate / last["rate"] - 1) * 100
                flags.append(Flag("PRICE_UP", f"Rate {inr(rate)} is {pct:.1f}% above last {inr(last['rate'])} "
                                              f"({last['vendor']}, {clock.fmt(last['decided_at'], with_time=False)})"))
            requested = item["qty"] if item else None
            if item and unit == norm_unit(item["unit"]) and q > item["qty"] + 1e-9:
                flags.append(Flag("QTY_OVER", f"Buying {qty(q)} {unit}; site asked for {qty(item['qty'])}"))
            if not item:
                flags.append(Flag("NOT_REQUESTED", "Not requested by any site engineer"))
            if not vendor_match and vendor.lower() not in known_vendors:
                flags.append(Flag("NEW_VENDOR", f"New vendor \"{vendor}\" — not on the approved vendor list"))
            recent = store.recent_purchase(self.db, key, site_code, self.s.recent_purchase_days, exclude_slip=slip_id)
            if recent:
                flags.append(Flag("RECENT_PURCHASE", f"Already bought {qty(recent['qty'])} {recent['unit']} for "
                                                     f"{self.roster.site_name(site_code)} on "
                                                     f"{clock.fmt(recent['decided_at'], with_time=False)} ({recent['slip_no']})"))
            if item and item["by_logistics"]:
                flags.append(Flag("ENTERED_BY_LOGISTICS", "Requirement was entered by logistics, not by the site engineer"))
            out.append({
                "site_code": site_code, "req_item_id": item["id"] if item else None, "name": name, "item_key": key,
                "qty": q, "unit": unit, "vendor": vendor, "rate": round(rate, 2), "amount": round(q * rate, 2),
                "requested_qty": requested, "last_rate": last["rate"] if last else None,
                "last_rate_date": last["decided_at"] if last else None, "last_vendor": last["vendor"] if last else None,
                "flags": json.dumps([f.to_dict() for f in flags], ensure_ascii=False),
            })
        # group lines by site so the slip reads site by site
        order = {s.code: i for i, s in enumerate(self.roster.sites)}
        out.sort(key=lambda l: order.get(l["site_code"], 99))
        return out, problems

    def _slip_button(self, p: Person, action: str, slip_id: int) -> None:
        slip = store.load_slip(self.db, slip_id)
        if slip is None or slip.prepared_by_phone != p.phone:
            return self._text(p, "That slip isn't yours.")
        if slip.status != DRAFT:
            return self._text(p, f"{slip.slip_no} is already {slip.status.lower()}.")
        if action == "SL_EDIT":
            return self._text(p, "Send the change, e.g. \"N17 rate 410\", \"remove line 3\", \"N20 Hira Metals 58\".")
        if action == "SL_X":
            self.db.run("UPDATE slips SET status = 'CANCELLED', updated_at = ? WHERE id = ?", (clock.now_iso(), slip_id))
            self.db.audit(p.phone, "slip_discard", slip.slip_no)
            return self._text(p, f"🗑 {slip.slip_no} discarded.")
        self._submit_slip(p, slip)

    def _submit_slip(self, p: Person, slip: Slip) -> None:
        now = clock.now_iso()
        version = slip.version + (1 if slip.submitted_at else 0)
        with self.db.transaction():
            self.db.run("UPDATE slips SET status = 'PENDING', version = ?, submitted_at = ?, updated_at = ?, "
                        "reminded_at = NULL, reminder_count = 0 WHERE id = ?", (version, now, now, slip.id))
            for l in slip.lines:
                if l.req_item_id:
                    self.db.run("UPDATE req_items SET status = 'IN_SLIP' WHERE id = ?", (l.req_item_id,))
        slip = store.load_slip(self.db, slip.id)
        path = Path(self.s.pdf_dir) / f"{slip.slip_no}_v{slip.version}_PENDING.pdf"
        render_slip_pdf(slip, self.roster, path)
        self.db.run("UPDATE slips SET pdf_path = ? WHERE id = ?", (str(path), slip.id))
        self.db.audit(p.phone, "slip_submit", slip.slip_no, version=slip.version, total=slip.total)
        enqueue(self.db, "slip", slip.id)
        approvers = self.roster.by_role("approver")
        for a in approvers:
            self._send_approval_card(a, slip, str(path))
        self._text(p, f"📤 *{slip.slip_no}* ({inr(slip.total)}) sent to {', '.join(a.name for a in approvers)} for approval.")

    def _send_approval_card(self, a: Person, slip: Slip, pdf_path: str, prefix: str = "") -> None:
        entity = f"slip:{slip.id}:{slip.version}"

        def send():
            self._doc(a, pdf_path, f"{slip.slip_no} — for your approval", kind="approval", entity=entity)
            self._text(a, (prefix + "\n\n" if prefix else "") + render.slip_text(slip, self.roster, "for your approval"),
                       kind="approval", entity=entity)
            self._buttons(a, render.approval_prompt(slip),
                          [(f"AP_YES:{slip.id}:{slip.version}", "✅ Approve all"),
                           (f"AP_NO:{slip.id}:{slip.version}", "❌ Reject"),
                           (f"AP_ASK:{slip.id}:{slip.version}", "❓ Ask logistics")],
                          kind="approval", entity=entity)

        self._notify(a, f"Purchase slip {slip.slip_no} ({inr(slip.total)}) is waiting for your approval", send)

    def _withdraw_slip(self, p: Person, number: int) -> None:
        slip = store.slip_by_number(self.db, number)
        if slip is None:
            return self._text(p, f"No slip PS-{number:04d}.")
        if slip.status == DRAFT:
            return self._text(p, f"{slip.slip_no} is already a draft — send your changes.")
        if slip.status != PENDING:
            return self._text(p, f"{slip.slip_no} is {slip.status.lower()} and can't be changed. Make a new slip instead.")
        if store.draft_slip_id(self.db, p.phone):
            return self._text(p, "You already have a draft slip open. Send it or discard it first.")
        with self.db.transaction():
            self.db.run("UPDATE slips SET status = 'DRAFT', updated_at = ? WHERE id = ?", (clock.now_iso(), slip.id))
            for l in slip.lines:
                if l.req_item_id:
                    self.db.run("UPDATE req_items SET status = 'OPEN' WHERE id = ?", (l.req_item_id,))
        self.db.audit(p.phone, "slip_withdraw", slip.slip_no)
        for a in self.roster.by_role("approver"):
            self._notify(a, f"{slip.slip_no} withdrawn by {p.name}",
                         lambda a=a: self._text(a, f"↩️ {p.name} pulled back *{slip.slip_no}* to make changes. "
                                                   "Ignore the earlier copy — a revised one will follow."))
        self._text(p, f"✏️ {slip.slip_no} is a draft again. Send your changes, then tap 📤 Send for approval.")

    def _slip_status(self, p: Person) -> None:
        rows = self.db.q("SELECT id FROM slips WHERE status != 'CANCELLED' ORDER BY id DESC LIMIT 10")
        if not rows:
            return self._text(p, "No slips yet.")
        icon = {DRAFT: "✏️", PENDING: "⏳", APPROVED: "✅", PARTIAL: "🟡", REJECTED: "❌"}
        lines = ["🧾 *Recent slips*"]
        for r in rows:
            s = store.load_slip(self.db, r["id"])
            recv = sum(1 for l in s.lines if l.received_qty is not None)
            appr = sum(1 for l in s.lines if l.status == "APPROVED")
            extra = f" · delivered {recv}/{appr}" if s.status in (APPROVED, PARTIAL) else ""
            lines.append(f"{icon.get(s.status, '')} {s.slip_no} {s.status.lower()} · {inr(s.total)}{extra}")
        self._text(p, "\n".join(lines))

    # ================================================================ approver

    def _as_approver(self, p: Person, msg: Incoming) -> None:
        state, data = self.db.get_state(p.phone)
        voice = msg.kind == "audio"
        if voice:
            text = self._content(msg).heard
        elif msg.kind == "text":
            text = msg.text.strip()
        else:
            return self._text(p, "I can read your text and voice replies. Please reply in text, or tap a button.")
        t = text.lower()
        if state == "QUERY":
            self.db.set_state(p.phone, "")
            slip = store.load_slip(self.db, data["slip_id"])
            d = approval.read_decision(text, len(slip.lines))
            if d.kind in (approval.APPROVE_ALL, approval.REJECT_ALL, approval.PARTIAL):
                return self._approver_text(p, slip.id, data["version"], text, msg.wamid, voice)
            return self._relay_query(p, data["slip_id"], data["version"], text)
        if state in ("PARTIAL_CONFIRM", "VOICE_CONFIRM"):
            d = approval.read_decision(text, 1)
            if d.kind in (approval.APPROVE_ALL, approval.REJECT_ALL):
                return self._confirm_pending_decision(p, d.kind == approval.APPROVE_ALL, msg.wamid)
            self.db.set_state(p.phone, "")
        if re.fullmatch(r"(pending|slips|baki|baaki)", t):
            return self._show_pending(p)
        if re.fullmatch(r"(report|summary|hisab|hisaab|spend)", t):
            return self._text(p, self._report())
        number = approval.find_slip_number(text)
        if number is not None:
            slip = store.slip_by_number(self.db, number)
            if slip is None:
                return self._text(p, f"There's no slip PS-{number:04d}.")
            return self._approver_text(p, slip.id, slip.version, approval.strip_slip_ref(text), msg.wamid, voice)
        pending = store.pending_slips(self.db)
        if len(pending) == 1:
            return self._approver_text(p, pending[0].id, pending[0].version, text, msg.wamid, voice)
        if not pending:
            return self._text(p, "Nothing is waiting for your approval right now. Send *report* for this month's spend.")
        listing = "\n".join(f"• {s.slip_no} — {inr(s.total)}" for s in pending)
        self._text(p, f"{len(pending)} slips are waiting:\n{listing}\n\n"
                      "Please *reply on the slip's message* (swipe right on it), or include the number, e.g. *yes PS-42*.")

    def _approver_text(self, p: Person, slip_id: int, version: int, text: str, ref: str, voice: bool = False) -> None:
        slip = store.load_slip(self.db, slip_id)
        decision = approval.read_decision(text, len(slip.lines))
        if decision.kind == approval.QUERY:
            return self._relay_query(p, slip_id, version, text)
        if voice:
            # Speech-to-text can mishear "haan"/"nahi"; voice decisions always get a confirm tap.
            return self._ask_confirm(p, slip, version, decision, text, ref, voice=True)
        self._approver_decides(p, slip_id, version, decision, text, ref)

    def _approver_decides(self, p: Person, slip_id: int, version: int, d: Decision, text: str, ref: str) -> None:
        slip = store.load_slip(self.db, slip_id)
        if slip is None:
            return self._text(p, "I can't find that slip.")
        if slip.status == DRAFT:
            return self._text(p, f"{slip.slip_no} was pulled back by logistics for changes. "
                                 "Nothing was approved; a revised slip will come to you.")
        if slip.status != PENDING:
            when = f" on {clock.fmt(slip.decided_at)}" if slip.decided_at else ""
            by = f" by {slip.decided_by_name}" if slip.decided_by_name else ""
            return self._text(p, f"{slip.slip_no} is already *{slip.status.lower()}*{by}{when}. Nothing changed.")
        if version != slip.version:
            self._text(p, f"⚠️ {slip.slip_no} was changed after that message. Here is the latest version:")
            return self._send_approval_card(p, slip, slip.pdf_path or "")
        if d.kind == approval.AMBIGUOUS:
            return self._text(p, f"I couldn't read that safely for {slip.slip_no}. Please reply *yes*, *no*, "
                                 "or e.g. *3 nahi* / *only 1 2*.")
        if d.kind == approval.PARTIAL:
            return self._ask_confirm(p, slip, version, d, text, ref)
        approve = set(range(1, len(slip.lines) + 1)) if d.kind == approval.APPROVE_ALL else set()
        self._finalize(p, slip, approve, text, ref)

    def _ask_confirm(self, p: Person, slip: Slip, version: int, d: Decision, text: str, ref: str, voice: bool = False) -> None:
        if d.kind == approval.AMBIGUOUS:
            return self._text(p, f"🎙 I heard: \"{text}\"\nI couldn't read that as a decision. Please reply yes / no.")
        lines = set(range(1, len(slip.lines) + 1))
        approve = lines if d.kind == approval.APPROVE_ALL else (set() if d.kind == approval.REJECT_ALL else d.approve)
        reject = lines - approve
        self.db.set_state(p.phone, "VOICE_CONFIRM" if voice else "PARTIAL_CONFIRM",
                          {"slip_id": slip.id, "version": version, "approve": sorted(approve), "text": text, "ref": ref})
        amt_ok = sum(l.amount for l in slip.lines if l.line_no in approve)
        amt_no = sum(l.amount for l in slip.lines if l.line_no in reject)
        body = (f"🎙 I heard: \"{text}\"\n\n" if voice else "") + f"*{slip.slip_no}* — please confirm:\n"
        if approve:
            body += f"✅ Approve line {', '.join(map(str, sorted(approve)))} ({inr(amt_ok)})\n"
        if reject:
            body += f"❌ Reject line {', '.join(map(str, sorted(reject)))} ({inr(amt_no)})\n"
        self._buttons(p, body, [(f"AP_PYES:{slip.id}:{version}", "✅ Confirm"), (f"AP_PNO:{slip.id}:{version}", "↩️ Cancel")],
                      kind="confirm")

    def _confirm_pending_decision(self, p: Person, yes: bool, wamid: str) -> None:
        state, data = self.db.get_state(p.phone)
        self.db.set_state(p.phone, "")
        if state not in ("PARTIAL_CONFIRM", "VOICE_CONFIRM"):
            return self._text(p, "There's nothing waiting for confirmation.")
        if not yes:
            slip = store.load_slip(self.db, data["slip_id"])
            return self._text(p, f"↩️ Cancelled. {slip.slip_no} is still waiting — reply on it when ready.")
        slip = store.load_slip(self.db, data["slip_id"])
        if slip.status != PENDING or slip.version != data["version"]:
            return self._text(p, f"{slip.slip_no} changed in the meantime; nothing was done. Reply on the latest copy.")
        self._finalize(p, slip, set(data["approve"]), data["text"], data["ref"] or wamid)

    def _finalize(self, p: Person, slip: Slip, approve: set[int], text: str, ref: str) -> None:
        now = clock.now_iso()
        all_lines = {l.line_no for l in slip.lines}
        status = APPROVED if approve == all_lines else (REJECTED if not approve else PARTIAL)
        with self.db.transaction():
            for l in slip.lines:
                ok = l.line_no in approve
                self.db.run("UPDATE slip_lines SET status = ? WHERE id = ?", ("APPROVED" if ok else "REJECTED", l.id))
                if l.req_item_id:
                    self.db.run("UPDATE req_items SET status = ? WHERE id = ?", ("ORDERED" if ok else "REJECTED", l.req_item_id))
            self.db.run("UPDATE slips SET status = ?, decided_at = ?, decided_by_phone = ?, decided_by_name = ?, "
                        "decision_ref = ?, decision_text = ?, updated_at = ? WHERE id = ?",
                        (status, now, p.phone, p.name, ref, text, now, slip.id))
        slip = store.load_slip(self.db, slip.id)
        if status != REJECTED:
            sig = self.signer.sign(canonical(self.signed_payload(slip)))
            self.db.run("UPDATE slips SET signature = ?, verify_code = ? WHERE id = ?", (sig, verify_code(sig), slip.id))
            slip = store.load_slip(self.db, slip.id)
        path = Path(self.s.pdf_dir) / f"{slip.slip_no}_{status}.pdf"
        render_slip_pdf(slip, self.roster, path, verify_url=self.verify_url(slip) if slip.verify_code else "")
        self.db.run("UPDATE slips SET pdf_path = ? WHERE id = ?", (str(path), slip.id))
        self._close_finished_requisitions(slip)
        self.db.audit(p.phone, f"slip_{status.lower()}", slip.slip_no, approved_lines=sorted(approve),
                      approved_total=slip.approved_total, reply=text, wamid=ref)
        enqueue(self.db, "slip", slip.id)
        self._announce_decision(p, slip, str(path))

    def signed_payload(self, slip: Slip) -> dict:
        return {
            "company": self.roster.company.name,
            "slip_no": slip.slip_no,
            "version": slip.version,
            "prepared_by": slip.prepared_by_name,
            "decided_by": slip.decided_by_name,
            "decided_by_phone": slip.decided_by_phone,
            "decided_at": slip.decided_at,
            "decision_ref": slip.decision_ref,
            "lines": [{"n": l.line_no, "site": l.site_code, "item": l.name, "qty": l.qty, "unit": l.unit,
                       "vendor": l.vendor, "rate": l.rate, "amount": l.amount, "status": l.status} for l in slip.lines],
            "approved_total": slip.approved_total,
        }

    def verify_url(self, slip: Slip) -> str:
        return f"{self.s.public_base_url.rstrip('/')}/verify/{slip.slip_no}?c={slip.verify_code}"

    def _close_finished_requisitions(self, slip: Slip) -> None:
        req_ids = {r["requisition_id"] for r in self.db.q(
            "SELECT DISTINCT ri.requisition_id FROM slip_lines sl JOIN req_items ri ON ri.id = sl.req_item_id WHERE sl.slip_id = ?",
            (slip.id,))}
        for rid in req_ids:
            open_left = self.db.one("SELECT COUNT(*) AS n FROM req_items WHERE requisition_id = ? AND status IN ('OPEN','IN_SLIP')", (rid,))
            if open_left["n"] == 0:
                self.db.run("UPDATE requisitions SET status = 'CLOSED', updated_at = ? WHERE id = ?", (clock.now_iso(), rid))
            enqueue(self.db, "req", rid)

    def _announce_decision(self, p: Person, slip: Slip, pdf_path: str) -> None:
        rejected = [l for l in slip.lines if l.status == "REJECTED"]
        if slip.status == REJECTED:
            headline = f"❌ *{slip.slip_no} REJECTED* by {p.name}"
        elif slip.status == PARTIAL:
            headline = f"🟡 *{slip.slip_no} PARTLY APPROVED* by {p.name} — {inr(slip.approved_total)} of {inr(slip.total)}"
        else:
            headline = f"✅ *{slip.slip_no} APPROVED* by {p.name} — {inr(slip.approved_total)}"
        detail = headline
        if slip.decision_text and "(button)" not in slip.decision_text:
            detail += f"\nReply: \"{slip.decision_text}\""
        if rejected and slip.status == PARTIAL:
            detail += "\n\nNot approved — do *not* buy:\n" + "\n".join(f"❌ {l.line_no}. {l.name} ({l.vendor})" for l in rejected)
        if slip.verify_code:
            detail += f"\n\nVerification code: *{slip.verify_code}*"
        caption = f"{slip.slip_no} — {slip.status.lower()}" + (f" · code {slip.verify_code}" if slip.verify_code else "")

        self._text(p, f"Done. {headline}\nThe signed slip has gone to logistics.")
        self._doc(p, pdf_path, caption)
        for l in self.roster.by_role("logistics"):
            msg = detail + ("\n\nBuy only what is approved, from the vendors listed. When loaded, send "
                            f"*dispatch {slip.slip_no} <site> <vessel/vehicle>*." if slip.status != REJECTED else "")
            self._notify(l, f"{slip.slip_no} was {slip.status.lower()}", lambda l=l, msg=msg: (
                self._text(l, msg, kind="decision", entity=f"slip:{slip.id}:{slip.version}"),
                self._doc(l, pdf_path, caption)))
        for o in self.roster.by_role("observer") + [a for a in self.roster.by_role("approver") if a.phone != p.phone]:
            self._notify(o, f"{slip.slip_no} was {slip.status.lower()}", lambda o=o: (
                self._text(o, detail), self._doc(o, pdf_path, caption)))
        for site in slip.sites():
            lines = slip.lines_for_site(site)
            ok = [l for l in lines if l.status == "APPROVED"]
            no = [l for l in lines if l.status == "REJECTED" and l.req_item_id]
            if not ok and not no:
                continue
            parts = [f"🧾 *{slip.slip_no}* update for {self.roster.site_name(site)}:"]
            parts += [f"✅ {l.ref or ''} {l.name} {qty(l.qty)} {l.unit} — approved for purchase" for l in ok]
            parts += [f"❌ {l.ref or ''} {l.name} — not approved" for l in no]
            for e in self.roster.engineers_for(site):
                self._notify(e, f"Update on your requirements ({slip.slip_no})", lambda e=e, t="\n".join(parts): self._text(e, t))

    def _relay_query(self, p: Person, slip_id: int, version: int, text: str) -> None:
        slip = store.load_slip(self.db, slip_id)
        entity = f"slip:{slip.id}:{slip.version}"
        logistics = self.roster.by_role("logistics")
        for l in logistics:
            self._notify(l, f"{p.name} has a question about {slip.slip_no}", lambda l=l: self._text(
                l, f"❓ *{p.name} asks about {slip.slip_no}:*\n{text}\n\n_Reply to this message to answer. "
                   f"To change the slip, send *edit {slip.slip_no}*._", kind="query", entity=entity))
        self.db.audit(p.phone, "query", slip.slip_no, text=text)
        sent = f"📨 Sent to {', '.join(l.name for l in logistics) or 'logistics'}: \"{text}\""
        if slip.status == PENDING:
            sent += f"\n{slip.slip_no} is still waiting for your decision."
        self._text(p, sent)

    def _show_pending(self, p: Person) -> None:
        if p.role in ("approver", "observer"):
            pending = store.pending_slips(self.db)
            if not pending:
                return self._text(p, "✅ Nothing is waiting for approval.")
            if p.role == "observer":
                return self._text(p, "⏳ Waiting for approval:\n" + "\n".join(f"• {s.slip_no} — {inr(s.total)}" for s in pending))
            for s in pending:
                self._send_approval_card(p, s, s.pdf_path or "")
            return
        if p.role == "logistics":
            draft_id = store.draft_slip_id(self.db, p.phone)
            if draft_id:
                self._text(p, render.slip_text(store.load_slip(self.db, draft_id), self.roster, "draft (not sent yet)"))
            return self._open_list(p)
        draft_id = store.draft_requisition_id(self.db, p.phone, p.phone)
        if draft_id:
            req = store.load_requisition(self.db, draft_id)
            self._text(p, render.req_card(req, self.roster))
            self._buttons(p, "This list hasn't been sent yet.", [(f"RQ_OK:{draft_id}", "✅ Confirm"), (f"RQ_X:{draft_id}", "❌ Cancel")],
                          kind="req", entity=f"req:{draft_id}")
        self._deliveries_due(p, quiet=bool(draft_id))

    def _as_observer(self, p: Person, msg: Incoming) -> None:
        t = msg.text.strip().lower()
        if re.fullmatch(r"(report|summary|hisab|hisaab|spend)", t):
            return self._text(p, self._report())
        if re.fullmatch(r"(pending|slips)", t):
            return self._show_pending(p)
        if t == "stock":
            return self._text(p, render.stock_text(store.stock_summary(self.db), self.roster))
        self._text(p, render.help_text(p, self.roster))

    # ================================================================ dispatch & delivery

    def _dispatch(self, p: Person, text: str) -> None:
        number = approval.find_slip_number(text)
        if number is None:
            return self._text(p, "Which slip? e.g. *dispatch PS-42 Nicobar MV Campbell Bay*")
        slip = store.slip_by_number(self.db, number)
        if slip is None or slip.status not in (APPROVED, PARTIAL):
            return self._text(p, f"PS-{number:04d} is not an approved slip.")
        rest = re.sub(r"^\s*\w+\s*", "", approval.strip_slip_ref(text))
        words = rest.split()
        site = self.roster.find_site(words[0]) if words else None
        note = " ".join(words[1:] if site else words)
        sites = [site.code] if site else slip.sites()
        now = clock.now_iso()
        sent_any = False
        for sc in sites:
            lines = [l for l in slip.lines_for_site(sc) if l.status == "APPROVED" and l.received_qty is None]
            if not lines:
                continue
            sent_any = True
            for l in lines:
                self.db.run("UPDATE slip_lines SET dispatched_at = ?, dispatch_note = ? WHERE id = ?", (now, note, l.id))
            fresh = store.load_slip(self.db, slip.id)
            self._send_grn_card(fresh, sc, note)
        if not sent_any:
            return self._text(p, f"Nothing left to dispatch on {slip.slip_no}" + (f" for {site.name}" if site else "") + ".")
        self.db.audit(p.phone, "dispatch", slip.slip_no, sites=sites, note=note)
        enqueue(self.db, "slip", slip.id)
        names = ", ".join(self.roster.site_name(s) for s in sites)
        self._text(p, f"🚚 {slip.slip_no} marked dispatched to {names}. The site will confirm delivery.")

    def _send_grn_card(self, slip: Slip, site_code: str, note: str = "") -> None:
        lines = [l for l in slip.lines_for_site(site_code) if l.status == "APPROVED" and l.received_qty is None]
        if not lines:
            return
        entity = f"grn:{slip.id}:{site_code}"
        for e in self.roster.engineers_for(site_code):
            def send(e=e):
                self._text(e, render.grn_text(slip, site_code, lines, self.roster, note), kind="grn", entity=entity)
                self._buttons(e, f"{slip.slip_no}: did everything arrive?",
                              [(f"GR_ALL:{slip.id}:{site_code}", "✅ All received"),
                               (f"GR_SHORT:{slip.id}:{site_code}", "⚠️ Short/damaged")], kind="grn", entity=entity)
            self._notify(e, f"Material dispatched to your site ({slip.slip_no})", send)

    def _deliveries_due(self, p: Person, quiet: bool = False) -> None:
        rows = self.db.q(
            "SELECT DISTINCT s.id FROM slips s JOIN slip_lines sl ON sl.slip_id = s.id WHERE sl.site_code = ? "
            "AND sl.status = 'APPROVED' AND sl.received_qty IS NULL ORDER BY s.id", (p.site,))
        if not rows:
            if not quiet:
                self._text(p, "No deliveries due for your site.")
            return
        for r in rows:
            slip = store.load_slip(self.db, r["id"])
            lines = [l for l in slip.lines_for_site(p.site) if l.status == "APPROVED" and l.received_qty is None]
            note = lines[0].dispatch_note or ("dispatched " + clock.fmt(lines[0].dispatched_at) if lines[0].dispatched_at else "not dispatched yet")
            entity = f"grn:{slip.id}:{p.site}"
            self._text(p, render.grn_text(slip, p.site, lines, self.roster, note), kind="grn", entity=entity)
            self._buttons(p, f"{slip.slip_no}: did everything arrive?",
                          [(f"GR_ALL:{slip.id}:{p.site}", "✅ All received"), (f"GR_SHORT:{slip.id}:{p.site}", "⚠️ Short/damaged")],
                          kind="grn", entity=entity)

    def _grn_button(self, p: Person, action: str, slip_id: int, site: str) -> None:
        if site != p.site:
            return self._text(p, "That delivery is for another site.")
        slip = store.load_slip(self.db, slip_id)
        lines = [l for l in slip.lines_for_site(site) if l.status == "APPROVED" and l.received_qty is None]
        if not lines:
            return self._text(p, f"{slip.slip_no} is already fully recorded for your site. Thank you.")
        if action == "GR_ALL":
            return self._record_receipt(p, slip, site, {l.line_no: l.qty for l in lines}, "all received")
        self.db.set_state(p.phone, "GRN_DETAIL", {"slip_id": slip_id, "site": site})
        listing = "\n".join(f"{i}. {l.name} — {qty(l.qty)} {l.unit}" for i, l in enumerate(lines, start=1))
        self._text(p, f"Tell me what actually came for {slip.slip_no}:\n{listing}\n\n"
                      "Reply like *1-45, 3-0* (line – qty received), or in words: \"cement 45 bag aaya, sand nahi aaya\".\n"
                      "_Lines you don't mention are counted as fully received._")

    def _grn_detail(self, p: Person, msg: Incoming, data: dict) -> None:
        self.db.set_state(p.phone, "")
        slip = store.load_slip(self.db, data["slip_id"])
        lines = [l for l in slip.lines_for_site(data["site"]) if l.status == "APPROVED" and l.received_qty is None]
        if not lines:
            return self._text(p, f"{slip.slip_no} is already recorded for your site.")
        text = self._content(msg).text if msg.kind != "text" else msg.text
        local = [{"line_no": i, "name": l.name, "qty": l.qty, "unit": l.unit} for i, l in enumerate(lines, start=1)]
        reported = self.parser.parse_receipt(text, local)
        if not reported:
            return self._text(p, "I couldn't match that to the lines, so nothing was recorded. Tap *Short/damaged* again "
                                 "and reply like *1-45, 3-0* (line – qty received), or tap *All received*.")
        got = {l.line_no: l.qty for l in lines}
        for r in reported:
            if 1 <= r.line_no <= len(lines):
                got[lines[r.line_no - 1].line_no] = r.qty
        self._record_receipt(p, slip, data["site"], got, text)

    def _record_receipt(self, p: Person, slip: Slip, site: str, got: dict[int, float], text: str) -> None:
        now = clock.now_iso()
        short = []
        ledger_ids = []
        with self.db.transaction():
            for l in slip.lines_for_site(site):
                if l.line_no not in got:
                    continue
                q = got[l.line_no]
                self.db.run("UPDATE slip_lines SET received_qty = ?, received_at = ?, received_by = ? WHERE id = ?",
                            (q, now, p.phone, l.id))
                if q > 0:
                    ledger_ids.append(self.db.run(
                        "INSERT INTO stock_ledger(site_code, item_key, name, unit, qty, kind, ref, by_phone, note, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (site, l.item_key, l.name, l.unit, q, "RECEIVED", slip.slip_no, p.phone, l.vendor, now)))
                if q + 1e-9 < l.qty:
                    short.append((l, q))
        self.db.audit(p.phone, "receipt", slip.slip_no, site=site, received=got, text=text)
        enqueue(self.db, "slip", slip.id)
        for lid in ledger_ids:
            enqueue(self.db, "ledger", lid)
        site_name = self.roster.site_name(site)
        if short:
            lines = "\n".join(f"• {l.name}: got {qty(q)} of {qty(l.qty)} {l.unit} ({l.vendor})" for l, q in short)
            alert = f"⚠️ *Short delivery at {site_name}* — {slip.slip_no}\n{lines}\nReported by {p.name}."
            for who in self.roster.by_role("logistics") + self.roster.by_role("approver"):
                self._notify(who, f"Short delivery at {site_name} ({slip.slip_no})", lambda who=who: self._text(who, alert))
            self._text(p, f"Recorded. Shortage reported to logistics and the approver.\n{lines}")
        else:
            for l in self.roster.by_role("logistics"):
                self._notify(l, f"{site_name} received {slip.slip_no}",
                             lambda l=l: self._text(l, f"✅ {site_name} confirmed delivery of {slip.slip_no} ({p.name})."))
            self._text(p, f"✅ Recorded. Stock for {site_name} updated.")

    def _usage(self, p: Person, text: str) -> None:
        stock = store.stock_summary(self.db, p.site)
        used = self.parser.parse_usage(text, stock)
        if not used:
            return self._text(p, "Tell me what was used, e.g. *used 10 bag cement, 2 brass sand*.")
        now = clock.now_iso()
        report = []
        for u in used:
            if u.qty <= 0:
                continue
            lid = self.db.run(
                "INSERT INTO stock_ledger(site_code, item_key, name, unit, qty, kind, ref, by_phone, note, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", (p.site, u.item_key, u.name, u.unit, -u.qty, "USED", "", p.phone, text[:200], now))
            enqueue(self.db, "ledger", lid)
            left = self.db.one("SELECT ROUND(SUM(qty), 3) AS q FROM stock_ledger WHERE site_code = ? AND item_key = ? AND unit = ?",
                               (p.site, u.item_key, u.unit))["q"]
            warn = " ⚠️ below zero — please check" if left < 0 else ""
            report.append(f"{u.name}: used {qty(u.qty)} {u.unit}, left {qty(left)}{warn}")
        self.db.audit(p.phone, "usage", p.site, text=text)
        self._text(p, "📝 Recorded:\n" + "\n".join(report))

    # ================================================================ reports & schedule

    def _report(self) -> str:
        now = clock.now()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
        approved = self.db.q(
            "SELECT sl.site_code, sl.vendor, sl.amount FROM slip_lines sl JOIN slips s ON s.id = sl.slip_id "
            "WHERE sl.status = 'APPROVED' AND s.decided_at >= ?", (start,))
        rejected = self.db.one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(sl.amount), 0) AS a FROM slip_lines sl JOIN slips s ON s.id = sl.slip_id "
            "WHERE sl.status = 'REJECTED' AND s.decided_at >= ?", (start,))
        n_slips = self.db.one("SELECT COUNT(*) AS n FROM slips WHERE status IN ('APPROVED','PARTIAL') AND decided_at >= ?", (start,))["n"]
        total = sum(r["amount"] for r in approved)
        by_site: dict[str, float] = {}
        by_vendor: dict[str, float] = {}
        for r in approved:
            by_site[r["site_code"]] = by_site.get(r["site_code"], 0) + r["amount"]
            by_vendor[r["vendor"]] = by_vendor.get(r["vendor"], 0) + r["amount"]
        pending = store.pending_slips(self.db)
        undelivered = self.db.one("SELECT COUNT(*) AS n FROM slip_lines WHERE status = 'APPROVED' AND received_qty IS NULL")["n"]
        shorts = self.db.one(
            "SELECT COUNT(*) AS n FROM slip_lines WHERE received_qty IS NOT NULL AND received_qty < qty AND received_at >= ?", (start,))["n"]
        lines = [f"📊 *{now.strftime('%B %Y')} so far*", f"Approved: *{lakh(total)}* across {n_slips} slip(s)"]
        if by_site:
            lines.append("By site: " + " · ".join(f"{self.roster.site_name(k)} {lakh(v)}" for k, v in sorted(by_site.items(), key=lambda x: -x[1])))
        if by_vendor:
            top = sorted(by_vendor.items(), key=lambda x: -x[1])[:5]
            lines.append("Top vendors: " + " · ".join(f"{k} {lakh(v)}" for k, v in top))
        if rejected["n"]:
            lines.append(f"Rejected: {lakh(rejected['a'])} ({rejected['n']} line{'s' if rejected['n'] != 1 else ''})")
        lines.append(f"Waiting for approval: {len(pending)}" + (f" ({lakh(sum(s.total for s in pending))})" if pending else ""))
        lines.append(f"Approved but not yet delivered: {undelivered} line(s)")
        if shorts:
            lines.append(f"⚠️ Short deliveries this month: {shorts}")
        return "\n".join(lines)

    def tick(self) -> None:
        """Periodic jobs: reminders, daily digest, backup, Google sync. Safe to call often."""
        with self.lock:
            now = clock.now()
            self._approval_reminders(now)
            self._draft_reminders(now)
            self._daily(now)
        if self.gsync is not None:
            with self._sync_lock:
                process_queue(self.db, self.gsync, self.roster)

    def _approval_reminders(self, now) -> None:
        due = now - timedelta(hours=self.s.approval_reminder_hours)
        for row in self.db.q("SELECT id, reminder_count FROM slips WHERE status = 'PENDING' AND reminder_count < ? AND COALESCE(reminded_at, submitted_at) <= ?",
                             (self.s.max_approval_reminders, due.isoformat(timespec="seconds"))):
            slip = store.load_slip(self.db, row["id"])
            hours = int((now - clock.parse(slip.submitted_at)).total_seconds() // 3600)
            for a in self.roster.by_role("approver"):
                self._send_approval_card(a, slip, slip.pdf_path or "", prefix=f"⏰ *Reminder:* waiting {hours}h for your approval")
            self.db.run("UPDATE slips SET reminded_at = ?, reminder_count = reminder_count + 1 WHERE id = ?",
                        (now.isoformat(timespec="seconds"), slip.id))
            if row["reminder_count"] + 1 >= self.s.max_approval_reminders:
                for l in self.roster.by_role("logistics"):
                    self._notify(l, f"{slip.slip_no} still waiting for approval",
                                 lambda l=l: self._text(l, f"⏳ {slip.slip_no} has waited {hours}h for approval. "
                                                           "You may want to call."))

    def _draft_reminders(self, now) -> None:
        due = (now - timedelta(minutes=self.s.draft_reminder_minutes)).isoformat(timespec="seconds")
        for r in self.db.q("SELECT id, entered_by_phone FROM requisitions WHERE status = 'DRAFT' AND reminded_at IS NULL AND updated_at <= ?", (due,)):
            person = self.roster.person(r["entered_by_phone"])
            self.db.run("UPDATE requisitions SET reminded_at = ? WHERE id = ?", (now.isoformat(timespec="seconds"), r["id"]))
            if person is None:
                continue
            req = store.load_requisition(self.db, r["id"])

            def send(person=person, req=req):
                self._text(person, "⏰ This list was *not sent* yet:\n\n" + render.req_card(req, self.roster), kind="req", entity=f"req:{req.id}")
                self._buttons(person, "Send it to logistics?", [(f"RQ_OK:{req.id}", "✅ Confirm"), (f"RQ_X:{req.id}", "❌ Cancel")],
                              kind="req", entity=f"req:{req.id}")
            self._notify(person, "Your material list has not been sent yet", send)

    def _daily(self, now) -> None:
        today = now.date().isoformat()
        if self.db.kv_get("last_backup") != today:
            dest = Path(self.s.backup_dir) / f"purchasebot-{today}.db"
            self.db.backup_to(dest)
            self.db.kv_set("last_backup", today)
            if self.gsync:
                enqueue(self.db, "file", f"{dest}|Backups")
            for old in sorted(Path(self.s.backup_dir).glob("purchasebot-*.db"))[:-30]:
                old.unlink(missing_ok=True)
        if 0 <= self.s.daily_digest_hour <= now.hour and self.db.kv_get("last_digest") != today:
            self.db.kv_set("last_digest", today)
            decided_today = self.db.one("SELECT COUNT(*) AS n FROM slips WHERE decided_at >= ?", (today,))["n"]
            pending = store.pending_slips(self.db)
            if decided_today or pending:
                body = "🌙 *Daily summary*\n" + self._report()
                for who in self.roster.by_role("approver") + self.roster.by_role("observer"):
                    self._notify(who, "Daily purchase summary", lambda who=who: self._text(who, body))
