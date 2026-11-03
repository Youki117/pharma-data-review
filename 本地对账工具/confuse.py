import re
from extract import nz
CONFUSABLE = {'0': 'OoΟοОо〇', '1': 'lIiıΙ', '2': 'ƧϨ', '5': 'Ƽ', '6': 'б', '8': 'Ȣ'}
_TO_DIGIT = {ch: d for d, chars in CONFUSABLE.items() for ch in chars}
_CONF = ''.join(_TO_DIGIT)
UNITS = '(?:mg|μg|ug|kg|g|mL|ml|L|cfu|CFU|EU|IU|mol/L|mmol/L|μm|um|nm|mm|cm|℃|°C|%|‰|min|h|片|粒|板|盒|袋|支|个|次|天|日|月|年|lx|Lx|LX|rpm|Hz|Pa|目)'
MEASURE = re.compile('(?<![0-9A-Za-z.])([0-9' + _CONF + ']+(?:[.][0-9' + _CONF + ']+)?)\\s*(' + UNITS + ')(?![0-9A-Za-z])')
_HAS_DIGIT = re.compile('\\d')
_HAS_CONF = re.compile('[' + _CONF + ']')

def check_confusables(blocks_, fname=''):
    out, seen = ([], set())
    for b in blocks_:
        if b['type'] == 'p':
            cells = [('正文', b['text'], None)]
        else:
            cells = [('表格', c['t'], [b.get('ti', 0), ri, ci, len(b['grid'])]) for ri, row in enumerate(b['grid']) for ci, c in enumerate(row) if c['t'].strip()]
        for where, raw, pos in cells:
            t = nz(raw)
            for m in MEASURE.finditer(t):
                num, unit = (m.group(1), m.group(2))
                if not (_HAS_DIGIT.search(num) and _HAS_CONF.search(num)):
                    continue
                fixed = ''.join((_TO_DIGIT.get(c, c) for c in num))
                key = (num, unit)
                if key in seen:
                    continue
                seen.add(key)
                bad = sorted({c for c in num if c in _TO_DIGIT})
                why = '、'.join(('「%s」应该是数字 %s' % (c, _TO_DIGIT[c]) for c in bad))
                a = max(0, m.start() - 24)
                ctx = t[a:m.end() + 24]
                out.append(dict(level='形近字符', cond='-', batch='-', spec='-', time='-', item='%s：%s%s' % (where, num, unit), sv='%s%s' % (num, unit), iv='疑似应为 %s%s' % (fixed, unit), file=fname, stable='', pos=pos, q=raw, note='「%s%s」的数值部分里%s。上下文：…%s…\u3000这类错误在正文字号下人眼几乎看不出来，但会原样进申报资料。' % (num, unit, why, ctx)))
    return out
