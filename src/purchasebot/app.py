"""HTTP server: WhatsApp webhook, slip verification page, health check."""

from __future__ import annotations

import hmac
import json
import logging
import threading
from contextlib import asynccontextmanager
from html import escape

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from . import clock
from .config import Settings, get_settings
from .fmt import inr, qty
from .signing import canonical
from .store import load_slip
from .whatsapp import parse_webhook, verify_signature
from .workflow import Bot

log = logging.getLogger(__name__)


def _scheduler(bot: Bot, interval: int, stop: threading.Event) -> None:
    while not stop.wait(interval):
        try:
            bot.tick()
        except Exception:
            log.exception("Scheduled tick failed")


def create_app(bot: Bot | None = None, settings: Settings | None = None, run_scheduler: bool = True) -> FastAPI:
    settings = settings or get_settings()
    if bot is None:
        from .bootstrap import build_bot

        bot = build_bot(settings)
    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if run_scheduler and settings.scheduler_interval_seconds > 0:
            threading.Thread(target=_scheduler, args=(bot, settings.scheduler_interval_seconds, stop), daemon=True).start()
        yield
        stop.set()

    app = FastAPI(title="Purchase approval bot", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.bot = bot

    @app.get("/healthz")
    def health():
        return {"ok": True, "time": clock.now_iso()}

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy():
        return HTMLResponse(_privacy_page(bot.roster.company.name, settings.privacy_contact))

    @app.get("/webhook")
    def verify_webhook(request: Request):
        q = request.query_params
        if q.get("hub.mode") == "subscribe" and settings.wa_verify_token and \
                hmac.compare_digest(q.get("hub.verify_token", ""), settings.wa_verify_token):
            return PlainTextResponse(q.get("hub.challenge", ""))
        raise HTTPException(status_code=403, detail="verification failed")

    @app.post("/webhook")
    async def webhook(request: Request, background: BackgroundTasks):
        body = await request.body()
        if settings.wa_app_secret:
            if not verify_signature(settings.wa_app_secret, body, request.headers.get("x-hub-signature-256")):
                raise HTTPException(status_code=401, detail="bad signature")
        elif not settings.allow_unsigned_webhooks:
            raise HTTPException(status_code=401, detail="WA_APP_SECRET not configured")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="invalid json")
        # Answer Meta immediately; reading a voice note or rendering a PDF takes seconds.
        for msg in parse_webhook(payload):
            background.add_task(bot.handle, msg)
        return {"ok": True}

    @app.post("/admin/tick")
    def admin_tick(request: Request):
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not settings.admin_token or not hmac.compare_digest(token, settings.admin_token):
            raise HTTPException(status_code=401)
        bot.tick()
        return {"ok": True}

    @app.get("/verify/{slip_no}", response_class=HTMLResponse)
    def verify_slip(slip_no: str, c: str = ""):
        row = bot.db.one("SELECT id, verify_code FROM slips WHERE slip_no = ?", (slip_no,))
        # The code acts as a capability: without it, don't reveal that the slip exists.
        if not row or not row["verify_code"] or not hmac.compare_digest(c.upper(), row["verify_code"]):
            raise HTTPException(status_code=404, detail="Not found")
        slip = load_slip(bot.db, row["id"])
        valid = bot.signer.verify(canonical(bot.signed_payload(slip)), slip.signature or "")
        return HTMLResponse(_verify_page(slip, bot.roster.company.name, valid, bot.roster.site_name))

    return app


def _privacy_page(company: str, contact: str) -> str:
    who = escape(company)
    reach = f" Contact: {escape(contact)}." if contact else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{who} Purchase Desk privacy</title>
<style>body{{margin:0;background:#fafaf9;color:#1f2933;font:15px/1.55 system-ui,sans-serif}}
main{{max-width:720px;margin:0 auto;padding:24px 16px}}h1{{font-size:22px}}h2{{font-size:16px;margin-top:22px}}</style></head>
<body><main><h1>{who} Purchase Desk: privacy policy</h1>
<p>The Purchase Desk is an internal WhatsApp number that {who} uses to record material requirements, purchase approvals,
dispatches and deliveries for its construction sites. It is used only by {who} staff.</p>
<h2>What we collect</h2><p>The WhatsApp number and name of staff who message it, and the messages, photos and voice notes they send to it.</p>
<h2>Why</h2><p>To keep a record of what each site needs, what was approved and bought, and what arrived. We do not use it for marketing.</p>
<h2>Who processes it</h2><p>Messages pass through Meta's WhatsApp Business Platform. Text and photos are read by Anthropic's Claude, and voice
notes are transcribed by Sarvam AI, only to turn them into purchase records. Records and purchase slips are stored on {who}'s own
server and in {who}'s Google Drive.</p>
<h2>Your choices</h2><p>Staff can ask {who} to see or correct their records.{reach}</p></main></body></html>"""


def _verify_page(slip, company: str, valid: bool, site_name) -> str:
    rows = "".join(
        f"<tr class='{'no' if l.status != 'APPROVED' else ''}'><td>{l.line_no}</td><td>{escape(l.name)}"
        f"<small>{escape(site_name(l.site_code))} · {escape(l.vendor)}</small></td>"
        f"<td>{qty(l.qty)} {escape(l.unit)}</td><td>{inr(l.rate)}</td><td>{inr(l.amount)}</td>"
        f"<td>{'Approved' if l.status == 'APPROVED' else 'Not approved'}</td></tr>"
        for l in slip.lines
    )
    verdict = ("<div class='ok'>✔ Genuine — matches the approved record</div>" if valid else
               "<div class='bad'>✘ Signature check FAILED — do not accept this slip</div>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Verify {escape(slip.slip_no)}</title>
<style>
:root{{--ink:#1f2933;--muted:#6b7280;--rule:#e5e7eb;--bg:#fafaf9;--ok:#15803d;--bad:#b91c1c}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:20px 16px}}
h1{{font-size:20px;margin:0 0 4px}} .muted{{color:var(--muted)}}
.ok,.bad{{padding:12px 14px;border-radius:8px;font-weight:600;margin:14px 0;color:#fff}}
.ok{{background:var(--ok)}} .bad{{background:var(--bad)}}
table{{width:100%;border-collapse:collapse;font-size:14px;margin-top:10px}}
th,td{{text-align:left;padding:8px 6px;border-bottom:1px solid var(--rule);vertical-align:top}}
td small{{display:block;color:var(--muted)}} tr.no td{{color:var(--muted);text-decoration:line-through}}
.wrap{{overflow-x:auto}}
</style></head><body><main>
<div class="muted">{escape(company)}</div>
<h1>Purchase slip {escape(slip.slip_no)}</h1>
{verdict}
<p><b>{escape(slip.status.title())}</b> by {escape(slip.decided_by_name or '')} on {clock.fmt(slip.decided_at)}<br>
Prepared by {escape(slip.prepared_by_name)} · Verification code {escape(slip.verify_code or '')}</p>
<div class="wrap"><table><thead><tr><th>#</th><th>Item</th><th>Qty</th><th>Rate</th><th>Amount</th><th></th></tr></thead>
<tbody>{rows}</tbody></table></div>
<p><b>Approved total: {inr(slip.approved_total)}</b></p>
<p class="muted">If the paper or PDF you hold differs from this page in any item, quantity, rate or vendor, it has been altered.</p>
</main></body></html>"""
