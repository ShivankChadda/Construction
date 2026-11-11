"""Turn parsed Tally vouchers + masters into Zoho Books import files for a date range.

Usage:
  python -I convert.py vouchers.json masters.json zoho_coa.json OUTDIR 20260401 20260930

zoho_coa.json is a Chart of Accounts listing from the Zoho API (used to avoid name clashes and to
skip accounts that already exist).  Writes numbered CSVs in import order plus expected.json
(the Zoho trial balance we expect, ledger by ledger) and a plan.json describing every voucher.
"""
import csv, json, os, re, sys, collections
from decimal import Decimal as D, ROUND_HALF_UP
sys.path.insert(0, os.path.dirname(__file__))
from masters import primary

r2 = lambda x: D(x).quantize(D('0.01'), rounding=ROUND_HALF_UP)
STD_RATES = [D(0), D(5), D(12), D(18), D(28), D(40)]
STATE_CODES = {'35': 'AN', '33': 'TN', '19': 'WB', '27': 'MH', '07': 'DL', '29': 'KA', '36': 'TS', '37': 'AP', '32': 'KL', '24': 'GJ',
               '09': 'UP', '06': 'HR', '08': 'RJ', '10': 'BR', '20': 'JH', '21': 'OD', '22': 'CG', '23': 'MP', '03': 'PB', '18': 'AS'}
STATE_NAMES = {'Andaman & Nicobar Islands': 'AN', 'Tamil Nadu': 'TN', 'West Bengal': 'WB'}
EXISTING_VENDORS = {'UTHAM GAS', 'New Gangaa Traders', 'GANGAA AGENCY', 'UDAI TRADING COMPANY', 'HIRA METALS',
                    'M/s Venkateshwara Hardware Pvt Ltd', 'AUGADH ENTERPRISES', 'Bharat Auto Parts', 'KARAN TRADING (I) PVT LTD'}
TAX_IN = {'INPUT CGST': 'c', 'INPUT UTGST': 'u', 'INPUT IGST': 'i'}
TAX_OUT = {'OUTPUT CGST': 'c', 'OUTPUT UTGST': 'u', 'OUTPUT IGST': 'i'}
ROUND = {'Round Off (P)', 'Round Off'}
BANK_GROUPS = {'Bank Accounts', 'Bank OD A/c'}
CASH_GROUPS = {'Cash-in-Hand'}
VTYPE_SHORT = {'Payment': 'PMT', 'Receipt': 'RCT', 'Contra': 'CTR', 'Journal': 'JV', 'Purchase': 'PUR', 'Sales': 'SAL', 'Debit Note': 'DN', 'Credit Note': 'CN'}
ZTYPE = {  # Tally primary group -> Zoho account type
    'Current Assets': 'Other Current Asset', 'Investments': 'Other Current Asset', 'Fixed Assets': 'Fixed Asset',
    'Misc. Expenses (ASSET)': 'Other Asset', 'Current Liabilities': 'Other Current Liability', 'Suspense A/c': 'Other Current Liability',
    'Branch / Divisions': 'Other Current Liability', 'Loans (Liability)': 'Long Term Liability', 'Capital Account': 'Equity',
    'Sales Accounts': 'Income', 'Direct Incomes': 'Income', 'Indirect Incomes': 'Other Income',
    'Purchase Accounts': 'Cost Of Goods Sold', 'Direct Expenses': 'Cost Of Goods Sold', 'Indirect Expenses': 'Expense',
}
GST_JV_SUFFIX = ' - Tally entries'   # GST ledgers posted outside bills/invoices get their own account (Zoho tax accounts are system-only)


def zdate(d): return f"{d[6:]}/{d[4:6]}/{d[:4]}"
def money(x): return f"{D(x):.2f}"


