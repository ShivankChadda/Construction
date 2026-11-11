# Tally → Zoho Books (test converter)

Copies KEC's Tally entries into Zoho Books so they can be compared. Tally stays the book of record.

1. In TallyPrime, export the Day Book for the period as **XML (Data Interchange)** (Alt+E → Current → File Format).
2. `python -I tools/tally2zoho/tally.py DayBook.xml vouchers.json` parses every voucher (ledger lines, items, GSTIN, supplier invoice no.).
3. `python -I tools/tally2zoho/bills.py vouchers.json bills.csv checks.json` writes a Zoho **Import Bills** file for the Purchase vouchers, plus the totals Zoho should show for each bill.

Notes
- Tally amounts are signed: negative = debit, positive = credit.
- GST is charged per line in Zoho (CGST + UTGST, half each, rounded per line). Where Tally's tax or round-off differs, the gap goes into the bill's Adjustment so the bill total always equals Tally's.
- Discounted lines whose net rate isn't a whole paisa are imported as quantity 1 at the net amount, with the quantity and list rate in the description.
- Never commit Tally exports or generated CSVs: they are the company's books.
