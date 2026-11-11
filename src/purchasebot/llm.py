"""Turning free-form WhatsApp messages into structured items.

Claude reads engineers' lists (Hinglish text, transcribed voice notes, photos
of handwritten lists) and Abbas's purchase notes. It only *extracts*; every
number is re-validated in code, amounts are computed in code, and approvals
never go through a model (see approval.py).

RuleParser is an offline fallback for tests, the simulator, and the day the
API is unreachable. It understands simple "item qty unit" lines.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger(__name__)

UNITS = [
    "bag", "kg", "mt", "ton", "quintal", "nos", "pcs", "cft", "cum", "brass", "sqft", "sqm", "rft", "m",
    "litre", "box", "roll", "bundle", "set", "load", "truck", "drum", "packet", "sheet", "length", "pair", "lot", "g",
]
_UNIT_ALIASES = {
    "bags": "bag", "bori": "bag", "katta": "bag", "kgs": "kg", "kilo": "kg", "tonne": "mt", "tons": "mt",
    "ton": "mt", "tonnes": "mt", "no": "nos", "nos.": "nos", "number": "nos", "numbers": "nos", "piece": "pcs",
    "pieces": "pcs", "pc": "pcs", "ltr": "litre", "liter": "litre", "litres": "litre", "l": "litre",
    "meter": "m", "metre": "m", "meters": "m", "mtr": "m", "feet": "rft", "ft": "rft", "trucks": "truck",
    "loads": "load", "boxes": "box", "rolls": "roll", "bundles": "bundle", "sets": "set", "drums": "drum",
    "sheets": "sheet", "packets": "packet", "pkt": "packet", "tractor": "load", "trolley": "load",
    "gram": "g", "grams": "g", "gm": "g", "gms": "g", "gram.": "g",
}


def norm_unit(u: str) -> str:
    u = (u or "").strip().lower().rstrip(".")
    return _UNIT_ALIASES.get(u, u) or "nos"


def norm_key(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", name.lower())).strip()


# ---------------------------------------------------------------- results


@dataclass
class ParsedItem:
    name: str
    item_key: str
    qty: float
    unit: str
    spec: str = ""


@dataclass
class ReqParse:
    items: list[ParsedItem]
    unclear: list[str] = field(default_factory=list)
    needed_by: str = ""
    urgent: bool = False
    note: str = ""  # one-line summary of what changed (revisions)


@dataclass
class ParsedSlipLine:
    ref: str  # open-item ref like N17, or ""
    site_code: str
    name: str
    item_key: str
    qty: float
    unit: str
    vendor: str
    rate: float
    lump_sum: float = 0.0
    action: str = "BUY"   # BUY, PENDING (not available now), SENT (already sent), DROP (not needed)
    remark: str = ""


@dataclass
class SlipParse:
    lines: list[ParsedSlipLine]
    unclear: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class ParsedBillLine:
    name: str
    item_key: str
    qty: float
    unit: str
    rate: float
    amount: float
    slip_line_id: int = 0  # the approved challan line this is, 0 if it isn't on the challan


@dataclass
class BillParse:
    vendor: str
    bill_no: str
    bill_date: str  # YYYY-MM-DD or ""
    lines: list[ParsedBillLine]
    tax_total: float = 0.0
    grand_total: float = 0.0
    unclear: list[str] = field(default_factory=list)


@dataclass
class ParsedDispatchItem:
    name: str
    item_key: str
    qty: float
    unit: str
    slip_line_id: int = 0  # approved slip line this is, 0 if none
    stock_item: bool = True


@dataclass
class DispatchParse:
    carrier: str
    note: str
    items: list[ParsedDispatchItem]
    unclear: list[str] = field(default_factory=list)


@dataclass
class QtyLine:
    line_no: int
    qty: float


@dataclass
class UsageItem:
    item_key: str
    name: str
    qty: float
    unit: str


class Parser(Protocol):
    def parse_requisition(self, text: str, site_name: str, known_items: list[str],
                          current: list[ParsedItem] | None = None, images: list[tuple[bytes, str]] | None = None) -> ReqParse: ...
    def parse_slip(self, text: str, open_items: list[dict], vendors: list[str], sites: list[tuple[str, str]],
                   known_items: list[str], current: list[ParsedSlipLine] | None = None) -> SlipParse: ...
    def parse_dispatch(self, text: str, open_lines: list[dict],
                       images: list[tuple[bytes, str]] | None = None) -> DispatchParse: ...
    def parse_receipt(self, text: str, lines: list[dict]) -> list[QtyLine]: ...
    def parse_usage(self, text: str, stock_items: list[dict]) -> list[UsageItem]: ...
    def parse_bill(self, text: str, images: list[tuple[bytes, str]], challan_lines: list[dict]) -> BillParse: ...
    def match_rates(self, items: list[dict]) -> dict[int, int]: ...


# ---------------------------------------------------------------- Claude

_REQ_SYSTEM = """You read material requirement messages sent on WhatsApp by site engineers of a construction company in the Andaman & Nicobar Islands. Messages are in English, Hindi, Hinglish, or other Indian languages, often abbreviated, sometimes a voice-note transcript or a photo of a handwritten list.

