import pytest

from purchasebot.approval import (
    AMBIGUOUS,
    APPROVE_ALL,
    PARTIAL,
    QUERY,
    REJECT_ALL,
    find_slip_number,
    read_decision,
)


@pytest.mark.parametrize("text", [
    "yes", "Yes.", "ok", "OK go ahead", "haan", "Haan ji", "theek hai", "theek hai na", "kar do", "le lo",
    "approved", "👍", "👍👍", "✅", "हाँ", "ठीक है", "कर दो",
])
def test_approve_all(text):
    d = read_decision(text, 4)
    assert d.kind == APPROVE_ALL and d.approve == {1, 2, 3, 4}


@pytest.mark.parametrize("text", ["no", "No", "nahi", "reject", "mat karo", "don't buy", "❌", "नहीं", "na"])
def test_reject_all(text):
    d = read_decision(text, 4)
    assert d.kind == REJECT_ALL and d.reject == {1, 2, 3, 4}


@pytest.mark.parametrize("text,approve,reject", [
    ("approve all except 3", {1, 2, 4}, {3}),
    ("sab ok 3 chhod ke", {1, 2, 4}, {3}),
    ("3 nahi", {1, 2, 4}, {3}),
    ("reject 2, 4", {1, 3}, {2, 4}),
    ("only 1 2", {1, 2}, {3, 4}),
    ("sirf 1 aur 4", {1, 4}, {2, 3}),
    ("1,2 ok", {1, 2}, {3, 4}),
    ("approve 1 2 reject 3 4", {1, 2}, {3, 4}),
    ("1 2 ok 3 4 no", {1, 2}, {3, 4}),
])
def test_partial(text, approve, reject):
    d = read_decision(text, 4)
    assert d.kind == PARTIAL
    assert d.approve == approve and d.reject == reject


@pytest.mark.parametrize("text", [
    "cement 40 bags only",          # 40 is not a line number: a quantity change
    "ok but check the rate first",  # conditional
    "what is the rate of cement?",
    "hold",
    "ok after checking with vendor about it",
    "call me",
])
def test_not_a_decision(text):
    assert read_decision(text, 4).kind == QUERY


@pytest.mark.parametrize("text", ["yes no", "1 2 ok 3 no"])
def test_ambiguous(text):
    assert read_decision(text, 4).kind == AMBIGUOUS


def test_listing_every_line_is_approve_all():
    assert read_decision("only 1 2", 2).kind == APPROVE_ALL
    assert read_decision("1 2 nahi", 2).kind == REJECT_ALL


def test_slip_numbers():
    assert find_slip_number("yes PS-0042") == 42
    assert find_slip_number("ps 7 ok") == 7
    assert find_slip_number("PS42") == 42
    assert find_slip_number("yes") is None
