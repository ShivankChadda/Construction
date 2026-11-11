"""Last purchase rates: what the approver compares a purchase against.

Rates come from shop bills recorded by the bot, from Zoho Books (bills and the item list), and from
rates logistics quoted on approved slips. Names rarely match exactly ("PPR stop cock 20x15" vs
"PPR Stop Cock 20 X 15 mm"), so items are matched loosely on words but strictly on sizes: a 20 mm
fitting must never be priced as a 25 mm one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .db import DB
from .llm import norm_unit

# Same item, different words people use for it.
_SYNONYMS = {
    "sariya": "saria", "sarya": "saria", "sariyaa": "saria", "rod": "saria", "tmt": "saria",
    "balu": "sand", "baalu": "sand", "reti": "sand", "gitti": "aggregate", "giti": "aggregate", "metal": "aggregate",
    "pipe": "pipe", "pipes": "pipe", "nos": "", "pcs": "", "pc": "", "no": "",
}
_STOP = {"of", "for", "the", "and", "with", "a", "an", "to", "in", "x", "by", "size", "type", "quality", "new"}
# Units of size stay as words ("mm", "inch") but carry no meaning on their own.
_SIZE_WORDS = {"mm", "cm", "inch", "in", "ft", "m", "kg", "g", "ltr", "litre", "l", "sqmm", "gauge", "g.i", "gi"}
_SAME_UNIT = {"pcs": "nos", "ton": "mt"}
MIN_SCORE = 0.6


def _tokens(name: str) -> tuple[frozenset[str], frozenset[str]]:
    """(words, numbers). '20x15mm' -> words {mm}, numbers {20, 15}."""
    s = name.lower().replace("×", " x ")
    s = re.sub(r"(\d)\s*[x*]\s*(\d)", r"\1 \2", s)          # 20x15 -> 20 15
    s = re.sub(r"(\d)([a-z])", r"\1 \2", s)                   # 15mm -> 15 mm
    s = re.sub(r"([a-z])(\d)", r"\1 \2", s)
    words, numbers = set(), set()
    for t in re.findall(r"\d+(?:\.\d+)?|[a-z]+", s):
        if t[0].isdigit():
            numbers.add(str(float(t)).rstrip("0").rstrip("."))
            continue
        t = _SYNONYMS.get(t, t)
        if t and t not in _STOP:
            words.add(t[:-1] if len(t) > 4 and t.endswith("s") and not t.endswith("ss") else t)
    return frozenset(words), frozenset(numbers)


def _close(a: str, b: str) -> bool:
    """Same word allowing one wrong letter in longer words: adapter/adaptor, cartrige/cartridge."""
    if a == b:
        return True
    if min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i + (len(a) == len(b)):] == b[i + 1:]


def similarity(a: str, b: str) -> float:
    wa, na = _tokens(a)
    wb, nb = _tokens(b)
    if na and nb and na != nb:
        return 0.0  # different sizes are different items
    core_a, core_b = wa - _SIZE_WORDS, wb - _SIZE_WORDS
    if not core_a or not core_b:
        return 0.0
    shared = sum(1 for x in core_a if any(_close(x, y) for y in core_b))
    score = shared / (len(core_a) + len(core_b) - shared)
    if bool(na) != bool(nb):
        score *= 0.8  # one side states a size, the other doesn't
    return score


def _unit(u: str) -> str:
    u = norm_unit(u) if u else ""
    return _SAME_UNIT.get(u, u)


@dataclass
class PastRate:
    rate: float
    vendor: str
    date: str          # ISO date or datetime; "" for a Zoho item-list rate
    name: str          # the past item's name, shown so the approver can judge the match
    source: str        # bill, zoho_bill, zoho_item, slip
    score: float

    def as_dict(self) -> dict:
        return {"rate": self.rate, "vendor": self.vendor, "decided_at": self.date, "name": self.name,
                "source": self.source}


class RateBook:
    """All past rates, loaded once per slip so each line doesn't query the database."""

    def __init__(self, db: DB, exclude_slip: int | None = None):
        self.rows: list[tuple[str, str, frozenset, frozenset, PastRate]] = []
        for r in db.q("SELECT name, item_key, unit, rate, vendor, rate_date, source FROM rate_history WHERE rate > 0"):
            self._add(r["name"], r["item_key"], r["unit"], r["rate"], r["vendor"], r["rate_date"], r["source"])
        for r in db.q(
                "SELECT sl.name, sl.item_key, sl.unit, sl.rate, sl.vendor, s.decided_at FROM slip_lines sl "
                "JOIN slips s ON s.id = sl.slip_id WHERE sl.status = 'APPROVED' AND sl.action = 'BUY' AND sl.rate > 0 "
                "AND s.id != ?", (exclude_slip or -1,)):
            self._add(r["name"], r["item_key"], r["unit"], r["rate"], r["vendor"], r["decided_at"], "slip")

    def _add(self, name, key, unit, rate, vendor, date, source) -> None:
        words, numbers = _tokens(name)
        self.rows.append((key, _unit(unit), words, numbers, PastRate(rate, vendor, date or "", name, source, 0)))

    def _scored(self, item_key: str, name: str, unit: str, floor: float) -> list[PastRate]:
        want_unit = _unit(unit)
        out: list[PastRate] = []
        for key, u, _, _, past in self.rows:
            if u and want_unit and u != want_unit:
                continue
            score = 1.0 if key == item_key else max(similarity(name, past.name), similarity(item_key, key))
            if score >= floor:
                out.append(PastRate(past.rate, past.vendor, past.date, past.name, past.source, score))
        return out

    @staticmethod
    def _latest(rates: list[PastRate]) -> PastRate:
        # Among equally good matches, the most recent purchase wins; an undated Zoho item rate comes last.
        best = max(p.score for p in rates)
        close = [p for p in rates if p.score >= best - 0.05]
        return max(close, key=lambda p: (p.date or "", p.score))

    def last(self, item_key: str, name: str, unit: str) -> PastRate | None:
        scored = self._scored(item_key, name, unit, MIN_SCORE)
        return self._latest(scored) if scored else None

    def candidates(self, item_key: str, name: str, unit: str, k: int = 6) -> list[PastRate]:
        """The closest past items by name, one per distinct name, latest rate each. For an AI to choose from
        when the names are too different for word matching (\"TMT bar 12mm\" vs \"Saria 12mm\")."""
        by_name: dict[str, list[PastRate]] = {}
        for p in self._scored(item_key, name, unit, 0.2):
            by_name.setdefault(p.name.lower(), []).append(p)
        best = [self._latest(v) for v in by_name.values()]
        return sorted(best, key=lambda p: -p.score)[:k]

    def by_name(self, past_name: str, unit: str) -> PastRate | None:
        rows = [PastRate(p.rate, p.vendor, p.date, p.name, p.source, 1.0) for _, u, _, _, p in self.rows
                if p.name.lower() == past_name.lower() and (not u or not unit or u == _unit(unit))]
        return self._latest(rows) if rows else None


def record(db: DB, source: str, ref: str, name: str, item_key: str, unit: str, rate: float, vendor: str,
           date: str) -> None:
    db.run(
        "INSERT INTO rate_history(source, ref, name, item_key, unit, rate, vendor, rate_date) VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(source, ref) DO UPDATE SET name = excluded.name, item_key = excluded.item_key, unit = excluded.unit, "
        "rate = excluded.rate, vendor = excluded.vendor, rate_date = excluded.rate_date",
        (source, ref, name, item_key, unit, rate, vendor, date),
    )
