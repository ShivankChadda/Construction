"""How the company actually works: everything happens in the 'Kailash Material' WhatsApp group.
Abbas forwards site requirements and his own dispatch posts from the group to the bot."""

from purchasebot import store
from purchasebot.llm import DispatchParse, ParsedDispatchItem, ParsedItem, ReqParse, RuleParser
from purchasebot.whatsapp import parse_webhook

from conftest import PHONES


def test_forwarded_requirement_is_logged_without_a_tap(chat):
    chat.say("abbas", "Diglipur site requirements --\n\n1). Welding goggles 10 nos", forwarded=True)
    req = store.load_requisition(chat.db, 1)
    assert req.status == "SUBMITTED" and req.req_no == "REQ-DIG-0001" and req.source == "group"
    assert [(i.ref, i.name, i.qty, i.unit) for i in req.items] == [("D1", "Welding goggles", 10, "nos")]
    summary = chat.last("abbas").body
    assert "Logged from the group" in summary and "D1 Welding goggles — 10 nos" in summary
    assert "logged these requirements for Diglipur" in chat.texts("siddhu")
    chat.say("abbas", "D1 Om Traders 180")
    # forwarded from the group means the site asked; it is not flagged as invented by logistics
    assert store.slip_by_number(chat.db, 1).lines[0].flags == []


def test_a_burst_of_forwards_gives_one_summary(make_chat):
    chat = make_chat(forward_batch_seconds=3600)
    chat.say("abbas", "Diglipur site requirements --\n1). Welding goggles 10 nos", forwarded=True)
    chat.say("abbas", "binding wire 25 kg", forwarded=True)            # no site named
    chat.say("abbas", "Remainder N/C @KEC Tambi Uncle", forwarded=True)  # a reminder, not a list
    assert chat.wa.to(PHONES["abbas"]) == []  # nothing yet: he is still forwarding
    chat.bot.flush_batches()
    sent = chat.wa.to(PHONES["abbas"])
    assert [s.kind for s in sent] == ["text", "buttons"]
    assert "3 messages" in sent[0].body and "D1 Welding goggles" in sent[0].body
    assert "not logged: \"Remainder N/C @KEC Tambi Uncle\"" in sent[0].body
    assert [t for _, t in sent[1].buttons] == ["Nicobar", "Kamorta", "Diglipur"]
    chat.tap("abbas", "Kamorta")
    assert "K1 Binding wire — 25 kg" in chat.last("abbas").body
    assert store.load_requisition(chat.db, 2).site_code == "KAM"
    chat.tap("abbas", "Kamorta", msg=sent[1])
    assert chat.last("abbas").body == "Already done."


def test_typing_after_forwarding_shows_the_summary_first(make_chat):
    chat = make_chat(forward_batch_seconds=3600)
    chat.say("abbas", "Nicobar - cement 50 bag", forwarded=True)
    chat.say("abbas", "list")
    bodies = [s.body for s in chat.wa.to(PHONES["abbas"]) if s.kind == "text"]
    assert "Logged from the group" in bodies[0] and "Open requirements" in bodies[1]


def test_abbas_fixes_what_was_logged(chat):
    chat.say("abbas", "Diglipur: welding goggles 10 nos, grease 2 kg", forwarded=True)
    chat.say("abbas", "D1 12 nos")
    assert "now 12 nos" in chat.last("abbas").body
    chat.say("abbas", "remove D2")
    assert "Removed: D2 Grease" in chat.last("abbas").body
    assert [(i["ref"], i["qty"]) for i in store.open_items(chat.db)] == [("D1", 12)]


class PhotoReqParser(RuleParser):
    def __init__(self):
        self.seen_images = []

    def parse_requisition(self, text, site_name, known_items, current=None, images=None):
        self.seen_images.append(images)
        return ReqParse(items=[ParsedItem("Laminated plywood door 8ft x 4ft (like photo)", "plywood door 8x4", 1, "nos")])


def test_forwarded_photo_is_read_then_site_asked(make_chat):
    parser = PhotoReqParser()
    chat = make_chat(parser=parser)
    chat.photo("abbas", "like this type of Ply for KEC house = 1 no 8ft×4ft", data=b"\xff\xd8door", forwarded=True)
    assert parser.seen_images[-1] == [(b"\xff\xd8door", "image/jpeg")]
    chat.tap("abbas", "Kamorta")
    req = store.load_requisition(chat.db, 1)
    assert req.site_code == "KAM" and req.items[0].name.startswith("Laminated plywood door")


class ScriptedDispatch(RuleParser):
    def __init__(self, make):
        self.make = make

    def parse_dispatch(self, text, open_lines, images=None):
        return self.make(open_lines)


