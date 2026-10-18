from datetime import timedelta
from pathlib import Path

from purchasebot import clock, store
from purchasebot.llm import ParsedSlipLine, RuleParser, SlipParse
from purchasebot.signing import canonical
from purchasebot.whatsapp import FakeWhatsApp

from conftest import PHONES


def slip_row(chat, n=1):
    return store.slip_by_number(chat.db, n)


def test_happy_path_requisition_to_signed_slip(chat):
    chat.say("chandra", "Cement OPC 53 grade 50 bags\nTMT 12mm 2 mt")
    card = chat.texts("chandra")
    assert "Requirement – Nicobar" in card and "draft" in card
    chat.tap("chandra", "✅ Confirm")
    assert "REQ-NIC-0001" in chat.last("chandra").body
    assert "N1 Cement OPC 53 grade — 50 bag" in chat.texts("abbas")

    chat.slip("N1 Om Traders 420\nN2 Hira Metals 62000")
    boss = chat.wa.to(PHONES["boss"])
    assert [s.kind for s in boss] == ["document", "text", "buttons"]
    assert Path(boss[0].path).exists()
    assert slip_row(chat).status == "PENDING"

    chat.say("boss", "haan", quote=boss[2])
    slip = slip_row(chat)
    assert slip.status == "APPROVED"
    assert slip.decided_by_name == "Rajesh Chadda" and slip.decision_text == "haan"
    assert slip.approved_total == 50 * 420 + 2 * 62000
    assert slip.verify_code and chat.bot.signer.verify(canonical(chat.bot.signed_payload(slip)), slip.signature)
    assert Path(slip.pdf_path).name == "PS-0001_APPROVED.pdf"

    abbas_docs = [s for s in chat.wa.to(PHONES["abbas"]) if s.kind == "document"]
    assert abbas_docs and abbas_docs[-1].path == slip.pdf_path
    assert any(s.kind == "document" for s in chat.wa.to(PHONES["shivank"]))
    assert "approved for purchase" in chat.texts("chandra")
    statuses = {r["status"] for r in chat.db.q("SELECT status FROM req_items")}
    assert statuses == {"ORDERED"}
    assert chat.db.one("SELECT status FROM requisitions")["status"] == "CLOSED"


def test_engineer_can_revise_draft_before_confirming(chat):
    chat.say("chandra", "cement 50 bags, sand 3 truck")
    chat.say("chandra", "remove sand\ncement 60 bags")
    req = store.load_requisition(chat.db, 1)
    assert [(i.name, i.qty) for i in req.items] == [("Cement", 60)]
    assert req.status == "DRAFT"


def test_partial_approval_needs_confirmation(chat):
    chat.requisition("chandra", "cement 50 bags\nsand 3 truck\nbricks 2000 nos")
    chat.slip("N1 Om Traders 420\nN2 Om Traders 9500\nN3 Om Traders 9")
    chat.say("boss", "2 nahi")
    assert slip_row(chat).status == "PENDING"
    confirm = chat.last("boss", "buttons")
    assert "Reject line 2" in confirm.body and "Approve line 1, 3" in confirm.body

    chat.tap("boss", "↩️ Cancel")
    assert slip_row(chat).status == "PENDING"

    chat.say("boss", "2 nahi")
    chat.tap("boss", "✅ Confirm")
    slip = slip_row(chat)
    assert slip.status == "PARTIAL"
    assert [l.status for l in slip.lines] == ["APPROVED", "REJECTED", "APPROVED"]
    assert chat.db.one("SELECT status FROM req_items WHERE ref = 'N2'")["status"] == "REJECTED"
    assert "do *not* buy" in chat.texts("abbas")
    assert "not approved" in chat.texts("chandra")


def test_only_the_approver_can_approve(chat):
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    slip = slip_row(chat)
    chat.press("chandra", f"AP_YES:{slip.id}:{slip.version}")
    chat.press("abbas", f"AP_YES:{slip.id}:{slip.version}")
    assert "isn't for you" in chat.last("chandra").body
    chat.say("abbas", "yes")  # for logistics this is not an approval
    assert slip_row(chat).status == "PENDING"


def test_old_message_cannot_approve_a_revised_slip(chat):
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    old_buttons = chat.last("boss", "buttons")

    chat.say("abbas", "edit PS-1")
    assert "pulled back" in chat.last("boss").body
    chat.tap("boss", "✅ Approve all", msg=old_buttons)
    assert slip_row(chat).status == "DRAFT"

    chat.say("abbas", "N1 Om Traders 400")
    chat.tap("abbas", "📤")
    slip = slip_row(chat)
    assert slip.version == 2 and slip.lines[0].rate == 400

    chat.tap("boss", "✅ Approve all", msg=old_buttons)
    assert slip_row(chat).status == "PENDING"
    assert "changed after that message" in chat.texts("boss")

    chat.tap("boss", "✅ Approve all")
    assert slip_row(chat).status == "APPROVED"


