"""Pull ledgers, groups and cost centres out of a TallyPrime "All Masters" XML export (can be 100+ MB).

Usage: python -I masters.py Master.xml masters.json
"""
import re, sys, json
import xml.etree.ElementTree as ET
sys.path.insert(0, __import__("os").path.dirname(__file__)); from tally import amt

PRIMARY = {  # Tally's 28 reserved groups -> nature
    'Capital Account': 'Liabilities', 'Loans (Liability)': 'Liabilities', 'Current Liabilities': 'Liabilities',
    'Suspense A/c': 'Liabilities', 'Branch / Divisions': 'Liabilities',
    'Fixed Assets': 'Assets', 'Investments': 'Assets', 'Current Assets': 'Assets', 'Misc. Expenses (ASSET)': 'Assets',
    'Sales Accounts': 'Income', 'Direct Incomes': 'Income', 'Indirect Incomes': 'Income',
    'Purchase Accounts': 'Expenses', 'Direct Expenses': 'Expenses', 'Indirect Expenses': 'Expenses',
}

def blocks(text, tag):
    for m in re.finditer(rf'<{tag} [^>]*>.*?</{tag}>', text, re.S):
        s = re.sub(r'&#([0-9]+);', lambda x: '' if int(x.group(1)) < 32 and int(x.group(1)) not in (9, 10, 13) else x.group(0), m.group(0))
        yield ET.fromstring(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '|', s))

def t(e, path):
    x = e.find(path)
    return (x.text or '').strip() if x is not None and x.text else ''

def main(src, dst):
    raw = open(src, 'rb').read()
    text = raw.decode('utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else raw.decode('utf-8')
    groups = {}
    for g in blocks(text, 'GROUP'):
        groups[g.get('NAME')] = {'parent': t(g, 'PARENT'), 'is_revenue': t(g, 'ISREVENUE'), 'affects_gp': t(g, 'AFFECTSGROSSPROFIT'),
                                 'deemed_positive': t(g, 'ISDEEMEDPOSITIVE'), 'is_subledger': t(g, 'ISSUBLEDGER')}
    ledgers = {}
    for l in blocks(text, 'LEDGER'):
        gstin = t(l, 'PARTYGSTIN') or next((t(r, 'GSTIN') for r in l.findall('LEDGSTREGDETAILS.LIST') if t(r, 'GSTIN')), '')
        mail = l.find('LEDMAILINGDETAILS.LIST')
        ledgers[l.get('NAME')] = {
            'parent': t(l, 'PARENT'), 'opening': str(amt(t(l, 'OPENINGBALANCE'))), 'gstin': gstin,
            'state': t(l, 'LEDSTATENAME') or (t(mail, 'STATE') if mail is not None else ''),
            'address': [a.text.strip() for a in (mail if mail is not None else l).findall('ADDRESS.LIST/ADDRESS') if a.text],
            'pan': t(l, 'INCOMETAXNUMBER'), 'billwise': t(l, 'ISBILLWISEON'), 'cost_centres_on': t(l, 'ISCOSTCENTRESON'),
            'tax_type': t(l, 'TAXTYPE'), 'gst_duty_head': t(l, 'GSTDUTYHEAD'), 'gst_type': t(l, 'GSTTYPEOFSUPPLY'),
            'bank_acno': t(l, 'BANKDETAILS') or t(l, 'BANKACCOUNTNUMBER'),
            'bills': [{'name': t(b, 'NAME'), 'date': t(b, 'BILLDATE'), 'amount': str(amt(t(b, 'OPENINGBALANCE')))} for b in l.findall('BILLALLOCATIONS.LIST') if t(b, 'NAME')],
        }
    cost_centres = {c.get('NAME'): {'parent': t(c, 'PARENT'), 'category': t(c, 'CATEGORY')} for c in blocks(text, 'COSTCENTRE')}
    json.dump({'groups': groups, 'ledgers': ledgers, 'cost_centres': cost_centres}, open(dst, 'w'), indent=1)
    print(len(groups), 'groups,', len(ledgers), 'ledgers,', len(cost_centres), 'cost centres')

def primary(name, groups):
    """Walk up to the Tally primary group of a group name."""
    seen = set()
    while name in groups and groups[name]['parent'] and groups[name]['parent'] != '&#4; Primary' and name not in seen:
        seen.add(name); name = groups[name]['parent']
    return name

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
