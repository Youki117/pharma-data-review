import re, os, json, unicodedata
from docxgrid import parse

def nz(s):
    s = unicodedata.normalize('NFKC', str(s or ''))
    s = s.replace('µ', 'μ').replace('～', '~').replace('－', '-').replace('—', '-')
    s = s.replace('°C', '℃')
    return re.sub('\\s+', '', s)

def blocks(row):
    out, i = ([], 0)
    while i < len(row):
        j = i + 1
        while j < len(row) and row[j]['hm']:
            j += 1
        out.append({'t': row[i]['t'].strip(), 'c0': i, 'c1': j - 1, 'vm': row[i]['vm']})
        i = j
    return out
EMPTY = {'', '/', '-', 'NA', 'N/A', '\\'}

def is_empty(v):
    s = nz(v)
    return s == '' or s in {nz(x) for x in EMPTY}
NOT_TESTED_MARK = re.compile('(此取样点不检查|该取样点不检查|本取样点不检查|不检查|未考察|不考察|未检验|未检测|未做|不适用)')

def value_status(v):
    s = nz(v)
    if s == '':
        return 'blank'
    if s in {nz(x) for x in EMPTY}:
        return 'not_tested'
    if NOT_TESTED_MARK.search(s):
        return 'not_tested'
    return 'value'

def strip_brackets(s):
    t = str(s or '').strip()
    t = re.sub('^[【\\[（(]+', '', t)
    if not re.search('[（(]', t):
        t = re.sub('[】\\]）)]+$', '', t)
    else:
        t = re.sub('[】\\]]+$', '', t)
    return t
CMP = '(?:≤|≥|＜|＞|<|>|=|不得过|应为|应不|应符合|均不得检出|不得检出|(?:应)?(?:不得|不)?(?:低于|少于|小于|高于|多于|大于|超过))'

def leaf_from_limit(limit):
    s = str(limit or '').strip()
    if not s:
        return ''
    s = s.split('\n')[0]
    m0 = re.match('^\\s*(?:每\\s*[\\d.]+\\s*(?:ml|mL|g|mg|片|粒|袋|支)\\s*(?:供试品)?中?)?\\s*(?:均)?不得检出\\s*(.+)$', s)
    if not m0:
        m0 = re.match('^\\s*(.{1,20}?)\\s*(?:均)?不得检出\\s*/?\\s*(?:g|ml|mL)?\\s*$', s)
    if m0:
        n0 = strip_brackets(m0.group(1)).strip('，,。;；:：/ ')
        n0 = re.sub('^(?:每\\s*[\\d.]+\\s*(?:ml|mL|g|mg|片|粒|袋|支)\\s*(?:供试品)?中?)', '', n0).strip('/ ')
        if 1 <= len(n0) <= 28:
            return n0
    m = re.match('^\\s*(.{1,44}?)\\s*' + CMP, s)
    if not m:
        return ''
    name = m.group(1).strip()
    name = re.sub('^(?:本品|每\\s*[\\d.]+\\s*(?:ml|mL|g|mg|片|粒|袋|支)中?|在.{0,20}?中)', '', name)
    name = re.sub('[（(]\\s*(?:除|不包括|扣除).{0,40}?[）)]\\s*$', '', name)
    name = re.sub('^\\d+\\s*(?:min|h|小时|分钟)\\s*时?', '', name)
    name = strip_brackets(name).strip('，,。;；:：')
    return name if 1 <= len(name) <= 30 else ''

def leaf_name(item, limit, sub=''):
    if sub and (not is_empty(sub)):
        return strip_brackets(sub)
    lf = leaf_from_limit(limit)
    return lf or strip_brackets(item)

def _lines(s):
    return [x.strip() for x in str(s or '').split('\n') if x.strip()]

def _mkey(s):
    t = nz(s)
    t = re.sub('^含', '', t)
    t = re.sub('[（(]\\s*(?:除|不包括|扣除).{0,40}?[）)]', '', t)
    t = re.sub('[（(][A-Za-z0-9₂-₉·\\.]+[）)]', '', t)
    t = re.sub('[\\s\u3000/／:：、,，;；。.]', '', t)
    return t
_NAMED = re.compile('^\\s*([^：:]{1,32}?)\\s*[：:]\\s*(\\S.*)$')