def test_unquoted_yes_with_two_pending_slips_asks_which(chat):
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    chat.requisition("siddhu", "gitti 20mm 4 brass")
    chat.slip("D1 Om Traders 6500")
    chat.say("boss", "yes")
    assert "2 slips are waiting" in chat.last("boss").body
    assert {s.status for s in store.pending_slips(chat.db)} == {"PENDING"}
    chat.say("boss", "yes PS-2")
    assert slip_row(chat, 2).status == "APPROVED" and slip_row(chat, 1).status == "PENDING"


def test_question_relay_between_approver_and_logistics(chat):
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    chat.say("boss", "cement 420 kyun? last time 395 tha")
    q = chat.last("abbas")
    assert q.kind == "text" and "asks about PS-0001" in q.body
    assert slip_row(chat).status == "PENDING"

    chat.say("abbas", "freight badh gaya", quote=q)
    reply = chat.last("boss")
    assert "Abbas replied about PS-0001" in reply.body and "freight badh gaya" in reply.body

    chat.say("boss", "ok", quote=reply)
    assert slip_row(chat).status == "APPROVED"


def test_ask_button_then_question(chat):
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    chat.tap("boss", "❓")
    chat.say("boss", "kaunsa brand?")
    assert "kaunsa brand?" in chat.last("abbas").body
    assert slip_row(chat).status == "PENDING"


def test_voice_approval_requires_a_tap(chat):
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    chat.voice("boss", "haan theek hai")
    assert slip_row(chat).status == "PENDING"
    assert "I heard" in chat.last("boss", "buttons").body
    chat.tap("boss", "✅ Confirm")
    assert slip_row(chat).status == "APPROVED"


def test_voice_requirement_is_transcribed(chat):
    chat.voice("siddhu", "cement 30 bag, gitti 20mm 4 brass, urgent")
    card = chat.texts("siddhu")
    assert "I heard" in card and "URGENT" in card
    assert len(store.load_requisition(chat.db, 1).items) == 2


def test_duplicate_webhook_delivery_is_ignored(chat):
    chat.say("chandra", "cement 50 bags", wamid="wamid.same")
    n = len(chat.wa.sent)
    chat.say("chandra", "cement 50 bags", wamid="wamid.same")
    assert len(chat.wa.sent) == n


def test_unknown_sender_gets_one_reply_per_day(chat):
    from purchasebot.whatsapp import Incoming

    for i in range(3):
        chat.bot.handle(Incoming(wamid=f"x{i}", phone="919999999999", kind="text", text="hello"))
    assert len(chat.wa.to("919999999999")) == 1
    assert chat.db.one("SELECT COUNT(*) AS n FROM audit WHERE action = 'unknown_sender'")["n"] == 3


def test_price_new_vendor_and_repeat_purchase_flags(chat):
    chat.requisition("chandra", "cement 40 bags")
    chat.slip("N1 Om Traders 395")
    chat.say("boss", "yes")
    clock.freeze(clock.now() + timedelta(days=3))
    chat.requisition("chandra", "cement 50 bags\nply 10 sheet")
    chat.slip("N2 Om Traders 420\nN3 Sagar Hardware 1450", send=False)
    slip = slip_row(chat, 2)
    codes = {l.name: l.flag_codes() for l in slip.lines}
    assert codes["Cement"] == {"PRICE_UP", "RECENT_PURCHASE"}
    assert codes["Ply"] == {"NEW_VENDOR"}
    assert "6.3% above last ₹395" in chat.texts("abbas")


class ScriptedSlipParser(RuleParser):
    def __init__(self, lines):
        self.lines = lines

    def parse_slip(self, text, open_items, vendors, sites, known_items, current=None):
        return SlipParse(lines=self.lines)