Extract every material, tool or consumable requested.
- name: clear English name with grade/size/spec in it, e.g. "Cement OPC 53 grade", "TMT bar 12 mm Fe500D", "River sand", "Binding wire 18 gauge".
- item_key: a short lowercase key for the same item across messages, e.g. "cement opc 53", "tmt 12mm", "river sand". If the item is the same as one in KNOWN ITEM KEYS, reuse that key exactly.
- qty: the number requested; 0 if no quantity was given.
- unit: one of bag, kg, mt, quintal, nos, pcs, cft, cum, brass, sqft, sqm, rft, m, litre, box, roll, bundle, set, load, truck, drum, packet, sheet, length, pair, lot. Convert words: bori/katta=bag, ton/tonne=mt, piece=pcs.
- spec: extra detail that doesn't belong in the name (brand preference, colour, length), else "".
Common Hindi terms: sariya/saria = TMT bar, gitti/rodi = stone aggregate, balu/reti = sand, eent = brick, patthar = stone, kil = nails, taar = wire, rang = paint, plywood/ply = shuttering plywood, pipe = PVC/GI pipe (keep as said).
- unclear: lines you could not turn into an item (quote them briefly). Greetings, chit-chat and headings like "Diglipur site requirements" are not unclear lines; ignore them.
- needed_by: the date or timing mentioned ("by Monday", "next ship"), else "".
- urgent: true only if the message says urgent/jaldi/emergency/ASAP.
- note: "" for a new list.

When CURRENT LIST is given, the new message edits that list: it may add items, change quantities, or remove items ("remove sand", "cement 60 nahi 50"). Return the complete updated list, and put a one-line summary of the change in note."""

_SLIP_SYSTEM = """You read the purchase plan of the logistics manager of a construction company in the Andaman & Nicobar Islands. He goes through the open requirements from the sites and says, item by item, which shop to buy each one from. He usually gives no prices: prices are set at the shop and checked later against the bill. He often speaks (voice-note transcript) in Hindi, English or a mix.

OPEN REQUIREMENTS lists what site engineers asked for, each with a ref like N17 (site letter + number). For every requirement he mentions, return one line with an action:
- BUY: he names a shop. vendor = the shop. rate = a price per unit only if he states one, else 0.
- PENDING: not available now ("not available", "nahi mila", "stock nahi hai", "out of stock", "baad mein", "dispatch pending"). The item stays on the open list. remark = why, and where he tried if he says so.
- SENT: already sent to the site earlier ("already sent", "pehle bhej diya", "last consignment mein gaya", "MV Manav Star se gaya"). remark = how or when it went (vessel, date) if he says so.
- DROP: not needed or cancelled ("not needed", "zarurat nahi", "cancel"). remark = the reason.

Refs: he may give ranges ("N1 to N5", "N1 se N5" = N1, N2, N3, N4, N5), lists ("N2, N3 aur N7"), or say "baaki sab" / "rest" / "all others" = every open requirement he has not mentioned yet (of the site he is talking about, or all sites if he names none). He may also name items instead of refs; match them to the open requirement.

For each line:
- ref: the open requirement ref, or "" for something nobody requested (freight, extra items) - those are always BUY, with site_code from the note.
- site_code: one of the SITES codes (from the ref, or from the note).
- name, item_key, unit, qty: as in the requirement when a ref is used (use the requested qty unless he states another); otherwise a clear English name, a short lowercase key (reuse KNOWN ITEM KEYS when it is the same item), and a unit.
- vendor: for BUY only, else "". If it matches one of KNOWN SHOPS (spelling variations like Ome/Om, Hera/Hira), use the known name exactly. Otherwise write the shop name as he said it; do not add words like Traders, Stores or Trading.
- rate: per unit in rupees if stated ("62/kg" with qty in mt -> rate per mt = 62000), else 0.
- lump_sum: total rupees for the line if he gives a total instead of a rate, else 0.
- remark: as described above for PENDING / SENT / DROP; for BUY anything he adds about the purchase ("brand Supreme", "urgent"), else "".
- unclear: only parts of the note you could not place at all. A PENDING / SENT / DROP item is not unclear - put the reason in remark.
- note: "" for a new plan.