def test_dispatch_photo_with_non_purchase_items(make_chat):
    def manifest(open_lines):
        cement = next(l for l in open_lines if "cement" in l["item_key"])
        return DispatchParse(carrier="Prem, by ship", note="", items=[
            ParsedDispatchItem("Cement", "cement", 50, "bag", cement["id"]),
            ParsedDispatchItem("Grinding machine (repaired)", "grinding machine", 2, "nos", 0, stock_item=False),
            ParsedDispatchItem("Calculator", "calculator", 1, "nos"),
        ])

    chat = make_chat(parser=ScriptedDispatch(manifest))
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    chat.say("boss", "yes")
    chat.photo("abbas", "Car Nicobar Sector - Item handed over to Prem travelling in ship to C/N. @KEC Engineer Chandramohan",
               forwarded=True)
    assert "DSP-0001" in chat.last("abbas").body and "matched to approved slips (PS-0001)" in chat.last("abbas").body
    card = chat.texts("chandra")
    assert "DSP-0001 → Nicobar" in card and "via Prem, by ship" in card and "Grinding machine (repaired)" in card

    chat.tap("chandra", "⚠️")
    chat.say("chandra", "1-45")
    stock = {r["name"]: r["qty"] for r in store.stock_summary(chat.db, "NIC")}
    assert stock == {"Cement": 45, "Calculator": 1}  # the repaired machine is not stock
    assert store.slip_by_number(chat.db, 1).lines[0].received_qty == 45
    assert "Short delivery at Nicobar" in chat.texts("boss") and "sent via Prem, by ship" in chat.texts("boss")


def test_bus_dispatch_caption_without_a_list(chat):
    chat.requisition("siddhu", "gitti 20mm 4 brass\nwelding glass 10 nos")
    chat.slip("D1 Om Traders 6500\nD2 Om Traders 150")
    chat.say("boss", "yes")
    chat.say("abbas", "Diglipur Sector - Welding glass loaded in Anand Bus AN01F3868 departed today at 10.00 AM. "
                      "Bus will be parked near BD BAR due to Puja festival. Transportation not paid.", forwarded=True)
    card = chat.texts("siddhu")
    assert "Welding glass — 10 nos (PS-0001)" in card and "Gitti" not in card.split("DSP-0001")[1]
    assert "Transportation not paid" in card
    chat.say("siddhu", "received")
    assert "Approved but not dispatched yet" in chat.texts("siddhu") and "Gitti 20mm" in chat.last("siddhu").body


def test_father_style_go_ahead(chat):
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    chat.say("boss", "Abbas do it", quote=chat.last("boss", "buttons"))
    assert store.slip_by_number(chat.db, 1).status == "APPROVED"


def test_webhook_marks_forwarded_messages():
    p = {"entry": [{"changes": [{"value": {"messages": [
        {"from": PHONES["abbas"], "id": "f1", "type": "text", "text": {"body": "Diglipur site requirements"},
         "context": {"forwarded": True}},
        {"from": PHONES["abbas"], "id": "f2", "type": "text", "text": {"body": "x"}, "context": {"frequently_forwarded": True}},
        {"from": PHONES["abbas"], "id": "f3", "type": "text", "text": {"body": "x"}},
    ]}}]}]}
    got = {m.wamid: m.forwarded for m in parse_webhook(p)}
    assert got == {"f1": True, "f2": True, "f3": False}


def test_dispatch_is_mirrored_to_sheets(chat):
    from purchasebot.google_sync import process_queue
    from test_integrations import FakeSync

    chat.requisition("siddhu", "gitti 20mm 4 brass")
    chat.slip("D1 Om Traders 6500")
    chat.say("boss", "yes")
    chat.say("abbas", "dispatch PS-1 Anand Bus")
    chat.tap("siddhu", "✅ All received")
    sync = FakeSync()
    process_queue(chat.db, sync, chat.bot.roster)
    rows = [r for t, rs in sync.upserts if t == "Dispatches" for r in rs]
    assert rows[-1][0] == "DSP-0001#1" and rows[-1][7] == "PS-0001" and rows[-1][13] == "RECEIVED"


def test_morning_list_for_abbas_and_evening_summary_for_dad(make_chat):
    from datetime import timedelta
    from purchasebot import clock

    chat = make_chat(logistics_todo_hour=8, daily_digest_hour=20)
    chat.say("abbas", "Diglipur: welding goggles 10 nos", forwarded=True)
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    clock.freeze(clock.now().replace(hour=8, minute=5) + timedelta(days=4))
    chat.bot.tick()
    todo = chat.last("abbas").body
    assert "Today's list" in todo and "D1 Welding goggles — 10 nos ⏰ 3d" in todo and "*Waiting for approval:* PS-0001" in todo
    clock.freeze(clock.now().replace(hour=20, minute=5))
    chat.bot.tick()
    digest = chat.last("boss").body
    assert "Daily summary" in digest and "Diglipur: 1 requested, no slip yet (oldest 4d)" in digest


def test_site_is_asked_again_if_dispatch_not_confirmed(chat):
    from datetime import timedelta
    from purchasebot import clock

    chat.requisition("siddhu", "gitti 20mm 4 brass")
    chat.slip("D1 Om Traders 6500")
    chat.say("boss", "yes")
    chat.say("abbas", "dispatch PS-1 Anand Bus")
    n = len(chat.wa.to(PHONES["siddhu"]))
    clock.freeze(clock.now() + timedelta(hours=49))
    chat.bot.tick()
    assert len(chat.wa.to(PHONES["siddhu"])) == n + 2  # the dispatch card again, once
    chat.bot.tick()
    assert len(chat.wa.to(PHONES["siddhu"])) == n + 2
