"""Run the real Purchase Desk bot through the tutorial's story and record every message it sends.

    python3 video/capture.py            # -> video/build/capture.json, PDFs and page images in video/build/bot/

The video never invents a bot message: each bubble on screen is the text, buttons and PDF that
src/purchasebot sends for that step. The story is the one the tutorial tells: three sites post in the
"Kailash Material" group, Abbas forwards the posts, prices a slip, Munishwer Chander Chadda asks a
question and approves all but one line, Abbas dispatches, and the sites confirm what arrived.

Offline: the bot's rule parser reads plain lines. A Hindi voice note and a photo of a handwritten list
need Claude in real use; here SCRIPTED stands in for what Claude reads from them, and everything after
that (numbering, site buttons, alerts, approval rules, signing) is the bot's own code.
"""
from __future__ import annotations

import itertools
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from purchasebot import clock  # noqa: E402
from purchasebot.bootstrap import build_bot  # noqa: E402
from purchasebot.config import get_settings  # noqa: E402
from purchasebot.db import DB  # noqa: E402
from purchasebot.llm import ParsedItem, ReqParse, RuleParser  # noqa: E402
from purchasebot.roster import load_roster  # noqa: E402
from purchasebot.whatsapp import FakeWhatsApp, Incoming  # noqa: E402

OUT = HERE / "build" / "bot"

# What Claude reads from the two posts the rule parser can't: Tambi Uncle's Hindi voice note and
# Siddhu's photo of a handwritten list (the photo itself is drawn by video/web/art.py).
VOICE_TAMBI = "बाइंडिंग वायर पच्चीस किलो और शटरिंग प्लाई बीस शीट चाहिए"
SCRIPTED = {
    VOICE_TAMBI: [("Binding wire", 25, "kg"), ("Shuttering ply", 20, "sheet")],
    "Diglipur site": [("Cement OPC 53 grade", 30, "bag"), ("Gitti 20mm", 4, "brass"), ("Welding goggles", 10, "nos")],
}

# The group posts Abbas forwards (the same text is shown in the group on screen).
POST_NIC = "Car Nicobar site requirement\nCement OPC 53 grade 50 bag\nTMT 12mm 2 mt\nRiver sand 3 truck"
POST_DIG_CAPTION = "Diglipur site"
POST_CHAT = "ok sir"
POST_DISPATCH = ("Diglipur Sector - Cement, gitti and welding goggles loaded in Anand Bus AN01F3868 departed today "
                 "at 10.00 AM. Bus will be parked near BD BAR. Transportation not paid.")
SLIP_LINES = ("N2 Om Traders 420\nN3 Hira Metals 62000\nN4 Om Traders 9500\nK1 Hira Metals 85\n"
              "K2 Sagar Hardware 1450\nD1 Om Traders 420\nD2 Om Traders 6500\nD3 Om Traders 180")


class ScriptedParser(RuleParser):
    def parse_requisition(self, text, site_name, known_items, current=None, images=None):
        if text.strip() in SCRIPTED:
            from purchasebot.llm import norm_key
            return ReqParse(items=[ParsedItem(n, norm_key(n), q, u) for n, q, u in SCRIPTED[text.strip()]])
        return super().parse_requisition(text, site_name, known_items, current, images)


class ScriptedSpeech:
    def transcribe(self, audio: bytes, mime: str) -> str:
        return audio.decode()