class Books:
    def __init__(self, masters, zoho_coa):
        self.G, self.L = masters['groups'], masters['ledgers']
        self.zoho = {a['account_name'].lower(): a for a in zoho_coa}
        self.used_accounts = {}   # zoho account name -> (type, parent)

    def parent(self, n): return self.L[n]['parent']
    def prim(self, n): return primary(self.parent(n), self.G)
    def kind(self, n):
        p = self.parent(n)
        if p == 'Sundry Creditors': return 'AP'
        if p == 'Sundry Debtors': return 'AR'
        if p in BANK_GROUPS: return 'bank'
        if p in CASH_GROUPS: return 'cash'
        return 'acct'

    def state(self, n):
        l = self.L[n]; g = l['gstin']
        if re.match(r'^[0-9]{2}[A-Z0-9]{13}$', g or '') and g[:2] in STATE_CODES: return STATE_CODES[g[:2]]
        return STATE_NAMES.get(l['state'], 'AN')

    def gstin(self, n):
        g = self.L[n]['gstin']
        return g if re.match(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$', g or '') else ''

    def zname(self, ledger, gst_outside_tax=False):
        """Zoho account name for a Tally ledger (registers the account so it lands in the COA file)."""
        k = self.kind(ledger)
        if k == 'AP': return 'Accounts Payable'
        if k == 'AR': return 'Accounts Receivable'
        name = ledger
        if ledger in TAX_IN or ledger in TAX_OUT or ledger in ('CGST', 'UTGST'):
            name = ledger + GST_JV_SUFFIX
        elif ' '.join(ledger.split()).lower() == ' '.join(self.parent(ledger).split()).lower():
            name = self.group_name(self.parent(ledger))   # Zoho names are case-insensitive: "SUSPENSE A/C" is the group "Suspense A/c"
        self._register(name, ledger)
        return name

    def group_name(self, g):
        if g == 'Investments': return 'Investments (Tally)'   # Zoho already has an equity account "Investments"
        return g

    def _register(self, name, ledger):
        if name in self.used_accounts: return
        k = self.kind(ledger)
        if k == 'bank': self.used_accounts[name] = ('Bank', '', ledger); return
        if k == 'cash': self.used_accounts[name] = ('Cash', '', ledger); return
        typ = ZTYPE[self.prim(ledger)]
        grp = self.parent(ledger)
        prim = self.prim(ledger)
        # Two levels of grouping at most: Tally primary group > immediate group > ledger.
        chain = [prim] if grp == prim else [prim, grp]
        if name == self.group_name(grp):   # ledger has the same name as its group (e.g. "Bank Charges", "Salary Payable"): post to the group account
            chain = chain[:-1]
        if name.lower() in self.zoho and name.lower() == 'purchase account':
            chain = []
        if grp == 'Purchase Account':
            chain = ['Purchase Account']   # existing Zoho parent (created in the November test)
        parent = ''
        for i, g in enumerate(chain):
            gname = self.group_name(g)
            if gname not in self.used_accounts:
                self.used_accounts[gname] = (typ, self.group_name(chain[i - 1]) if i else '', None)
            parent = gname
        self.used_accounts[name] = (typ, parent, ledger)


def postings(v):
    p = [(l['ledger'], D(l['amount'])) for l in v['lines']]
    for i in v['inventory']:
        p += [(a['ledger'], D(a['amount'])) for a in i['accounting']]
    return p


def tag(v): return f"Tally {v['vouchertypename']} No. {v['vouchernumber']}"


# ---------------------------------------------------------------- bills / invoices

def doc_lines(b, v, party, sign):
    """Item/ledger lines of a purchase (sign=-1) or sales (sign=+1) voucher.  Amount positive.  Rate may be None (unknown)."""
    out = []
    for i in v['inventory']:
        amount = sign * D(i['amount'])
        acct = i['accounting'][0]['ledger']
        q = D(i['qty']); unit = i['unit']
        rate_s = i['rate'].split('/')[0].replace(',', '')
        gst = next((D(r) for h, r in i['gst_rates'] if h == 'IGST'), None)
        if q and r2(q * (amount / q).quantize(D('0.01'))) == amount:
            qty, rate = q, (amount / q).quantize(D('0.01'))
            desc = f"List rate {rate_s} less {i['discount']}% discount" if i['discount'] else ''
        else:
            qty, rate = D(1), amount
            desc = f"{q.normalize()} {unit} @ {rate_s}" + (f" less {i['discount']}% discount" if i['discount'] else '')
        out.append(dict(name=i['item'], ledger=acct, qty=qty, rate=rate, amount=amount, hsn=i['hsn'], gst=gst, desc=desc))
    for l in v['lines']:
        n = l['ledger']
        if n == party or n in TAX_IN or n in TAX_OUT or n in ROUND: continue
        amount = sign * D(l['amount'])
        m = re.search(r'@?\s*([0-9]+)\s*%', n)
        gst = D(m.group(1)) if m else None
        out.append(dict(name=n, ledger=n, qty=D(1), rate=amount, amount=amount, hsn='', gst=gst, desc=''))
    return out


def solve_rates(lines, tally_tax):
    """Fill in unknown GST rates so Zoho's tax lands as close as possible to Tally's."""
    unknown = [l for l in lines if l['gst'] is None]
    if not unknown: return True
    known_tax = sum(l['amount'] * l['gst'] / 100 for l in lines if l['gst'] is not None)
    base = sum(l['amount'] for l in unknown)
    if not base: return False
    implied = (tally_tax - known_tax) / base * 100
    best = min(STD_RATES, key=lambda r: abs(r - implied))
    if abs((best - implied) * base / 100) > 1: return False
    for l in unknown: l['gst'] = best
    return True


def zoho_tax(lines, inter):
    """Zoho computes tax on the document total per rate, rounded once (CGST and UTGST halves separately)."""
    by = collections.Counter()
    for l in lines: by[l['gst']] += l['amount']
    if inter: return sum(r2(a * r / 100) for r, a in by.items())
    return 2 * sum(r2(a * r / 2 / 100) for r, a in by.items())


def bill_or_journal(b, v, kind):
    """Return document dict for a bill/invoice, or (None, reason) if it must go in as a journal."""
    party = v['partyledgername']
    want = 'AP' if kind == 'bill' else 'AR'
    if b.kind(party) != want: return None, f"party {party!r} is {b.parent(party)}"
    taxes = TAX_IN if kind == 'bill' else TAX_OUT
    sign = -1 if kind == 'bill' else 1
    odd = [l['ledger'] for l in v['lines'] if b.parent(l['ledger']) == 'Duties & Taxes' and l['ledger'] not in taxes]
    if odd: return None, 'uses ' + ', '.join(odd)
    party_total = sum(-sign * D(l['amount']) for l in v['lines'] if l['ledger'] == party)
    lines = doc_lines(b, v, party, sign)
    if any(l['amount'] <= 0 for l in lines): return None, 'has a negative/zero line'
    if any(b.kind(l['ledger']) != 'acct' for l in lines): return None, 'line posts to a party/bank ledger'
    tt = collections.Counter()
    for l in v['lines']:
        if l['ledger'] in taxes: tt[taxes[l['ledger']]] += sign * D(l['amount'])
    tally_tax = tt['c'] + tt['u'] + tt['i']
    inter = bool(tt['i'])
    if inter and (tt['c'] or tt['u']): return None, 'mixes IGST and CGST/UTGST'
    gstin = b.gstin(party)
    if not tally_tax and not gstin:
        for l in lines: l['gst'] = 'none'
        z_tax = D(0)
    else:
        if not solve_rates(lines, tally_tax): return None, f"cannot work out GST rate (Tally tax {tally_tax})"
        z_tax = zoho_tax(lines, inter)
    if not gstin and tally_tax and kind == 'bill': return None, 'unregistered vendor but Tally charged GST'
    sub = sum(l['amount'] for l in lines)
    adj = party_total - sub - z_tax
    if abs(adj) > 50: return None, f"Zoho total would differ by {adj}"
    tally_round = sum(sign * D(l['amount']) for l in v['lines'] if l['ledger'] in ROUND)
    return dict(v=v, party=party, lines=lines, inter=inter, gstin=gstin, tally_tax=tally_tax, zoho_tax=z_tax, sub=sub,
                total=party_total, adj=adj, tally_round=tally_round, tt=tt), None


def tax_cols(l, inter):
    if l['gst'] == 'none': return '', '', ''
    r = int(l['gst'])
    return (f"IGST{r}" if inter else f"GST{r}"), str(r), ('Simple' if inter else 'Tax Group')


def bill_rows(b, d):
    v, party = d['v'], d['party']
    rows = []
    for l in d['lines']:
        tn, tp, tt = tax_cols(l, d['inter'])
        rows.append({
            'Bill Date': zdate(v['date']), 'Due Date': zdate(v['date']),
            'Bill Number': v['reference'] or f"TALLY-PUR-{v['vouchernumber']}", 'Reference Number': tag(v),
            'Bill Status': 'Open', 'Vendor Name': party, 'Currency Code': 'INR',
            'GST Treatment': 'business_gst' if d['gstin'] else 'business_none', 'GST Identification Number (GSTIN)': d['gstin'],
            'Source of Supply': b.state(party), 'Destination of Supply': 'AN', 'Is Inclusive Tax': 'false',
            'Item Name': l['name'][:100], 'Description': '; '.join(x for x in [l['desc'], tag(v)] if x),
            'Account': b.zname(l['ledger']), 'HSN/SAC': l['hsn'], 'Quantity': f"{l['qty'].normalize():f}", 'Rate': money(l['rate']),
            'Tax Name': tn, 'Tax Percentage': tp, 'Tax Type': tt,
            'Adjustment': money(d['adj']) if d['adj'] else '', 'Adjustment Description': 'Round off / GST rounding as in Tally' if d['adj'] else '',
        })
    return rows


def invoice_rows(b, d):
    v, party = d['v'], d['party']
    rows = []
    for l in d['lines']:
        tn, tp, tt = tax_cols(l, d['inter'])
        rows.append({
            'Invoice Date': zdate(v['date']), 'Due Date': zdate(v['date']), 'Invoice Number': v['vouchernumber'],
            'Reference Number': tag(v), 'Invoice Status': 'Sent', 'Customer Name': party, 'Currency Code': 'INR',
            'GST Treatment': 'business_gst' if d['gstin'] else 'business_none', 'GST Identification Number (GSTIN)': d['gstin'],
            'Place of Supply': b.state(party), 'Is Inclusive Tax': 'false',
            'Item Name': l['name'][:100], 'Item Desc': '; '.join(x for x in [l['desc'], tag(v)] if x),
            'Account': b.zname(l['ledger']), 'HSN/SAC': l['hsn'], 'Quantity': f"{l['qty'].normalize():f}", 'Item Price': money(l['rate']),
            'Item Tax': tn, 'Item Tax %': tp, 'Item Tax Type': tt,
            'Adjustment': money(d['adj']) if d['adj'] else '', 'Adjustment Description': 'Round off / GST rounding as in Tally' if d['adj'] else '',
            'Notes': tag(v),
        })
    return rows


# ---------------------------------------------------------------- expenses / journals

def expense_rows(b, v):
    """Straight payment from one bank/cash ledger to expense ledgers only -> one Zoho expense per debit line."""
    ps = postings(v)
    cr = [(n, a) for n, a in ps if a > 0]
    dr = [(n, a) for n, a in ps if a < 0]
    if len(cr) != 1 or b.kind(cr[0][0]) not in ('bank', 'cash'): return None
    if not dr or any(b.kind(n) != 'acct' or b.prim(n) not in ('Indirect Expenses', 'Direct Expenses', 'Purchase Accounts') for n, _ in dr): return None
    rows = []
    for i, (n, a) in enumerate(dr, 1):
        rows.append({'Expense Date': zdate(v['date']), 'Expense Account': b.zname(n), 'Paid Through': b.zname(cr[0][0]),
                     'Amount': money(-a), 'Currency Code': 'INR', 'Reference#': f"{VTYPE_SHORT[v['vouchertypename']]}-{v['vouchernumber']}" + (f"/{i}" if len(dr) > 1 else ''),
                     'Description': (tag(v) + (' - ' + v['narration'] if v['narration'] else ''))[:500]})
    return rows


def journal_rows(b, v, number):
    rows = []
    net = collections.OrderedDict()
    for n, a in postings(v):
        net[n] = net.get(n, D(0)) + a
    for n, a in net.items():
        if not a: continue
        k = b.kind(n)
        rows.append({'Journal Date': zdate(v['date']), 'Journal Number': number, 'Reference Number': tag(v)[:50],
                     'Notes': (tag(v) + (' - ' + v['narration'] if v['narration'] else ''))[:500], 'Journal Type': 'both', 'Currency': 'INR',
                     'Account': b.zname(n), 'Description': n if k in ('AP', 'AR') else '', 'Contact Name': n if k in ('AP', 'AR') else '',
                     'Debit': money(-a) if a < 0 else '', 'Credit': money(a) if a > 0 else ''})
    return rows


# ---------------------------------------------------------------- main

def nm(x):
    """Zoho collapses repeated spaces in names, so do it here to keep parent/contact references matching."""
    return ' '.join(x.split()) if isinstance(x, str) else x


def write(path, rows):
    if not rows: return 0
    rows = [{k: nm(v) for k, v in r.items()} for r in rows]
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    return os.path.getsize(path)


def main(vpath, mpath, coapath, out, start, end):
    masters = json.load(open(mpath)); coa = json.load(open(coapath))['data']['chartofaccounts']
    b = Books(masters, coa)
    vs = [v for v in json.load(open(vpath)) if start <= v['date'] <= end and v['iscancelled'] != 'Yes' and v['isoptional'] != 'Yes']
    vs.sort(key=lambda v: (v['date'], v['vouchertypename'], v['vouchernumber']))
    os.makedirs(out, exist_ok=True)
    plan, bills, invoices, expenses = [], [], [], []
    journals = collections.defaultdict(list)
    docs = []
    for v in vs:
        t = v['vouchertypename']; ps = postings(v)
        if not any(a for _, a in ps):
            plan.append(dict(vch=tag(v), date=v['date'], as_='skipped', why='zero amount')); continue
        rec, why = None, ''
        if t == 'Purchase':
            d, why = bill_or_journal(b, v, 'bill')
            if d: bills += bill_rows(b, d); docs.append(('bill', d)); rec = 'bill'
        elif t == 'Sales':
            d, why = bill_or_journal(b, v, 'invoice')
            if d: invoices += invoice_rows(b, d); docs.append(('invoice', d)); rec = 'invoice'
        elif t == 'Payment':
            e = expense_rows(b, v)
            if e: expenses += e; rec = 'expense'
        if not rec:
            num = f"{VTYPE_SHORT[t]}-{v['date'][2:6]}-{v['vouchernumber']}"
            journals[v['date'][:6]] += journal_rows(b, v, num); rec = 'journal'
        plan.append(dict(vch=tag(v), date=v['date'], as_=rec, why=why or ''))

    # parties
    parties = collections.OrderedDict()
    for v in vs:
        for n, _ in postings(v):
            if b.kind(n) in ('AP', 'AR'): parties[n] = 1
    for n, l in b.L.items():
        if b.kind(n) in ('AP', 'AR') and D(l['opening']): parties[n] = 1
    vendors, customers = [], []
    openings = [(n, b.kind(n), D(l['opening'])) for n, l in b.L.items() if D(l['opening'])]
    for n in parties:
        l = b.L[n]; ob = D(l['opening']); g = b.gstin(n)
        row = {'Display Name': n, 'Company Name': n, 'GST Treatment': 'business_gst' if g else 'business_none',
               'GST Identification Number (GSTIN)': g, 'PAN Number': l['pan'],
               'Billing Address': ', '.join(l['address'])[:500], 'Billing State': l['state'], 'Billing Country': 'India', 'Currency Code': 'INR',
               'Notes': 'Tally ledger: ' + n + ('' if g or not l['gstin'] else f" (Tally GSTIN field: {l['gstin']})")}
        if b.kind(n) == 'AP':
            if n in EXISTING_VENDORS:
                continue
            row['Source of Supply'] = b.state(n)
            vendors.append(row)
        else:
            row['Place of Supply'] = b.state(n)
            customers.append(row)

    # chart of accounts, by depth so parents exist before children
    levels = {0: [], 1: [], 2: []}; banks = []
    def depth(name):
        p = b.used_accounts[name][1]; return 0 if not p else 1 + depth(p) if p in b.used_accounts else 1
    for name, (typ, parent, ledger) in b.used_accounts.items():
        if name.lower() in b.zoho: continue
        row = {'Account Name': name, 'Account Code': '', 'Account Type': typ, 'Parent Account': parent,
               'Description': f"Tally ledger: {ledger} (group {b.parent(ledger)})" if ledger else 'Tally group', 'Currency': 'INR'}
        if typ in ('Bank', 'Cash'): banks.append(row)
        else: levels[min(depth(name), 2)].append(row)

    files = []
    def emit(fname, rows, what):
        if rows: files.append((fname, len(rows), write(os.path.join(out, fname), rows), what))
    emit('01a_accounts_top_groups.csv', levels[0], 'Chart of Accounts - top-level groups')
    emit('01b_accounts_sub_groups.csv', levels[1], 'Chart of Accounts - sub groups / ledgers directly under a top group')
    emit('01c_accounts_ledgers.csv', levels[2], 'Chart of Accounts - ledgers under sub groups')
    emit('01d_bank_cash_accounts.csv', banks, 'Bank and cash accounts')
    emit('02_vendors.csv', vendors, 'Vendors')
    emit('03_customers.csv', customers, 'Customers')
    by_month = collections.defaultdict(list)
    for r in bills: by_month[r['Bill Date'][6:] + r['Bill Date'][3:5]].append(r)
    for i, (mth, rows) in enumerate(sorted(by_month.items())):
        emit(f"04{chr(97 + i)}_bills_{mth}.csv", rows, f"Bills {mth}")
    emit('05_invoices.csv', invoices, 'Invoices')
    emit('06_expenses.csv', expenses, 'Expenses')
    for i, (mth, rows) in enumerate(sorted(journals.items())):
        emit(f"07{chr(97 + i)}_journals_{mth}.csv", rows, f"Manual journals {mth}")

    # expected Zoho balances, per Tally ledger, and how Zoho will show them
    tb = collections.Counter()
    for v in vs:
        for n, a in postings(v): tb[n] += a
    json.dump(dict(files=files, plan=plan, openings=[(nm(n), k, str(a)) for n, k, a in openings],
                   docs=[dict(kind=k, vch=tag(d['v']), party=d['party'], sub=str(d['sub']), tally_tax=str(d['tally_tax']), zoho_tax=str(d['zoho_tax']),
                              tt={x: str(y) for x, y in d['tt'].items()}, inter=d['inter'], adj=str(d['adj']), tally_round=str(d['tally_round']), total=str(d['total']),
                              lines=[dict(ledger=l['ledger'], amount=str(l['amount']), gst=str(l['gst'])) for l in d['lines']]) for k, d in docs],
                   tally_movement={n: str(a) for n, a in tb.items()}),
              open(os.path.join(out, 'plan.json'), 'w'), indent=1)
    for f in files: print(f"{f[0]:34s} {f[1]:5d} rows {f[2] / 1024:7.1f} KB  {f[3]}")
    print(collections.Counter(p['as_'] for p in plan))
    for p in plan:
        if p['why']: print('  ->', p['as_'], p['vch'], p['date'], p['why'])


if __name__ == '__main__':
    main(*sys.argv[1:7])