def split_multi(item_cat, limit, value, sub=''):
    ll, vl = (_lines(limit), _lines(value))
    named = {}
    for b in vl:
        m = _NAMED.match(b)
        if m:
            named[_mkey(m.group(1))] = m.group(2).strip()
    if len(named) >= 2:
        cand = []
        for a in ll:
            lf = leaf_from_limit(a)
            if lf:
                cand.append((lf, a))
        hit = [(lf, a) for lf, a in cand if _mkey(lf) in named]
        if len(hit) >= 2 and len(hit) * 2 >= len(cand):
            return [(lf, a, named[_mkey(lf)]) for lf, a in hit]
    if nz(item_cat) == '微生物限度' and nz(value).rstrip('。.;；') in ('符合规定', '均符合规定') and (len(ll) >= 2):
        shared = []
        for a in ll:
            named_limit = _NAMED.match(a)
            lf = named_limit.group(1).strip() if named_limit else leaf_from_limit(a)
            if lf not in ('需氧菌总数', '霉菌和酵母菌总数', '大肠埃希菌', '洋葱伯克霍尔德菌'):
                break
            shared.append((lf, a, value))
        if len(shared) == len(ll) and len({r[0] for r in shared}) == len(ll):
            return shared
    if len(ll) >= 2 and len(ll) == len(vl):
        out = []
        ok = True
        for a, b in zip(ll, vl):
            lf = leaf_from_limit(a)
            if not lf:
                ok = False
                break
            out.append((lf, a, strip_leading_name(b, lf)))
        if ok:
            return out
    return [(leaf_name(item_cat, limit, sub), limit, value)]

def strip_leading_name(v, leaf):
    s = str(v or '').strip()
    for cand in (leaf, leaf.lstrip('含'), '含' + leaf.lstrip('含')):
        if cand and s.startswith(cand):
            return s[len(cand):].strip('：: ') or s
    return s

def nz_sp(s):
    t = unicodedata.normalize('NFKC', str(s or ''))
    t = t.replace('µ', 'μ').replace('～', '~').replace('－', '-').replace('—', '-')
    t = t.replace('°C', '℃')
    return re.sub('\\s+', ' ', t).strip()

def cond_time(text):
    s = nz(text)
    sp = nz_sp(text)
    m = re.search('加速[^0-9]{0,12}?(\\d+)\\s*月', s) or re.search('加(\\d+)(?![0-9])', s)
    if m:
        return ('acc', int(m.group(1)))
    m = re.search('长期\\s*(?:试验)?\\s*(I{1,3})[^0-9]{0,14}?(\\d+)\\s*月', sp) or re.search('长期\\s*(?:试验)?\\s*([12])(?![0-9])[^0-9]{1,14}?(\\d+)\\s*月', sp)
    if m:
        n = {'I': 1, 'II': 2, 'III': 3, '1': 1, '2': 2}.get(m.group(1), 1)
        return ('lt%d' % n, int(m.group(2)))
    m = re.search('长期[^0-9]{0,14}?(\\d+)\\s*月', s) or re.search('长(\\d+)(?![0-9])', s)
    if m:
        return ('lt?', int(m.group(1)))
    m = re.search('效期末[^0-9]{0,6}(\\d+)\\s*月', s)
    if m:
        return ('eol', int(m.group(1)))
    if re.search('0天|零天|全检', s):
        return ('base', 0)
    return ('', None)

def cond_from_storage(text):
    s = nz(text)
    if '40℃' in s and '75%' in s:
        return 'acc'
    if '30℃' in s and '65%' in s:
        return 'lt1'
    if '25℃' in s and '60%' in s:
        return 'lt2'
    return ''

def cond_from_caption(cap):
    s = nz(cap)
    if re.search('影响因素', s):
        return 'stress'
    if re.search('温度循环|低温循环|冻融', s):
        return 'cycle'
    if re.search('使用中', s):
        return 'inuse'
    if re.search('加速', s):
        return 'acc'
    sp = nz_sp(cap)
    m = re.search('长期(?:试验)?\\s*(I{1,3})(?![A-Za-z])', sp) or re.search('长期(?:试验)?\\s*([12])(?![0-9])', sp)
    if m:
        return 'lt%d' % {'I': 1, 'II': 2, 'III': 3, '1': 1, '2': 2}.get(m.group(1), 1)
    if re.search('长期', s):
        c = cond_from_storage(s)
        return c if c.startswith('lt') else 'lt?'
    return ''
