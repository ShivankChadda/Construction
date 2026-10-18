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
    "litre", "box", "roll", "bundle", "set", "load", "truck", "drum", "packet", "sheet", "length", "pair", "lot",
]
_UNIT_ALIASES = {
    "bags": "bag", "bori": "bag", "katta": "bag", "kgs": "kg", "kilo": "kg", "tonne": "mt", "tons": "mt",
    "ton": "mt", "tonnes": "mt", "no": "nos", "nos.": "nos", "number": "nos", "numbers": "nos", "piece": "pcs",
    "pieces": "pcs", "pc": "pcs", "ltr": "litre", "liter": "litre", "litres": "litre", "l": "litre",
    "meter": "m", "metre": "m", "meters": "m", "mtr": "m", "feet": "rft", "ft": "rft", "trucks": "truck",
    "loads": "load", "boxes": "box", "rolls": "roll", "bundles": "bundle", "sets": "set", "drums": "drum",
    "sheets": "sheet", "packets": "packet", "pkt": "packet", "tractor": "load", "trolley": "load",
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


@dataclass
class SlipParse:
    lines: list[ParsedSlipLine]
    unclear: list[str] = field(default_factory=list)
    note: str = ""


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
    def parse_receipt(self, text: str, lines: list[dict]) -> list[QtyLine]: ...
    def parse_usage(self, text: str, stock_items: list[dict]) -> list[UsageItem]: ...


# ---------------------------------------------------------------- Claude

_REQ_SYSTEM = """You read material requirement messages sent on WhatsApp by site engineers of a construction company in the Andaman & Nicobar Islands. Messages are in English, Hindi, Hinglish, or other Indian languages, often abbreviated, sometimes a voice-note transcript or a photo of a handwritten list.

Extract every material, tool or consumable requested.
- name: clear English name with grade/size/spec in it, e.g. "Cement OPC 53 grade", "TMT bar 12 mm Fe500D", "River sand", "Binding wire 18 gauge".
- item_key: a short lowercase key for the same item across messages, e.g. "cement opc 53", "tmt 12mm", "river sand". If the item is the same as one in KNOWN ITEM KEYS, reuse that key exactly.
- qty: the number requested; 0 if no quantity was given.
- unit: one of bag, kg, mt, quintal, nos, pcs, cft, cum, brass, sqft, sqm, rft, m, litre, box, roll, bundle, set, load, truck, drum, packet, sheet, length, pair, lot. Convert words: bori/katta=bag, ton/tonne=mt, piece=pcs.
- spec: extra detail that doesn't belong in the name (brand preference, colour, length), else "".
Common Hindi terms: sariya/saria = TMT bar, gitti/rodi = stone aggregate, balu/reti = sand, eent = brick, patthar = stone, kil = nails, taar = wire, rang = paint, plywood/ply = shuttering plywood, pipe = PVC/GI pipe (keep as said).
- unclear: lines you could not turn into an item (quote them briefly). Greetings and chit-chat are not unclear lines; ignore them.
- needed_by: the date or timing mentioned ("by Monday", "next ship"), else "".
- urgent: true only if the message says urgent/jaldi/emergency/ASAP.
- note: "" for a new list.

When CURRENT LIST is given, the new message edits that list: it may add items, change quantities, or remove items ("remove sand", "cement 60 nahi 50"). Return the complete updated list, and put a one-line summary of the change in note."""

_SLIP_SYSTEM = """You read purchase notes written by the logistics manager of a construction company. He decides which vendor supplies each requested item and at what rate. Turn his note into purchase lines.

OPEN REQUIREMENTS lists items site engineers asked for, each with a ref like N17 (site letter + number). Map each purchase line to its ref when it clearly matches (by ref, or by item name and site). Use the requested qty when he doesn't state one. Use ref "" for things nobody requested (transport, freight, extra items) and then set site_code from the note.

For each line:
- ref: the open requirement ref or "".
- site_code: the site code the material is for (from the ref, or from the note). Use one of the SITES codes.
- name, item_key, unit: as in the requirement when a ref is used; otherwise a clear English name, a short lowercase key (reuse KNOWN ITEM KEYS when it's the same item), and a unit.
- qty: quantity being bought (0 only if truly unknown).
- vendor: supplier name as written; if it matches one in KNOWN VENDORS (spelling variations like Ome/Om, Hera/Hira), use the known name exactly.
- rate: price per unit in rupees (e.g. "420" for 420 per bag; "62/kg" with qty in mt means rate per kg — convert so rate is per the line's unit; 62/kg -> 62000 per mt). 0 if only a total was given.
- lump_sum: total rupees for the line when he gives a total instead of a rate, else 0.
- unclear: parts of the note you could not turn into a line.
- note: "" for a new slip.

When CURRENT SLIP is given, the note edits it (change rate/vendor/qty, add or remove lines). Return the complete updated list of lines and summarise the change in note."""

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
                "vendor": {"type": "string"},
                "rate": {"type": "number"},
                "lump_sum": {"type": "number"},
            },
            "required": ["ref", "site_code", "name", "item_key", "qty", "unit", "vendor", "rate", "lump_sum"],
            "additionalProperties": False,
        }},
        "unclear": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
    },
    "required": ["lines", "unclear", "note"],
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

    def _call(self, system: str, content: list[dict], schema: dict) -> dict:
        try:
            # Server-side fallback re-runs the request on another model if a safety
            # classifier ever declines it (unlikely for material lists, but free to enable).
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
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
            f"KNOWN VENDORS: {', '.join(vendors) or '(none)'}",
            f"KNOWN ITEM KEYS: {', '.join(known_items) or '(none)'}",
            f"OPEN REQUIREMENTS:\n{req_lines}",
        ]
        if current:
            parts.append("CURRENT SLIP:\n" + "\n".join(
                f"{i}. ref={l.ref or '-'} | site={l.site_code} | {l.name} | {l.qty:g} {l.unit} | {l.vendor} | rate {l.rate:g}"
                for i, l in enumerate(current, 1)))
        parts.append(f"NOTE:\n{text}")
        d = self._call(_SLIP_SYSTEM, [{"type": "text", "text": "\n\n".join(parts)}], SLIP_SCHEMA)
        return SlipParse(
            lines=[ParsedSlipLine(ref=l["ref"].strip().upper(), site_code=l["site_code"].strip().upper(),
                                  name=l["name"].strip(), item_key=norm_key(l["item_key"]) or norm_key(l["name"]),
                                  qty=float(l["qty"]), unit=norm_unit(l["unit"]), vendor=l["vendor"].strip(),
                                  rate=float(l["rate"]), lump_sum=float(l["lump_sum"]))
                   for l in d["lines"]],
            unclear=d["unclear"], note=d["note"],
        )

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
_SLIP_LINE = re.compile(
    r"^\s*(?P<refs>(?:[a-z]\d+[\s,&]*(?:and\s+)?)+)\s*[-:]?\s*(?P<vendor>[a-z][a-z .&']*?)\s*@?\s*(?:rs\.?\s*)?(?P<rate>\d+(?:\.\d+)?)\s*(?:/\s*\w+)?\s*$",
    re.IGNORECASE,
)


def _split_lines(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[\n;]|,(?!\d)", text) if p.strip()]


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
        by_ref = {it["ref"].upper(): it for it in open_items}
        lines = list(current or [])
        unclear: list[str] = []
        for raw in [p.strip() for p in re.split(r"[\n;]", text) if p.strip()]:
            m = _SLIP_LINE.match(raw)
            if not m:
                unclear.append(raw)
                continue
            refs = re.findall(r"[a-z]\d+", m.group("refs"), re.IGNORECASE)
            vendor = m.group("vendor").strip()
            known = next((v for v in vendors if v.lower().startswith(vendor.lower()[:3])), vendor)
            rate = float(m.group("rate"))
            for ref in refs:
                it = by_ref.get(ref.upper())
                if not it:
                    unclear.append(f"{ref}: not an open requirement")
                    continue
                lines = [l for l in lines if l.ref != ref.upper()]
                lines.append(ParsedSlipLine(ref=ref.upper(), site_code=it["site_code"], name=it["name"],
                                            item_key=it["item_key"], qty=it["qty"], unit=it["unit"],
                                            vendor=known, rate=rate))
        return SlipParse(lines=lines, unclear=unclear, note="slip updated" if current else "")

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
