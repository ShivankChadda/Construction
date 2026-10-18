"""WhatsApp Cloud API (Meta) — sending, media, webhook parsing and signature check."""

from __future__ import annotations

import hashlib
import hmac
import itertools
import logging
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

# Meta error code when the person hasn't messaged us in 24h; only templates may be sent.
REENGAGEMENT_ERROR = 131047

MAX_BUTTON_TITLE = 20
MAX_BODY = 1024
MAX_TEXT = 4096


class WhatsAppError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"WhatsApp error {code}: {message}")
        self.code = code


@dataclass
class Incoming:
    wamid: str
    phone: str
    kind: str  # text | button | audio | image | document | reaction | other
    text: str = ""
    button_id: str = ""
    media_id: str = ""
    mime: str = ""
    filename: str = ""
    context_id: str = ""  # wamid of the message this one replies to (quoted)
    profile_name: str = ""
    timestamp: str = ""


class WhatsApp(Protocol):
    def send_text(self, to: str, text: str, reply_to: str = "") -> str: ...
    def send_buttons(self, to: str, body: str, buttons: list[tuple[str, str]], footer: str = "", reply_to: str = "") -> str: ...
    def send_document(self, to: str, path: str, caption: str = "", filename: str = "") -> str: ...
    def send_template(self, to: str, name: str, lang: str, body_params: list[str], button_payload: str = "") -> str: ...
    def download_media(self, media_id: str) -> tuple[bytes, str]: ...
    def mark_read(self, wamid: str) -> None: ...


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def parse_webhook(payload: dict) -> list[Incoming]:
    out: list[Incoming] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
            for st in value.get("statuses", []):
                if st.get("status") == "failed":
                    log.warning("WhatsApp delivery failed to %s: %s", st.get("recipient_id"), st.get("errors"))
            for m in value.get("messages", []):
                msg = Incoming(
                    wamid=m.get("id", ""),
                    phone=m.get("from", ""),
                    kind="other",
                    context_id=(m.get("context") or {}).get("id", ""),
                    profile_name=names.get(m.get("from"), ""),
                    timestamp=m.get("timestamp", ""),
                )
                t = m.get("type")
                if t == "text":
                    msg.kind, msg.text = "text", m["text"].get("body", "")
                elif t == "interactive":
                    it = m["interactive"]
                    reply = it.get("button_reply") or it.get("list_reply") or {}
                    msg.kind, msg.button_id, msg.text = "button", reply.get("id", ""), reply.get("title", "")
                elif t == "button":  # quick-reply button on a template
                    msg.kind, msg.button_id, msg.text = "button", m["button"].get("payload", ""), m["button"].get("text", "")
                elif t == "audio":
                    msg.kind, msg.media_id, msg.mime = "audio", m["audio"]["id"], m["audio"].get("mime_type", "audio/ogg")
                elif t == "image":
                    msg.kind, msg.media_id, msg.mime = "image", m["image"]["id"], m["image"].get("mime_type", "image/jpeg")
                    msg.text = m["image"].get("caption", "")
                elif t == "document":
                    d = m["document"]
                    msg.kind, msg.media_id, msg.mime = "document", d["id"], d.get("mime_type", "")
                    msg.text, msg.filename = d.get("caption", ""), d.get("filename", "")
                elif t == "reaction":
                    msg.kind, msg.text = "reaction", m["reaction"].get("emoji", "")
                    msg.context_id = m["reaction"].get("message_id", "")
                out.append(msg)
    return out


