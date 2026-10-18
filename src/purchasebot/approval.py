"""Deterministic reading of the approver's replies.

Approval is never decided by an AI model. A reply either matches these rules
or the bot asks again / forwards it to logistics as a question.

Examples (N = number of lines on the slip):
    "yes" / "ok" / "haan" / "go ahead" / "👍"     -> approve all
    "no" / "nahi" / "reject"                      -> reject all
    "approve all except 3" / "3 nahi" / "no 3,5"  -> approve all but the listed lines
    "only 1 2" / "1,2 ok" / "approve 1 and 4"     -> approve only the listed lines
    "1 2 ok 3 no"                                 -> per-line, must cover every line
    "cement 40 bags only" (40 > N)                -> not a decision: forwarded to logistics
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

APPROVE_ALL = "APPROVE_ALL"
REJECT_ALL = "REJECT_ALL"
PARTIAL = "PARTIAL"
QUERY = "QUERY"  # not a decision; forward to logistics
AMBIGUOUS = "AMBIGUOUS"  # looks like a decision but can't be read safely; ask again

APPROVE_WORDS = {
    "yes", "y", "yep", "yeah", "ok", "okay", "okk", "k", "approve", "approved", "approval",
    "go", "goahead", "doit", "proceed", "confirm", "confirmed", "done", "fine", "sure", "accept",
    "haan", "han", "haa", "ha", "hanji", "haanji", "ji", "theek", "thik", "theekhai", "thikhai",
    "sahi", "chalega", "kardo", "karo", "lelo", "le", "kharido", "manjoor", "manzoor",
    "हाँ", "हां", "हा", "ठीक", "जी", "करो", "लेलो", "मंजूर",
    "👍", "✅", "👌", "🙏",
}
REJECT_WORDS = {
    "no", "n", "nope", "reject", "rejected", "decline", "declined", "cancel", "dont", "don't",
    "nahi", "nahin", "nai", "na", "mat", "don", "matkaro", "mat karo", "band", "radd",
    "नहीं", "नही", "ना", "मत", "रद्द",
    "❌", "👎", "✖",
}
EXCEPT_WORDS = {"except", "but", "excluding", "without", "minus", "chhod", "chod", "chhodke", "chodke", "bina", "छोड़", "छोड़कर", "बिना"}
ONLY_WORDS = {"only", "just", "sirf", "bas", "keval", "सिर्फ", "बस", "केवल"}
ALL_WORDS = {"all", "sab", "sabhi", "saare", "sare", "everything", "full", "सब", "सभी"}

# A token is a run of digits, or a run of anything that isn't space, digit or
# punctuation. (\w would split Devanagari words at their vowel signs.)
_TOKEN = re.compile(r"\d+|[^\s\d.,;:!?()\[\]{}\"'/\\|+*=&_-]+")


@dataclass
class Decision:
    kind: str
    approve: set[int] = field(default_factory=set)
    reject: set[int] = field(default_factory=set)
    reason: str = ""


def _tokens(text: str) -> list[str]:
    t = unicodedata.normalize("NFC", text.lower())
    t = t.replace("go ahead", "goahead").replace("do it", "doit").replace("theek hai", "theekhai").replace("thik hai", "thikhai")
    t = t.replace("ठीक है", "ठीक").replace("mat karo", "matkaro").replace("haan ji", "haanji")
    t = re.sub(r"\bkar\s+(do|lo|dijiye|dena)\b", "kardo", t)
    t = re.sub(r"\ble\s+(lo|lijiye|lena)\b", "lelo", t)
    t = t.replace("कर दो", "करो").replace("ले लो", "लेलो")
    toks: list[str] = []
    for tok in _TOKEN.findall(t):
        stripped = tok.replace("\ufe0f", "")
        # "👍👍" -> two approve tokens
        if stripped and all(ch in APPROVE_WORDS or ch in REJECT_WORDS for ch in stripped):
            toks.extend(stripped)
        else:
            toks.append(tok)
    return toks


def _kind(tok: str) -> str:
    if tok.isdigit():
        return "num"
    if tok in APPROVE_WORDS:
        return "yes"
    if tok in REJECT_WORDS:
        return "no"
    if tok in EXCEPT_WORDS:
        return "except"
    if tok in ONLY_WORDS:
        return "only"
    if tok in ALL_WORDS:
        return "all"
    return "other"


def read_decision(text: str, n_lines: int) -> Decision:
    toks = _tokens(text)
    kinds = [_kind(t) for t in toks]
    nums = [int(t) for t, k in zip(toks, kinds) if k == "num"]
    # "kar do na", "theek hai na": a trailing Hindi "na" is a softener, not a "no".
    if "yes" in kinds:
        kinds = ["other" if (t == "na" and k == "no") else k for t, k in zip(toks, kinds)]
    has_yes = "yes" in kinds
    has_no = "no" in kinds
    has_except = "except" in kinds
    has_only = "only" in kinds
    words = [t for t, k in zip(toks, kinds) if k == "other" and t.isalpha()]

    if not (has_yes or has_no or has_except or has_only):
        return Decision(QUERY, reason="no approve/reject word")

    # A number that isn't a line number ("cement 40 bags only") means the approver
    # is changing a quantity or rate — that's a note for logistics, not a decision.
    if any(n < 1 or n > n_lines for n in nums):
        return Decision(QUERY, reason="numbers are not line numbers")

    # Free text with an incidental "ok" ("ok but check the rate first") is a
    # comment, not an approval.
    if len(words) > (6 if nums else 3):
        return Decision(QUERY, reason="too much free text to treat as a decision")

    lines = set(range(1, n_lines + 1))
    listed = set(nums)

    if not nums:
        if has_except:
            return Decision(QUERY, reason="conditional reply ('ok but ...')")
        if has_yes and not has_no:
            return Decision(APPROVE_ALL, approve=lines)
        if has_no and not has_yes:
            return Decision(REJECT_ALL, reject=lines)
        return Decision(AMBIGUOUS, reason="both yes and no without line numbers")

    if has_except:
        # "approve all except 3", "sab ok 3 chhod ke"
        if has_no and not has_yes:
            return Decision(AMBIGUOUS, reason="'except' with only reject words")
        return _partial(lines - listed, listed, lines)

    if has_yes and has_no:
        return _per_line(toks, kinds, lines)

    if has_no:
        # "3 nahi", "reject 3 5", "no 2"
        return _partial(lines - listed, listed, lines)

    # has_yes or has_only: "only 1 2", "1,2 ok", "approve 1 and 4"
    return _partial(listed, lines - listed, lines)


def _partial(approve: set[int], reject: set[int], lines: set[int]) -> Decision:
    if not approve:
        return Decision(REJECT_ALL, reject=lines)
    if not reject:
        return Decision(APPROVE_ALL, approve=lines)
    return Decision(PARTIAL, approve=approve, reject=reject)


def _per_line(toks: list[str], kinds: list[str], lines: set[int]) -> Decision:
    """'1 2 ok 3 no' (numbers then word) or 'approve 1 2 reject 3' (word then numbers)."""
    sig = [(t, k) for t, k in zip(toks, kinds) if k in ("num", "yes", "no")]
    approve: set[int] = set()
    reject: set[int] = set()
    word_first = sig[0][1] != "num"
    if word_first:
        current = None
        for t, k in sig:
            if k == "num":
                (approve if current == "yes" else reject).add(int(t))
            else:
                current = k
    else:
        pending: list[int] = []
        for t, k in sig:
            if k == "num":
                pending.append(int(t))
            else:
                (approve if k == "yes" else reject).update(pending)
                pending = []
        if pending:
            return Decision(AMBIGUOUS, reason="line numbers after the last yes/no")
    if approve & reject:
        return Decision(AMBIGUOUS, reason="a line is both approved and rejected")
    if approve | reject != lines:
        return Decision(AMBIGUOUS, reason="not every line was covered")
    return _partial(approve, reject, lines)


_SLIP_REF = re.compile(r"\bps[\s\-#/]*0*(\d{1,6})\b", re.IGNORECASE)


def find_slip_number(text: str) -> int | None:
    """'PS-0042', 'ps 42', 'PS42' -> 42."""
    m = _SLIP_REF.search(text)
    return int(m.group(1)) if m else None


def strip_slip_ref(text: str) -> str:
    return _SLIP_REF.sub(" ", text).strip()
