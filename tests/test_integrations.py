"""Claude, Sarvam and Google adapters, exercised against fakes (no network)."""

import json
from types import SimpleNamespace

import httpx
import pytest

from purchasebot import store
from purchasebot.google_sync import enqueue, process_queue
from purchasebot.llm import ClaudeParser, ParseError
from purchasebot.speech import SarvamSpeech
from purchasebot.whatsapp import CloudWhatsApp, WhatsAppError


class FakeAnthropicClient:
    def __init__(self, payload, stop_reason="end_turn"):
        self.calls = []
        self.payload = payload
        self.stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        content = [SimpleNamespace(type="text", text=json.dumps(self.payload))] if self.stop_reason != "refusal" else []
        return SimpleNamespace(stop_reason=self.stop_reason, content=content)


def test_claude_requisition_request_shape_and_parsing():
    client = FakeAnthropicClient({
        "items": [{"name": "TMT bar 12 mm", "item_key": "TMT 12mm", "qty": 2, "unit": "Ton", "spec": ""},
                  {"name": "Cement OPC 53 grade", "item_key": "cement opc 53", "qty": 50, "unit": "bori", "spec": "ACC"}],
        "unclear": [], "needed_by": "next ship", "urgent": True, "note": "",
    })
    p = ClaudeParser(client=client)
    r = p.parse_requisition("do ton sariya 12mm, pachaas bori cement ACC, jaldi", "Nicobar", ["cement opc 53"],
                            images=[(b"\x89PNG", "image/png")])
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["messages"][0]["content"][0]["type"] == "image"
    assert "KNOWN ITEM KEYS: cement opc 53" in call["messages"][0]["content"][-1]["text"]
    assert [(i.item_key, i.qty, i.unit) for i in r.items] == [("tmt 12mm", 2, "mt"), ("cement opc 53", 50, "bag")]
    assert r.urgent and r.needed_by == "next ship"


def test_claude_refusal_becomes_parse_error():
    p = ClaudeParser(client=FakeAnthropicClient({}, stop_reason="refusal"))
    with pytest.raises(ParseError):
        p.parse_requisition("x", "Nicobar", [])


def test_claude_slip_parsing():
    client = FakeAnthropicClient({"lines": [
        {"ref": "n1", "site_code": "nic", "name": "Cement", "item_key": "cement", "qty": 50, "unit": "bags",
         "action": "BUY", "vendor": "Om Traders", "rate": 0, "lump_sum": 0, "remark": ""},
        {"ref": "n2", "site_code": "nic", "name": "Sand", "item_key": "sand", "qty": 3, "unit": "truck",
         "action": "SENT", "vendor": "", "rate": 0, "lump_sum": 0, "remark": "MV Manav Star"}], "unclear": [], "note": ""})
    r = ClaudeParser(client=client).parse_slip("N1 om se, N2 already sent", [
        {"ref": "N1", "site_code": "NIC", "name": "Cement", "qty": 50, "unit": "bag", "item_key": "cement"},
        {"ref": "N2", "site_code": "NIC", "name": "Sand", "qty": 3, "unit": "truck", "item_key": "sand"}],
        ["Om Traders"], [("NIC", "Nicobar")], [])
    assert (r.lines[0].ref, r.lines[0].site_code, r.lines[0].unit, r.lines[0].action) == ("N1", "NIC", "bag", "BUY")
    assert (r.lines[1].action, r.lines[1].remark) == ("SENT", "MV Manav Star")
    sent = client.calls[0]
    assert "KNOWN SHOPS: Om Traders" in sent["messages"][0]["content"][0]["text"]
    assert sent["output_config"]["format"]["schema"]["properties"]["lines"]["items"]["properties"]["action"]["enum"] == \
        ["BUY", "PENDING", "SENT", "DROP"]