When CURRENT PLAN is given, the note edits it (change shop, mark an item not available, add or remove lines). Return the complete updated list and summarise the change in note."""

_RATE_MATCH_SYSTEM = """A construction company compares each item it is about to buy with what it paid last time. For each ITEM, choose the PAST PURCHASE that is the same item: same material and the same size, grade or specification. Sizes must match exactly (20 mm is not 25 mm; 20x15 is not 20x20). Different wording is fine ("TMT bar 12mm" = "Saria 12 mm", "Male adapter" = "Male adaptor"), and so is a different brand of the identical item. If none of the candidates is the same item, answer 0. Never guess."""

_BILL_SYSTEM = """You read a shop's bill, cash memo, invoice or delivery challan photographed by the logistics manager of a construction company after buying materials on credit. Read it carefully, including handwriting.

Extract:
- vendor: the shop's name as printed or written on the bill.
- bill_no: the bill / invoice / memo number, "" if none.
- bill_date: the bill date as YYYY-MM-DD, "" if not readable.
- lines: every item billed. name (keep size/spec), item_key (short lowercase key), qty, unit (nos, kg, bag, mt, m, litre, set, pair, box, roll, packet, sheet, length, ...), rate per unit before tax as written (if only the amount is given, amount / qty), amount for the line.
  slip_line_id: if the item is one of APPROVED CHALLAN LINES (same item and size), that line's id, else 0. Never match two bill lines to one challan line unless the bill clearly splits it.
- tax_total: total GST/tax on the bill, 0 if none shown.
- grand_total: the bill's final total, 0 if not readable.
- unclear: anything you could not read with confidence (quote it briefly)."""

_DISPATCH_SYSTEM = """The logistics manager of a construction company in the Andaman & Nicobar Islands reports a dispatch to a site: a caption, and often a photo of a handwritten list of what was sent (or a photo of the parcel / vehicle).

Extract:
- carrier: who or what carries it, e.g. "Prem, by ship", "Anand Bus AN01F3868". "" if not said.
- note: anything the site must know to collect it: collection point, timing, freight paid or not paid. "" if nothing.
- items: everything sent. name (clear English, keep size/spec), item_key (short lowercase key), qty (0 if not stated), unit (nos, kg, gram, bag, packet, set, mt, litre, sheet, m, ...).
  slip_line_id: if the item is clearly one of APPROVED LINES AWAITING DISPATCH, that line's id, else 0. Never match two items to one line.
  stock_item: false for documents, drawings, attendance cards, letters, repaired or returned machines, personal items; true for materials, consumables and tools the site keeps in stock.
  If the photo shows only a parcel or vehicle, take the items from the caption.
