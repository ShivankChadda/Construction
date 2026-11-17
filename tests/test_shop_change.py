"""After approval, the shop doesn't have an item: change the shop (approved again) or take it off the challan."""

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from purchasebot import store
from purchasebot.app import create_app
from purchasebot.llm import ParsedSlipLine, RuleParser, SlipParse
from purchasebot.signing import canonical

from conftest import PHONES

DIGLIPUR = "LED light 6 nos\nbinding wire 10 bundle\nelectrical wire 2 bundle"  # D1, D2, D3


class Abbas(RuleParser):
    """Stands in for Claude reading Abbas's voice note; records what it was shown."""

    def __init__(self):
        self.reply: list[ParsedSlipLine] | None = None
        self.approved_seen: list[dict] | None = None

    def parse_slip(self, text, open_items, vendors, sites, known_items, current=None, approved=None):
        self.approved_seen = approved
        if self.reply is None:
            return super().parse_slip(text, open_items, vendors, sites, known_items, current, approved)
        lines, self.reply = self.reply, None
        return SlipParse(lines=lines)


def _approved(make_chat):
    """PS-0001 approved: D1 + D3 from Ganga Agency (PS-0001-1), D2 from Hira Metals (PS-0001-2)."""
    parser = Abbas()
    chat = make_chat(parser=parser)
    chat.requisition("siddhu", DIGLIPUR)
    chat.slip("D1 D3 Ganga Agency\nD2 Hira Metals")
    chat.say("boss", "yes")
    return chat, parser


def _line(chat, ref: str, slip_no: int = 1):
    return next(l for l in store.slip_by_number(chat.db, slip_no).lines if l.ref == ref)


def test_voice_correction_after_approval_goes_for_approval_and_moves_the_item(make_chat):
    chat, parser = _approved(make_chat)
    # "One correction: D1 LED light for Diglipur isn't at Ganga Agency, we'll take it from Navjeevan.
    #  Please share this. Is it approved or not, sir?"
    parser.reply = [ParsedSlipLine("D1", "DIG", "LED light", "led light", 6, "nos", "Navjeevan", 0,
                                   remark="not available at Ganga Agency")]
    chat.voice("abbas", "D1 LED light Ganga Agency mein nahi hai, Navjeevan se lena hoga. Please share. Approved hai ki nahi sir?")
    assert [(a["ref"], a["vendor"], a["challan_no"]) for a in parser.approved_seen] == [
        ("D1", "Ganga Agency", "PS-0001-1"), ("D3", "Ganga Agency", "PS-0001-1"), ("D2", "Hira Metals", "PS-0001-2")]
    draft = chat.texts("abbas").split("---")[-2]
    assert "PS-0002* — draft" in draft and "not an open requirement" not in draft
    assert "🔁 *Change to approved list PS-0001-1* — needs approval again" in draft
    assert "🏪 Navjeevan" in draft and "_not available at Ganga Agency_" in draft
    assert "Change to PS-0001-1: was 6 nos from Ganga Agency, approved 18 Oct 2026" in draft
    assert "Already bought" not in draft  # the approval being changed is not a repeat purchase

    chat.tap("abbas", "📤 Send for approval")
    assert store.item_by_ref(chat.db, "D1")["status"] == "ORDERED"  # still approved at Ganga until decided
    card = [s.body for s in chat.wa.to(PHONES["boss"])][-3:]
    assert card[0] == "PS-0002 — for your approval" and "Change to PS-0001-1" in card[1]

    chat.say("boss", "haan")
    new, old = _line(chat, "D1", 2), _line(chat, "D1", 1)
    assert new.status == "APPROVED" and (old.status, old.replaced_by) == ("MOVED", new.id)
    assert [(c.challan_no, c.vendor) for c in store.challans_for_slip(chat.db, 2)] == [("PS-0002-1", "Navjeevan")]
    told = chat.texts("abbas")
    assert "↪️ D1 LED light — now from *Navjeevan* (PS-0002-1); taken off PS-0001-1 (Ganga Agency), don't buy it there" in told
    assert "PS-0002 update" not in chat.texts("siddhu")  # nothing changed for the site

    # What was signed still verifies; the old challan stays open for D3 only and its QR page says so.
    old_slip = store.slip_by_number(chat.db, 1)
    assert chat.bot.signer.verify(canonical(chat.bot.signed_payload(old_slip)), old_slip.signature)
    ganga = store.challan_by_number(chat.db, "PS-0001-1")
    assert ganga.status == "OPEN" and chat.bot.signer.verify(canonical(chat.bot.challan_payload(ganga)), ganga.signature)
    c = TestClient(create_app(bot=chat.bot, settings=chat.bot.s, run_scheduler=False))
    url = urlparse(chat.bot.verify_url(ganga))
    page = c.get(url.path, params={"c": parse_qs(url.query)["c"][0]}).text
    assert "Genuine and valid" in page and "Cancelled — do not supply" in page and "cancelled after approval" in page
    url = urlparse(chat.bot.verify_url(old_slip))
    page = c.get(url.path, params={"c": parse_qs(url.query)["c"][0]}).text
    assert "Genuine" in page and "later moved to PS-0002" in page

    # Ganga bills only D3 now, and that finishes its challan. D1 goes out once, on PS-0002.
    chat.say("abbas", "Bill 77\nElectrical wire 2 bundle 900")
    assert "Not on this bill" not in chat.texts("abbas").split("---")[-2]
    chat.tap("abbas", "✅ Record bill")
    assert store.challan_by_number(chat.db, "PS-0001-1").status == "BILLED"
    chat.say("abbas", "dispatch PS-1 Diglipur MV Campbell Bay")
    sent = [i.name for d in store.open_dispatches(chat.db, "DIG") for i in d.items]
    assert sorted(sent) == ["Binding wire", "Electrical wire"]  # not the LED light: it moved to PS-0002