META_LABELS = {'样品名称', '批号', '规格', '包装', '来源', '批量', '送检量', '生产日期', '送样日期', '报告日期', '有效期', '检验依据', '检验目的', '报告编号'}

def split_batches(raw):
    s = str(raw or '').strip()
    paren = ''
    m = re.search('[（(]([^）)]*)[）)]\\s*$', s)
    if m:
        paren = m.group(1)
        s = s[:m.start()].strip()
    parts = [p.strip() for p in re.split('[、，,;；/\\s]+', s) if p.strip()]
    return (parts, paren)
ITEM_HDR = ('检验项目', '检查项目', '考察项目', '项目')
RESULT_HDR = ('检验结果', '检测结果', '检查结果', '实测结果', '结果')
LIMIT_HDR = ('标准规定', '质量标准', '限度', '标准要求', '规定', '标准', '要求')
RESULT_NOT = re.compile('判定|结论|评价')

def _find_header(rowb):
    for strict in (True, False):
        items = ITEM_HDR[:1] if strict else ITEM_HDR
        results = RESULT_HDR[:1] if strict else RESULT_HDR
        for i, bs in enumerate(rowb):
            txt = [nz(x['t']) for x in bs]
            ic = rc = lc = None
            for k, t in enumerate(txt):
                if ic is None and any((h in t for h in items)):
                    ic = k
                    continue
                if rc is None and any((h in t for h in results)) and (not RESULT_NOT.search(t)):
                    rc = k
                    continue
                if lc is None and any((h in t for h in LIMIT_HDR)):
                    lc = k
            if ic is not None and rc is not None and (len(bs) >= 2):
                span = lambda k: (bs[k]['c0'], bs[k]['c1'])
                cols = {'item': span(ic), 'result': span(rc), 'limit': span(lc) if lc is not None else None}
                return (i, not strict, cols)
    return (-1, False, {})

def _in_span(bs, span):
    if not span:
        return []
    return [x for x in bs if span[0] <= x['c0'] <= span[1]]

def _row_cells(bs, cols):
    ibs = _in_span(bs, cols['item'])
    ib = ibs[0] if ibs else bs[0]
    vbs = _in_span(bs, cols['result'])
    vb = vbs[-1] if vbs else bs[-1]
    if ib is vb or vb['c0'] <= ib['c0']:
        return (ib, None, None, vb)
    lbs = [x for x in _in_span(bs, cols.get('limit')) if ib['c0'] < x['c0'] < vb['c0']]
    if cols.get('limit') and lbs:
        lb = lbs[-1]
        between = [x for x in bs if ib['c1'] < x['c0'] < lb['c0']]
        sb = between[0] if between else None
    else:
        cand = [x for x in bs if ib['c1'] < x['c0'] < vb['c0']]
        lb = cand[-1] if cand else None
        sb = cand[0] if len(cand) >= 2 else None
    return (ib, sb, lb, vb)

def cell_pos(grid, ti, ri, ci, hdr=0):
    while ri > 0 and ci < len(grid[ri]) and grid[ri][ci]['vm']:
        ri -= 1
    return [ti, ri, ci, len(grid), hdr]

def extract_inspection(path, blocks_):
    return extract_inspection_diag(path, blocks_)[0]