def test_claude_bill_reading_and_rate_matching():
    client = FakeAnthropicClient({"vendor": "OM TRADERS", "bill_no": "4521", "bill_date": "2026-10-19",
                                  "lines": [{"name": "Cement OPC", "item_key": "cement", "qty": 50, "unit": "bags",
                                             "rate": 410, "amount": 20500, "slip_line_id": 7}],
                                  "tax_total": 0, "grand_total": 20500, "unclear": []})
    b = ClaudeParser(client=client).parse_bill("bill", [(b"\xff\xd8", "image/jpeg")],
                                               [{"id": 7, "name": "Cement", "qty": 50, "unit": "bag", "vendor": "Om Traders",
                                                 "challan_no": "PS-0001-1"}])
    assert (b.vendor, b.bill_no, b.lines[0].unit, b.lines[0].slip_line_id) == ("OM TRADERS", "4521", "bag", 7)
    content = client.calls[0]["messages"][0]["content"]
    assert content[0]["type"] == "image" and "7 | Cement | 50 bag | Om Traders | PS-0001-1" in content[1]["text"]

    client = FakeAnthropicClient({"matches": [{"item": 1, "past": 2}, {"item": 2, "past": 0}, {"item": 9, "past": 1}]})
    m = ClaudeParser(client=client).match_rates([
        {"name": "Saria 12mm", "unit": "mt", "candidates": [{"name": "Binding wire", "unit": ""}, {"name": "TMT bar 12 mm", "unit": ""}]},
        {"name": "Hand gloves", "unit": "pair", "candidates": [{"name": "Gum boots", "unit": ""}]}])
    assert m == {0: 1}
    assert client.calls[0]["output_config"]["effort"] == "low"


def test_sarvam_request():
    seen = {}

    def handler(request: httpx.Request):
        seen["headers"] = request.headers
        seen["body"] = request.content
        return httpx.Response(200, json={"transcript": "पचास बैग सीमेंट", "language_code": "hi-IN"})

    s = SarvamSpeech("key123")
    s.http = httpx.Client(transport=httpx.MockTransport(handler))
    assert s.transcribe(b"OggS...", "audio/ogg; codecs=opus") == "पचास बैग सीमेंट"
    assert seen["headers"]["api-subscription-key"] == "key123"
    assert b"saaras:v4" in seen["body"] and b"keyterms" in seen["body"] and b'filename="voice.ogg"' in seen["body"]


def test_whatsapp_register_request_and_refusal():
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.url.path, json.loads(request.content)))
        if len(seen) == 1:
            return httpx.Response(200, json={"success": True})
        return httpx.Response(400, json={"error": {"code": 133016, "message": "Too many registration attempts"}})

    wa = CloudWhatsApp("1234", "tok")
    wa.http = httpx.Client(transport=httpx.MockTransport(handler))
    wa.register("482915")
    assert seen[0] == ("/v23.0/1234/register", {"messaging_product": "whatsapp", "pin": "482915"})
    with pytest.raises(WhatsAppError) as e:
        wa.register("482915")
    assert e.value.code == 133016


