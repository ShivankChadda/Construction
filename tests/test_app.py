import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from purchasebot import store
from purchasebot.app import create_app
from purchasebot.whatsapp import parse_webhook, verify_signature

from conftest import PHONES

SECRET = "app-secret"


def _client(chat, **kw):
    settings = chat.bot.s.model_copy(update={"wa_app_secret": SECRET, "wa_verify_token": "tok", **kw})
    chat.bot.s = settings
    return TestClient(create_app(bot=chat.bot, settings=settings, run_scheduler=False))


def _payload(phone, wamid, text):
    return {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": phone, "profile": {"name": "X"}}],
        "messages": [{"from": phone, "id": wamid, "timestamp": "1", "type": "text", "text": {"body": text}}],
    }}]}]}


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_verification_handshake(chat):
    c = _client(chat)
    r = c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "tok", "hub.challenge": "42"})
    assert r.status_code == 200 and r.text == "42"
    assert c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "bad", "hub.challenge": "42"}).status_code == 403


def test_webhook_rejects_bad_signature_and_processes_good_one(chat):
    c = _client(chat)
    body = json.dumps(_payload(PHONES["chandra"], "wamid.1", "cement 50 bags")).encode()
    assert c.post("/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=deadbeef"}).status_code == 401
    assert not chat.wa.sent
    r = c.post("/webhook", content=body, headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"})
    assert r.status_code == 200
    assert "Requirement – Nicobar" in chat.texts("chandra")


def test_unsigned_webhooks_refused_without_secret(chat):
    c = _client(chat, wa_app_secret="", allow_unsigned_webhooks=False)
    assert c.post("/webhook", content=b"{}").status_code == 401


def test_verify_page_valid_then_tampered(chat):
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    chat.say("boss", "yes")
    slip = store.slip_by_number(chat.db, 1)
    c = _client(chat)
    url = urlparse(chat.bot.verify_url(slip))
    code = parse_qs(url.query)["c"][0]
    r = c.get(url.path, params={"c": code})
    assert r.status_code == 200 and "Genuine" in r.text and "Rajesh Chadda" in r.text

    assert c.get(url.path, params={"c": "WRONG-CODE"}).status_code == 404
    assert c.get("/verify/PS-9999", params={"c": code}).status_code == 404

    chat.db.run("UPDATE slip_lines SET rate = 380, amount = 19000")  # someone edits the record
    r = c.get(url.path, params={"c": code})
    assert "FAILED" in r.text


def test_signature_helper():
    body = b'{"a":1}'
    assert verify_signature(SECRET, body, _sign(body))
    assert not verify_signature(SECRET, body + b" ", _sign(body))
    assert not verify_signature(SECRET, body, None)


def test_parse_webhook_variants():
    p = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "91", "id": "a", "type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": "AP_YES:1:1", "title": "ok"}}},
        {"from": "91", "id": "b", "type": "button", "button": {"payload": "SHOW_PENDING", "text": "Show details"}},
        {"from": "91", "id": "c", "type": "audio", "audio": {"id": "m1", "mime_type": "audio/ogg; codecs=opus"}},
        {"from": "91", "id": "d", "type": "image", "image": {"id": "m2", "caption": "Nicobar list"}},
        {"from": "91", "id": "e", "type": "text", "text": {"body": "yes"}, "context": {"id": "wamid.out.7"}},
        {"from": "91", "id": "f", "type": "reaction", "reaction": {"emoji": "👍", "message_id": "wamid.out.9"}},
    ]}}]}]}
    m = {x.wamid: x for x in parse_webhook(p)}
    assert m["a"].kind == "button" and m["a"].button_id == "AP_YES:1:1"
    assert m["b"].button_id == "SHOW_PENDING"
    assert m["c"].kind == "audio" and m["c"].media_id == "m1"
    assert m["d"].kind == "image" and m["d"].text == "Nicobar list"
    assert m["e"].context_id == "wamid.out.7"
    assert m["f"].kind == "reaction" and m["f"].text == "👍" and m["f"].context_id == "wamid.out.9"


def test_thumbs_up_reaction_on_slip_asks_for_confirmation(chat):
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    card = chat.last("boss", "buttons")
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"from": PHONES["boss"], "id": "r1", "type": "reaction", "reaction": {"emoji": "👍", "message_id": card.wamid}}]}}]}]}
    for msg in parse_webhook(payload):
        chat.bot.handle(msg)
    assert store.slip_by_number(chat.db, 1).status == "PENDING"  # a reaction alone never approves
    chat.tap("boss", "✅ Confirm")
    assert store.slip_by_number(chat.db, 1).status == "APPROVED"


def test_reactions_from_others_are_ignored(chat):
    chat.requisition("chandra", "cement 50 bags")
    n = len(chat.wa.sent)
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"from": PHONES["chandra"], "id": "r2", "type": "reaction", "reaction": {"emoji": "👍", "message_id": "x"}}]}}]}]}
    for msg in parse_webhook(payload):
        chat.bot.handle(msg)
    assert len(chat.wa.sent) == n
