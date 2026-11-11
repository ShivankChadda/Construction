"""Turn parsed Tally purchase vouchers into a Zoho Books bill-import CSV, and check the totals Zoho will compute."""
import json, csv, sys
from decimal import Decimal as D, ROUND_HALF_UP

TAX_LEDGERS = {'INPUT CGST': 'cgst', 'INPUT UTGST': 'utgst', 'INPUT SGST': 'utgst', 'INPUT IGST': 'igst'}
ROUND_LEDGERS = {'Round Off (P)'}
STATE = {'Andaman & Nicobar Islands': 'AN'}
r2 = lambda x: D(x).quantize(D('0.01'), rounding=ROUND_HALF_UP)

def iso(d): return f"{d[6:]}/{d[4:6]}/{d[:4]}"  # Zoho org date format dd/MM/yyyy

def lines_of(v):
    """Purchase lines as (name, account, qty, unit, rate, amount, hsn, gst%, description). Amounts positive."""
    out = []
    for i in v['inventory']:
        amount = -D(i['amount'])
        acct = i['accounting'][0]['ledger'] if i['accounting'] else 'PURCHASE GST'
        q = D(i['qty']); unit = i['unit']
        rate_s = i['rate'].split('/')[0].replace(',', '')
        gst = next((D(r) for h, r in i['gst_rates'] if h == 'IGST'), D(0))
        desc = ''
        if q and r2(q * (amount / q).quantize(D('0.01'))) == amount:
            qty, rate = q, (amount / q).quantize(D('0.01'))
            if i['discount']: desc = f"List rate {rate_s} less {i['discount']}% discount"
        else:
            qty, rate, desc = D(1), amount, f"{q.normalize()} {unit} @ {rate_s} less {i['discount']}% discount"
            unit = 'lot'
        out.append(dict(name=i['item'], account=acct, qty=qty, unit=unit, rate=rate, amount=amount, hsn=i['hsn'], gst=gst, desc=desc))
    for l in v['lines']:
        n = l['ledger']
        if n == v['partyledgername'] or n in TAX_LEDGERS or n in ROUND_LEDGERS: continue
        amount = -D(l['amount'])
        gst = D(18) if '18%' in n else D(0) if '0%' in n else None
        if gst is None: raise SystemExit(f"Don't know GST rate for ledger {n!r} in voucher {v['vouchernumber']}")
        out.append(dict(name=n, account=n, qty=D(1), unit='', rate=amount, amount=amount, hsn='', gst=gst, desc='Tally accounting-mode entry (no item details)'))
    return out

def build(vs):
    rows, checks = [], []
    for v in vs:
        if v['vouchertypename'] != 'Purchase' or v['iscancelled'] == 'Yes': continue
        ls = lines_of(v)
        tally_tax = {k: D(0) for k in ('cgst', 'utgst', 'igst')}
        tally_round = D(0)
        for l in v['lines']:
            if l['ledger'] in TAX_LEDGERS: tally_tax[TAX_LEDGERS[l['ledger']]] += -D(l['amount'])
            if l['ledger'] in ROUND_LEDGERS: tally_round += -D(l['amount'])   # + = debit (adds to bill)
        party_total = next(D(l['amount']) for l in v['lines'] if l['ledger'] == v['partyledgername'])
        sub = sum(l['amount'] for l in ls)
        # Zoho: intra-state group = CGST half + UTGST half, each rounded per line
        z_c = sum(r2(l['amount'] * l['gst'] / 2 / 100) for l in ls)
        z_u = z_c
        z_line_total = sub + z_c + z_u
        adjustment = party_total - z_line_total
        reason = []
        if tally_round: reason.append(f"Tally round-off {tally_round:+}")
        tax_diff = (z_c + z_u) - (tally_tax['cgst'] + tally_tax['utgst'])
        if tax_diff: reason.append(f"GST in Zoho {z_c+z_u} vs Tally {tally_tax['cgst']+tally_tax['utgst']}")
        checks.append(dict(vch=v['vouchernumber'], date=iso(v['date']), vendor=v['partyledgername'], bill=v['reference'],
                           taxable=sub, tally_gst=tally_tax['cgst'] + tally_tax['utgst'], zoho_gst=z_c + z_u,
                           adjustment=adjustment, total=party_total, lines=len(ls), note='; '.join(reason)))
        for l in ls:
            rows.append({
                'Bill Date': iso(v['date']), 'Due Date': iso(v['date']), 'Bill Number': v['reference'] or f"TALLY-{v['vouchernumber']}",
                'Bill Status': 'Open', 'Vendor Name': v['partyledgername'], 'Currency Code': 'INR',
                'GST Treatment': 'business_gst', 'GST Identification Number (GSTIN)': v['partygstin'],
                'Source of Supply': STATE[v['placeofsupply']], 'Destination of Supply': 'AN', 'Is Inclusive Tax': 'false',
                'Item Name': l['name'], 'Description': l['desc'], 'Account': l['account'], 'HSN/SAC': l['hsn'],
                'Quantity': f"{l['qty'].normalize():f}", 'Usage unit': l['unit'], 'Rate': f"{l['rate']:.2f}",
                'Tax Name': f"GST{int(l['gst'])}", 'Tax Percentage': f"{int(l['gst'])}", 'Tax Type': 'Tax Group',
                'Adjustment': f"{adjustment:.2f}" if adjustment else '', 'Adjustment Description': 'Round off (as in Tally)' if adjustment else '',
                'Notes': f"Tally Purchase No. {v['vouchernumber']} dated {iso(v['date'])}",
            })
    return rows, checks

if __name__ == '__main__':
    vs = json.load(open(sys.argv[1]))
    rows, checks = build(vs)
    with open(sys.argv[2], 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    json.dump(checks, open(sys.argv[3], 'w'), default=str, indent=1)
    print(f"{len(checks)} bills, {len(rows)} rows")
    T = lambda k: sum(c[k] for c in checks)
    for c in checks:
        print(f"#{c['vch']:>4} {c['date']} {c['vendor'][:34]:34s} {c['bill']:20s} taxable {c['taxable']:>12} GST T{c['tally_gst']:>10} Z{c['zoho_gst']:>10} adj {c['adjustment']:>6} total {c['total']:>12}  {c['note']}")
    print('TOTAL taxable', T('taxable'), 'tally gst', T('tally_gst'), 'zoho gst', T('zoho_gst'), 'adj', T('adjustment'), 'total', T('total'))