def _trim(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


class CloudWhatsApp:
    def __init__(self, phone_number_id: str, token: str, version: str = "v23.0", timeout: float = 30.0):
        self.base = f"https://graph.facebook.com/{version}"
        self.phone_number_id = phone_number_id
        self.http = httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {token}"})

    def _post(self, payload: dict) -> str:
        r = self.http.post(f"{self.base}/{self.phone_number_id}/messages", json={"messaging_product": "whatsapp", **payload})
        data = r.json() if r.content else {}
        if r.status_code >= 400 or "error" in data:
            err = data.get("error", {})
            raise WhatsAppError(int(err.get("code", r.status_code)), err.get("message", r.text))
        return data["messages"][0]["id"]

    def send_text(self, to: str, text: str, reply_to: str = "") -> str:
        payload: dict = {"to": to, "type": "text", "text": {"body": _trim(text, MAX_TEXT), "preview_url": False}}
        if reply_to:
            payload["context"] = {"message_id": reply_to}
        return self._post(payload)

    def send_buttons(self, to: str, body: str, buttons: list[tuple[str, str]], footer: str = "", reply_to: str = "") -> str:
        interactive: dict = {
            "type": "button",
            "body": {"text": _trim(body, MAX_BODY)},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": bid, "title": _trim(title, MAX_BUTTON_TITLE)}} for bid, title in buttons[:3]
            ]},
        }
        if footer:
            interactive["footer"] = {"text": _trim(footer, 60)}
        payload: dict = {"to": to, "type": "interactive", "interactive": interactive}
        if reply_to:
            payload["context"] = {"message_id": reply_to}
        return self._post(payload)

    def upload_media(self, path: str) -> str:
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            r = self.http.post(
                f"{self.base}/{self.phone_number_id}/media",
                data={"messaging_product": "whatsapp", "type": mime},
                files={"file": (Path(path).name, fh, mime)},
            )
        data = r.json()
        if r.status_code >= 400 or "error" in data:
            err = data.get("error", {})
            raise WhatsAppError(int(err.get("code", r.status_code)), err.get("message", r.text))
        return data["id"]

    def send_document(self, to: str, path: str, caption: str = "", filename: str = "") -> str:
        media_id = self.upload_media(path)
        doc = {"id": media_id, "filename": filename or Path(path).name}
        if caption:
            doc["caption"] = _trim(caption, MAX_BODY)
        return self._post({"to": to, "type": "document", "document": doc})

    def send_template(self, to: str, name: str, lang: str, body_params: list[str], button_payload: str = "") -> str:
        components: list[dict] = [{"type": "body", "parameters": [{"type": "text", "text": _trim(p, 900)} for p in body_params]}]
        if button_payload:
            components.append({"type": "button", "sub_type": "quick_reply", "index": "0",
                               "parameters": [{"type": "payload", "payload": button_payload}]})
        return self._post({"to": to, "type": "template",
                           "template": {"name": name, "language": {"code": lang}, "components": components}})

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        meta = self.http.get(f"{self.base}/{media_id}")
        meta.raise_for_status()
        info = meta.json()
        blob = self.http.get(info["url"])
        blob.raise_for_status()
        return blob.content, info.get("mime_type", "application/octet-stream")

    def mark_read(self, wamid: str) -> None:
        try:
            self.http.post(f"{self.base}/{self.phone_number_id}/messages",
                           json={"messaging_product": "whatsapp", "status": "read", "message_id": wamid})
        except httpx.HTTPError:
            pass


@dataclass
class Sent:
    wamid: str
    to: str
    kind: str  # text | buttons | document | template
    body: str
    buttons: list[tuple[str, str]] = field(default_factory=list)
    path: str = ""
    reply_to: str = ""


class FakeWhatsApp:
    """In-memory WhatsApp for tests and the terminal simulator."""

    def __init__(self, media: dict[str, tuple[bytes, str]] | None = None, closed_windows: set[str] | None = None):
        self.sent: list[Sent] = []
        self.media = media or {}
        self.closed_windows = closed_windows or set()  # phones outside the 24h window
        self._ids = itertools.count(1)
        self.listeners: list = []

    def _record(self, s: Sent) -> str:
        if s.kind != "template" and s.to in self.closed_windows:
            raise WhatsAppError(REENGAGEMENT_ERROR, "Re-engagement message")
        self.sent.append(s)
        for fn in self.listeners:
            fn(s)
        return s.wamid

    def _id(self) -> str:
        return f"wamid.out.{next(self._ids)}"

    def send_text(self, to, text, reply_to=""):
        return self._record(Sent(self._id(), to, "text", text, reply_to=reply_to))

    def send_buttons(self, to, body, buttons, footer="", reply_to=""):
        return self._record(Sent(self._id(), to, "buttons", body + (f"\n_{footer}_" if footer else ""), list(buttons[:3]), reply_to=reply_to))

    def send_document(self, to, path, caption="", filename=""):
        return self._record(Sent(self._id(), to, "document", caption, path=path))

    def send_template(self, to, name, lang, body_params, button_payload=""):
        self.closed_windows.discard(to)
        return self._record(Sent(self._id(), to, "template", " | ".join(body_params), [(button_payload, "Show details")] if button_payload else []))

    def download_media(self, media_id):
        return self.media[media_id]

    def mark_read(self, wamid):
        pass

    # helpers for tests
    def to(self, phone: str) -> list[Sent]:
        return [s for s in self.sent if s.to == phone]

    def last(self, phone: str, kind: str | None = None) -> Sent:
        msgs = [s for s in self.to(phone) if kind is None or s.kind == kind]
        if not msgs:
            raise AssertionError(f"nothing sent to {phone}" + (f" of kind {kind}" if kind else ""))
        return msgs[-1]

    def clear(self) -> None:
        self.sent.clear()