def extract_inspection_diag(path, blocks_):
    fname = os.path.basename(path)
    reports = []
    diag = {'file': fname, 'tables': 0, 'header_hit': 0, 'loose_hit': 0, 'blocks': 0}
    for b in blocks_:
        if b['type'] != 'table':
            continue
        grid = b['grid']
        ti = b.get('ti', diag['tables'])
        diag['tables'] += 1
        rowb = [blocks(r) for r in grid]
        hidx, loose, cols = _find_header(rowb)
        if hidx < 0:
            continue
        diag['header_hit'] += 1
        if loose:
            diag['loose_hit'] += 1
        meta = {}
        for bs in rowb[:hidx]:
            for k in range(len(bs) - 1):
                lab = nz(bs[k]['t'])
                if lab in META_LABELS and lab not in meta:
                    v = bs[k + 1]['t'].strip()
                    if v and nz(v) != lab:
                        meta[lab] = v
        recs, warn = ([], [])
        last_item = ''
        for ri, bs in enumerate(rowb[hidx + 1:], hidx + 1):
            if len(bs) <= 1:
                last_item = ''
                continue
            first, subb, limb, valb = _row_cells(bs, cols)
            if first is valb:
                last_item = ''
                continue
            pos = cell_pos(grid, ti, ri, valb['c0'], hidx)
            item_raw = first['t'].strip()
            value = valb['t'].strip()
            limit = limb['t'].strip() if limb is not None else ''
            sub = subb['t'].strip() if subb is not None else ''
            item_cat = strip_brackets(item_raw) or last_item
            if item_cat:
                last_item = item_cat
            if re.match('^(结论|备注|报告人|复核人|QA|检验依据)', nz(item_cat)):
                continue
            if nz(value) == nz(limit) or nz(value) == nz(item_cat):
                continue
            st = value_status(value)
            if st == 'blank':
                continue
            if st == 'not_tested':
                lf = leaf_name(item_cat, limit, sub)
                recs.append({'cat': item_cat, 'leaf': lf or item_cat, 'limit': limit, 'value': value, 'status': 'not_tested', 'pos': pos})
                continue
            for lf, lm, vv in split_multi(item_cat, limit, value, sub):
                recs.append({'cat': item_cat, 'leaf': lf, 'limit': lm, 'value': vv, 'status': 'value', 'pos': pos})
        batches, paren = split_batches(meta.get('批号', ''))
        c1, t1 = cond_time(paren)
        c2, t2 = cond_time(meta.get('样品名称', ''))
        c3 = cond_from_storage(meta.get('来源', '')) or cond_from_storage(meta.get('检验目的', ''))
        c4, t4 = cond_time(fname)
        cond = c1 or c2 or c3 or c4 or ''
        time = t1 if t1 is not None else t2 if t2 is not None else t4
        if cond in ('', 'lt?') and c4 not in ('', 'lt?'):
            cond = c4
        if not cond and time is None:
            cond, time = ('base', 0.0)
        conflicts = []
        if c4 and cond and (c4 != cond) and ('lt?' not in (c4, cond)):
            conflicts.append('文件名条件 %s ≠ 正文条件 %s' % (c4, cond))
        if t4 is not None and time is not None and (t4 != time):
            conflicts.append('文件名时间点 %d月 ≠ 正文时间点 %d月' % (t4, time))
        reports.append({'file': fname, 'batches': batches, 'spec': meta.get('规格', ''), 'cond': cond, 'time': time, 'meta': meta, 'records': recs, 'conflicts': conflicts, 'warnings': warn, 'loose_header': loose})
    diag['blocks'] = len(reports)
    return (reports, diag)
TIME_RE = re.compile('^(\\d+(?:\\.\\d+)?)\\s*(?:月|个月|天|日)?$')

def time_of(txt):
    s = nz(txt)
    m = TIME_RE.match(s)
    return float(m.group(1)) if m else None

def nested_records(sub_hdr, cells):
    if len(sub_hdr) < 2 or len(cells) < 2:
        return []
    um = re.search('[（(]\\s*([A-Za-z]+)\\s*[）)]', sub_hdr[0])
    unit = um.group(1) if um else ''
    xv = cells[0].strip()
    if not xv or is_empty(xv):
        return []
    out = []
    for j in range(1, min(len(sub_hdr), len(cells))):
        lab = re.sub('[（(].*?[）)]', '', sub_hdr[j]).strip().strip('/').strip()
        v = cells[j].strip()
        if not lab or is_empty(v):
            continue
        out.append(('%s%s%s' % (xv, unit, lab), v, j))
    return out
PLAN_CAP = re.compile('方案|留样地点|样品信息|方法及限度|承诺|研究结论|考察结果汇总')

def time_header(rowb):
    for i, bs in enumerate(rowb[:4]):
        idx, tv = ([], [])
        for k, x in enumerate(bs):
            tm = time_of(x['t'])
            if tm is not None:
                idx.append(k)
                tv.append(tm)
        if len(idx) >= 2 and idx == list(range(idx[0], idx[0] + len(idx))):
            return (i, idx, tv)
    return (-1, [], [])
