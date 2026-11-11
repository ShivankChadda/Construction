"""Read a TallyPrime Trial Balance exported in display format (DSPACCNAME / DSPACCINFO pairs).
Returns [(name, opening, debit, credit, closing)] with Tally signs (negative = Dr)."""
import re, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from tally import load, txt, amt

def read(path):
    root = load(path); out = []; name = None
    for e in root:
        if e.tag == 'DSPACCNAME': name = txt(e, 'DSPDISPNAME')
        elif e.tag == 'DSPACCINFO':
            g = lambda p: amt(txt(e, p))
            out.append((name, g('DSPOPAMT/DSPOPAMTA'), g('DSPDRAMT/DSPDRAMTA'), g('DSPCRAMT/DSPCRAMTA'), g('DSPCLAMT/DSPCLAMTA')))
    return out

if __name__ == '__main__':
    for r in read(sys.argv[1]): print(*r, sep='\t')
