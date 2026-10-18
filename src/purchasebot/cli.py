"""Command line: serve, setup helpers, a terminal simulator and a scripted demo."""

from __future__ import annotations

import argparse
import itertools
import logging
import sys
from datetime import timedelta
from pathlib import Path

from . import clock
from .config import Settings, get_settings
from .signing import generate_seed_b64


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="purchasebot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the webhook server")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    sub.add_parser("gen-key", help="print a new SIGNING_KEY")
    sub.add_parser("check", help="check configuration")
    sub.add_parser("google-auth", help="one-time Google sign-in; prints GOOGLE_OAUTH_REFRESH_TOKEN")
    sub.add_parser("google-setup", help="create the Drive folder and Purchase Register sheet")
    sub.add_parser("tick", help="run reminders / digest / backup / sync once")
    sim = sub.add_parser("simulate", help="chat with the bot in the terminal (no WhatsApp needed)")
    sim.add_argument("--db", default="data/simulator.db")
    d = sub.add_parser("demo", help="run a scripted end-to-end scenario and write sample PDFs")
    d.add_argument("--out", default="data/demo")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "serve":
        import uvicorn

        from .app import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port)
    elif args.cmd == "gen-key":
        print(f"SIGNING_KEY={generate_seed_b64()}")
        print("# Keep this secret and backed up. Slips signed with it can only be verified with it.")
    elif args.cmd == "check":
        _check(get_settings())
    elif args.cmd == "google-auth":
        _google_auth(get_settings())
    elif args.cmd == "google-setup":
        _google_setup(get_settings())
    elif args.cmd == "tick":
        from .bootstrap import build_bot

        build_bot(get_settings()).tick()
    elif args.cmd == "simulate":
        simulate(args.db)
    elif args.cmd == "demo":
        demo(Path(args.out))


def _check(settings: Settings) -> None:
    from .bootstrap import resolve_roster_path
    from .roster import load_roster

    ok = True
    try:
        r = load_roster(resolve_roster_path(settings))
        print(f"✔ roster: {len(r.sites)} sites, {len(r.people)} people, {len(r.vendors)} vendors")
        for p in r.people:
            print(f"    {p.role:9} {p.name:22} {p.short_phone} {p.site}")
    except Exception as e:
        ok = False
        print(f"✘ roster: {e}")
    for label, val in [("WA_PHONE_NUMBER_ID", settings.wa_phone_number_id), ("WA_ACCESS_TOKEN", settings.wa_access_token),
                       ("WA_APP_SECRET", settings.wa_app_secret), ("WA_VERIFY_TOKEN", settings.wa_verify_token),
                       ("ANTHROPIC_API_KEY", settings.anthropic_api_key), ("SARVAM_API_KEY", settings.sarvam_api_key),
                       ("SIGNING_KEY", settings.signing_key), ("PUBLIC_BASE_URL", settings.public_base_url),
                       ("ADMIN_TOKEN", settings.admin_token)]:
        print(f"{'✔' if val else '✘'} {label}")
        ok &= bool(val)
    print(f"{'✔' if settings.google_auth_mode != 'none' else '–'} Google sync: {settings.google_auth_mode}")
    sys.exit(0 if ok else 1)


def _google_auth(settings: Settings) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    from .google_sync import SCOPES

    if not (settings.google_oauth_client_id and settings.google_oauth_client_secret):
        sys.exit("Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET first (see docs/SETUP.md).")
    flow = InstalledAppFlow.from_client_config(
        {"installed": {"client_id": settings.google_oauth_client_id, "client_secret": settings.google_oauth_client_secret,
                       "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
                       "redirect_uris": ["http://localhost"]}},
        SCOPES,
    )
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    print(f"\nGOOGLE_AUTH_MODE=oauth\nGOOGLE_OAUTH_REFRESH_TOKEN={creds.refresh_token}")


def _google_setup(settings: Settings) -> None:
    from .bootstrap import resolve_roster_path
    from .google_sync import GoogleSync
    from .roster import load_roster

    company = load_roster(resolve_roster_path(settings)).company.name
    folder, sheet = GoogleSync.create_workspace(settings, company)
    print(f"GOOGLE_DRIVE_ROOT_FOLDER_ID={folder}\nGOOGLE_SHEET_ID={sheet}")
    print(f"Sheet: https://docs.google.com/spreadsheets/d/{sheet}")


# ---------------------------------------------------------------- simulator


class ScriptedSpeech:
    """Stands in for Sarvam: the 'audio' bytes are the transcript."""

    def transcribe(self, audio: bytes, mime: str) -> str:
        return audio.decode()


