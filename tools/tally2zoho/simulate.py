"""Re-read the generated import CSVs and post them the way Zoho Books will, then compare with Tally.

Usage: python -I simulate.py OUTDIR masters.json   (OUTDIR holds the CSVs and plan.json from convert.py)
Writes OUTDIR/expected_tb.csv: every Tally ledger, its Apr-Sep movement in Tally, where Zoho shows it, and any difference.
"""
import csv, glob, json, os, sys, collections
from decimal import Decimal as D, ROUND_HALF_UP
sys.path.insert(0, os.path.dirname(__file__))
from convert import GST_JV_SUFFIX, nm

r2 = lambda x: D(x).quantize(D('0.01'), rounding=ROUND_HALF_UP)
BILL_ADJ = 'Other Expenses'          # where Zoho posts a bill's Adjustment
INV_ADJ = 'Other Charges'            # where Zoho posts an invoice's Adjustment


def rows(pattern, out):
    for f in sorted(glob.glob(os.path.join(out, pattern))):
        yield from csv.DictReader(open(f, encoding='utf-8'))


def docs(rs, key):
    g = collections.OrderedDict()
    for r in rs: g.setdefault(key(r), []).append(r)
    return g.values()


def post_doc(lines, z, sign, party_acct, contact, price, taxname, adjacct, taxacct):
    """sign -1 for bills (Dr lines), +1 for invoices (Cr lines). z: Counter of Zoho account -> Tally-sign amount."""
    by = collections.Counter(); sub = D(0)
    for r in lines:
        amt = r2(D(r['Quantity']) * D(r[price]))
        z[r['Account']] += sign * amt; sub += amt
        by[(r[taxname], r[taxname.replace('Name', 'Percentage') if 'Name' in taxname else taxname + ' %'])] += amt
    tax = D(0)
    for (tn, tp), a in by.items():
        if not tn: continue
        rate = D(tp)
        if tn.startswith('IGST'):
            t = r2(a * rate / 100); z[taxacct['i']] += sign * t; tax += t
        else:
            h = r2(a * rate / 2 / 100); z[taxacct['c']] += sign * h; z[taxacct['u']] += sign * h; tax += 2 * h
    adj = D(lines[0]['Adjustment'] or 0)
    z[adjacct] += sign * adj
    total = sub + tax + adj
    z[(party_acct, contact)] += -sign * total
    return total


def main(out, mpath):
    z = collections.Counter()
    tin = {'c': 'Input CGST', 'u': 'Input SGST', 'i': 'Input IGST'}
    tout = {'c': 'Output CGST', 'u': 'Output SGST', 'i': 'Output IGST'}
    nb = ni = 0
    for d in docs(rows('04*_bills_*.csv', out), lambda r: (r['Vendor Name'], r['Bill Number'])):
        post_doc(d, z, -1, 'Accounts Payable', d[0]['Vendor Name'], 'Rate', 'Tax Name', BILL_ADJ, tin); nb += 1
    for d in docs(rows('05_invoices.csv', out), lambda r: r['Invoice Number']):
        post_doc(d, z, 1, 'Accounts Receivable', d[0]['Customer Name'], 'Item Price', 'Item Tax', INV_ADJ, tout); ni += 1
    ne = 0
    for r in rows('06_expenses.csv', out):
        a = D(r['Amount']); z[r['Expense Account']] -= a; z[r['Paid Through']] += a; ne += 1
    nj = set()
    for r in rows('07*_journals_*.csv', out):
        a = D(r['Credit'] or 0) - D(r['Debit'] or 0)
        acct = r['Account']
        z[(acct, r['Contact Name']) if acct in ('Accounts Payable', 'Accounts Receivable') else acct] += a
        nj.add(r['Journal Number'])
    plan = json.load(open(os.path.join(out, 'plan.json')))
    L = {nm(n): l for n, l in json.load(open(mpath))['ledgers'].items()}
    tally = collections.Counter()
    for n, a in plan['tally_movement'].items(): tally[nm(n)] += D(a)

    # Map Zoho accounts back to Tally ledgers.
    zl = collections.Counter(); notes = collections.defaultdict(list)
    for k, a in z.items():
        if isinstance(k, tuple): zl[k[1]] += a; continue
        if k.endswith(GST_JV_SUFFIX): zl[k[:-len(GST_JV_SUFFIX)]] += a; continue
        zl['@' + k] += a
    # Zoho tax accounts hold the bill/invoice GST; Tally keeps it in INPUT/OUTPUT ledgers.
    for t, zk in [('INPUT CGST', '@Input CGST'), ('INPUT UTGST', '@Input SGST'), ('INPUT IGST', '@Input IGST'),
                  ('OUTPUT CGST', '@Output CGST'), ('OUTPUT UTGST', '@Output SGST'), ('OUTPUT IGST', '@Output IGST')]:
        if zk in zl: zl[t] += zl.pop(zk); notes[t].append(f"shown in Zoho as {zk[1:]} (+ '{t}{GST_JV_SUFFIX}' for journal entries)")
    adj_b, adj_i = zl.pop('@' + BILL_ADJ, D(0)), zl.pop('@' + INV_ADJ, D(0))
    for k in list(zl):
        if k.startswith('@'): zl[k[1:]] += zl.pop(k)

    # Zoho account names are case-insensitive ("SUSPENSE A/C" ledger lives in the "Suspense A/c" account).
    canon = {k.lower(): k for k in tally}
    for k in list(zl):
        if k not in tally and k.lower() in canon: zl[canon[k.lower()]] += zl.pop(k)
    out_rows = []
    allk = sorted(set(tally) | set(zl), key=lambda n: (L.get(n, {}).get('parent', 'zz'), n))
    diff_total = D(0)
    for n in allk:
        t, zz = tally.get(n, D(0)), zl.get(n, D(0))
        if not t and not zz: continue
        d = zz - t; diff_total += d
        out_rows.append({'Tally ledger': n, 'Tally group': L.get(n, {}).get('parent', ''), 'Tally Dr(-)/Cr(+)': str(t),
                         'Zoho Dr(-)/Cr(+)': str(zz), 'Difference': str(d) if d else '', 'Where in Zoho': '; '.join(notes.get(n, []))})
    out_rows.append({'Tally ledger': f'(Zoho) {BILL_ADJ} - bill adjustments', 'Tally group': '', 'Tally Dr(-)/Cr(+)': '0',
                     'Zoho Dr(-)/Cr(+)': str(adj_b), 'Difference': str(adj_b), 'Where in Zoho': 'Tally round-off on bills + GST rounding differences'})
    out_rows.append({'Tally ledger': f'(Zoho) {INV_ADJ} - invoice adjustments', 'Tally group': '', 'Tally Dr(-)/Cr(+)': '0',
                     'Zoho Dr(-)/Cr(+)': str(adj_i), 'Difference': str(adj_i), 'Where in Zoho': 'Tally round-off on invoices + GST rounding differences'})
    with open(os.path.join(out, 'expected_tb.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys())); w.writeheader(); w.writerows(out_rows)
    print(f"bills {nb}, invoices {ni}, expense rows {ne}, journals {len(nj)}")
    print('Zoho total (must be 0):', sum(z.values()))
    for r in out_rows:
        if r['Difference']: print(f"  {r['Tally ledger'][:45]:45s} Tally {r['Tally Dr(-)/Cr(+)']:>14} Zoho {r['Zoho Dr(-)/Cr(+)']:>14} diff {r['Difference']:>10}")
    return out_rows


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