def test_quantity_over_request_and_unrequested_items_are_flagged(make_chat):
    chat = make_chat(parser=ScriptedSlipParser([
        ParsedSlipLine("N1", "", "Cement", "cement", 60, "bag", "ome", 420),
        ParsedSlipLine("", "NIC", "Freight MV Campbell Bay", "freight", 1, "lot", "Shipping Corp", 0, lump_sum=4500),
        ParsedSlipLine("", "", "Mystery item", "mystery", 1, "nos", "Om Traders", 100),
    ]))
    chat.requisition("chandra", "cement 50 bags")
    chat.say("abbas", "anything")
    slip = slip_row(chat)
    cement, freight = slip.lines
    assert cement.vendor == "Om Traders"  # alias "ome" resolved
    assert "QTY_OVER" in cement.flag_codes() and cement.requested_qty == 50
    assert freight.rate == 4500 and {"NOT_REQUESTED", "NEW_VENDOR"} <= freight.flag_codes()
    assert "Which site is \"Mystery item\" for?" in chat.texts("abbas")


def test_logistics_can_enter_requirement_for_a_site(chat):
    chat.say("abbas", "Komoota: binding wire 25 kg")
    chat.tap("abbas", "✅ Confirm")
    req = store.load_requisition(chat.db, 1)
    assert req.site_code == "KAM" and req.entered_by_logistics and req.req_no == "REQ-KAM-0001"
    assert "entered this requirement for your site" in chat.texts("kam")
    chat.say("abbas", "K1 Hira Metals 85")
    assert "ENTERED_BY_LOGISTICS" in slip_row(chat).lines[0].flag_codes()


def test_dispatch_short_delivery_and_stock(chat):
    chat.requisition("chandra", "cement 50 bags\nsand 3 truck")
    chat.slip("N1 Om Traders 420\nN2 Om Traders 9500")
    chat.say("boss", "yes")
    chat.say("abbas", "dispatch PS-1 Nicobar MV Campbell Bay")
    assert "MV Campbell Bay" in chat.texts("chandra")
    chat.tap("chandra", "⚠️")
    chat.say("chandra", "2-2")
    assert "Short delivery at Nicobar" in chat.texts("abbas")
    assert "Short delivery at Nicobar" in chat.texts("boss")
    stock = {r["name"]: r["qty"] for r in store.stock_summary(chat.db, "NIC")}
    assert stock == {"Cement": 50, "Sand": 2}

    chat.say("chandra", "used 10 bag cement")
    stock = {r["name"]: r["qty"] for r in store.stock_summary(chat.db, "NIC")}
    assert stock["Cement"] == 40
    chat.say("chandra", "stock")
    assert "Cement — 40 bag" in chat.last("chandra").body


def test_all_received_button(chat):
    chat.requisition("siddhu", "gitti 20mm 4 brass")
    chat.slip("D1 Om Traders 6500")
    chat.say("boss", "yes")
    chat.say("abbas", "dispatch PS-1 truck")
    chat.tap("siddhu", "✅ All received")
    assert store.stock_summary(chat.db, "DIG")[0]["qty"] == 4
    assert "Diglipur confirmed delivery" in chat.texts("abbas")
    chat.tap("siddhu", "✅ All received")
    assert "already fully recorded" in chat.last("siddhu").body


def test_rejection_reopens_nothing_and_tells_everyone(chat):
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    chat.tap("boss", "❌ Reject")
    slip = slip_row(chat)
    assert slip.status == "REJECTED" and slip.signature is None
    assert "REJECTED" in chat.texts("abbas")
    assert chat.db.one("SELECT status FROM req_items")["status"] == "REJECTED"
    chat.say("boss", "yes PS-1")
    assert "already *rejected*" in chat.last("boss").body


def test_outside_24h_window_falls_back_to_template(make_chat):
    wa = FakeWhatsApp(closed_windows={PHONES["boss"]})
    chat = make_chat(wa=wa)
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    tmpl = chat.last("boss")
    assert tmpl.kind == "template" and "PS-0001" in tmpl.body
    chat.press("boss", "SHOW_PENDING")
    assert chat.last("boss", "buttons").buttons[0][0].startswith("AP_YES")


def test_reminders_and_daily_backup(chat):
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    chat.say("siddhu", "gitti 4 brass")  # left unconfirmed
    n_before = len(chat.wa.to(PHONES["boss"]))
    clock.freeze(clock.now() + timedelta(hours=5))
    chat.bot.tick()
    boss_new = chat.wa.to(PHONES["boss"])[n_before:]
    assert any("Reminder" in s.body for s in boss_new)
    assert "not sent" in chat.texts("siddhu")
    assert list(Path(chat.bot.s.backup_dir).glob("purchasebot-*.db"))
    chat.bot.tick()  # no second reminder within the interval
    assert len(chat.wa.to(PHONES["boss"])) == n_before + len(boss_new)


def test_report(chat):
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    chat.say("boss", "yes")
    chat.say("boss", "report")
    body = chat.last("boss").body
    assert "October 2026" in body and "₹21,000" in body and "Nicobar" in body
