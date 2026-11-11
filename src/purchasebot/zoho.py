"""Past purchase rates from Zoho Books: vendor bills (rate, shop, date per line) and the item list.

Read-only. Uses a Zoho "Self Client" refresh token with scopes ZohoBooks.bills.READ,ZohoBooks.settings.READ.
Zoho allows 100 calls a minute and 1,000-10,000 a day depending on the plan, so the sync paces itself,
fetches line details only for bills it hasn't seen (or that changed), and stops after `max_calls`; the
next run carries on where it stopped.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

import httpx

from . import clock
from .db import DB
from .llm import norm_key, norm_unit
from .rates import record

log = logging.getLogger(__name__)


class ZohoError(Exception):
    pass


class ZohoBooks:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str, org_id: str, dc: str = "in",
                 http: httpx.Client | None = None, pause: float = 0.65):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.org_id = org_id
        self.accounts = f"https://accounts.zoho.{dc}"
        self.api = f"https://www.zohoapis.{dc}/books/v3"
        self.http = http or httpx.Client(timeout=30)
        self.pause = pause
        self.calls = 0
        self._token = ""
        self._token_until = 0.0

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_until:
            return self._token
        r = self.http.post(f"{self.accounts}/oauth/v2/token", data={
            "refresh_token": self.refresh_token, "client_id": self.client_id, "client_secret": self.client_secret,
            "grant_type": "refresh_token"})
        data = r.json() if r.content else {}
        if r.status_code >= 400 or "access_token" not in data:
            raise ZohoError(f"Zoho sign-in failed: {data.get('error', r.status_code)}")
        self._token = data["access_token"]
        self._token_until = time.monotonic() + int(data.get("expires_in", 3600)) - 300
        return self._token

    def _get(self, path: str, **params) -> dict:
        if self.calls and self.pause:
            time.sleep(self.pause)  # stay under 100 calls a minute
        self.calls += 1
        r = self.http.get(f"{self.api}/{path}", params={"organization_id": self.org_id, **params},
                          headers={"Authorization": f"Zoho-oauthtoken {self._access_token()}"})
        data = r.json() if r.content else {}
        if r.status_code == 429:
            raise ZohoError("Zoho's API limit for today is used up; the sync continues tomorrow")
        if r.status_code >= 400 or data.get("code", 0) != 0:
            raise ZohoError(f"Zoho error {data.get('code', r.status_code)}: {data.get('message', r.text[:200])}")
        return data

    def organizations(self) -> list[dict]:
        return self._get("organizations").get("organizations", [])

    def items(self, page: int) -> tuple[list[dict], bool]:
        d = self._get("items", page=page, per_page=200)
        return d.get("items", []), bool(d.get("page_context", {}).get("has_more_page"))

    def bills(self, date_start: str, page: int) -> tuple[list[dict], bool]:
        d = self._get("bills", page=page, per_page=200, date_start=date_start, sort_column="date", sort_order="D")
        return d.get("bills", []), bool(d.get("page_context", {}).get("has_more_page"))

    def bill(self, bill_id: str) -> dict:
        return self._get(f"bills/{bill_id}").get("bill", {})


def sync_rates(db: DB, zb: ZohoBooks, days: int = 365, max_calls: int = 600) -> dict:
    """Copy rates from Zoho Books into rate_history. Returns counts for the log."""
    stats = {"items": 0, "bills": 0, "lines": 0, "remaining": 0, "calls": 0}
    page, more = 1, True
    while more and zb.calls < max_calls:
        items, more = zb.items(page)
        for it in items:
            rate = float(it.get("purchase_rate") or 0)
            name = (it.get("name") or "").strip()
            if rate > 0 and name and it.get("status", "active") == "active":
                record(db, "zoho_item", str(it["item_id"]), name, norm_key(name), _unit(it.get("unit")), rate, "", "")
                stats["items"] += 1
        page += 1

    start = (clock.now() - timedelta(days=days)).date().isoformat()
    todo: list[dict] = []
    page, more = 1, True
    while more and zb.calls < max_calls:
        bills, more = zb.bills(start, page)
        for b in bills:
            if b.get("status") == "void":
                continue
            seen = db.one("SELECT last_modified FROM zoho_bills WHERE bill_id = ?", (str(b["bill_id"]),))
            if not seen or seen["last_modified"] != (b.get("last_modified_time") or ""):
                todo.append(b)
        page += 1

    for b in todo:
        if zb.calls >= max_calls:
            break
        bill = zb.bill(str(b["bill_id"]))
        vendor = (bill.get("vendor_name") or b.get("vendor_name") or "").strip()
        date = bill.get("date") or b.get("date") or ""
        for n, li in enumerate(bill.get("line_items", []), start=1):
            rate = float(li.get("rate") or 0)
            name = (li.get("name") or li.get("description") or "").strip()
            if rate <= 0 or not name:
                continue
            ref = f"{b['bill_id']}#{li.get('line_item_id') or n}"
            record(db, "zoho_bill", ref, name, norm_key(name), _unit(li.get("unit")), rate, vendor, date)
            stats["lines"] += 1
        db.run("INSERT INTO zoho_bills(bill_id, last_modified, synced_at) VALUES (?,?,?) "
               "ON CONFLICT(bill_id) DO UPDATE SET last_modified = excluded.last_modified, synced_at = excluded.synced_at",
               (str(b["bill_id"]), b.get("last_modified_time") or "", clock.now_iso()))
        stats["bills"] += 1
    stats["remaining"] = len(todo) - stats["bills"]
    stats["calls"] = zb.calls
    return stats


def _unit(u: str | None) -> str:
    return norm_unit(u) if u and u.strip() else ""


def from_settings(settings) -> ZohoBooks | None:
    if not (settings.zoho_client_id and settings.zoho_client_secret and settings.zoho_refresh_token and settings.zoho_org_id):
        return None
    return ZohoBooks(settings.zoho_client_id, settings.zoho_client_secret, settings.zoho_refresh_token,
                     settings.zoho_org_id, settings.zoho_dc)
