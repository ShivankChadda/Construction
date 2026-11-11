"""Zoho Books rate sync against a fake Zoho (no network)."""

import httpx
import pytest

from purchasebot.cli import _zoho_sync
from purchasebot.db import DB
from purchasebot.rates import RateBook
from purchasebot.zoho import ZohoBooks, ZohoError, sync_rates


class FakeZoho:
    def __init__(self):
        self.bills = [
            {"bill_id": "B1", "vendor_name": "Om Traders", "date": "2026-10-01", "status": "open",
             "last_modified_time": "2026-10-01T10:00:00+0530"},
            {"bill_id": "B2", "vendor_name": "Hira Metals", "date": "2026-09-20", "status": "void",
             "last_modified_time": "2026-09-20T10:00:00+0530"},
        ]
        self.details = {"B1": {"bill_id": "B1", "vendor_name": "Om Traders", "date": "2026-10-01", "line_items": [
            {"line_item_id": "L1", "name": "Cement OPC 53", "unit": "bags", "quantity": 50, "rate": 405},
            {"line_item_id": "L2", "name": "Freight", "unit": "", "quantity": 1, "rate": 0}]}}
        self.seen: list[httpx.Request] = []
        self.token_calls = 0
        self.limit_hit = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path
        if path == "/oauth/v2/token":
            self.token_calls += 1
            assert b"grant_type=refresh_token" in request.content
            return httpx.Response(200, json={"access_token": "AT", "expires_in": 3600})
        assert request.headers["authorization"] == "Zoho-oauthtoken AT"
        assert request.url.params["organization_id"] == "ORG1"
        if self.limit_hit:
            return httpx.Response(429, json={"code": 44, "message": "limit"})
        if path == "/books/v3/items":
            return httpx.Response(200, json={"code": 0, "items": [
                {"item_id": "I1", "name": "PPR Stop Cock 20x15", "purchase_rate": 52, "unit": "pcs", "status": "active"},
                {"item_id": "I2", "name": "Service charge", "purchase_rate": 0}], "page_context": {"has_more_page": False}})
        if path == "/books/v3/bills":
            assert request.url.params["date_start"] == "2025-10-18"
            return httpx.Response(200, json={"code": 0, "bills": self.bills, "page_context": {"has_more_page": False}})
        if path.startswith("/books/v3/bills/"):
            return httpx.Response(200, json={"code": 0, "bill": self.details[path.rsplit("/", 1)[1]]})
        return httpx.Response(404, json={"code": 1, "message": "not found"})


def _zoho(fake: FakeZoho) -> ZohoBooks:
    return ZohoBooks("cid", "secret", "refresh", "ORG1", "in",
                     http=httpx.Client(transport=httpx.MockTransport(fake)), pause=0)


def test_sync_copies_bill_and_item_rates_once(tmp_path):
    db = DB(tmp_path / "z.db")
    fake = FakeZoho()
    stats = sync_rates(db, _zoho(fake), days=365)
    assert stats == {"items": 1, "bills": 1, "lines": 1, "remaining": 0, "calls": 3}
    assert all(str(r.url).startswith(("https://accounts.zoho.in/", "https://www.zohoapis.in/books/v3/")) for r in fake.seen)
    rows = {r["source"]: dict(r) for r in db.q("SELECT * FROM rate_history")}
    assert (rows["zoho_bill"]["name"], rows["zoho_bill"]["rate"], rows["zoho_bill"]["vendor"],
            rows["zoho_bill"]["rate_date"], rows["zoho_bill"]["unit"]) == ("Cement OPC 53", 405, "Om Traders", "2026-10-01", "bag")
    assert (rows["zoho_item"]["name"], rows["zoho_item"]["rate"], rows["zoho_item"]["rate_date"]) == ("PPR Stop Cock 20x15", 52, "")

    # Unchanged bills aren't fetched again; a changed one is.
    fake2 = FakeZoho()
    assert sync_rates(db, _zoho(fake2), days=365)["bills"] == 0
    fake3 = FakeZoho()
    fake3.bills[0]["last_modified_time"] = "2026-10-05T09:00:00+0530"
    fake3.details["B1"]["line_items"][0]["rate"] = 410
    assert sync_rates(db, _zoho(fake3), days=365)["bills"] == 1
    assert db.one("SELECT rate FROM rate_history WHERE source = 'zoho_bill'")["rate"] == 410

    # The approver's list now finds these rates.
    book = RateBook(db)
    assert book.last("ppr stop cock 20 x 15 mm", "PPR stop cock 20 x 15 mm", "nos").rate == 52
    # "Cement" vs "Cement OPC 53" is too loose to assume; it is offered to the AI to decide.
    assert book.last("cement", "Cement", "bag") is None
    assert [c.name for c in book.candidates("cement", "Cement", "bag")] == ["Cement OPC 53"]


def test_sync_stops_at_the_call_budget_and_resumes(tmp_path):
    db = DB(tmp_path / "z.db")
    fake = FakeZoho()
    fake.bills.append({"bill_id": "B3", "vendor_name": "Om Traders", "date": "2026-08-01", "status": "paid",
                       "last_modified_time": "x"})
    fake.details["B3"] = {"line_items": [{"name": "Sand", "rate": 9000, "unit": "truck"}]}
    stats = sync_rates(db, _zoho(fake), days=365, max_calls=3)
    assert (stats["bills"], stats["remaining"]) == (1, 1)
    stats = sync_rates(db, _zoho(fake), days=365, max_calls=10)
    assert stats["bills"] == 1 and db.one("SELECT COUNT(*) AS n FROM zoho_bills")["n"] == 2


def test_daily_limit_and_bad_login_raise_clear_errors(tmp_path):
    db = DB(tmp_path / "z.db")
    fake = FakeZoho()
    fake.limit_hit = True
    with pytest.raises(ZohoError, match="limit for today"):
        sync_rates(db, _zoho(fake))

    def deny(request):
        return httpx.Response(400, json={"error": "invalid_client"})
    zb = ZohoBooks("c", "s", "r", "ORG1", http=httpx.Client(transport=httpx.MockTransport(deny)), pause=0)
    with pytest.raises(ZohoError, match="invalid_client"):
        sync_rates(db, zb)


def test_cli_sync_reports_counts(tmp_path, capsys):
    from types import SimpleNamespace
    settings = SimpleNamespace(database_path=str(tmp_path / "z.db"), zoho_sync_days=365, zoho_max_calls=600)
    _zoho_sync(settings, None, client=_zoho(FakeZoho()))
    out = capsys.readouterr().out
    assert "1 item rates, 1 bills (1 lines) read; 2 past rates on file." in out


def test_bot_does_not_sync_without_zoho_settings(chat):
    chat.bot.tick()
    assert chat.db.kv_get("last_zoho_sync") == ""