class Harness:
    """Drive a Bot with fake WhatsApp, printing the conversation."""

    def __init__(self, db_path: str, out_dir: Path | None = None, echo=print):
        from .bootstrap import build_bot, resolve_roster_path
        from .db import DB
        from .llm import ClaudeParser, RuleParser
        from .roster import load_roster
        from .whatsapp import FakeWhatsApp

        settings = get_settings()
        base = out_dir or Path(db_path).parent
        overrides = {"pdf_dir": str(base / "pdfs"), "backup_dir": str(base / "backups"),
                     "signing_key_path": str(base / "signing.key"), "google_auth_mode": "none",
                     "forward_batch_seconds": 0}
        settings = settings.model_copy(update=overrides)
        self.echo = echo
        self.wa = FakeWhatsApp()
        self.wa.listeners.append(self._print)
        self.roster = load_roster(resolve_roster_path(settings))
        parser = ClaudeParser(settings.claude_model, settings.claude_effort) if settings.anthropic_api_key else RuleParser()
        self.bot = build_bot(settings, wa=self.wa, parser=parser, speech=ScriptedSpeech(), roster=self.roster,
                             db=DB(db_path), use_google=False)
        self._ids = itertools.count(1)

    def _print(self, s) -> None:
        p = self.roster.person(s.to)
        who = p.name if p else s.to
        if s.kind == "document":
            self.echo(f"\n  ⇢ {who}  📄 {Path(s.path).name}  — {s.body}")
            return
        body = s.body.replace("\n", "\n      ")
        quoted = "  (reply)" if s.reply_to else ""
        self.echo(f"\n  ⇢ {who}{quoted}\n      {body}")
        for i, (_, title) in enumerate(s.buttons, start=1):
            self.echo(f"      [{i}] {title}")

    def person(self, name: str):
        n = name.lower()
        matches = [p for p in self.roster.people if p.name.lower().startswith(n) or p.name.lower().replace(" ", "").startswith(n)]
        if not matches:
            raise SystemExit(f"Nobody called {name!r} in the roster")
        return matches[0]

    def _wamid(self) -> str:
        return f"wamid.in.{next(self._ids)}"

    def say(self, name: str, text: str, quote_last: bool = False, forwarded: bool = False):
        from .whatsapp import Incoming

        p = self.person(name)
        self.echo(f"\n{p.name} ▶ {'↪ forwarded from group: ' if forwarded else ''}{text}")
        ctx = ""
        if quote_last:
            ctx = next((s.wamid for s in reversed(self.wa.to(p.phone)) if s.kind in ("text", "buttons")), "")
        self.bot.handle(Incoming(wamid=self._wamid(), phone=p.phone, kind="text", text=text, context_id=ctx,
                                 forwarded=forwarded))

    def voice(self, name: str, transcript: str):
        from .whatsapp import Incoming

        p = self.person(name)
        media_id = f"media{next(self._ids)}"
        self.wa.media[media_id] = (transcript.encode(), "audio/ogg")
        self.echo(f"\n{p.name} ▶ 🎙 (voice note)")
        self.bot.handle(Incoming(wamid=self._wamid(), phone=p.phone, kind="audio", media_id=media_id, mime="audio/ogg"))

    def tap(self, name: str, index: int = 1):
        from .whatsapp import Incoming

        p = self.person(name)
        last = self.wa.last(p.phone, "buttons")
        bid, title = last.buttons[index - 1]
        self.echo(f"\n{p.name} ▶ [taps {title}]")
        self.bot.handle(Incoming(wamid=self._wamid(), phone=p.phone, kind="button", button_id=bid, text=title))


def simulate(db_path: str) -> None:
    h = Harness(db_path)
    print("Purchase bot simulator. Commands:\n"
          "  @name message        send a WhatsApp message as that person (e.g. @chandra cement 50 bags)\n"
          "  @name ^ message      same, but as a reply to the last message they got\n"
          "  @name #2             tap button 2 on the last button message they got\n"
          "  @name !voice text    send a voice note whose transcript is 'text'\n"
          "  @name fwd: text      forward a message from the group (e.g. @abbas fwd: Diglipur site requirements ...)\n"
          "  /who  /tick  /quit")
    for p in h.roster.people:
        print(f"    {p.role:9} {p.name}")
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("/quit", "/exit"):
            break
        if line == "/who":
            for p in h.roster.people:
                print(f"    {p.role:9} {p.name}")
            continue
        if line == "/tick":
            h.bot.tick()
            continue
        if not line.startswith("@") or " " not in line:
            print("Start with @name")
            continue
        name, rest = line[1:].split(" ", 1)
        rest = rest.strip()
        try:
            if rest.startswith("#") and rest[1:].isdigit():
                h.tap(name, int(rest[1:]))
            elif rest.startswith("!voice "):
                h.voice(name, rest[7:])
            elif rest.startswith("^"):
                h.say(name, rest[1:].strip(), quote_last=True)
            elif rest.lower().startswith("fwd:"):
                h.say(name, rest[4:].strip().replace("\\n", "\n"), forwarded=True)
            else:
                h.say(name, rest)
        except (SystemExit, AssertionError, IndexError) as e:
            print(f"  ! {e}")


