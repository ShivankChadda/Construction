"""Number formatting in the Indian style (1,55,000)."""

from __future__ import annotations


def inr(amount: float, symbol: str = "₹", decimals: bool = False) -> str:
    neg = amount < 0
    amount = abs(amount)
    whole = int(round(amount)) if not decimals else int(amount)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    if decimals:
        s += f".{int(round((amount - int(amount)) * 100)):02d}"
    return f"{'-' if neg else ''}{symbol}{s}"


def qty(q: float) -> str:
    if q is None:
        return "?"
    return str(int(q)) if float(q).is_integer() else f"{q:g}"


def lakh(amount: float) -> str:
    """Compact: ₹1.55 L, ₹2.1 Cr, ₹45,000."""
    if amount >= 1_00_00_000:
        return f"₹{amount / 1_00_00_000:.2f} Cr"
    if amount >= 1_00_000:
        return f"₹{amount / 1_00_000:.2f} L"
    return inr(amount)
