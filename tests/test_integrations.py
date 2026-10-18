"""Claude, Sarvam and Google adapters, exercised against fakes (no network)."""

import json
from types import SimpleNamespace

import httpx
import pytest

from purchasebot import store
from purchasebot.google_sync import enqueue, process_queue
from purchasebot.llm import ClaudeParser, ParseError
from purchasebot.speech import SarvamSpeech


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
         "vendor": "Om Traders", "rate": 420, "lump_sum": 0}], "unclear": [], "note": ""})
    r = ClaudeParser(client=client).parse_slip("N1 om 420", [{"ref": "N1", "site_code": "NIC", "name": "Cement",
                                                             "qty": 50, "unit": "bag", "item_key": "cement"}],
                                               ["Om Traders"], [("NIC", "Nicobar")], [])
    assert (r.lines[0].ref, r.lines[0].site_code, r.lines[0].unit) == ("N1", "NIC", "bag")


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
