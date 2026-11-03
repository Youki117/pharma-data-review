import re
from extract import nz, blocks, time_header, value_status
TRIAL = '(加速|长期试验\\s*(?:I{1,3}|[123])|长期\\s*(?:I{1,3}|[123])|长期|中间条件|影响因素|温度循环)'
CAPTION = re.compile('表\\s*3\\.2\\.[PS]\\.\\d+\\s*-?\\s*\\d+.{0,60}?' + TRIAL)
ROMAN = {'I': '1', 'II': '2', 'III': '3'}

def norm_trial(x):
    t = x.replace('试验', '').replace(' ', '')
    m = re.match('^长期(I{1,3}|[123])$', t)
    if m:
        return '长期' + ROMAN.get(m.group(1), m.group(1))
    return t
ACC_STORAGE = re.compile('40[℃±2\\s]{0,6}.{0,10}?(?:RH|相对湿度为?)\\s*75')
STORAGE_PARAM = [('acc', '加速(40℃/RH75%)', re.compile('40\\s*[℃°C±0-9\\s]{0,8}.{0,12}?(?:RH|相对湿度为?)\\s*75')), ('lt', '长期(25℃/RH60%)', re.compile('25\\s*[℃°C±0-9\\s]{0,8}.{0,12}?(?:RH|相对湿度为?)\\s*60')), ('int', '中间条件(30℃/RH65%)', re.compile('30\\s*[℃°C±0-9\\s]{0,8}.{0,12}?(?:RH|相对湿度为?)\\s*65'))]

def storage_of(s):
    return {k: cn for k, cn, rx in STORAGE_PARAM if rx.search(s)}
TRIAL_NAMES = ('加速', '长期', '中间条件', '影响因素', '温度循环')
STRESS_SUB = ('高温', '高湿', '光照')
NO_TEST = re.compile('(加速试验|长期试验\\s*(?:I{1,3}|[123])|长期试验|中间条件试验|影响因素试验)[^。；]{0,24}?(?:只进行了取样|仅取样|未进行样品检测|未进行检测|不检测|未检测)')
TYPO = [(re.compile('[%％]{2}'), '连续两个百分号'), (re.compile('\\d+\\.\\.\\d+'), '数字里有两个小数点'), (re.compile('。。'), '连续两个句号'), (re.compile('[，,]{2}'), '连续两个逗号')]
MIN_LEN = 25
TOC_TAIL = re.compile('(?:\t|\\s{2,})\\d{1,3}\\s*$|[一-龥\\)）%]\\s*\\d{1,3}\\s*$')

def _is_toc(text):
    return bool(TOC_TAIL.search(text))
MAX_TIME = 60

def _has_data(grid):
    rowb = [blocks(r) for r in grid]
    trow, tcols, times = time_header(rowb)
    if trow < 0 or not times or max(times) > MAX_TIME:
        return False
    for bs in rowb[trow + 1:]:
        for x in bs[-len(times):] if len(bs) > len(times) else []:
            if value_status(x['t']) == 'value':
                return True
    return False