def test_refused_change_leaves_the_first_approval(make_chat):
    chat, _ = _approved(make_chat)
    chat.slip("D1 Navjeevan")
    chat.say("boss", "no")
    assert store.slip_by_number(chat.db, 2).status == "REJECTED"
    assert _line(chat, "D1", 1).status == "APPROVED"
    assert store.item_by_ref(chat.db, "D1")["status"] == "ORDERED"
    assert "↩️ D1 LED light — change not approved; stays on PS-0001-1 (Ganga Agency)" in chat.texts("abbas")


def test_not_available_anywhere_takes_it_off_the_challan_without_approval(make_chat):
    chat, _ = _approved(make_chat)
    assert chat.db.one("SELECT status FROM requisitions")["status"] == "CLOSED"
    n_boss = len(chat.wa.to(PHONES["boss"]))
    chat.slip("D2 not available\nD1 not needed")
    assert chat.last("abbas", "buttons").buttons[0][1] == "📤 Record"
    assert _line(chat, "D2").status == "CANCELLED" and _line(chat, "D1").status == "CANCELLED"
    assert store.challan_by_number(chat.db, "PS-0001-2").status == "CANCELLED"  # Hira had only D2
    assert store.challan_by_number(chat.db, "PS-0001-1").status == "OPEN"       # Ganga still has D3
    d2 = store.item_by_ref(chat.db, "D2")
    assert d2["status"] == "OPEN" and d2["note"].startswith("Not available") and d2["req_status"] == "SUBMITTED"
    assert store.item_by_ref(chat.db, "D1")["status"] == "DROPPED"
    assert "D2" in [i["ref"] for i in store.open_items(chat.db)]
    assert "Change to approved list" not in chat.texts("abbas")  # taking items off needs no approval
    assert "_(taken off PS-0001-2, Hira Metals)_" in chat.texts("abbas")
    msg = chat.last("abbas").body
    assert "Taken off the challans — don't buy these there:" in msg and "✖️ D2 Binding wire — PS-0001-2 Hira Metals" in msg
    fyi = [s.body for s in chat.wa.to(PHONES["boss"])][n_boss:]
    assert len(fyi) == 1 and "took these off approved lists (no approval needed)" in fyi[0]

    c = TestClient(create_app(bot=chat.bot, settings=chat.bot.s, run_scheduler=False))
    hira = store.challan_by_number(chat.db, "PS-0001-2")
    url = urlparse(chat.bot.verify_url(hira))
    assert "This challan was cancelled" in c.get(url.path, params={"c": parse_qs(url.query)["c"][0]}).text