- unclear: list entries you could not read."""

_RECEIPT_SYSTEM = """A site engineer is reporting what was actually delivered against a list of dispatched lines (numbered). For each line he mentions, return the quantity received. "ok"/"received"/"aa gaya" for a line means the full quantity; "nahi aaya"/"not received" means 0. Lines he does not mention: omit them."""

_USAGE_SYSTEM = """A site engineer reports materials used/consumed at site. Return each item with quantity and unit. If the item matches one in SITE STOCK, reuse its item_key and unit exactly."""

_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "item_key": {"type": "string"},
        "qty": {"type": "number"},
        "unit": {"type": "string"},
        "spec": {"type": "string"},
    },
    "required": ["name", "item_key", "qty", "unit", "spec"],
    "additionalProperties": False,
}
REQ_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": _ITEM_SCHEMA},
        "unclear": {"type": "array", "items": {"type": "string"}},
        "needed_by": {"type": "string"},
        "urgent": {"type": "boolean"},
        "note": {"type": "string"},
    },
    "required": ["items", "unclear", "needed_by", "urgent", "note"],
    "additionalProperties": False,
}
SLIP_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "site_code": {"type": "string"},
                "name": {"type": "string"},
                "item_key": {"type": "string"},
                "qty": {"type": "number"},
                "unit": {"type": "string"},
                "action": {"type": "string", "enum": ["BUY", "PENDING", "SENT", "DROP"]},
                "vendor": {"type": "string"},
                "rate": {"type": "number"},
                "lump_sum": {"type": "number"},
                "remark": {"type": "string"},
            },
            "required": ["ref", "site_code", "name", "item_key", "qty", "unit", "action", "vendor", "rate", "lump_sum",
                         "remark"],
            "additionalProperties": False,
        }},
        "unclear": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
    },
    "required": ["lines", "unclear", "note"],
    "additionalProperties": False,
}
RATE_MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {"type": "array", "items": {
            "type": "object",
            "properties": {"item": {"type": "integer"}, "past": {"type": "integer"}},
            "required": ["item", "past"],
            "additionalProperties": False,
        }},
    },
    "required": ["matches"],
    "additionalProperties": False,
}
BILL_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor": {"type": "string"},
        "bill_no": {"type": "string"},
        "bill_date": {"type": "string"},
        "lines": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "item_key": {"type": "string"},
                "qty": {"type": "number"},
                "unit": {"type": "string"},
                "rate": {"type": "number"},
                "amount": {"type": "number"},
                "slip_line_id": {"type": "integer"},
            },
            "required": ["name", "item_key", "qty", "unit", "rate", "amount", "slip_line_id"],
            "additionalProperties": False,
        }},
        "tax_total": {"type": "number"},
        "grand_total": {"type": "number"},
        "unclear": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["vendor", "bill_no", "bill_date", "lines", "tax_total", "grand_total", "unclear"],
    "additionalProperties": False,
}
DISPATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "carrier": {"type": "string"},
        "note": {"type": "string"},
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "item_key": {"type": "string"},
                "qty": {"type": "number"},
                "unit": {"type": "string"},
                "slip_line_id": {"type": "integer"},
                "stock_item": {"type": "boolean"},
            },
            "required": ["name", "item_key", "qty", "unit", "slip_line_id", "stock_item"],
            "additionalProperties": False,
        }},
        "unclear": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["carrier", "note", "items", "unclear"],
    "additionalProperties": False,
}
RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {"lines": {"type": "array", "items": {
        "type": "object",
        "properties": {"line_no": {"type": "integer"}, "qty": {"type": "number"}},
        "required": ["line_no", "qty"],
        "additionalProperties": False,
    }}},
    "required": ["lines"],
    "additionalProperties": False,
}
USAGE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"item_key": {"type": "string"}, "name": {"type": "string"},
                       "qty": {"type": "number"}, "unit": {"type": "string"}},
        "required": ["item_key", "name", "qty", "unit"],
        "additionalProperties": False,
    }}},
    "required": ["items"],
    "additionalProperties": False,
}


class ParseError(Exception):
    pass


class ClaudeParser:
    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium", client=None):
        import anthropic

        self.anthropic = anthropic
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.effort = effort

    def _call(self, system: str, content: list[dict], schema: dict, effort: str | None = None) -> dict:
        try:
            # Server-side fallback re-runs the request on another model if a safety
            # classifier ever declines it (unlikely for material lists, but free to enable).
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": effort or self.effort, "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except self.anthropic.RateLimitError as e:
            raise ParseError(f"Claude rate limited: {e.message}") from e
        except self.anthropic.APIStatusError as e:
            raise ParseError(f"Claude API error {e.status_code}: {e.message}") from e
        except self.anthropic.APIConnectionError as e:
            raise ParseError("Could not reach Claude") from e
        if resp.stop_reason == "refusal":
            raise ParseError("Claude declined this message")
        if resp.stop_reason == "max_tokens":
            raise ParseError("Message too long to read in one go")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ParseError("Claude returned unreadable output") from e

    def parse_requisition(self, text, site_name, known_items, current=None, images=None):
        parts = [f"SITE: {site_name}", f"KNOWN ITEM KEYS: {', '.join(known_items) or '(none yet)'}"]
        if current:
            parts.append("CURRENT LIST:\n" + "\n".join(
                f"{i}. {it.name} | key={it.item_key} | {it.qty:g} {it.unit} | {it.spec}" for i, it in enumerate(current, 1)))
        parts.append(f"MESSAGE:\n{text or '(see image)'}")
        content: list[dict] = []
        for data, mime in images or []:
            block = "document" if mime == "application/pdf" else "image"
            content.append({"type": block, "source": {"type": "base64", "media_type": mime,
                                                      "data": base64.standard_b64encode(data).decode()}})
        content.append({"type": "text", "text": "\n\n".join(parts)})
        d = self._call(_REQ_SYSTEM, content, REQ_SCHEMA)
        return ReqParse(
            items=[ParsedItem(name=i["name"].strip(), item_key=norm_key(i["item_key"]) or norm_key(i["name"]),
                              qty=max(0.0, float(i["qty"])), unit=norm_unit(i["unit"]), spec=i["spec"].strip())
                   for i in d["items"] if i["name"].strip()],
            unclear=d["unclear"], needed_by=d["needed_by"], urgent=bool(d["urgent"]), note=d["note"],
        )

    def parse_slip(self, text, open_items, vendors, sites, known_items, current=None):
        req_lines = "\n".join(
            f"{it['ref']} | site={it['site_code']} | {it['name']} | {it['qty']:g} {it['unit']} | key={it['item_key']}"
            for it in open_items) or "(none)"
        parts = [
            "SITES: " + ", ".join(f"{c}={n}" for c, n in sites),
            f"KNOWN SHOPS: {', '.join(vendors) or '(none)'}",
            f"KNOWN ITEM KEYS: {', '.join(known_items) or '(none)'}",
            f"OPEN REQUIREMENTS:\n{req_lines}",
        ]
        if current:
            parts.append("CURRENT PLAN:\n" + "\n".join(
                f"{i}. ref={l.ref or '-'} | site={l.site_code} | {l.name} | {l.qty:g} {l.unit} | {l.action} | "
                f"shop={l.vendor or '-'} | rate {l.rate:g} | remark={l.remark or '-'}"
                for i, l in enumerate(current, 1)))
        parts.append(f"NOTE:\n{text}")
        d = self._call(_SLIP_SYSTEM, [{"type": "text", "text": "\n\n".join(parts)}], SLIP_SCHEMA)
        return SlipParse(
            lines=[ParsedSlipLine(ref=l["ref"].strip().upper(), site_code=l["site_code"].strip().upper(),
                                  name=l["name"].strip(), item_key=norm_key(l["item_key"]) or norm_key(l["name"]),
                                  qty=float(l["qty"]), unit=norm_unit(l["unit"]), vendor=l["vendor"].strip(),
                                  rate=max(0.0, float(l["rate"])), lump_sum=max(0.0, float(l["lump_sum"])),
                                  action=l["action"] if l["action"] in ("BUY", "PENDING", "SENT", "DROP") else "BUY",
                                  remark=l["remark"].strip())
                   for l in d["lines"]],
            unclear=d["unclear"], note=d["note"],
        )

    def parse_dispatch(self, text, open_lines, images=None):
        listing = "\n".join(f"{l['id']} | {l['name']} | {l['qty']:g} {l['unit']} | {l['slip_no']}" for l in open_lines) or "(none)"
        content: list[dict] = []
        for data, mime in images or []:
            block = "document" if mime == "application/pdf" else "image"
            content.append({"type": block, "source": {"type": "base64", "media_type": mime,
                                                      "data": base64.standard_b64encode(data).decode()}})
        content.append({"type": "text", "text": f"APPROVED LINES AWAITING DISPATCH:\n{listing}\n\nCAPTION:\n{text or '(none)'}"})
        d = self._call(_DISPATCH_SYSTEM, content, DISPATCH_SCHEMA)
        return DispatchParse(
            carrier=d["carrier"].strip(), note=d["note"].strip(),
            items=[ParsedDispatchItem(name=i["name"].strip(), item_key=norm_key(i["item_key"]) or norm_key(i["name"]),
                                      qty=max(0.0, float(i["qty"])), unit=norm_unit(i["unit"]),
                                      slip_line_id=int(i["slip_line_id"]), stock_item=bool(i["stock_item"]))
                   for i in d["items"] if i["name"].strip()],
            unclear=d["unclear"],
        )

    def parse_bill(self, text, images, challan_lines):
        listing = "\n".join(f"{l['id']} | {l['name']} | {l['qty']:g} {l['unit']} | {l['vendor']} | {l['challan_no']}"
                            for l in challan_lines) or "(none)"
        content: list[dict] = []
        for data, mime in images:
            block = "document" if mime == "application/pdf" else "image"
            content.append({"type": block, "source": {"type": "base64", "media_type": mime,
                                                      "data": base64.standard_b64encode(data).decode()}})
        content.append({"type": "text", "text": f"APPROVED CHALLAN LINES (id | item | qty | shop | challan):\n{listing}"
                                                f"\n\nCAPTION:\n{text or '(none)'}"})
        d = self._call(_BILL_SYSTEM, content, BILL_SCHEMA)
        return BillParse(
            vendor=d["vendor"].strip(), bill_no=d["bill_no"].strip(), bill_date=d["bill_date"].strip(),
            lines=[ParsedBillLine(name=l["name"].strip(), item_key=norm_key(l["item_key"]) or norm_key(l["name"]),
                                  qty=max(0.0, float(l["qty"])), unit=norm_unit(l["unit"]), rate=max(0.0, float(l["rate"])),
                                  amount=max(0.0, float(l["amount"])), slip_line_id=int(l["slip_line_id"]))
                   for l in d["lines"] if l["name"].strip()],
            tax_total=max(0.0, float(d["tax_total"])), grand_total=max(0.0, float(d["grand_total"])),
            unclear=d["unclear"],
        )

    def match_rates(self, items):
        parts = []
        for i, it in enumerate(items, 1):
            cands = "\n".join(f"   {j}. {c['name']} ({c['unit'] or '-'})" for j, c in enumerate(it["candidates"], 1))
            parts.append(f"ITEM {i}: {it['name']} ({it['unit']})\n PAST PURCHASES:\n{cands}")
        d = self._call(_RATE_MATCH_SYSTEM, [{"type": "text", "text": "\n\n".join(parts)}], RATE_MATCH_SCHEMA, effort="low")
        out: dict[int, int] = {}
        for m in d["matches"]:
            i, j = int(m["item"]), int(m["past"])
            if 1 <= i <= len(items) and 1 <= j <= len(items[i - 1]["candidates"]):
                out[i - 1] = j - 1
        return out

    def parse_receipt(self, text, lines):
        listing = "\n".join(f"{l['line_no']}. {l['name']} - dispatched {l['qty']:g} {l['unit']}" for l in lines)
        d = self._call(_RECEIPT_SYSTEM, [{"type": "text", "text": f"DISPATCHED LINES:\n{listing}\n\nENGINEER SAYS:\n{text}"}], RECEIPT_SCHEMA)
        return [QtyLine(int(x["line_no"]), max(0.0, float(x["qty"]))) for x in d["lines"]]

    def parse_usage(self, text, stock_items):
        listing = "\n".join(f"key={s['item_key']} | {s['name']} | {s['qty']:g} {s['unit']}" for s in stock_items) or "(empty)"
        d = self._call(_USAGE_SYSTEM, [{"type": "text", "text": f"SITE STOCK:\n{listing}\n\nENGINEER SAYS:\n{text}"}], USAGE_SCHEMA)
        return [UsageItem(norm_key(i["item_key"]), i["name"], max(0.0, float(i["qty"])), norm_unit(i["unit"])) for i in d["items"]]


# ---------------------------------------------------------------- offline fallback

_unit_words = sorted(set(UNITS) | set(_UNIT_ALIASES), key=len, reverse=True)
_UNIT_RE = "|".join(re.escape(u) for u in _unit_words)
_ITEM_LINE = re.compile(
    rf"^\s*(?:\d+[.)]\s*)?(?P<name>.*[a-z].*?)\s*[-:=]?\s*(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT_RE})?\b\.?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_QTY_FIRST = re.compile(
    rf"^\s*(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT_RE})?\b\.?\s*(?:of\s+)?(?P<name>[a-z].*)$", re.IGNORECASE
)
_SLIP_REFS = re.compile(r"^\s*(?P<refs>(?:[a-z]\d+(?:\s*(?:-|to|se)\s*[a-z]?\d+)?[\s,&]*(?:and\s+|aur\s+)?)+)\s*[-:]?\s*(?P<rest>.*)$",
                        re.IGNORECASE)
_SLIP_VENDOR = re.compile(r"^(?:from\s+)?(?P<vendor>[a-z][a-z .&']*?)(?:\s+se)?\s*@?\s*(?:rs\.?\s*)?(?P<rate>\d+(?:\.\d+)?)?\s*(?:/\s*\w+)?\s*$",
                          re.IGNORECASE)
_NOTE_ACTIONS = [
    ("DROP", re.compile(r"\b(not needed|no need|cancel(?:led)?|drop|zarurat nahi|nahi chahiye)\b", re.IGNORECASE)),
    ("SENT", re.compile(r"\b(already sent|sent already|bhej diya|bheja hua|already dispatched|gaya hua|gaya tha)\b", re.IGNORECASE)),
    ("PENDING", re.compile(r"\b(not available|unavailable|nahi mila|out of stock|no stock|pending|later|baad mein)\b", re.IGNORECASE)),
]
_BILL_LINE = re.compile(
    r"^\s*(?P<name>.*[a-z].*?)\s+(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>" + _UNIT_RE + r")?\b\.?\s*(?:@|x|×|rate)?\s*"
    r"(?:rs\.?\s*)?(?P<rate>\d+(?:\.\d+)?)\s*(?:/\s*\w+)?\s*$",
    re.IGNORECASE,
)


def _expand_refs(refs: str) -> list[str]:
    out: list[str] = []
    for m in re.finditer(r"([a-z])(\d+)(?:\s*(?:-|to|se)\s*([a-z])?(\d+))?", refs, re.IGNORECASE):
        letter, a, b = m.group(1).upper(), int(m.group(2)), m.group(4)
        if b and int(b) >= a and int(b) - a <= 50:
            out += [f"{letter}{n}" for n in range(a, int(b) + 1)]
        else:
            out.append(f"{letter}{a}")
    return out


# Words that mark a logistics message as a dispatch report ("Car Nicobar Sector - items handed over to Prem").
DISPATCH_WORDS = re.compile(r"\b(dispatch(?:ed)?|loaded|handed over|by hand|departed|shipped|sector)\b", re.IGNORECASE)
# Caption lines (carrier, collection notes) that are not items.
_CAPTION_WORDS = re.compile(
    r"\b(dispatch(?:ed)?|loaded|handed over|by hand|departed|shipped|sector|in ship|by ship|bus|vessel|"
    r"transportation|freight|parked|collect(?:ion)?)\b", re.IGNORECASE)


def _split_lines(text: str) -> list[str]:
    # drop list numbering like "1)." or "2." (but not "2.5 mt")
    parts = [re.sub(r"^\s*\d+\s*[.)]+\s*(?=[^\d\s])", "", p) for p in re.split(r"[\n;]|,(?!\d)", text)]
    return [p.strip() for p in parts if p.strip()]


class RuleParser:
    """Understands 'Cement 50 bags', '50 bags cement', and 'N1 N2 Om Traders 420'."""

    def parse_requisition(self, text, site_name, known_items, current=None, images=None):
        items = list(current or [])
        unclear: list[str] = []
        urgent = bool(re.search(r"\b(urgent|jaldi|asap|emergency)\b", text, re.IGNORECASE))
        for line in _split_lines(text):
            low = line.lower()
            rm = re.match(r"^(?:remove|delete|hatao|cancel)\s+(.+)$", low) or re.match(r"^(.+?)\s+(?:hatao|hata do|remove)$", low)
            if rm:
                key = norm_key(rm.group(1))
                before = len(items)
                items = [i for i in items if key not in i.item_key and key not in i.name.lower()]
                if len(items) == before:
                    unclear.append(line)
                continue
            if re.search(r"requirement|required|list\b", low) and not re.search(r"\d", low):
                continue  # a heading like "Diglipur site requirements --"
            m = _QTY_FIRST.match(line) or _ITEM_LINE.match(line)
            if not m:
                if not re.fullmatch(r"(?:(?:hi|hello|namaste|sir|ji|ok|thanks|thank you|urgent|jaldi)[ .!,]*)+", low):
                    unclear.append(line)
                continue
            name = re.sub(r"\s+", " ", m.group("name")).strip(" -:")
            name = name[:1].upper() + name[1:]
            key = norm_key(name)
            unit = norm_unit(m.group("unit") or "nos")
            q = float(m.group("qty"))
            spec = (m.groupdict().get("rest") or "").strip()
            existing = next((i for i in items if i.item_key == key), None)
            if existing:
                existing.qty, existing.unit = q, unit
            else:
                items.append(ParsedItem(name=name, item_key=key, qty=q, unit=unit, spec=spec))
        return ReqParse(items=items, unclear=unclear, urgent=urgent,
                        note="list updated" if current else "")

    def parse_slip(self, text, open_items, vendors, sites, known_items, current=None):
        """'N1 N2 Om Traders', 'N3-N5 Hira 62', 'N6 not available at Om', 'N7 already sent MV Campbell Bay'."""
        by_ref = {it["ref"].upper(): it for it in open_items}
        lines = list(current or [])
        unclear: list[str] = []
        for raw in [p.strip() for p in re.split(r"[\n;]", text) if p.strip()]:
            m = _SLIP_REFS.match(raw)
            if not m or not m.group("rest").strip():
                unclear.append(raw)
                continue
            rest = m.group("rest").strip()
            action = next((a for a, rx in _NOTE_ACTIONS if rx.search(rest)), "BUY")
            vendor, rate, remark = "", 0.0, ""
            if action == "BUY":
                vm = _SLIP_VENDOR.match(rest)
                if not vm:
                    unclear.append(raw)
                    continue
                vendor = vm.group("vendor").strip()
                vendor = next((v for v in vendors if v.lower().startswith(vendor.lower()[:3])), vendor.title())
                rate = float(vm.group("rate") or 0)
            else:
                remark = rest
            for ref in _expand_refs(m.group("refs")):
                it = by_ref.get(ref)
                if not it:
                    unclear.append(f"{ref}: not an open requirement")
                    continue
                lines = [l for l in lines if l.ref != ref]
                lines.append(ParsedSlipLine(ref=ref, site_code=it["site_code"], name=it["name"], item_key=it["item_key"],
                                            qty=it["qty"], unit=it["unit"], vendor=vendor, rate=rate, action=action,
                                            remark=remark))
        return SlipParse(lines=lines, unclear=unclear, note="plan updated" if current else "")

    def parse_bill(self, text, images, challan_lines):
        """Typed bills only ('Cement 50 bag 410' per line); reading photos needs Claude."""
        lines: list[ParsedBillLine] = []
        unclear: list[str] = []
        bill_no = ""
        total = 0.0
        used: set[int] = set()
        for raw in [p.strip() for p in re.split(r"[\n;]", text or "") if p.strip()]:
            low = raw.lower()
            if m := re.match(r"^(?:bill|invoice|memo)\s*(?:no\.?|number|#)?\s*[:\-]?\s*(\S+)$", low):
                bill_no = m.group(1).upper()
                continue
            if m := re.match(r"^(?:grand\s+)?total\s*[:\-]?\s*(?:rs\.?\s*)?(\d+(?:\.\d+)?)$", low):
                total = float(m.group(1))
                continue
            if re.fullmatch(r"(bill|invoice|challan|cash memo)", low):
                continue
            m = _BILL_LINE.match(raw)
            if not m:
                unclear.append(raw)
                continue
            name = m.group("name").strip(" -:")
            key = norm_key(name)
            q, rate = float(m.group("qty")), float(m.group("rate"))
            match = next((c for c in challan_lines if c["id"] not in used and
                          (key in norm_key(c["name"]) or norm_key(c["name"]) in key)), None)
            if match:
                used.add(match["id"])
            lines.append(ParsedBillLine(name=name[:1].upper() + name[1:], item_key=key, qty=q,
                                        unit=norm_unit(m.group("unit") or "nos"), rate=rate, amount=round(q * rate, 2),
                                        slip_line_id=match["id"] if match else 0))
        if images and not lines:
            unclear.append("Reading bill photos needs the Claude API key. Type the bill as lines like: Cement 50 bag 410")
        return BillParse(vendor="", bill_no=bill_no, bill_date="", lines=lines, grand_total=total, unclear=unclear)

    def match_rates(self, items):
        out: dict[int, int] = {}
        for i, it in enumerate(items):
            best = max(range(len(it["candidates"])), key=lambda j: it["candidates"][j]["score"], default=None)
            if best is not None and it["candidates"][best]["score"] >= 0.6:
                out[i] = best
        return out

    def parse_dispatch(self, text, open_lines, images=None):
        m = re.search(r"(?:handed over to|by hand of|loaded in|sent with|sent by|through)\s+(.+?)(?=\s+departed|\s+travelling|[,\n]|\.\s|$)",
                      text, re.IGNORECASE)
        carrier = m.group(1).strip() if m else ""
        note = ". ".join(s.strip() for s in re.findall(r"[^.\n]*(?:collect|parked|freight|transportation)[^.\n]*", text, re.IGNORECASE))
        listing = "\n".join(l for l in text.splitlines() if not _CAPTION_WORDS.search(l))
        req = self.parse_requisition(listing, "", [])
        items = [ParsedDispatchItem(i.name, i.item_key, i.qty, i.unit) for i in req.items]
        if not items:  # "Cement and gitti loaded in bus": take the approved lines the caption names
            low = text.lower()
            items = [ParsedDispatchItem(l["name"], l["item_key"], l["qty"], l["unit"], l["id"]) for l in open_lines
                     if any(w in low for w in l["item_key"].split() if len(w) > 3)]
        used: set[int] = set()
        for it in items:
            if it.slip_line_id:
                used.add(it.slip_line_id)
                continue
            match = next((l for l in open_lines if l["id"] not in used and (l["item_key"] in it.item_key or it.item_key in l["item_key"])), None)
            if match:
                it.slip_line_id = match["id"]
                used.add(match["id"])
        return DispatchParse(carrier=carrier, note=note, items=items)

    def parse_receipt(self, text, lines):
        out = []
        for m in re.finditer(r"(\d+)\s*[-:=.]\s*(\d+(?:\.\d+)?)", text):
            out.append(QtyLine(int(m.group(1)), float(m.group(2))))
        return out

    def parse_usage(self, text, stock_items):
        out = []
        body = re.sub(r"^\s*(used|use|consumed|kharch|lag gaya|lagaya)\s*[:\-]?\s*", "", text, flags=re.IGNORECASE)
        for line in _split_lines(body):
            m = _QTY_FIRST.match(line) or _ITEM_LINE.match(line)
            if not m:
                continue
            name = m.group("name").strip()
            key = norm_key(name)
            match = next((s for s in stock_items if key and (key in s["item_key"] or s["item_key"] in key)), None)
            out.append(UsageItem(match["item_key"] if match else key, match["name"] if match else name,
                                 float(m.group("qty")), match["unit"] if match else norm_unit(m.group("unit") or "nos")))
        return out