_MULTI_BATCH = re.compile('批号\\s*[:：]?\\s*([A-Za-z0-9\\-]+)((?:\\s*[、，,/;；]\\s*[A-Za-z0-9\\-]{4,})+)')
_SPEC_TOKEN = re.compile('^\\d+(?:\\.\\d+)?(?:mg|g|ml|μg|ug)$', re.I)

def _multi_batch(cap):
    m = _MULTI_BATCH.search(nz(cap))
    if not m:
        return []
    rest = [x for x in re.split('[、，,/;；]', m.group(2)) if x]
    rest = [x for x in rest if not _SPEC_TOKEN.match(x)]
    return [m.group(1)] + rest if rest else []
_INITIAL_HDR = re.compile('^(?:初始|初始值|起始|起始值|零天|零点|T0|initial|start)$', re.I)
_LIMIT_WORD = re.compile('限度|标准|规定|要求')
_PLAIN_NUM = re.compile('^\\d+(?:\\.\\d+)?$')

def _lead_misread(grid, rowb, trow, tcols):
    c0 = rowb[trow][tcols[0]]['c0']
    if c0 > 0:
        left = nz(grid[trow][c0 - 1]['t'])
        if _INITIAL_HDR.match(left):
            return '时间点表头左边一格写的是「%s」，它应该是 0 时间点，但工具只认数字写法（0 / 0月 / 0天）；这一列的实测值会被当成限度' % left
    if c0 < 2:
        return ''
    limit_col = c0 - 1
    hdr = ''.join((nz(grid[r][limit_col]['t']) for r in range(0, trow + 1)))
    if _LIMIT_WORD.search(hdr):
        return ''
    rows = [r for r in grid[trow + 1:] if nz(r[limit_col]['t'])]
    if len(rows) < 2:
        return ''
    numeric = [r for r in rows if _PLAIN_NUM.match(nz(r[limit_col]['t']))]
    if len(numeric) * 2 > len(rows):
        return '「限度」那一列的表头是「%s」，%d 行里有 %d 行写的是纯数字（例：%s），看起来是一列实测值而不是限度' % (hdr[:12] or '（空）', len(rows), len(numeric), nz(numeric[0][limit_col]['t']))
    return ''

