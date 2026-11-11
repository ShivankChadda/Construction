# Tally → Zoho Books (test converter)

Copies KEC's Tally entries into Zoho Books so they can be compared. Tally stays the book of record.

1. In TallyPrime, export the Day Book for the period as **XML (Data Interchange)** (Alt+E → Current → File Format).
2. `python -I tools/tally2zoho/tally.py DayBook.xml vouchers.json` parses every voucher (ledger lines, items, GSTIN, supplier invoice no.).
3. `python -I tools/tally2zoho/bills.py vouchers.json bills.csv checks.json` writes a Zoho **Import Bills** file for the Purchase vouchers, plus the totals Zoho should show for each bill.

Notes
- Tally amounts are signed: negative = debit, positive = credit.
- GST is charged per line in Zoho (CGST + UTGST, half each, rounded per line). Where Tally's tax or round-off differs, the gap goes into the bill's Adjustment so the bill total always equals Tally's.
- Discounted lines whose net rate isn't a whole paisa are imported as quantity 1 at the net amount, with the quantity and list rate in the description.
- Zoho posts bill adjustments to its **Other Expenses** account (Tally: Round Off (P)), and posts UTGST to **Input SGST**.
- Never commit Tally exports or generated CSVs: they are the company's books.

## Full period (Apr–Sep 2026 run)
4. `python -I masters.py Master.xml masters.json`: ledgers, groups, opening balances and GSTINs from an "All Masters" export.
5. `python -I trialbal.py TrialBal.xml`: reads a Trial Balance display export, so the Day Book parse can be checked against it.
6. `python -I convert.py vouchers.json masters.json zoho_coa.json OUT 20260401 20260930` writes the numbered import files in import order. Accounts come first, then vendors and customers, bills, invoices, expenses and manual journals. Purchases go in as bills and sales as invoices. A payment straight from bank/cash to expense ledgers becomes an expense. Everything else becomes a manual journal, with the vendor/customer on the payable/receivable line. A voucher whose GST or party doesn't fit a bill/invoice also goes in as a journal, so balances still match Tally.
7. `python -I simulate.py OUT masters.json` re-reads the CSVs, posts them the way Zoho will, and writes `expected_tb.csv` (Tally vs Zoho, ledger by ledger).
- GST on Tally journals/receipts goes to separate "<ledger> - Tally entries" accounts, because Zoho's tax accounts only take tax from bills and invoices.
- Names are whitespace-normalised: Zoho collapses double spaces.