def check_prose(blocks_):
    sect_has_data, sect, pending = ({}, None, None)
    for b in blocks_:
        if b['type'] == 'p':
            t = b['text'].strip()
            if not t:
                continue
            m = CAPTION.search(nz(t))
            pending = m.group(1) if m and (not _is_toc(t)) else None
        else:
            if pending:
                sect, pending = (norm_trial(pending), None)
            if sect and _has_data(b['grid']):
                sect_has_data[sect] = True
    out, sect, pending = ([], None, None)
    for b in blocks_:
        if b['type'] != 'p':
            if pending:
                sect, pending = (norm_trial(pending), None)
            continue
        raw = b['text'].strip()
        if not raw:
            continue
        m = CAPTION.search(nz(raw))
        if m and (not _is_toc(raw)):
            pending = m.group(1)
            continue
        pending = None
        s = nz(raw)
        for rx, why in TYPO:
            if rx.search(s):
                out.append(dict(level='正文格式硬伤', note=why, text=raw, section=sect or '-'))
        m4 = NO_TEST.search(s)
        if m4:
            who = norm_trial(m4.group(1))
            same = [k for k in sect_has_data if k == who or (who == '长期' and k.startswith('长期'))]
            if same:
                out.append(dict(level='正文与表格矛盾', note='正文说「%s试验只取样、未检测」，但汇总表里%s试验的结果表是有实测数据的' % (who, '、'.join(same)), text=raw, section=sect or '-'))
        if len(s) < MIN_LEN or sect is None:
            continue
        enumerating = sum((1 for w in TRIAL_NAMES if w in s)) >= 2
        if sect and sect.startswith('长期') and (not enumerating):
            named_acc = bool(re.search('经?加速试验', s))
            st = storage_of(s)
            if named_acc and 'acc' in st:
                out.append(dict(level='正文与表格矛盾', note='所在章节是「%s试验」，但这段话的试验名和储存条件（40℃/RH75%%）都是加速的 —— 整段疑似从加速那一节复制过来' % sect, text=raw, section=sect))
            elif named_acc and st:
                out.append(dict(level='正文段内矛盾', note='同一段话里试验名写的是「加速试验」，储存条件写的却是%s' % '、'.join(sorted(st.values())), text=raw, section=sect))
            elif 'acc' in st:
                out.append(dict(level='正文与表格矛盾', note='所在章节是「%s试验」，正文写的储存条件却是加速的 40℃/RH75%%' % sect, text=raw, section=sect))
        m3 = re.match('^(高温|高湿|光照)条件下?\\s*[:：]', s)
        if m3:
            head = m3.group(1)
            rest = s[m3.end():]
            others = [w for w in STRESS_SUB if w != head and w in rest]
            if others and head not in rest:
                out.append(dict(level='正文段内矛盾', note='段首写的是「%s条件」，段内叙述却说「%s条件下」' % (head, others[0]), text=raw, section=sect))
    return out
SIM_MIN = 0.9
HEAD_CHARS = 12
DUP_MINLEN = 30

def _dup_body(blocks_):
    out = []
    for b in blocks_:
        if b['type'] != 'p':
            continue
        t = b['text'].strip()
        if len(t) < DUP_MINLEN or _is_toc(t) or CAPTION.search(nz(t)):
            continue
        out.append(t)
    return out

def check_dupes(blocks_):
    import difflib
    ps = _dup_body(blocks_)
    out, seen = ([], set())
    for i in range(len(ps)):
        for j in range(i + 1, len(ps)):
            a, b = (nz(ps[i]), nz(ps[j]))
            if a == b:
                continue
            if abs(len(a) - len(b)) > max(len(a), len(b)) * 0.4:
                continue
            sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
            if sm.ratio() < SIM_MIN:
                continue
            ops = [o for o in sm.get_opcodes() if o[0] != 'equal']
            if not ops or not all((o[1] < HEAD_CHARS and o[3] < HEAD_CHARS for o in ops)):
                continue
            key = (ps[i][:40], ps[j][:40])
            if key in seen:
                continue
            seen.add(key)
            d = '；'.join(('「%s」↔「%s」' % (a[o[1]:o[2]].strip() or '（空）', b[o[3]:o[4]].strip() or '（空）') for o in ops[:4]))
            out.append(dict(level='正文段落雷同', note='这两段话除了开头之外一字不差，只改了 %s。典型的复制上一段后忘了改正文 —— 请确认后一段的叙述、引用的图谱编号、数据是不是也该跟着变。' % d, text='A：%s\nB：%s' % (ps[i][:110], ps[j][:110]), section='-'))
    return out
if __name__ == '__main__':
    import sys, io, os
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from docxgrid import parse
    for p in sys.argv[1:]:
        hits = check_prose(parse(p))
        print('\n===== %s：%d 条' % (os.path.basename(p), len(hits)))
        for h in hits:
            print('  [%s] %s' % (h['level'], h['note']))
            print('      「%s」' % h['text'][:150])
