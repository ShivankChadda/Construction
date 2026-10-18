import fitz  # pymupdf

from purchasebot import store
from purchasebot.fmt import inr, lakh
from purchasebot.pdf import render_requirements_pdf


def _text(path) -> str:
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def test_pending_pdf_is_marked_not_valid(chat):
    chat.requisition("chandra", "cement 50 bags")
    chat.slip("N1 Om Traders 420")
    text = _text(store.slip_by_number(chat.db, 1).pdf_path)
    assert "PENDING APPROVAL - NOT VALID FOR PURCHASE" in text
    assert "Verification code" not in text


def test_approved_pdf_carries_signature_block(chat):
    chat.requisition("chandra", "cement 50 bags\nsand 3 truck")
    chat.slip("N1 Om Traders 420\nN2 Om Traders 9500")
    chat.say("boss", "2 nahi")
    chat.tap("boss", "✅ Confirm")
    slip = store.slip_by_number(chat.db, 1)
    text = _text(slip.pdf_path)
    assert "PARTIALLY APPROVED" in text
    assert "APPROVED AND DIGITALLY SIGNED BY" in text and "Rajesh Chadda" in text
    assert slip.verify_code in text
    assert "NOT APPROVED" in text
    assert "Rs. 21,000" in text and "₹" not in text
    with fitz.open(slip.pdf_path) as doc:
        assert doc.page_count == 1


def test_requirements_pdf(chat, tmp_path):
    chat.requisition("chandra", "cement 50 bags")
    chat.requisition("siddhu", "gitti 4 brass urgent")
    out = render_requirements_pdf(store.open_items(chat.db), chat.bot.roster, tmp_path / "list.pdf")
    text = _text(out)
    assert "NICOBAR" in text and "DIGLIPUR" in text and "URGENT" in text and "N1" in text


def test_indian_number_format():
    assert inr(155000) == "₹1,55,000"
    assert inr(12345678) == "₹1,23,45,678"
    assert inr(999) == "₹999"
    assert lakh(255000) == "₹2.55 L"
    assert lakh(31000000) == "₹3.10 Cr"