class Story:
    def __init__(self):
        if OUT.exists():
            shutil.rmtree(OUT)
        OUT.mkdir(parents=True)  # the signing key lives one level up, so codes stay the same between runs
        settings = get_settings().model_copy(update={
            "pdf_dir": str(OUT / "pdfs"), "backup_dir": str(OUT / "backups"), "signing_key_path": str(HERE / "build" / "signing.key"),
            "google_auth_mode": "none", "forward_batch_seconds": 3600, "public_base_url": "https://desk.example.in",
            "anthropic_api_key": "", "sarvam_api_key": ""})
        self.roster = load_roster(HERE / "roster.yaml")
        self.wa = FakeWhatsApp()
        self.bot = build_bot(settings, wa=self.wa, parser=ScriptedParser(), speech=ScriptedSpeech(), roster=self.roster,
                             db=DB(str(OUT / "story.db")), use_google=False)
        self.ids = itertools.count(1)
        self.steps: list[dict] = []
        self.seen = 0

    def who(self, name: str):
        return next(p for p in self.roster.people if p.name.lower().startswith(name.lower()))

    def at(self, when: str) -> None:
        clock.freeze(datetime.fromisoformat(when).replace(tzinfo=clock.tz()))

    def _step(self, sid: str, actor: str, kind: str, **inp) -> dict:
        new = self.wa.sent[self.seen:]
        self.seen = len(self.wa.sent)
        outs = []
        for s in new:
            p = self.roster.person(s.to)
            outs.append({"wamid": s.wamid, "to": p.name if p else s.to, "kind": s.kind, "body": s.body,
                         "buttons": [t for _, t in s.buttons], "path": str(Path(s.path).relative_to(OUT)) if s.path else "",
                         "reply_to": s.reply_to})
        step = {"id": sid, "time": clock.now().isoformat(timespec="minutes"), "actor": actor, "kind": kind, **inp,
                "out": outs}
        self.steps.append(step)
        return step

    def _wamid(self) -> str:
        return f"wamid.in.{next(self.ids)}"

    def say(self, sid, name, text, quote=None, forwarded=False):
        """quote: the wamid of the message this replies to (swipe right on it)."""
        p = self.who(name)
        w = self._wamid()
        self.bot.handle(Incoming(wamid=w, phone=p.phone, kind="text", text=text, context_id=quote or "", forwarded=forwarded))
        return self._step(sid, p.name, "text", text=text, quote=quote or "", forwarded=forwarded, wamid=w)

    def media(self, sid, name, kind, data: bytes, mime: str, caption="", forwarded=False):
        p = self.who(name)
        mid = f"media{next(self.ids)}"
        self.wa.media[mid] = (data, mime)
        w = self._wamid()
        self.bot.handle(Incoming(wamid=w, phone=p.phone, kind=kind, media_id=mid, mime=mime, text=caption, forwarded=forwarded))
        return self._step(sid, p.name, kind, text=caption, forwarded=forwarded, wamid=w)

    def tap(self, sid, name, title_start: str):
        p = self.who(name)
        last = self.wa.last(p.phone, "buttons")
        i, (bid, title) = next((i, b) for i, b in enumerate(last.buttons) if b[1].startswith(title_start) or
                               title_start in b[1])
        self.bot.handle(Incoming(wamid=self._wamid(), phone=p.phone, kind="button", button_id=bid, text=title))
        return self._step(sid, p.name, "tap", text=title, on=last.wamid, button=i)

    def flush(self, sid):
        self.bot.flush_batches()
        return self._step(sid, "bot", "flush")

    def tick(self, sid):
        self.bot.tick()
        return self._step(sid, "bot", "tick")

    def last_to(self, name, kind=None, contains=""):
        p = self.who(name)
        return next(s.wamid for s in reversed(self.wa.to(p.phone)) if (kind is None or s.kind == kind) and contains in s.body)


