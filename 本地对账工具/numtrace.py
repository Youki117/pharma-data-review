import re
from extract import nz
from prose import CAPTION, _is_toc
RESTATE = re.compile('→|→')
NUM = re.compile('\\d+(?:\\.\\d+)?')
NOISE = [('表\\s*3\\.2\\.[PS]\\.\\d+\\s*-?\\s*\\d+', '表号'), ('附图\\s*[\\d.\\-a-zA-Z]*\\s*图?\\s*\\d+\\s*[~～]\\s*图?\\s*\\d+', '附图号范围'), ('附图\\s*[\\d.\\-a-zA-Z]+', '附图号'), ('附件\\s*[\\d.\\-a-zA-Z]+', '附件号'), ('[（(]\\s*批号[^）)]*[）)]', '括号里的批号'), ('批号\\s*[：:]?\\s*[A-Za-z0-9、，,\\s]{4,}', '批号列表'), ('\\d{5,}\\s*批', '不带前缀的批号'), ('(?:中国药典|药典)\\s*\\d{0,4}\\s*年?\\s*版?\\s*[一二三四]?\\s*部?\\s*\\d{0,4}', '药典版本'), ('ICH\\s*Q?\\d?[A-E]?(?:\\s*\\(?R\\d\\)?)?', 'ICH 指导原则'), ('\\d{4}\\s*年(?:\\d{1,2}\\s*月)?', '年月'), ('通则\\s*\\d+', '通则号'), ('\\b9001\\b', '稳定性指导原则编号'), ('\\d+(?:\\.\\d+)?\\s*±\\s*\\d+(?:\\.\\d+)?\\s*(?:℃|°C)', '带公差的温度'), ('\\d+\\s*(?:℃|°C)\\s*[±\\d\\s]*', '温度'), ('(?:RH|相对湿度为?)\\s*[\\d.]+\\s*%?\\s*(?:±\\s*[\\d.]+\\s*%?)?', '湿度'), ('[\\d.]+\\s*%\\s*±\\s*[\\d.]+\\s*%', '带公差的百分数'), ('\\d+\\s*(?:lx|Lx|LX)\\s*(?:±\\s*\\d+\\s*(?:lx|Lx))?', '光照度'), ('\\d+\\s*[μu]w?/cm2?', '光照强度'), ('\\d+(?:\\.\\d+)?\\s*(?:mg|g|ml|mL|μg)\\s*(?:规格|/袋|/片|/支)?', '规格与用量'), ('\\d+\\s*(?:片|板|盒|袋|支|个月|月|天|日|min|分钟|小时|h)', '数量与时间'), ('[（(]\\s*[A-Z][a-z]?\\d+(?:[A-Z][a-z]?\\d*)+\\s*[）)]', '分子式'), ('聚乙二醇\\s*\\d+', '带分子量的品名')]
NOISE_RX = [(re.compile(p), why) for p, why in NOISE]

def _strip_noise(t):
    for rx, _why in NOISE_RX:
        t = rx.sub(' ', t)
    return t
NEAR_SPAN = 12
_N = '\\d+(?:\\.\\d+)?'
SIMPLE_PAIR = re.compile('(?<![\\d.~～])(' + _N + ')\\s*[%％]?\\s*(?![~～])→\\s*([^，。；、（）()]{0,6}?)(' + _N + ')(?![~～\\d])')
_CELL_NUM = re.compile('\\s*(' + _N + ')\\s*[%％]?\\s*$')

def _table_nums(b):
    s = set()
    for row in b['grid']:
        for c in row:
            for m in NUM.finditer(nz(c['t'])):
                try:
                    s.add(float(m.group(0)))
                except ValueError:
                    pass
    return s

def build_pools(blocks_):
    per, allp = ([], set())
    for i, b in enumerate(blocks_):
        if b['type'] == 'table':
            s = _table_nums(b)
            per.append((i, s))
            allp |= s
    return (per, allp)

def _near_pool(per, idx, span=NEAR_SPAN):
    out = set()
    for i, s in per:
        if abs(i - idx) <= span:
            out |= s
    return out

def _row_values(grid):
    out = []
    for row in grid:
        vals = []
        for j, c in enumerate(row):
            m = _CELL_NUM.match(nz(c['t']))
            if m:
                vals.append((j, float(m.group(1))))
        out.append(vals)
    return out

def build_rows(blocks_):
    return [(i, _row_values(b['grid'])) for i, b in enumerate(blocks_) if b['type'] == 'table']

def pair_evidence(tables, x, y):
    after = []
    for rows in tables:
        for vals in rows:
            for jx, vx in vals:
                if abs(vx - x) > 1e-09:
                    continue
                for jy, vy in vals:
                    if jy <= jx:
                        continue
                    if abs(vy - y) < 1e-09:
                        return (True, [])
                    if vy not in after:
                        after.append(vy)
    return (False, after)

def _fmtnums(vs, n=6):
    s = '、'.join(('%g' % v for v in vs[:n]))
    return s + ('…' if len(vs) > n else '')

def trace_numbers(blocks_, fname=''):
    per, allp = build_pools(blocks_)
    if not allp:
        return []
    rows_per = build_rows(blocks_)
    out = []
    for i, b in enumerate(blocks_):
        if b['type'] != 'p':
            continue
        raw = b['text'].strip()
        if not raw or _is_toc(raw) or CAPTION.search(nz(raw)):
            continue
        if not RESTATE.search(raw):
            continue
        s = nz(raw)
        near_rows = [r for j, r in rows_per if abs(j - i) <= NEAR_SPAN]
        covered = set()
        for m in SIMPLE_PAIR.finditer(s):
            xs, mid, ys = (m.group(1), m.group(2), m.group(3))
            covered.add(xs)
            covered.add(ys)
            ok, after = pair_evidence(near_rows, float(xs), float(ys))
            if ok:
                continue
            out.append(dict(level='正文数据对不上表格', cond='-', batch='-', spec='-', time='-', item='汇总表正文', sv=raw[:140], iv='正文写「%s→%s%s」，附近结果表里没有这一对' % (xs, mid, ys), file=fname, note='正文在复述表格数据，写的是从 %s 变到 %s。但附近的结果表里，没有哪一行是「%s 在前、%s 在后」——%s请核对是不是抄错了其中一个数。（工具只比数字，不判断这句话的意思）' % (xs, ys, xs, ys, '表里 %s 后面跟的是 %s。' % (xs, _fmtnums(after)) if after else '表里根本没有 %s 这个值。' % xs)))
        pool = _near_pool(per, i)
        seen = set()
        for m in NUM.finditer(_strip_noise(s)):
            s2 = m.group(0)
            if s2 in covered:
                continue
            try:
                v = float(s2)
            except ValueError:
                continue
            if v in pool or s2 in seen:
                continue
            seen.add(s2)
            num = s2
            elsewhere = v in allp
            out.append(dict(level='正文数字无出处', cond='-', batch='-', spec='-', time='-', item='汇总表正文', sv=raw[:140], iv='数字 %s 不在附近的结果表里%s' % (num, '（文档别处出现过）' if elsewhere else '，整份文档也没有'), file=fname, note='这段正文在复述表格数据（写了「→」），但其中的 %s 在附近的结果表里找不到。%s请对照原文和对应的结果表确认。（工具只比数字，不判断这句话的意思）' % (num, '它在文档别的表格里出现过，可能是跨章节引用（正常），也可能是抄了别处的数。' if elsewhere else '整份汇总表的任何表格里都没有这个数，抄错的可能性较大。')))
    return out
