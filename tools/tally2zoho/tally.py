"""Parse a TallyPrime XML export (UTF-16 or UTF-8) into plain vouchers."""
import re, sys, json
import xml.etree.ElementTree as ET
from decimal import Decimal

def load(path):
    raw = open(path, 'rb').read()
    t = raw.decode('utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else raw.decode('utf-8')
    t = re.sub(r'&#([0-9]+);', lambda m: '' if int(m.group(1)) < 32 and int(m.group(1)) not in (9, 10, 13) else m.group(0), t)
    t = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '|', t)
    return ET.fromstring(t)

def txt(e, tag):
    x = e.find(tag)
    return (x.text or '').strip() if x is not None and x.text else ''

def amt(s):
    # Tally amounts: negative = debit, positive = credit. May carry "@ rate" or "= value" parts.
    s = (s or '').strip()
    if not s: return Decimal(0)
    s = s.split('=')[-1] if '=' in s else s
    m = re.search(r'-?[0-9][0-9,]*\.?[0-9]*', s.replace(' ', ''))
    return Decimal(m.group(0).replace(',', '')) if m else Decimal(0)

def qty(s):
    s = (s or '').strip()
    m = re.match(r'(-?[0-9.,]+)\s*(.*)', s)
    return (Decimal(m.group(1).replace(',', '')), m.group(2).strip()) if m else (Decimal(0), '')

def voucher(v):
    out = {k.lower(): txt(v, k) for k in ['GUID', 'ALTERID', 'MASTERID', 'DATE', 'VOUCHERTYPENAME', 'VOUCHERNUMBER', 'REFERENCE',
                                         'REFERENCEDATE', 'PARTYLEDGERNAME', 'PARTYGSTIN', 'PLACEOFSUPPLY', 'STATENAME',
                                         'GSTREGISTRATIONTYPE', 'NARRATION', 'ISCANCELLED', 'ISOPTIONAL', 'ISDELETED', 'ISINVOICE', 'PERSISTEDVIEW']}
    out['action'] = v.get('ACTION', '')
    out['address'] = [a.text.strip() for a in v.findall('ADDRESS.LIST/ADDRESS') if a.text]
    lines = []
    for tag in ('ALLLEDGERENTRIES.LIST', 'LEDGERENTRIES.LIST'):
        for le in v.findall(tag):
            name = txt(le, 'LEDGERNAME')
            if not name: continue
            cc = []
            for cat in le.findall('CATEGORYALLOCATIONS.LIST'):
                for c in cat.findall('COSTCENTREALLOCATIONS.LIST'):
                    cc.append({'category': txt(cat, 'CATEGORY'), 'name': txt(c, 'NAME'), 'amount': str(amt(txt(c, 'AMOUNT')))})
            bills = [{'name': txt(b, 'NAME'), 'type': txt(b, 'BILLTYPE'), 'amount': str(amt(txt(b, 'AMOUNT')))} for b in le.findall('BILLALLOCATIONS.LIST') if txt(b, 'NAME') or txt(b, 'BILLTYPE')]
            lines.append({'ledger': name, 'amount': str(amt(txt(le, 'AMOUNT'))), 'is_party': txt(le, 'ISPARTYLEDGER'),
                          'deemed_positive': txt(le, 'ISDEEMEDPOSITIVE'), 'cost_centres': cc, 'bills': bills,
                          'gst_rate': txt(le, 'GSTRATE') or '', 'tax_class': txt(le, 'GSTCLASS')})
    inv = []
    for tag in ('ALLINVENTORYENTRIES.LIST', 'INVENTORYENTRIES.LIST'):
        for ie in v.findall(tag):
            item = txt(ie, 'STOCKITEMNAME')
            if not item: continue
            q, unit = qty(txt(ie, 'ACTUALQTY') or txt(ie, 'BILLEDQTY'))
            accs = [{'ledger': txt(a, 'LEDGERNAME'), 'amount': str(amt(txt(a, 'AMOUNT'))),
                     'cost_centres': [{'category': txt(cat, 'CATEGORY'), 'name': txt(c, 'NAME'), 'amount': str(amt(txt(c, 'AMOUNT')))}
                                      for cat in a.findall('CATEGORYALLOCATIONS.LIST') for c in cat.findall('COSTCENTREALLOCATIONS.LIST')]}
                    for a in ie.findall('ACCOUNTINGALLOCATIONS.LIST')]
            batches = [{'godown': txt(b, 'GODOWNNAME'), 'tracking': txt(b, 'TRACKINGNUMBER'), 'order': txt(b, 'ORDERNO')} for b in ie.findall('BATCHALLOCATIONS.LIST')]
            hsn = txt(ie, 'GSTHSNNAME') or txt(ie, 'HSNCODE')
            rates = [ (txt(r, 'GSTRATEDUTYHEAD'), txt(r, 'GSTRATE')) for r in ie.findall('.//RATEDETAILS.LIST') if txt(r, 'GSTRATE')]
            inv.append({'item': item, 'qty': str(q), 'unit': unit, 'rate': txt(ie, 'RATE'), 'amount': str(amt(txt(ie, 'AMOUNT'))),
                        'discount': txt(ie, 'DISCOUNT'), 'hsn': hsn, 'gst_rates': rates, 'description': [d.text.strip() for d in ie.findall('BASICUSERDESCRIPTION.LIST/BASICUSERDESCRIPTION') if d.text],
                        'accounting': accs, 'batches': batches})
    out['lines'] = lines
    out['inventory'] = inv
    return out

if __name__ == '__main__':
    root = load(sys.argv[1])
    vs = [voucher(v) for v in root.iter('VOUCHER')]
    json.dump(vs, open(sys.argv[2], 'w'), indent=1)
    print(len(vs), 'vouchers')
