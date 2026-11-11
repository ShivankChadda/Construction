"""Plan without prices -> approval -> one challan per shop -> shop bill checked against the challan."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import fitz  # pymupdf
from fastapi.testclient import TestClient

from purchasebot import store
from purchasebot.app import create_app
from purchasebot.db import DB
from purchasebot.llm import BillParse, ParsedBillLine, RuleParser
from purchasebot.rates import RateBook, record, similarity
from purchasebot.signing import canonical

from conftest import PHONES


def _pdf_text(path) -> str:
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def _plan(chat, text: str, send: bool = True) -> None:
    chat.say("abbas", text)
    if send:
        chat.tap("abbas", "📤")


def _item(chat, ref: str) -> dict:
    return store.item_by_ref(chat.db, ref)


def test_plan_needs_no_prices_and_records_pending_sent_and_dropped(chat):
    chat.requisition("chandra", "cement 50 bags\nsand 3 truck\nbricks 2000 nos\ngloves 10 pair\nwire 5 kg")
    _plan(chat, "N1 N2 Om Traders\nN3 not available at Om\nN4 already sent MV Manav Star\nN5 not needed", send=False)
    draft = chat.texts("abbas")
    assert "Rate missing" not in draft and "Not understood" not in draft
    assert "🏪 Om Traders" in draft and "no past rate" in draft
    assert "⏳ N3 Bricks — not available: not available at Om" in draft
    assert "📦 N4 Gloves — already sent: already sent MV Manav Star" in draft
    assert "Not buying now: 1 not available, 1 already sent, 1 not needed" in draft

    chat.tap("abbas", "📤")
    slip = store.slip_by_number(chat.db, 1)
    assert slip.status == "PENDING" and [l.line_no for l in slip.lines] == [1, 2] and len(slip.notes) == 3
    assert [s.kind for s in chat.wa.to(PHONES["boss"])] == ["document", "text", "buttons"]
    assert "NOT BUYING NOW" in _pdf_text(slip.pdf_path)
    status = {r: (_item(chat, r)["status"], _item(chat, r)["note"]) for r in ("N1", "N3", "N4", "N5")}
    assert status["N1"] == ("IN_SLIP", "")
    assert status["N3"][0] == "OPEN" and status["N3"][1].startswith("Not available (18 Oct 2026)")
    assert status["N4"] == ("SENT", "already sent MV Manav Star")
    assert status["N5"][0] == "DROPPED"
    told = chat.texts("chandra")
    assert "Abbas* on your requirements" in told and "already sent" in told and "stays pending" in told

    chat.say("abbas", "list")
    assert "N3* Bricks" in chat.last("abbas").body or "N3* Bricks" in chat.texts("abbas")
    assert "⏳ _Not available (18 Oct 2026)" in chat.texts("abbas")


def test_only_notes_are_recorded_without_approval(chat):
    chat.requisition("chandra", "cement 50 bags\nsand 3 truck")
    _plan(chat, "N1 not available\nN2 not needed", send=False)
    assert chat.last("abbas", "buttons").buttons[0][1] == "📤 Record"
    chat.tap("abbas", "📤")
    assert not chat.wa.to(PHONES["boss"])
    assert "Recorded: 1 not available, 1 not needed" in chat.last("abbas").body
    assert _item(chat, "N1")["status"] == "OPEN" and _item(chat, "N2")["status"] == "DROPPED"
    assert store.slip_by_number(chat.db, 1).status == "CANCELLED"


def test_withdraw_puts_noted_items_back(chat):
    chat.requisition("chandra", "cement 50 bags\nsand 3 truck")
    _plan(chat, "N1 Om Traders\nN2 already sent")
    assert _item(chat, "N2")["status"] == "SENT"
    chat.say("abbas", "edit PS-1")
    assert (_item(chat, "N2")["status"], _item(chat, "N2")["note"]) == ("OPEN", "")
    assert chat.db.one("SELECT status FROM requisitions")["status"] == "SUBMITTED"


def test_approval_makes_one_signed_challan_per_shop_without_prices(chat):
    chat.requisition("chandra", "cement 50 bags\nsand 3 truck\nbricks 2000 nos")
    _plan(chat, "N1 Om Traders\nN2 Hira Metals\nN3 Om Traders")
    chat.say("boss", "yes")
    slip = store.slip_by_number(chat.db, 1)
    challans = store.challans_for_slip(chat.db, slip.id)
    assert [(c.challan_no, c.vendor, [l.name for l in c.lines]) for c in challans] == [
        ("PS-0001-1", "Om Traders", ["Cement", "Bricks"]), ("PS-0001-2", "Hira Metals", ["Sand"])]
    for c in challans:
        assert chat.bot.signer.verify(canonical(chat.bot.challan_payload(c)), c.signature)
        text = _pdf_text(c.pdf_path)
        assert "PURCHASE CHALLAN" in text and c.vendor in text and c.verify_code in text
        assert "Rs." not in text  # the shop bills at its own rate
        assert c.valid_until.startswith("2026-10-25")
    msg = chat.texts("abbas")
    assert "PS-0001-1* Om Traders — 2 items" in msg and "photo of the shop's bill" in msg
    docs = [s.body for s in chat.wa.to(PHONES["abbas"]) if s.kind == "document"]
    assert docs[-2:] == ["PS-0001-1 · Om Traders — show this at the shop", "PS-0001-2 · Hira Metals — show this at the shop"]
    assert any(s.kind == "document" for s in chat.wa.to(PHONES["krishna"]))  # accounts get the approved list


def test_partial_approval_challans_only_approved_lines(chat):
    chat.requisition("chandra", "cement 50 bags\nsand 3 truck")
    _plan(chat, "N1 Om Traders\nN2 Hira Metals")
    chat.say("boss", "2 nahi")
    chat.tap("boss", "✅ Confirm")
    challans = store.challans_for_slip(chat.db, 1)
    assert [c.vendor for c in challans] == ["Om Traders"]


def test_rejection_makes_no_challans(chat):
    chat.requisition("chandra", "cement 50 bags")
    _plan(chat, "N1 Om Traders")
    chat.say("boss", "no")
    assert store.challans_for_slip(chat.db, 1) == []


class BillReader(RuleParser):
    """Stands in for Claude reading a bill photo: returns whatever the test sets."""

    def __init__(self):
        self.bill: BillParse | None = None
        self.calls = 0

    def parse_bill(self, text, images, challan_lines):
        self.calls += 1
        self.seen = challan_lines
        return self.bill


def _approved(make_chat, reqs="cement 50 bags\nsand 3 truck", plan="N1 N2 Om Traders"):
    reader = BillReader()
    chat = make_chat(parser=reader)
    chat.requisition("chandra", reqs)
    _plan(chat, plan)
    chat.say("boss", "yes")
    return chat, reader, store.challans_for_slip(chat.db, 1)


def test_bill_photo_is_checked_against_the_challan_and_recorded(make_chat):
    chat, reader, (ch,) = _approved(make_chat)
    cement, sand = ch.lines
    reader.bill = BillParse("OM TRADERS PORT BLAIR", "4521", "2026-10-19", [
        ParsedBillLine("Cement OPC 53", "cement", 50, "bag", 410, 20500, cement.id),
        ParsedBillLine("River sand", "sand", 3, "truck", 9000, 27000, sand.id)], 0, 47500)
    chat.photo("abbas", caption="bill")
    shown = chat.texts("abbas")
    assert "Bill BL-0001* — Om Traders (bill no 4521, 19 Oct 2026)" in shown
    assert "Against challan *PS-0001-1*" in shown and "✔ Matches the approved challan." in shown
    assert reader.seen[0]["challan_no"] == "PS-0001-1"

    chat.tap("abbas", "✅ Record bill")
    assert store.challan_by_number(chat.db, "PS-0001-1").status == "BILLED"
    for who in ("boss", "krishna"):
        sent = chat.wa.to(PHONES[who])
        assert any("Bill BL-0001" in s.body and "Recorded by Abbas" in s.body for s in sent)
        assert sent[-1].kind == "document" and sent[-1].body == "BL-0001 · Om Traders bill"
    assert not any("Bill BL-0001" in s.body for s in chat.wa.to(PHONES["shivank"]))  # observers don't get bills
    assert "When loaded, send *dispatch PS-0001" in chat.last("abbas").body
    rates = {r["name"]: (r["rate"], r["vendor"], r["rate_date"]) for r in chat.db.q("SELECT * FROM rate_history")}
    assert rates == {"Cement": (410, "Om Traders", "2026-10-19"), "Sand": (9000, "Om Traders", "2026-10-19")}

    # The next purchase of cement shows what was paid.
    chat.requisition("chandra", "cement 20 bags")
    _plan(chat, "N3 Hira Metals", send=False)
    assert "last ₹410 (Om Traders, 19 Oct 2026)" in chat.texts("abbas")
    chat.say("shivank", "report")
    assert "On credit (shop bills recorded): Om Traders" in chat.last("shivank").body


def test_bill_flags_unapproved_items_extra_quantity_and_price_rise(make_chat):
    chat, reader, (ch,) = _approved(make_chat)
    cement = ch.lines[0]
    chat.db.run("UPDATE slip_lines SET last_rate = 400, last_vendor = 'Om Traders', last_rate_date = '2026-09-01' "
                "WHERE id = ?", (cement.id,))
    reader.bill = BillParse("Hira Metals", "", "", [
        ParsedBillLine("Cement", "cement", 60, "bag", 450, 27000, cement.id),
        ParsedBillLine("Paint 20 litre", "paint", 1, "drum", 3000, 3000, 0)], 0, 31000)
    chat.photo("abbas", caption="Om bill")
    shown = chat.texts("abbas")
    assert "Billed 60 bag; approved 50 bag" in shown
    assert "Rate ₹450 is 12% above last ₹400 (Om Traders, 01 Sep 2026)" in shown
    assert "Not on challan PS-0001-1 — was not approved" in shown
    assert "Bill is from \"Hira Metals\" but PS-0001-1 is for Om Traders" in shown
    assert "Bill total ₹31,000 doesn't match the lines (₹30,000)" in shown
    assert "Not on this bill: Sand 3 truck" in shown
    chat.tap("abbas", "✅ Record bill")
    assert store.challan_by_number(chat.db, "PS-0001-1").status == "PART_BILLED"
    assert "Still open on PS-0001-1: Sand 3 truck" in chat.last("abbas").body


def test_untagged_photo_asks_bill_or_requirement(make_chat):
    chat, reader, (ch,) = _approved(make_chat)
    reader.bill = BillParse("Om Traders", "77", "", [ParsedBillLine("Cement", "cement", 50, "bag", 410, 20500, ch.lines[0].id)])
    chat.photo("abbas")
    assert chat.last("abbas", "buttons").body.startswith("📷 Is this a shop's bill")
    chat.tap("abbas", "🧾 Shop bill")
    assert reader.calls == 1 and "Bill BL-0001" in chat.texts("abbas")

    chat.photo("abbas", caption="")  # within 15 minutes of an unconfirmed bill: the next page
    assert reader.calls == 2
    bill = store.load_bill(chat.db, store.draft_bill_id(chat.db, PHONES["abbas"]))
    assert len(bill.media) == 2 and bill.bill_ref == "BL-0002"


def test_requirement_photo_still_works_after_choosing_list(make_chat):
    chat, reader, _ = _approved(make_chat)
    chat.photo("abbas", caption="Nicobar: cement 10 bag")
    chat.tap("abbas", "📋 Requirement list")
    assert reader.calls == 0
    assert "Nicobar" in chat.texts("abbas")


def test_typed_bill_without_claude(chat):
    chat.requisition("chandra", "cement 50 bags")
    _plan(chat, "N1 Om Traders")
    chat.say("boss", "yes")
    chat.say("abbas", "Bill 4521\nCement 50 bag 410")
    assert "Against challan *PS-0001-1*" in chat.texts("abbas")
    chat.tap("abbas", "✅ Record bill")
    assert store.challan_by_number(chat.db, "PS-0001-1").status == "BILLED"


def test_challan_verify_page_shows_billed_and_rejects_tampering(make_chat):
    chat, reader, (ch,) = _approved(make_chat, reqs="cement 50 bags", plan="N1 Om Traders")
    c = TestClient(create_app(bot=chat.bot, settings=chat.bot.s, run_scheduler=False))
    url = urlparse(chat.bot.verify_url(ch))
    code = parse_qs(url.query)["c"][0]
    r = c.get(url.path, params={"c": code})
    assert r.status_code == 200 and "Genuine and valid" in r.text and "Om Traders" in r.text
    assert c.get(url.path, params={"c": "WRONG"}).status_code == 404

    reader.bill = BillParse("Om Traders", "1", "", [ParsedBillLine("Cement", "cement", 50, "bag", 410, 20500, ch.lines[0].id)])
    chat.photo("abbas", caption="bill")
    chat.tap("abbas", "✅ Record bill")
    assert "already billed" in c.get(url.path, params={"c": code}).text

    chat.db.run("UPDATE slip_lines SET qty = 500 WHERE id = ?", (ch.lines[0].id,))
    assert "FAILED" in c.get(url.path, params={"c": code}).text


class Matcher(RuleParser):
    def __init__(self):
        self.asked = []

    def match_rates(self, items):
        self.asked.append([i["name"] for i in items])
        return {i: 0 for i, it in enumerate(items) if it["candidates"]}


def test_last_rate_from_history_with_ai_match_cached(make_chat):
    matcher = Matcher()
    chat = make_chat(parser=matcher)
    record(chat.db, "zoho_bill", "b1#1", "TMT bar 12 mm", "tmt bar 12 mm", "mt", 61000, "Hira Metals", "2026-10-01")
    chat.requisition("chandra", "saria 12mm 2 mt")
    _plan(chat, "N1 Om Traders", send=False)
    assert matcher.asked == [["Saria 12mm"]]
    assert 'last ₹61,000 (Hira Metals, 01 Oct 2026) for "TMT bar 12 mm"' in chat.texts("abbas")
    _plan(chat, "N1 Hira Metals", send=False)  # the draft is re-checked: the match is remembered
    assert matcher.asked == [["Saria 12mm"]]


def test_quoted_rate_above_last_rate_is_flagged(chat):
    record(chat.db, "bill", "BL-9#1", "Cement", "cement", "bag", 400, "Om Traders", "2026-10-10")
    chat.requisition("chandra", "cement 50 bags")
    _plan(chat, "N1 Om Traders 450", send=False)
    assert "Rate ₹450 is 12.5% above last ₹400" in chat.texts("abbas")
    slip = store.slip_by_number(chat.db, 1)
    assert slip.lines[0].est_amount == 22500 and slip.total == 22500


def test_estimate_uses_last_rate_when_no_price_given(chat):
    record(chat.db, "zoho_item", "i1", "Cement OPC", "cement", "bag", 395, "", "")
    chat.requisition("chandra", "cement 50 bags\nsand 3 truck")
    _plan(chat, "N1 N2 Om Traders", send=False)
    slip = store.slip_by_number(chat.db, 1)
    assert slip.lines[0].last_rate == 395 and slip.total == 19750 and slip.unpriced == 1
    assert "Est. value: ₹19,750* _(+1 item with no past rate)_" in chat.texts("abbas")
    assert "Zoho item rate" in chat.texts("abbas")


def test_name_matching_is_strict_on_sizes():
    assert similarity("PPR stop cock 20 x 15 mm", "PPR Stop Cock 20X15MM") == 1.0
    assert similarity("PPR stop cock 20 x 15 mm", "PPR Stop Cock 25x20 mm") == 0.0
    assert similarity("PPR male adapter 20 x 15", "PPR Male Adaptor 20x15") == 1.0
    assert similarity("plastic sheet", "plaster sheet") < 0.6
    assert similarity("Sariya 12mm", "Saria 12 mm") == 1.0


def test_rule_parser_reads_actions_ranges_and_optional_rates():
    items = [{"ref": f"N{i}", "site_code": "NIC", "name": f"Item {i}", "item_key": f"item {i}", "qty": 5, "unit": "nos"}
             for i in range(1, 9)]
    r = RuleParser().parse_slip("N1 to N3 Om Traders\nN4 Hira 62\nN5 nahi mila\nN6 bhej diya MV Manav Star\nN7 cancel\nN8 from current",
                                items, ["Om Traders", "Hira Metals"], [], [])
    got = [(l.ref, l.action, l.vendor, l.rate) for l in r.lines]
    assert got == [("N1", "BUY", "Om Traders", 0), ("N2", "BUY", "Om Traders", 0), ("N3", "BUY", "Om Traders", 0),
                   ("N4", "BUY", "Hira Metals", 62), ("N5", "PENDING", "", 0), ("N6", "SENT", "", 0),
                   ("N7", "DROP", "", 0), ("N8", "BUY", "Current", 0)]


def test_old_database_gets_new_columns(tmp_path):
    path = tmp_path / "old.db"
    import sqlite3
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE req_items (id INTEGER PRIMARY KEY, requisition_id INTEGER, line_no INTEGER, ref TEXT, "
                      "name TEXT, item_key TEXT, qty REAL, unit TEXT, spec TEXT, status TEXT);"
                      "CREATE TABLE slip_lines (id INTEGER PRIMARY KEY, slip_id INTEGER, line_no INTEGER, site_code TEXT, "
                      "name TEXT, item_key TEXT, qty REAL, unit TEXT, vendor TEXT, rate REAL, amount REAL);")
    con.close()
    db = DB(path)
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(slip_lines)")}
    assert {"action", "remark", "last_rate_name", "challan_id"} <= cols
    assert "note" in {r[1] for r in db.conn.execute("PRAGMA table_info(req_items)")}