def run() -> dict:
    s = Story()
    eng, abbas, boss = "Chandramohan", "Abbas", "Munishwer"

    # 9 Oct: everyone saves the number and says hi
    s.at("2026-10-09T09:30")
    for name in (eng, "Siddhu", "Tambi", abbas, boss):
        s.say(f"hi_{name.split()[0].lower()}", name, "hi")

    # 12 Oct: an earlier cement purchase, so the bot has a price to compare with (and, inside its 10-day window,
    # a repeat purchase to flag)
    s.at("2026-10-12T10:00")
    s.say("hist_fwd", abbas, "Car Nicobar site requirement\nCement OPC 53 grade 40 bag", forwarded=True)
    s.flush("hist_flush")
    s.say("hist_slip", abbas, "N1 Om Traders 395")
    s.tap("hist_send", abbas, "📤")
    s.at("2026-10-12T12:10")
    s.say("hist_yes", boss, "yes")
    s.at("2026-10-13T10:00")
    s.say("hist_dsp", abbas, "dispatch PS-0001 Nicobar MV Campbell Bay")
    s.at("2026-10-15T11:30")
    s.tap("hist_rcv", eng, "✅")
    s.at("2026-10-15T20:00")
    s.tick("hist_tick")

    # 20 Oct: the day the tutorial follows (the bot's scheduler ticks every few minutes; 08:00 is the morning list)
    s.at("2026-10-20T08:00")
    s.tick("morning0")
    s.at("2026-10-20T11:05")
    s.say("fwd_nic", abbas, POST_NIC, forwarded=True)
    s.media("fwd_voice", abbas, "audio", VOICE_TAMBI.encode(), "audio/ogg", forwarded=True)
    s.media("fwd_photo", abbas, "image", b"\x89PNG photo of the list", "image/jpeg", caption=POST_DIG_CAPTION, forwarded=True)
    s.say("fwd_chat", abbas, POST_CHAT, forwarded=True)
    s.at("2026-10-20T11:07")
    s.flush("summary")
    s.tap("site_kam", abbas, "Kamorta")
    s.at("2026-10-20T11:20")
    s.say("list", abbas, "list")
    s.at("2026-10-20T13:40")
    s.say("slip", abbas, SLIP_LINES)
    s.tap("send", abbas, "📤")
    s.at("2026-10-20T15:10")
    s.say("ask", boss, "cement 420 kyun? last time 395 tha")   # one slip waiting: no need to reply on it
    s.at("2026-10-20T15:18")
    s.say("answer", abbas, "Ship freight badh gaya, Om Traders ka naya rate hai", quote=s.last_to(abbas, "text", "asks about"))
    s.at("2026-10-20T15:25")
    s.say("decide", boss, "5 nahi")
    s.tap("confirm", boss, "✅")
    s.at("2026-10-20T20:00")
    s.tick("evening")

    # 21 Oct: Abbas buys and dispatches
    s.at("2026-10-21T08:00")
    s.tick("morning")
    s.at("2026-10-21T10:32")
    s.media("dsp_dig", abbas, "image", b"\x89PNG photo of the dispatch list", "image/jpeg", caption=POST_DISPATCH,
            forwarded=True)
    s.at("2026-10-21T10:40")
    s.say("dsp_nic", abbas, "dispatch PS-0002 Nicobar MV Campbell Bay")
    s.at("2026-10-21T10:45")
    s.say("dsp_kam", abbas, "dispatch PS-0002 Kamorta MV Swaraj Dweep")

    # 23 Oct: the sites say what arrived
    s.at("2026-10-22T08:00")
    s.tick("morning2")
    s.at("2026-10-23T08:00")
    s.tick("morning3")
    s.at("2026-10-23T10:15")
    s.tap("rcv_dig", "Siddhu", "✅")
    s.at("2026-10-23T11:00")
    s.tick("remind")  # Kamorta hasn't confirmed DSP-0002 after 48 h
    s.at("2026-10-23T12:40")
    s.tap("short", eng, "⚠️")
    s.say("short_qty", eng, "3-2")
    s.at("2026-10-23T17:05")
    s.say("used", eng, "used 10 bag cement")
    s.say("stock", eng, "stock")
    s.at("2026-10-23T19:30")
    s.say("report", boss, "report")
    s.at("2026-10-23T20:00")
    s.tick("evening2")
    clock.freeze(None)

    data = {"people": [{"name": p.name, "role": p.role, "site": p.site, "title": getattr(p, "title", "")}
                       for p in s.roster.people], "steps": s.steps}
    (HERE / "build").mkdir(exist_ok=True)
    (HERE / "build" / "capture.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def page_images() -> None:
    """Every PDF the bot wrote, as PNG pages (2x), for the document bubbles and the PDF viewer."""
    import fitz
    for pdf in sorted((OUT / "pdfs").rglob("*.pdf")):
        doc = fitz.open(pdf)
        for i, page in enumerate(doc):
            page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5)).save(pdf.with_suffix(f".p{i + 1}.png"))


if __name__ == "__main__":
    d = run()
    page_images()
    for st in d["steps"]:
        for o in st["out"]:
            head = o["body"].splitlines()[0] if o["body"] else ""
            print(f"{st['id']:12} -> {o['to']:26} {o['kind']:9} {head[:70]}{'  📄 ' + o['path'] if o['path'] else ''}")