def test_whatsapp_lists_numbers_the_token_can_reach(capsys):
    from purchasebot.cli import _wa_numbers

    def handler(request: httpx.Request):
        path = request.url.path
        if path.endswith("/debug_token"):
            assert request.url.params["input_token"] == "tok"
            return httpx.Response(200, json={"data": {"granular_scopes": [
                {"scope": "whatsapp_business_management", "target_ids": ["111", "222"]},
                {"scope": "whatsapp_business_messaging", "target_ids": ["111"]},
                {"scope": "business_management", "target_ids": ["999"]}]}})
        if path.endswith("/111/phone_numbers"):
            return httpx.Response(200, json={"data": [
                {"id": "555001", "display_phone_number": "+91 92398 21334", "verified_name": "Kailash Engineering Company",
                 "status": "CONNECTED"}]})
        return httpx.Response(400, json={"error": {"code": 100, "message": "Unsupported get request"}})

    wa = CloudWhatsApp("", "tok")
    wa.http = httpx.Client(transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer tok"})
    numbers, notes = wa.list_numbers()
    assert [(n["id"], n["account_id"]) for n in numbers] == [("555001", "111")]
    assert notes[0] == "Token lists messaging accounts: 111, 222"
    assert any(n.startswith("222: WhatsApp error 100") for n in notes)

    settings = SimpleNamespace(wa_access_token="tok", wa_phone_number_id="555001")
    _wa_numbers(settings, client=wa)
    out = capsys.readouterr().out
    assert "+91 92398 21334" in out and "WA_PHONE_NUMBER_ID=555001" in out and "in use" in out

    # An explicit account ID skips the token lookup entirely.
    numbers, notes = wa.list_numbers(["111"])
    assert [n["id"] for n in numbers] == ["555001"] and notes == []


def test_wa_numbers_explains_an_empty_result(capsys):
    from purchasebot.cli import _wa_numbers

    def handler(request: httpx.Request):
        if request.url.path.endswith("/debug_token"):
            return httpx.Response(200, json={"data": {"granular_scopes": [{"scope": "whatsapp_business_messaging"}]}})
        return httpx.Response(404)

    wa = CloudWhatsApp("", "tok")
    wa.http = httpx.Client(transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer tok"})
    with pytest.raises(SystemExit) as e:
        _wa_numbers(SimpleNamespace(wa_access_token="tok", wa_phone_number_id=""), client=wa)
    assert "asset_id" in str(e.value)
    assert "Token lists messaging accounts: none" in capsys.readouterr().out


def test_wa_subscribe_posts_then_lists_apps(capsys):
    from purchasebot.cli import _wa_subscribe

    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json={"data": [
            {"whatsapp_business_api_data": {"name": "Kailash Purchase Desk", "id": "1424811252480092"}}]})

    wa = CloudWhatsApp("", "tok")
    wa.http = httpx.Client(transport=httpx.MockTransport(handler))
    _wa_subscribe(SimpleNamespace(wa_access_token="tok"), "939883728955320", client=wa)
    assert seen == [("POST", "/v23.0/939883728955320/subscribed_apps"), ("GET", "/v23.0/939883728955320/subscribed_apps")]
    assert "Kailash Purchase Desk" in capsys.readouterr().out


def test_cli_keeps_request_urls_out_of_the_log():
    import logging

    from purchasebot.cli import main

    main(["gen-key"])
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


class FakeSync:
    def __init__(self, fail_times=0):
        self.upserts = []
        self.uploads = []
        self.fail_times = fail_times

    def upsert(self, tab, rows):
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("network down")
        self.upserts.append((tab, rows))

    def replace(self, tab, rows):
        self.upserts.append((tab, rows))

    def upload(self, path, *folders):
        self.uploads.append((str(path), folders))
        return "https://drive.google.com/file/d/abc/view"


def test_google_queue_mirrors_slip_and_uploads_pdf(chat):
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    chat.say("boss", "yes")
    sync = FakeSync()
    done = process_queue(chat.db, sync, chat.bot.roster)
    assert done >= 2
    tabs = {t for t, _ in sync.upserts}
    assert {"Purchase Register", "Requisitions"} <= tabs
    assert sync.uploads[0][1] == ("Purchase Slips", "2026", "10-October")
    reg = [rows for t, rows in sync.upserts if t == "Purchase Register"][-1]
    assert reg[0][0] == "PS-0001#1" and reg[0][3] == "APPROVED"
    assert store.slip_by_number(chat.db, 1).drive_link.startswith("https://drive.google.com")
    assert chat.db.one("SELECT COUNT(*) AS n FROM sync_queue")["n"] == 0


def test_google_queue_retries_after_failure(chat):
    chat.requisition("chandra", "cement 50 bags")
    sync = FakeSync(fail_times=1)
    assert process_queue(chat.db, sync, chat.bot.roster) == 0
    job = chat.db.one("SELECT attempts, last_error FROM sync_queue")
    assert job["attempts"] == 1 and "network down" in job["last_error"]
    assert process_queue(chat.db, sync, chat.bot.roster) == 1
    enqueue(chat.db, "req", 1)
    enqueue(chat.db, "req", 1)  # de-duplicated
    assert chat.db.one("SELECT COUNT(*) AS n FROM sync_queue")["n"] == 1


def test_real_sdk_serializes_structured_output_and_fallbacks():
    """Run the real Anthropic SDK against a mock transport to check the wire format."""
    import anthropic

    try:
        import httpx2 as hx
    except ImportError:  # older SDKs use httpx
        hx = httpx
    seen = {}

    def handler(req):
        seen["headers"], seen["body"] = req.headers, json.loads(req.content)
        return hx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps({"lines": [{"line_no": 1, "qty": 45}]})}],
            "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})

    client = anthropic.Anthropic(api_key="sk-test", http_client=hx.Client(transport=hx.MockTransport(handler)))
    got = ClaudeParser(client=client).parse_receipt("cement 45 aaya", [{"line_no": 1, "name": "Cement", "qty": 50, "unit": "bag"}])
    assert got[0].qty == 45
    assert seen["headers"]["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert seen["body"]["fallbacks"] == "default"
    assert seen["body"]["output_config"]["format"]["schema"]["required"] == ["lines"]