# ---------------------------------------------------------------- demo


def demo(out: Path) -> None:
    """End-to-end scenario with the offline parser. Writes PDFs and a transcript to `out`."""
    import shutil

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    log: list[str] = []

    def echo(s: str) -> None:
        print(s)
        log.append(s)

    from datetime import datetime

    h = Harness(str(out / "demo.db"), out_dir=out, echo=echo)
    eng_n = h.roster.engineers_for("NIC")[0].name
    eng_k = h.roster.engineers_for("KAM")[0].name
    eng_d = h.roster.engineers_for("DIG")[0].name
    abbas = h.roster.by_role("logistics")[0].name
    boss = h.roster.by_role("approver")[0].name
    t0 = datetime(2026, 10, 10, 10, 0, tzinfo=clock.tz())

    echo("=== 10 Oct: an earlier purchase, so the bot has price history ===")
    clock.freeze(t0)
    h.say(eng_n, "Cement OPC 53 grade 40 bags")
    h.tap(eng_n, 1)
    h.say(abbas, "N1 Om Traders 395")
    h.tap(abbas, 1)
    h.say(boss, "yes")

    echo("\n\n=== 18 Oct: three sites send requirements ===")
    clock.freeze(t0 + timedelta(days=8))
    h.say(eng_n, "Cement OPC 53 grade 50 bags\nTMT 12mm 2 mt\nRiver sand 3 truck")
    h.tap(eng_n, 1)
    h.say(eng_k, "binding wire 25 kg\nshuttering ply 20 sheet")
    h.tap(eng_k, 1)
    echo("\n(Diglipur posts in the 'Kailash Material' group as usual; Abbas forwards it to the bot)")
    h.say(abbas, "Diglipur site requirements --\n1). Cement OPC 53 grade 30 bag\n2). Gitti 20mm 4 brass\n3). Welding goggles 10 nos",
          forwarded=True)

    clock.freeze(t0 + timedelta(days=8, hours=2))
    h.say(abbas, "list")
    h.say(abbas, "N2 Om Traders 420\nN3 Hira Metals 62000\nN4 Om Traders 9500\nK1 Hira Metals 85\n"
                 "K2 Sagar Hardware 1450\nD1 Om Traders 420\nD2 Om Traders 6500\nD3 Om Traders 180")
    h.tap(abbas, 1)

    clock.freeze(t0 + timedelta(days=8, hours=3))
    h.say(boss, "cement 420 kyun? last time 395 tha", quote_last=True)
    h.say(abbas, "Ship freight badh gaya, Om Traders ka naya rate hai", quote_last=True)
    h.say(boss, "5 nahi", quote_last=True)
    h.tap(boss, 1)

    clock.freeze(t0 + timedelta(days=9))
    h.say(abbas, "dispatch PS-0002 Nicobar MV Campbell Bay")
    h.say(abbas, "dispatch PS-0002 Kamorta MV Swaraj Dweep")
    echo("\n(Abbas forwards his usual dispatch post from the group)")
    h.say(abbas, "Diglipur Sector - Cement, gitti and welding goggles loaded in Anand Bus AN01F3868 departed today at "
                 "10.00 AM. Bus will be parked near BD BAR. Transportation not paid.", forwarded=True)
    clock.freeze(t0 + timedelta(days=11))
    h.tap(eng_n, 2)
    h.say(eng_n, "3-2")
    h.tap(eng_k, 1)
    h.tap(eng_d, 1)
    h.say(eng_n, "used 10 bag cement")
    h.say(eng_n, "stock")
    h.say(boss, "report")
    clock.freeze(None)

    (out / "transcript.txt").write_text("\n".join(log), encoding="utf-8")
    pdfs = sorted((out / "pdfs").rglob("*.pdf"))
    print("\nPDFs written:")
    for p in pdfs:
        print(f"  {p}")
    print(f"Transcript: {out / 'transcript.txt'}")


if __name__ == "__main__":
    main()
