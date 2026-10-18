"""Wire settings into a ready Bot."""

from __future__ import annotations

import logging
from pathlib import Path

from .config import Settings
from .db import DB
from .google_sync import GoogleSync
from .llm import ClaudeParser, Parser, RuleParser
from .roster import Roster, load_roster
from .signing import Signer
from .speech import NoSpeech, SarvamSpeech, Speech
from .whatsapp import CloudWhatsApp, FakeWhatsApp, WhatsApp
from .workflow import Bot

log = logging.getLogger(__name__)


def resolve_roster_path(settings: Settings) -> Path:
    path = Path(settings.roster_path)
    if path.exists():
        return path
    example = Path("config/roster.example.yaml")
    log.warning("%s not found; using %s (placeholder numbers)", path, example)
    return example


def build_bot(settings: Settings, *, wa: WhatsApp | None = None, parser: Parser | None = None,
              speech: Speech | None = None, gsync: GoogleSync | None = None, roster: Roster | None = None,
              db: DB | None = None, use_google: bool = True) -> Bot:
    roster = roster or load_roster(resolve_roster_path(settings))
    db = db or DB(settings.database_path)
    if wa is None:
        if settings.wa_phone_number_id and settings.wa_access_token:
            wa = CloudWhatsApp(settings.wa_phone_number_id, settings.wa_access_token, settings.wa_graph_version)
        else:
            log.warning("WhatsApp credentials missing; messages will only be logged")
            wa = FakeWhatsApp()
    if parser is None:
        parser = ClaudeParser(settings.claude_model, settings.claude_effort) if settings.anthropic_api_key else RuleParser()
        if isinstance(parser, RuleParser):
            log.warning("ANTHROPIC_API_KEY missing; using the simple rule-based parser")
    if speech is None:
        speech = SarvamSpeech(settings.sarvam_api_key, settings.sarvam_model) if settings.sarvam_api_key else NoSpeech()
    if gsync is None and use_google and settings.google_auth_mode != "none":
        if settings.google_sheet_id and settings.google_drive_root_folder_id:
            gsync = GoogleSync(settings)
        else:
            log.warning("GOOGLE_SHEET_ID / GOOGLE_DRIVE_ROOT_FOLDER_ID missing; run `purchasebot google-setup`")
    signer = Signer.from_settings(settings.signing_key, settings.signing_key_path)
    return Bot(settings, db, roster, wa, parser, speech, signer, gsync)
