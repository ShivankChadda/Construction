import itertools
from datetime import datetime

import pytest

from purchasebot import clock
from purchasebot.config import Settings
from purchasebot.db import DB
from purchasebot.llm import RuleParser
from purchasebot.roster import roster_from_dict
from purchasebot.signing import Signer, generate_seed_b64
from purchasebot.whatsapp import FakeWhatsApp, Incoming
from purchasebot.workflow import Bot

ROSTER = {
    "company": {"name": "Test Constructions", "address": "Port Blair"},
    "sites": [
        {"code": "NIC", "name": "Nicobar", "letter": "N"},
        {"code": "KAM", "name": "Kamorta", "letter": "K", "aliases": ["komoota"]},
        {"code": "DIG", "name": "Diglipur", "letter": "D"},
    ],
    "people": [
        {"name": "Chandramohan", "phone": "9000000001", "role": "engineer", "site": "NIC"},
        {"name": "Siddhu", "phone": "9000000002", "role": "engineer", "site": "DIG"},
        {"name": "Kamorta Engineer", "phone": "9000000003", "role": "engineer", "site": "KAM"},
        {"name": "Abbas", "phone": "9000000004", "role": "logistics"},
        {"name": "Rajesh Chadda", "phone": "9000000005", "role": "approver", "initials": "RC", "title": "MD"},
        {"name": "Shivank", "phone": "9000000006", "role": "observer"},
    ],
    "vendors": [
        {"name": "Om Traders", "aliases": ["ome", "om"]},
        {"name": "Hira Metals", "aliases": ["hera"]},
    ],
}

PHONES = {"chandra": "919000000001", "siddhu": "919000000002", "kam": "919000000003",
          "abbas": "919000000004", "boss": "919000000005", "shivank": "919000000006"}


class ScriptedSpeech:
    def transcribe(self, audio: bytes, mime: str) -> str:
        return audio.decode()


class Chat:
    """Talk to the bot as named people; inspect what it sent."""

    def __init__(self, bot: Bot, wa: FakeWhatsApp):
        self.bot = bot
        self.wa = wa
        self.db = bot.db
        self._ids = itertools.count(1)

    def wamid(self) -> str:
        return f"wamid.in.{next(self._ids)}"

    def say(self, who: str, text: str, quote=None, wamid=None, forwarded=False) -> str:
        wamid = wamid or self.wamid()
        ctx = quote.wamid if quote is not None else ""
        self.bot.handle(Incoming(wamid=wamid, phone=PHONES[who], kind="text", text=text, context_id=ctx, forwarded=forwarded))
        return wamid

    def photo(self, who: str, caption: str = "", data: bytes = b"\xff\xd8jpeg", forwarded=False) -> None:
        media = f"m{next(self._ids)}"
        self.wa.media[media] = (data, "image/jpeg")
        self.bot.handle(Incoming(wamid=self.wamid(), phone=PHONES[who], kind="image", media_id=media, mime="image/jpeg",
                                 text=caption, forwarded=forwarded))

    def voice(self, who: str, transcript: str, quote=None) -> None:
        media = f"m{next(self._ids)}"
        self.wa.media[media] = (transcript.encode(), "audio/ogg")
        self.bot.handle(Incoming(wamid=self.wamid(), phone=PHONES[who], kind="audio", media_id=media, mime="audio/ogg",
                                 context_id=quote.wamid if quote is not None else ""))

    def tap(self, who: str, title_prefix: str, msg=None) -> None:
        msg = msg or self.wa.last(PHONES[who], "buttons")
        bid = next(b for b, t in msg.buttons if t.startswith(title_prefix) or title_prefix in t)
        self.bot.handle(Incoming(wamid=self.wamid(), phone=PHONES[who], kind="button", button_id=bid))

    def press(self, who: str, button_id: str) -> None:
        self.bot.handle(Incoming(wamid=self.wamid(), phone=PHONES[who], kind="button", button_id=button_id))

    def last(self, who: str, kind=None):
        return self.wa.last(PHONES[who], kind)

    def texts(self, who: str) -> str:
        return "\n---\n".join(s.body for s in self.wa.to(PHONES[who]))

    # common journeys
    def requisition(self, who: str, text: str) -> None:
        self.say(who, text)
        self.tap(who, "✅ Confirm")

    def slip(self, text: str, send: bool = True) -> None:
        self.say("abbas", text)
        if send:
            self.tap("abbas", "📤")


def make_settings(tmp_path, **kw) -> Settings:
    base = dict(
        database_path=str(tmp_path / "t.db"), pdf_dir=str(tmp_path / "pdfs"), backup_dir=str(tmp_path / "backups"),
        signing_key=generate_seed_b64(), public_base_url="https://bot.example.com", google_auth_mode="none",
        daily_digest_hour=-1, logistics_todo_hour=-1, forward_batch_seconds=0, wa_app_secret="",
        allow_unsigned_webhooks=True,
    )
    base.update(kw)
    return Settings(_env_file=None, **base)


@pytest.fixture
def make_chat(tmp_path):
    def _make(parser=None, wa=None, **settings_kw):
        settings = make_settings(tmp_path, **settings_kw)
        wa = wa or FakeWhatsApp()
        bot = Bot(settings, DB(settings.database_path), roster_from_dict(ROSTER), wa, parser or RuleParser(),
                  ScriptedSpeech(), Signer(settings.signing_key), None)
        return Chat(bot, wa)

    return _make


@pytest.fixture
def chat(make_chat):
    return make_chat()


@pytest.fixture(autouse=True)
def frozen_clock():
    clock.set_timezone("Asia/Kolkata")
    clock.freeze(datetime(2026, 10, 18, 10, 0, tzinfo=clock.tz()))
    yield
    clock.freeze(None)
