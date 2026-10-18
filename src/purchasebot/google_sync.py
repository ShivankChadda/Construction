"""Mirror to Google Drive and Sheets.

Why OAuth and not a service account: Google service accounts have no Drive
storage of their own, so they can't upload PDFs into a personal (gmail.com)
My Drive. With OAuth and the narrow `drive.file` scope, the bot can only see
files it created — the folder and spreadsheet made by `purchasebot google-setup`.
A service account works only if you use a Google Workspace shared drive.

Everything is queued in `sync_queue` and pushed by upserts keyed on stable
ids, so retries after a network failure never create duplicate rows.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from . import clock
from .config import Settings
from .db import DB
from .fmt import qty as fmt_qty
from .roster import Roster
from .store import load_dispatch, load_requisition, load_slip, stock_summary

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

TABS: dict[str, list[str]] = {
    "Purchase Register": [
        "Key", "Slip No", "Line", "Status", "Site", "Item", "Qty", "Unit", "Vendor", "Rate", "Amount",
        "Requested Qty", "Req Ref", "Requisition", "Flags", "Prepared By", "Submitted", "Decided By", "Decided At",
        "Verification Code", "PDF", "Dispatched", "Received Qty", "Received At",
    ],
    "Requisitions": [
        "Key", "Req No", "Line", "Ref", "Site", "Engineer", "Entered By", "Item", "Qty", "Unit", "Spec",
        "Item Status", "Req Status", "Source", "Urgent", "Needed By", "Submitted",
    ],
    "Dispatches": [
        "Key", "Dispatch No", "Line", "Site", "Item", "Qty", "Unit", "Slip", "Stock Item", "Carrier", "Note",
        "Sent By", "Sent At", "Status", "Received Qty", "Received By", "Received At",
    ],
    "Stock Ledger": ["Key", "Date", "Site", "Item", "Qty", "Unit", "Type", "Ref", "By", "Note"],
    "Stock Summary": ["Site", "Item", "Qty", "Unit", "Last Movement"],
    "Audit Log": ["Key", "Time", "Actor", "Action", "Entity", "Details"],
}


def build_credentials(settings: Settings):
    if settings.google_auth_mode == "oauth":
        from google.oauth2.credentials import Credentials

        return Credentials(
            token=None,
            refresh_token=settings.google_oauth_refresh_token,
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=SCOPES,
        )
    if settings.google_auth_mode == "service_account":
        from google.oauth2 import service_account

        return service_account.Credentials.from_service_account_file(
            settings.google_service_account_file,
            scopes=["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"],
        )
    return None


class GoogleSync:
    def __init__(self, settings: Settings, creds=None):
        from googleapiclient.discovery import build

        self.settings = settings
        creds = creds or build_credentials(settings)
        self.drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        self.sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self.root = settings.google_drive_root_folder_id
        self.sheet_id = settings.google_sheet_id
        self._folders: dict[tuple[str, str], str] = {}
        self._tabs_checked = False

    # ---------- setup ----------
    @classmethod
    def create_workspace(cls, settings: Settings, company: str) -> tuple[str, str]:
        """Create the Drive folder and the register spreadsheet. Returns (folder_id, sheet_id)."""
        sync = cls(settings)
        folder = sync.drive.files().create(
            body={"name": f"{company} - Purchases", "mimeType": "application/vnd.google-apps.folder"}, fields="id"
        ).execute()["id"]
        sheet = sync.sheets.spreadsheets().create(
            body={"properties": {"title": f"{company} - Purchase Register"},
                  "sheets": [{"properties": {"title": t, "gridProperties": {"frozenRowCount": 1}}} for t in TABS]},
            fields="spreadsheetId",
        ).execute()["spreadsheetId"]
        sync.drive.files().update(fileId=sheet, addParents=folder, fields="id").execute()
        sync.sheet_id = sheet
        for tab, header in TABS.items():
            sync._write(tab, "A1", [header])
        return folder, sheet

    # ---------- drive ----------
    def _folder(self, name: str, parent: str) -> str:
        key = (parent, name)
        if key in self._folders:
            return self._folders[key]
        safe = name.replace("'", "\\'")
        found = self.drive.files().list(
            q=f"name = '{safe}' and '{parent}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            fields="files(id)", spaces="drive",
        ).execute().get("files", [])
        fid = found[0]["id"] if found else self.drive.files().create(
            body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent]}, fields="id"
        ).execute()["id"]
        self._folders[key] = fid
        return fid

    def upload(self, path: str | Path, *folders: str) -> str:
        from googleapiclient.http import MediaFileUpload

        parent = self.root
        for f in folders:
            parent = self._folder(f, parent)
        path = Path(path)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        f = self.drive.files().create(
            body={"name": path.name, "parents": [parent]},
            media_body=MediaFileUpload(str(path), mimetype=mime, resumable=False),
            fields="id, webViewLink",
        ).execute()
        return f["webViewLink"]

    # ---------- sheets ----------
    def ensure_tabs(self) -> None:
        """Add tabs introduced after the sheet was created (once per process)."""
        if self._tabs_checked:
            return
        meta = self.sheets.spreadsheets().get(spreadsheetId=self.sheet_id, fields="sheets.properties.title").execute()
        have = {s["properties"]["title"] for s in meta.get("sheets", [])}
        missing = [t for t in TABS if t not in have]
        if missing:
            self.sheets.spreadsheets().batchUpdate(spreadsheetId=self.sheet_id, body={"requests": [
                {"addSheet": {"properties": {"title": t, "gridProperties": {"frozenRowCount": 1}}}} for t in missing]}).execute()
            for t in missing:
                self._write(t, "A1", [TABS[t]])
        self._tabs_checked = True

    def _write(self, tab: str, a1: str, rows: list[list]) -> None:
        self.sheets.spreadsheets().values().update(
            spreadsheetId=self.sheet_id, range=f"'{tab}'!{a1}", valueInputOption="USER_ENTERED", body={"values": rows}
        ).execute()

    def upsert(self, tab: str, rows: list[list]) -> None:
        """Rows keyed by column A. Existing keys are overwritten in place; new keys are appended."""
        if not rows:
            return
        self.ensure_tabs()
        keys = self.sheets.spreadsheets().values().get(spreadsheetId=self.sheet_id, range=f"'{tab}'!A:A").execute()
        index = {r[0]: i + 1 for i, r in enumerate(keys.get("values", [])) if r}
        updates, appends = [], []
        for row in rows:
            if row[0] in index:
                updates.append({"range": f"'{tab}'!A{index[row[0]]}", "values": [row]})
            else:
                appends.append(row)
        if updates:
            self.sheets.spreadsheets().values().batchUpdate(
                spreadsheetId=self.sheet_id, body={"valueInputOption": "USER_ENTERED", "data": updates}
            ).execute()
        if appends:
            self.sheets.spreadsheets().values().append(
                spreadsheetId=self.sheet_id, range=f"'{tab}'!A1", valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS", body={"values": appends},
            ).execute()

    def replace(self, tab: str, rows: list[list]) -> None:
        self.sheets.spreadsheets().values().clear(spreadsheetId=self.sheet_id, range=f"'{tab}'!A2:Z").execute()
        if rows:
            self._write(tab, "A2", rows)


# ---------------------------------------------------------------- queue


def enqueue(db: DB, kind: str, key: str | int) -> None:
    db.run("INSERT OR IGNORE INTO sync_queue(kind, key) VALUES (?, ?)", (kind, str(key)))


def process_queue(db: DB, sync: GoogleSync | None, roster: Roster, limit: int = 50) -> int:
    """Push pending changes. Returns the number of jobs completed."""
    if sync is None:
        return 0
    done = 0
    for job in db.q("SELECT * FROM sync_queue WHERE attempts < 20 ORDER BY id LIMIT ?", (limit,)):
        try:
            _run_job(db, sync, roster, job["kind"], job["key"])
            db.run("DELETE FROM sync_queue WHERE id = ?", (job["id"],))
            done += 1
        except Exception as e:  # network, quota, auth: keep the job and retry next tick
            log.warning("Google sync %s:%s failed: %s", job["kind"], job["key"], e)
            db.run("UPDATE sync_queue SET attempts = attempts + 1, last_error = ? WHERE id = ?", (str(e)[:500], job["id"]))
            break
    return done


def _run_job(db: DB, sync: GoogleSync, roster: Roster, kind: str, key: str) -> None:
    if kind == "slip":
        slip = load_slip(db, int(key))
        if slip is None:
            return
        if slip.status in ("APPROVED", "PARTIAL", "REJECTED") and slip.pdf_path and not slip.drive_link:
            when = clock.parse(slip.decided_at or slip.created_at)
            link = sync.upload(slip.pdf_path, "Purchase Slips", when.strftime("%Y"), when.strftime("%m-%B"))
            db.run("UPDATE slips SET drive_link = ? WHERE id = ?", (link, slip.id))
            slip.drive_link = link
        reqs = []
        for l in slip.lines:
            reqs.append([
                f"{slip.slip_no}#{l.line_no}", slip.slip_no, l.line_no, l.status if slip.status != "PENDING" else "PENDING",
                roster.site_name(l.site_code), l.name, l.qty, l.unit, l.vendor, l.rate, l.amount,
                l.requested_qty if l.requested_qty is not None else "", l.ref or "", l.req_no or "",
                "; ".join(f.text for f in l.flags), slip.prepared_by_name, clock.fmt(slip.submitted_at),
                slip.decided_by_name or "", clock.fmt(slip.decided_at) if slip.decided_at else "",
                slip.verify_code or "", slip.drive_link or "", clock.fmt(l.dispatched_at) if l.dispatched_at else "",
                l.received_qty if l.received_qty is not None else "", clock.fmt(l.received_at) if l.received_at else "",
            ])
        sync.upsert("Purchase Register", reqs)
    elif kind == "req":
        req = load_requisition(db, int(key))
        if req is None:
            return
        entered = roster.person(req.entered_by_phone)
        sync.upsert("Requisitions", [[
            f"{req.req_no or 'DRAFT-' + str(req.id)}#{it.line_no}", req.req_no or "", it.line_no, it.ref or "",
            roster.site_name(req.site_code), req.engineer_name, entered.name if entered else req.entered_by_phone,
            it.name, fmt_qty(it.qty), it.unit, it.spec, it.status, req.status, req.source, "yes" if req.urgent else "",
            req.needed_by, clock.fmt(req.submitted_at) if req.submitted_at else "",
        ] for it in req.items])
    elif kind == "ledger":
        r = db.one("SELECT * FROM stock_ledger WHERE id = ?", (int(key),))
        if r is None:
            return
        by = roster.person(r["by_phone"]) if r["by_phone"] else None
        sync.upsert("Stock Ledger", [[
            f"L{r['id']}", clock.fmt(r["created_at"]), roster.site_name(r["site_code"]), r["name"], r["qty"], r["unit"],
            r["kind"], r["ref"], by.name if by else "", r["note"],
        ]])
        sync.replace("Stock Summary", [
            [roster.site_name(s["site_code"]), s["name"], s["qty"], s["unit"], clock.fmt(s["last_at"])]
            for s in stock_summary(db)
        ])
    elif kind == "dispatch":
        d = load_dispatch(db, int(key))
        if d is None:
            return
        by = roster.person(d.created_by)
        rcv = roster.person(d.received_by or "")
        sync.upsert("Dispatches", [[
            f"{d.dispatch_no}#{i.line_no}", d.dispatch_no, i.line_no, roster.site_name(d.site_code), i.name, i.qty, i.unit,
            i.slip_no or "", "yes" if i.stock_item else "no", d.carrier, d.note, by.name if by else d.created_by,
            clock.fmt(d.created_at), d.status, i.received_qty if i.received_qty is not None else "",
            rcv.name if rcv else "", clock.fmt(d.received_at) if d.received_at else "",
        ] for i in d.items])
    elif kind == "audit":
        r = db.one("SELECT * FROM audit WHERE id = ?", (int(key),))
        if r is None:
            return
        actor = roster.person(r["actor"]) if r["actor"].isdigit() else None
        sync.upsert("Audit Log", [[f"A{r['id']}", clock.fmt(r["at"]), actor.name if actor else r["actor"],
                                   r["action"], r["entity"], r["details"]]])
    elif kind == "file":
        # key = local path|folder/sub ; uploaded once (requisition originals, backups)
        path, _, folder = key.partition("|")
        if Path(path).exists():
            link = sync.upload(path, *[p for p in folder.split("/") if p])
            if folder.startswith("Originals"):
                db.run("UPDATE requisitions SET media_link = ? WHERE media_link = ?", (link, path))
    else:
        log.warning("Unknown sync job kind %s", kind)