def extract_summary(path, blocks_):
    fname = os.path.basename(path)
    out, tables, warn = ([], [], [])
    cap = ''
    seen_caps = set()
    for b in blocks_:
        if b['type'] == 'p':
            t = b['text'].strip()
            if t:
                cap = t
            continue
        grid = b['grid']
        ti = b.get('ti', len(tables))
        c = cond_from_caption(cap)
        bm = re.search('批号\\s*[:：]?\\s*([A-Za-z0-9\\-]+)', nz(cap))
        multi = _multi_batch(cap)
        info = {'caption': cap, 'cond': c, 'batch': bm.group(1) if bm else '', 'rows': len(grid), 'cols': len(grid[0]) if grid else 0}
        rowb = [blocks(r) for r in grid]
        trow, tcols, times = time_header(rowb)
        if not c or not bm or multi or (c not in ('acc', 'lt1', 'lt2', 'lt?')):
            info['scope'] = 'out'
            if trow >= 0 and c not in ('stress', 'cycle', 'inuse') and (not PLAN_CAP.search(nz(cap))):
                why = []
                if not c:
                    why.append('题注里读不出试验条件（加速 / 长期）')
                elif c not in ('acc', 'lt1', 'lt2', 'lt?'):
                    why.append('试验条件「%s」不在对账范围内' % c)
                if not bm:
                    why.append('题注里读不出批号')
                if multi:
                    why.append('题注里写了多个批号（%s），工具按「一张表一个批号」设计，分不清各列属于哪个批号' % '、'.join(multi))
                warn.append('疑似结果表未纳入对账：%s ← %s' % (cap[:44], '；'.join(why)))
            tables.append(info)
            cap = ''
            continue
        if nz(cap) in seen_caps:
            warn.append('题注重复：' + cap[:40])
        seen_caps.add(nz(cap))
        sm = re.search('(\\d+(?:\\.\\d+)?\\s*(?:mg|g|ml|μg))', nz(cap))
        spec = sm.group(1) if sm else ''
        pct_unit = bool(re.search('单位\\s*[:：]?\\s*%', nz(cap)))
        if trow < 0:
            info['scope'] = 'no-time-header'
            tables.append(info)
            warn.append('未识别时间表头：' + cap[:40])
            cap = ''
            continue
        nlead = tcols[0]
        bad = _lead_misread(grid, rowb, trow, tcols)
        if bad:
            info['scope'] = 'out'
            warn.append('疑似列错位：%s ← %s' % (cap[:44], bad))
            tables.append(info)
            cap = ''
            continue
        info.update({'scope': 'in', 'times': times, 'lead': nlead, 'spec': spec})
        tables.append(info)
        last_cat, added = ('', 0)
        nt = len(times)
        spans = [(rowb[trow][i]['c0'], rowb[trow][i]['c1']) for i in tcols]
        sub_hdr = {}
        for ri, (raw, bs) in enumerate(zip(grid[trow + 1:], rowb[trow + 1:]), trow + 1):
            if len(bs) < nt + 1:
                m = '行块数不足（%d<%d），已跳过：%s | %s' % (len(bs), nt + 1, bs[0]['t'].strip()[:12] if bs else '', cap[:24])
                if m not in warn:
                    warn.append(m)
                continue
            lead, vals = (bs[:-nt], bs[-nt:])
            if len(lead) > 3:
                ncat = strip_brackets(bs[0]['t']).strip() or last_cat
                is_hdr = not any((re.match('^[\\d.]+$', x['t'].strip()) for x in raw))
                if is_hdr:
                    for ki, (ca, cb) in enumerate(spans):
                        sub_hdr[ki] = [raw[x]['t'].strip() for x in range(ca, cb + 1)]
                    continue
                for ki, (ca, cb) in enumerate(spans):
                    if cb <= ca:
                        continue
                    cells = [raw[x]['t'].strip() for x in range(ca, cb + 1)]
                    for lf, vv, j in nested_records(sub_hdr.get(ki, []), cells):
                        out.append({'cond': c, 'batch': bm.group(1), 'spec': spec, 'time': times[ki], 'cat': ncat, 'leaf': lf, 'limit': '', 'value': vv, 'status': 'value', 'pct_unit': False, 'caption': cap, 'pos': cell_pos(grid, ti, ri, ca + j, trow)})
                        added += 1
                continue
            cat = strip_brackets(lead[0]['t']).strip()
            if cat and re.match('^\\d+(\\.\\d+)?$', nz(cat)):
                continue
            if cat:
                last_cat = cat
            else:
                cat = last_cat
            sub = strip_brackets(lead[1]['t']).strip() if len(lead) >= 3 else ''
            limit = lead[-1]['t'].strip() if len(lead) >= 2 else ''
            if re.match('^(结论|备注|注)', nz(cat)):
                continue
            leaf = leaf_name(cat, limit, sub)
            if not leaf:
                continue
            for k, tv in enumerate(times):
                v = vals[k]['t'].strip()
                st = value_status(v)
                if st == 'blank':
                    continue
                out.append({'cond': c, 'batch': bm.group(1), 'spec': spec, 'time': tv, 'cat': cat, 'leaf': leaf, 'limit': limit, 'value': v, 'status': st, 'pct_unit': pct_unit, 'caption': cap, 'pos': cell_pos(grid, ti, ri, vals[k]['c0'], trow)})
                if st == 'value':
                    added += 1
        if not added:
            warn.append('表无数据：' + cap[:40])
        cap = ''
    return {'file': fname, 'records': out, 'tables': tables, 'warnings': warn}

def is_summary(blocks_):
    txt = ''.join((b['text'] for b in blocks_ if b['type'] == 'p'))
    n = len(re.findall('加速试验|长期试验', nz(txt)))
    hdr = 0
    for b in blocks_:
        if b['type'] == 'table':
            for r in b['grid'][:6]:
                j = nz('|'.join((c['t'] for c in r)))
                if '检验项目' in j and '检验结果' in j:
                    hdr += 1
                    break
    return n >= 3 and hdr == 0