def test_billed_items_and_repeated_shops_are_not_changed(make_chat):
    chat, _ = _approved(make_chat)
    chat.say("abbas", "Bill 9\nLED light 6 nos 300")
    chat.tap("abbas", "✅ Record bill")
    chat.say("abbas", "D1 Navjeevan\nD3 Ganga Agency")
    msg = chat.last("abbas").body
    assert "couldn't make a purchase list" in msg
    assert "D1 LED light was already billed or sent on PS-0001-1 (Ganga Agency) — it can't be changed now" in msg
    assert "D3 Electrical wire is already approved from Ganga Agency (PS-0001-1) — nothing changed" in msg


def test_one_change_at_a_time_and_waiting_items_point_to_their_list(make_chat):
    chat, _ = _approved(make_chat)
    chat.slip("D1 Navjeevan")
    chat.say("abbas", "D1 Om Traders")
    assert "D1 LED light already has a change on PS-0002 — send *edit PS-0002* to change it" in chat.last("abbas").body
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders")
    chat.say("abbas", "N1 Hira Metals")
    assert "N1 Cement is on PS-0003, waiting for approval — send *edit PS-0003* to change it" in chat.last("abbas").body


def test_pulling_back_a_list_puts_cancelled_items_back_on_their_challan(make_chat):
    chat, _ = _approved(make_chat)
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders\nD2 not needed")
    assert _line(chat, "D2").status == "CANCELLED"
    assert store.challan_by_number(chat.db, "PS-0001-2").status == "CANCELLED"
    chat.say("abbas", "edit PS-2")
    assert (_line(chat, "D2").status, _line(chat, "D2").replaced_by) == ("APPROVED", None)
    assert store.challan_by_number(chat.db, "PS-0001-2").status == "OPEN"
    assert store.item_by_ref(chat.db, "D2")["status"] == "ORDERED"
    dig = chat.db.one("SELECT status FROM requisitions WHERE site_code = 'DIG'")
    assert dig["status"] == "CLOSED"


def test_claude_is_shown_approved_items_and_told_to_ignore_requests():
    from test_integrations import FakeAnthropicClient

    from purchasebot.llm import ClaudeParser

    client = FakeAnthropicClient({"lines": [
        {"ref": "d1", "site_code": "dig", "name": "LED light", "item_key": "led light", "qty": 6, "unit": "nos",
         "action": "BUY", "vendor": "Navjeevan", "rate": 0, "lump_sum": 0, "remark": "not available at Ganga Agency"}],
        "unclear": [], "note": ""})
    r = ClaudeParser(client=client).parse_slip(
        "D1 Ganga mein nahi hai, Navjeevan se lena hoga. Please share.", [], ["Ganga Agency"], [("DIG", "Diglipur")], [],
        approved=[{"ref": "D1", "site_code": "DIG", "name": "LED light", "qty": 6, "unit": "nos", "item_key": "led light",
                   "vendor": "Ganga Agency", "challan_no": "PS-0002-1", "slip_no": "PS-0002"}])
    assert (r.lines[0].ref, r.lines[0].vendor) == ("D1", "Navjeevan")
    call = client.calls[0]
    sent = call["messages"][0]["content"][0]["text"]
    assert "APPROVED, NOT BOUGHT YET:\nD1 | site=DIG | LED light | 6 nos | key=led light | approved shop=Ganga Agency | PS-0002-1" in sent
    system = call["system"] if isinstance(call["system"], str) else " ".join(b["text"] for b in call["system"])
    assert "approved hai ki nahi" in system and "Navjeevan se lena hoga" in system
