import re
from extract import nz
TOTAL_NAME = re.compile('^(?:总杂|总杂质|各杂质总和|杂质总和|杂质总量)$')
IMPURITY_CAT = re.compile('有关物质|杂质')
PLAIN_NUM = re.compile('^\\d+(?:\\.\\d+)?$')

def _num(v):
    s = nz(v)
    return float(s) if PLAIN_NUM.match(s) else None

def _key(r):
    return (r.get('cond', ''), str(r.get('batch', '')), str(r.get('spec', '')), r.get('time'))

def check_arith(records, fname=''):
    groups = {}
    for r in records:
        if r.get('status') != 'value':
            continue
        if not IMPURITY_CAT.search(nz(r.get('cat', ''))):
            continue
        groups.setdefault(_key(r), []).append(r)
    out = []
    for k, rows in sorted(groups.items(), key=lambda x: str(x[0])):
        totals = [r for r in rows if TOTAL_NAME.match(nz(r.get('leaf', '')))]
        if not totals:
            continue
        tv = _num(totals[0]['value'])
        if tv is None:
            continue
        tname = totals[0]['leaf'].strip()
        for r in rows:
            if TOTAL_NAME.match(nz(r.get('leaf', ''))):
                continue
            v = _num(r['value'])
            if v is None or v <= tv + 1e-09:
                continue
            cond, batch, spec, time = k
            if r.get('rl'):
                out.append(dict(level='单杂＞总杂（报告限写法）', cond=cond, batch=batch, spec=spec, time=time, stable=str(r.get('caption', '')), item='%s/%s' % (r.get('cat', ''), r.get('leaf', '')), sv='%s = %s' % (r.get('leaf', ''), r['value']), pos=r.get('pos'), q=r['value'], iv='（同一张表）%s = %s' % (tname, totals[0]['value']), file=fname, note='「%s」这一格在检验报告单里是「＜报告限（%s%%）」，汇总表按惯例直接写了 %s；它不是实测值，按"报告限以下不计入总杂"的惯例，比「%s」=%s 大不算矛盾%s。列出来只是供抽查。' % (r.get('leaf', ''), r['value'], r['value'], tname, totals[0]['value'], '（总杂那一格在报告单里也是「＜报告限（%s%%）」）' % totals[0]['value'] if totals[0].get('rl') else '')))
                continue
            out.append(dict(level='表内数据矛盾', cond=cond, batch=batch, spec=spec, time=time, stable=str(r.get('caption', '')), item='%s/%s' % (r.get('cat', ''), r.get('leaf', '')), sv='%s = %s' % (r.get('leaf', ''), r['value']), pos=r.get('pos'), q=r['value'], iv='（同一张表）%s = %s' % (tname, totals[0]['value']), file=fname, note='同一张表同一列里，单项杂质「%s」=%s 大于「%s」=%s。总杂包含这个单项，不可能比它小 —— 这两格里必有一个填错了。' % (r.get('leaf', ''), r['value'], tname, totals[0]['value'])))
    return out
