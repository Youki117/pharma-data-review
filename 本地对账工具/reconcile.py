import re, os, sys, io
from docxgrid import parse, parse_ex
from extract import extract_summary, extract_inspection, extract_inspection_diag, is_summary, nz, is_empty, strip_brackets
from prose import check_prose, check_dupes
from crosscheck import check_arith
from confuse import check_confusables
from numtrace import trace_numbers
ALIAS_RULES = [('^性状$', '性状', '同名，兜底用'), ('^含量(测定)?$', '含量', '「含量」与「含量测定」是同一项，后者是方法名带进来的'), ('^最大未知单杂$|^其他单个未知杂质$|^其它单个未知杂质$|^其他单杂$|^单个未知杂质$', '其他单个杂质', '都指「除已知杂质外，单个未知杂质中的最大者」，ICH Q3B 的 unspecified impurity'), ('^总杂质$|^各杂质总和$|^总杂|^杂质总量|^单个杂质总和$', '总杂', '都指「全部杂质之和」。不含「未知杂质总量」——那是子集，见上面的反面教材'), ('^(?:霉菌|酵母菌)[、及和与]?(?:霉菌|酵母菌)?总数$', '霉菌酵母菌总数', '「霉菌和酵母菌总数」「霉菌、酵母菌总数」「酵母菌及霉菌总数」同一项，仅连接词不同'), ('^大肠埃希菌', '大肠埃希菌', '同一项，仅后缀差异（如「大肠埃希菌（1ml）」）'), ('^需氧菌总数', '需氧菌总数', '同一项，仅后缀差异')]
ALIAS = [(pat, rep) for pat, rep, _why in ALIAS_RULES]

def canon(name):
    s = nz(name)
    s = re.sub('[【】\\[\\]]', '', s)
    s = s.replace('其它', '其他').replace('霉菌和酵母菌', '霉菌酵母菌')
    s = re.sub('[（(](单位[:：]?%|%|粒/支)[）)]$', '', s)
    s = re.sub('[（(]%[）)]', '', s)
    s = s.rstrip('。,，;；')
    for pat, rep in ALIAS:
        if re.match(pat, s):
            return rep
    s = re.sub('^含(?=[一-龥A-Za-z])', '', s)
    s = re.sub('[（(][A-Za-z0-9₂-₉·\\.]+[）)]', '', s)
    s = re.sub('^每\\s*[\\d.]+\\s*(?:ml|mL|g|mg|片|粒|袋|支)中?', '', s)
    return s
LIMIT_FRAGMENT = re.compile('^(?:标示量|按|在|每|A\\+|\\d)')

def _ws(s):
    return re.sub('[\\s\u3000]', '', str(s or ''))

def name_noise(s, limit=''):
    t = nz(s)
    t = re.sub('[（(](?:单位[:：]?)?[%％][）)]$', '', t)
    t = re.sub('[（(][%％][）)]', '', t)
    t = t.rstrip('。,，;；')
    if t.startswith('含') and len(t) >= 3:
        t = t[1:]
    if re.fullmatch('(?:霉菌[、及和与]?酵母菌|酵母菌[、及和与]?霉菌)总数', t):
        t = '霉菌酵母菌总数'
    t = re.sub('^大肠埃希菌(?:/g|\\(g\\))$', '大肠埃希菌(g)', t)
    full = nz(limit)
    if t == '大肠埃希菌' and re.search('每1g|不得检出/g', full):
        t = '大肠埃希菌(g)'
    if full.startswith(t):
        qualifier = _SCOPE_QUAL.match(full[len(t):])
        if qualifier:
            t += qualifier.group(0)
    return t

def keyset(rec):
    out = set()
    for x in (rec.get('leaf', ''), rec.get('cat', '')):
        c = canon(x)
        if c:
            out.add(c)
    return out
_NUM_UNIT = re.compile('^([-+]?(?:\\d+(?:\\.\\d+)?|\\.\\d+))\\s*(.*)$')
_SCI = re.compile('^([-+]?(?:\\d+(?:\\.\\d+)?|\\.\\d+))\\s*(?:[×xX*]\\s*10\\s*\\^\\s*|[eE])([-+]?\\d+)\\s*(.*)$')
_SUPER = str.maketrans('⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺', '0123456789-+')

def num_unit(v):
    pre = str(v or '')
    if any((ch in pre for ch in '⁰¹²³⁴⁵⁶⁷⁸⁹')):
        pre = re.sub('10([⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+)', lambda m: '10^' + m.group(1).translate(_SUPER), pre)
    s = nz(pre).replace('＜', '<').replace('＞', '>').replace(',', '')
    if not s or s[0] in '<>':
        return (None, '')
    m = _SCI.match(s)
    if m:
        return (float(m.group(1)) * 10.0 ** int(m.group(2)), m.group(3).strip())
    m = _NUM_UNIT.match(s)
    if not m:
        return (None, '')
    return (float(m.group(1)), m.group(2).strip())
_UNIT_SYN = [('毫升', 'ml'), ('微克', 'μg'), ('毫克', 'mg'), ('小时', 'h'), ('分钟', 'min'), ('秒', 's'), ('克', 'g'), ('升', 'l')]

def unit_key(u):
    t = nz(u).lower()
    for a, b in _UNIT_SYN:
        t = t.replace(a, b)
    return t

def to_num(v):
    return num_unit(v)[0]
NONDETECT = {'未检出', '未检出出'}

def norm_text(v):
    s = nz(v)
    s = re.sub('[。,，;；:：]', '', s)
    s = re.sub('^本品为|^为', '', s)
    s = s.replace('＜', '<').replace('＞', '>')
    return s
QUAL = {'符合规定', '符合', '均符合规定'}
STYLE = [('小于', '<'), ('少于', '<'), ('大于', '>'), ('多于', '>'), ('其它', '其他'), ('本品为', '')]

def norm2(s):
    t = str(s or '')
    for a, b in STYLE:
        t = t.replace(a, b)
    return t.rstrip('%％')

def norm_limit(s, leaf=''):
    t = nz(s)
    if not t:
        return ''
    t = re.sub('^本品含.{1,30}?计算[,，]?', '', t)
    t = re.sub('^本品', '', t)
    for nm in (nz(leaf), nz(leaf).lstrip('含'), '含' + nz(leaf).lstrip('含')):
        if nm and t.startswith(nm):
            t = t[len(nm):]
            break
    t = re.sub('^\\d+\\s*(?:min|h|分钟|小时)时?', '', t)
    t = re.sub('^每\\s*[\\d.]+\\s*(?:ml|mL|g|mg|片|粒|袋|支)\\s*(?:供试品)?中?', '', t)
    t = t.replace('其它', '其他').replace('霉菌和酵母菌', '霉菌酵母菌')
    t = t.replace('不得低于', '≥').replace('不低于', '≥').replace('不得少于', '≥')
    t = t.replace('不得过', '≤').replace('不得超过', '≤').replace('不大于', '≤')
    t = t.replace('～', '~').replace('－', '-')
    t = re.sub('[。,，;；:：、\\\'"“”（）()【】\\[\\]]', '', t)
    return t.replace('%', '').replace('％', '')
_LIM_NOISE = [re.compile('[（(]\\s*[A-Z][a-z]?\\d+(?:[A-Z][a-z]?\\d*)+\\s*[）)]'), re.compile('药典\\s*\\d+\\s*年版'), re.compile('通则\\s*\\d+'), re.compile('附录\\s*[A-Za-z0-9]+')]
_CMP_WORD = '(?:≤|≥|＜|＞|<|>|=|不得过|不得超过|不超过|不大于|不多于|不得少于|不得低于|不低于|不小于|应为|应不低于|标示量的|至少|至多)'
_THRESHOLD = re.compile(_CMP_WORD + '\\s*(\\d+(?:\\.\\d+)?)')
_THR_RANGE = re.compile('(\\d+(?:\\.\\d+)?)\\s*[%％]?\\s*[~～]\\s*(\\d+(?:\\.\\d+)?)')
_SCOPE_QUAL = re.compile('[（(]\\s*(?:除|不包括|扣除|不含)[^）)]{0,60}[）)]')
_BARE_OK = re.compile('^(?:本品)?(?:均)?(?:应)?符合规定[。.；;，,]?$')

def limit_thresholds(s):
    t = nz(s)
    for rx in _LIM_NOISE:
        t = rx.sub(' ', t)
    out = set(_THRESHOLD.findall(t))
    for m in _THR_RANGE.finditer(t):
        out.add(m.group(1))
        out.add(m.group(2))
    return frozenset((float(x) for x in out))

def _fmt(vals):
    return '/'.join(('%g' % v for v in sorted(vals)))
_LIM_SEG = re.compile('≤|≥|＜|＞|<|>|不得过|不得超过|不超过|不低于|不得低于|不小于|不大于|不多于|应为|不得检出')

def _merged_cell(text, leaf):
    t = nz(text)
    if len(_LIM_SEG.findall(t)) < 2:
        return False
    lf = nz(leaf)
    cands = [lf, re.sub('[（(][^）)]*[）)]\\s*$', '', lf)]
    return any((c and len(c) >= 2 and (c in t) for c in cands))

def limit_nature(a, b, leaf='', other_leaf=''):
    ta, tb = (nz(a), nz(b))
    oa, ob = (bool(_BARE_OK.match(ta)), bool(_BARE_OK.match(tb)))
    if oa != ob:
        which = '汇总表' if oa else '检验报告单'
        return ('限度实质不一致', '%s只写了「应符合规定」，另一侧写的是具体要求，两者无法互相溯源' % which)
    qa = bool(_SCOPE_QUAL.search(nz(leaf) + ta))
    qb = bool(_SCOPE_QUAL.search(nz(other_leaf) + tb))
    if qa != qb:
        which = '汇总表' if qa else '检验报告单'
        return ('限度实质不一致', '只有%s的限度带「除…外」这类范围限定：阈值相同，但两边说的可能不是同一个量' % which)
    if qa and qb and (set(_SCOPE_QUAL.findall(nz(leaf) + ta)) != set(_SCOPE_QUAL.findall(nz(other_leaf) + tb))):
        return ('限度实质不一致', '两侧排除范围不同，请按完整项目名和标准确认适用范围')
    ma, mb = (_merged_cell(ta, leaf), _merged_cell(tb, leaf))
    if ma != mb:
        which = '汇总表' if ma else '检验报告单'
        return ('限度表述不一致', '%s那一格把同组好几个项目的限度写在一起了，无法逐项比对阈值，请抽查确认本项的限度是否一致' % which)
    sa, sb = (limit_thresholds(a), limit_thresholds(b))
    if bool(sa) != bool(sb):
        which = '汇总表' if not sa else '检验报告单'
        return ('限度实质不一致', '一侧是定量限度、另一侧没有具体阈值（%s 无阈值），两者无法互相溯源' % which)
    if sa and sb and (not (sa <= sb or sb <= sa)):
        return ('限度实质不一致', '两侧限度阈值互有独有：汇总表 %s，报告单 %s。注册资料写的标准和报告单执行的标准不同，需确认以哪个为准' % (_fmt(sa - sb) or '—', _fmt(sb - sa) or '—'))
    if sa and sb and (sa != sb):
        big = '检验报告单' if sb > sa else '汇总表'
        return ('限度表述不一致', '阈值一致（%s），只是%s那一格里还写了别的限度' % (_fmt(sa & sb), big))
    return ('限度表述不一致', '阈值相同，只是文字写法不同')
MEAN = re.compile('平均值\\s*[：:]\\s*([＜＞<>]?\\s*[\\d.]+\\s*[%％]?)')
RL = re.compile('(?:[＜<]|小于)\\s*(报告限|检测限|定量限)\\s*[（(]\\s*(?:(?:报告限|检测限|定量限)\\s*[:：]\\s*)?([\\d.]+)\\s*[%％]?\\s*[）)]')

def mean_of(v):
    s = str(v or '')
    m = MEAN.search(s)
    return m.group(1).strip() if m else v
_NEG = re.compile('不符合|不合格|不适合|未通过|不通过|不澄清')
_POS = re.compile('符合规定|均符合|^符合$|^合格$')

def pass_phrase(t):
    s = norm_text(t)
    return bool(_POS.search(s)) and (not _NEG.search(s))

def polarity(t):
    s = norm_text(t)
    if not s:
        return None
    if _NEG.search(s):
        return False
    if _POS.search(s):
        return True
    if s in ('阴性', '澄清') or s in NONDETECT:
        return True
    if s in ('阳性', '检出'):
        return False
    return None

def cmp_value(a, b):
    ra, rb = (RL.search(str(a or '')), RL.search(str(b or '')))
    if ra or rb:
        if ra and rb:
            if ra.group(1) != rb.group(1):
                return ('review', '一侧写%s、另一侧写%s，不是同一个限' % (ra.group(1), rb.group(1)))
            return ('same', '') if ra.group(2) == rb.group(2) else ('diff', '两侧%s不同' % ra.group(1))
        other = norm_text(b if ra else a)
        word, lim = ((ra or rb).group(1), (ra or rb).group(2))
        if re.fullmatch('[\\d.]+[%％]?', other):
            same_num = abs(float(other.rstrip('%％')) - float(lim)) < 1e-09
            if ra:
                if same_num:
                    return ('review', '汇总表写“＜%s（%s%%）”，报告单写实测值 %s。需求方确认的是相反方向的写法，这个方向没有确认过' % (word, lim, other))
                return ('diff', '汇总表写“＜%s（%s%%）”，报告单写实测值 %s' % (word, lim, other))
            if same_num:
                return ('rl', '报告单为“＜%s（%s%%）”，汇总表直接写成数值 %s' % (word, lim, other))
            return ('diff', '报告单为＜%s（%s%%），汇总表写 %s' % (word, lim, other))
        if other in NONDETECT:
            return ('rlnd', '%s为“＜%s（%s%%）”，%s写“未检出”' % ('汇总表' if ra else '报告单', word, lim, '报告单' if ra else '汇总表'))
        if other in QUAL:
            return ('qual', '一侧只写“符合规定”')
        return ('review', '%s表述' % word)
    ta0, tb0 = (norm_text(a), norm_text(b))
    pa, pb = (polarity(ta0), polarity(tb0))
    if pa is not None and pb is not None and (pa != pb):
        return ('diff', '两侧结论相反：汇总表“%s” / 报告单“%s”' % (ta0[:24], tb0[:24]))
    if ta0 != tb0 and pass_phrase(ta0) and pass_phrase(tb0):
        return ('style', '两侧都是“符合规定”，但写法有出入：汇总表“%s” / 报告单“%s”' % (ta0[:20], tb0[:20]))
    if (ta0 in QUAL) != (tb0 in QUAL):
        other = tb0 if ta0 in QUAL else ta0
        if other:
            return ('qual', '一侧只写“符合规定”，另一侧是具体%s（%s 侧更具体，无法互相溯源）' % ('数值' if re.search('\\d', other) else '描述', '汇总表' if tb0 in QUAL else '报告单'))
    na, ua = num_unit(a)
    nb, ub = num_unit(b)
    if na is not None and nb is not None:
        if ua and ub and (unit_key(ua) != unit_key(ub)):
            return ('unit', '两侧单位不同：汇总表「%s」 / 报告单「%s」。两个数值不在同一个量纲上，没有可比性' % (ua, ub))
        return ('same', '') if abs(na - nb) < 1e-09 else ('diff', '数值')
    ta, tb = (norm_text(a), norm_text(b))
    if ta == tb:
        return ('same', '')
    if norm2(ta).replace('黏', '粘') == norm2(tb).replace('黏', '粘'):
        return ('style', '同一含义、写法不同')
    if ta in NONDETECT and tb in NONDETECT:
        return ('same', '')
    if na is not None and tb in NONDETECT or (nb is not None and ta in NONDETECT):
        num = na if na is not None else nb
        side_num = '汇总表' if na is not None else '报告单'
        if abs(num) < 1e-12:
            return ('style', '一侧写 0、另一侧写「未检出」，同一结论的两种写法')
        return ('diff', '%s是具体数值 %s，另一侧写「未检出」：测出了量和没测出是两个不同的结论' % (side_num, nz(a if na is not None else b)))
    if (na is None) != (nb is None) and (na is not None or nb is not None):
        other = tb if na is not None else ta
        if re.match('^[<>]', other):
            cmpside = '汇总表' if na is None else '检验报告单'
            return ('diff', '只有%s带「＜/＞」，另一侧是确切数值，两者不是同一个结论' % cmpside)
        if re.search('\\d', ta) and re.search('\\d', tb):
            return ('review', '一侧是数值、另一侧含数字但读不成数值（%s），请对照原文' % other[:24])
        return ('review', '文本与数值')
    return ('review', '文本')

def canon_spec(s):
    t = nz(s)
    m = re.search('(\\d+(?:\\.\\d+)?)\\s*(mg|g|ml|μg)', t)
    return m.group(1) + m.group(2) if m else ''
MATCH_NOTE = {0: '', 1: '项目名完全对应', 2: '子项名对应', 3: '按关键词匹配，对应关系未经确认'}
COND_CN = {'acc': '加速', 'lt': '长期', 'lt1': '长期1', 'lt2': '长期2', 'lt?': '长期?', 'base': '0天', 'eol': '效期末'}

def _loc(path, pos=None, q='', cap=''):
    q = str(q or '').split('\n')[0].strip()[:80]
    d = {'file': path, 'pos': list(pos) if pos else None, 'q': q}
    if cap:
        d['cap'] = str(cap).split('\n')[0].strip()[:60]
    return d

def run(name, summary_path, coa_paths, verbose=False, on_progress=None, doc_count=0, doc_unconverted=None, coa_notes=None):
    total = len(coa_paths) + 1
    if on_progress:
        on_progress(0, total, os.path.basename(summary_path))
    sbl, sinfo = parse_ex(summary_path)
    summ = extract_summary(summary_path, sbl)
    revised = []
    if sinfo['revisions']:
        revised.append((summ['file'], sinfo['revisions'], sinfo['revised_cells'], True))
    prose_hits = check_prose(sbl)
    reports = []
    file_diags = []
    for i, p in enumerate(coa_paths, 1):
        if on_progress:
            on_progress(i, total, os.path.basename(p))
        try:
            bl, info = parse_ex(p)
            rs, dg = extract_inspection_diag(p, bl)
            if info['revisions']:
                revised.append((os.path.basename(p), info['revisions'], info['revised_cells'], False))
        except Exception as e:
            file_diags.append({'file': os.path.basename(p), 'tables': 0, 'header_hit': 0, 'loose_hit': 0, 'blocks': 0, 'error': str(e)[:120]})
            continue
        for r in rs:
            r['path'] = p
        reports += rs
        file_diags.append(dg)
    lts = {r['cond'] for r in summ['records'] if r['cond'].startswith('lt')}
    lts_all = lts | {r['cond'] for r in reports if r['cond'].startswith('lt')}
    known = lts_all - {'lt?'}
    if len(known) <= 1:
        for r in summ['records']:
            if r['cond'].startswith('lt'):
                r['cond'] = 'lt'
        for r in reports:
            if r['cond'].startswith('lt'):
                r['cond'] = 'lt'
    else:
        target_lt = None
        if len(lts - {'lt?'}) == 1:
            target_lt = sorted(lts - {'lt?'})[0]
        if target_lt:
            for r in summ['records']:
                if r['cond'] == 'lt?':
                    r['cond'] = target_lt
            for r in reports:
                if r['cond'] == 'lt?':
                    r['cond'] = target_lt
    sspecs = {canon_spec(r['spec']) for r in summ['records']}
    use_spec = sspecs != {''}

    def sk(spec, batch, cond, t):
        return (canon_spec(spec) if use_spec else '', nz(batch), cond, float(t))
    src = {}
    for r in reports:
        for b in r['batches']:
            k = sk(r['spec'], b, r['cond'], r['time'] if r['time'] is not None else -1)
            src.setdefault(k, []).append(r)

    def find_src(spec, batch, cond, t):
        if float(t) == 0.0:
            return src.get(sk(spec, batch, 'base', 0), []) + src.get(sk(spec, batch, cond, 0), [])
        return src.get(sk(spec, batch, cond, t), [])
    issues = []
    stat = dict(compared=0, same=0, diff=0, review=0, nosrc=0, noitem=0, omitted=0)
    missing_groups, covered = ({}, set())
    for sr in summ['records']:
        docs = find_src(sr['spec'], sr['batch'], sr['cond'], sr['time'])
        if not docs:
            g = sk(sr['spec'], sr['batch'], sr['cond'], sr['time'])
            if g not in missing_groups:
                missing_groups[g] = 1
                stat['nosrc'] += 1
                issues.append(dict(stable=sr.get('caption', ''), level='缺少源文件', cond=sr['cond'], batch=sr['batch'], spec=sr['spec'], time=sr['time'], item='整个时间点', sv='-', iv='-', file='-', sloc=_loc(summary_path, sr.get('pos'), sr['value'], sr.get('caption')), note='汇总表有该批号/条件/时间点，但未找到对应检验报告单'))
            continue
        ks = keyset(sr)
        sleaf, scat = (canon(sr.get('leaf', '')), canon(sr.get('cat', '')))
        hit = hitdoc = None
        hitrule = 0
        for rule in (1, 2, 3):
            if rule <= 2 and (not sleaf):
                continue
            for d in docs:
                for ir in d['records']:
                    il, ic = (canon(ir.get('leaf', '')), canon(ir.get('cat', '')))
                    ok = il == sleaf and ic == scat if rule == 1 else il == sleaf if rule == 2 else bool(ks & keyset(ir))
                    if ok:
                        hit, hitdoc, hitrule = (ir, d, rule)
                        break
                if hit:
                    break
            if hit:
                break
        covered.add((sk(sr['spec'], sr['batch'], sr['cond'], sr['time']), frozenset(ks)))
        if not hit:
            if sr.get('status', 'value') != 'value':
                stat['nottested'] = stat.get('nottested', 0) + 1
                continue
            stat['noitem'] += 1
            issues.append(dict(stable=sr.get('caption', ''), level='源报告无此项', cond=sr['cond'], batch=sr['batch'], spec=sr['spec'], time=sr['time'], item=sr['cat'] + '/' + sr['leaf'], sv=sr['value'], iv='源报告中未找到同名项目', file='；'.join((d['file'] for d in docs))[:60], note='', sloc=_loc(summary_path, sr.get('pos'), sr['value'], sr.get('caption')), iloc=_loc(docs[0]['path']) if len(docs) == 1 else None))
            continue
        sst = sr.get('status', 'value')
        ist = hit.get('status', 'value')
        if sst != 'value' or ist != 'value':
            if sst != 'value' and ist != 'value':
                stat['nottested'] = stat.get('nottested', 0) + 1
            else:
                stat['teststate'] = stat.get('teststate', 0) + 1
                a, b = ('不考察', '有结果') if sst != 'value' else ('有结果', '不考察')
                issues.append(dict(stable=sr.get('caption', ''), level='考察状态不一致', cond=sr['cond'], batch=sr['batch'], spec=sr['spec'], time=sr['time'], item=sr['cat'] + '/' + sr['leaf'], sv=sr['value'], iv=hit['value'], file=hitdoc['file'], sloc=_loc(summary_path, sr.get('pos'), sr['value'], sr.get('caption')), iloc=_loc(hitdoc['path'], hit.get('pos'), hit['value']), note='汇总表%s，检验报告单%s' % (a, b)))
            continue
        stat['compared'] += 1
        svv, ivv = (sr['value'], mean_of(hit['value']))
        st, why = cmp_value(svv, ivv)
        LV = {'diff': ('明确不一致', 'diff'), 'style': ('写法不一致', 'style'), 'qual': ('定性/定量不对应', 'qual'), 'rl': ('报告限写成数值', 'rl'), 'rlnd': ('报告限写成未检出', 'rlnd'), 'review': ('文本待复核', 'review'), 'unit': ('单位口径不同', 'unitdiff')}
        if st == 'rl' and num_unit(svv)[0] is not None:
            sr['rl'] = True
        if st == 'same':
            stat['same'] += 1
        else:
            lv, sk_ = LV[st]
            note = why
            if hitrule == 3:
                if st == 'diff':
                    lv, sk_ = ('项目对应存疑', 'uncertain')
                    note = '汇总表「%s」与报告单「%s」是按关键词匹配上的，并非同名项目；两边取值不同（%s / %s）。请先确认这两项是不是同一个考察项目，再判断数值是否真的不一致' % (sr.get('leaf', ''), hit.get('leaf', ''), svv, ivv)
                else:
                    note = (note + '｜' if note else '') + '项目对应关系按关键词匹配得出，需确认'
            stat[sk_] = stat.get(sk_, 0) + 1
            issues.append(dict(stable=sr.get('caption', ''), level=lv, cond=sr['cond'], batch=sr['batch'], spec=sr['spec'], time=sr['time'], item=sr['cat'] + '/' + sr['leaf'], sv=svv, iv=ivv, file=hitdoc['file'], note=note, match=MATCH_NOTE[hitrule], sloc=_loc(summary_path, sr.get('pos'), sr['value'], sr.get('caption')), iloc=_loc(hitdoc['path'], hit.get('pos'), hit['value'])))
        na, nb = (sr.get('leaf', '').strip(), hit.get('leaf', '').strip())
        degenerate = nz(na) == nz(sr.get('cat', '')) or nz(nb) == nz(hit.get('cat', '')) or LIMIT_FRAGMENT.match(na) or LIMIT_FRAGMENT.match(nb)
        merged_names = nz(sr.get('cat', '')) == '微生物限度' and nz(hit.get('cat', '')) == '微生物限度' and _merged_cell(hit.get('limit', ''), na) and _merged_cell(hit.get('limit', ''), nb)
        if na and nb and (na != nb) and (not degenerate) and (not merged_names) and (name_noise(na, sr.get('limit', '')) != name_noise(nb, hit.get('limit', ''))):
            stat['name'] = stat.get('name', 0) + 1
            issues.append(dict(stable=sr.get('caption', ''), level='项目名称不一致', cond=sr['cond'], batch=sr['batch'], spec=sr['spec'], time=sr['time'], item=sr['cat'] + '/' + na, sv=na, iv=nb, file=hitdoc['file'], sloc=_loc(summary_path, sr.get('pos'), na, sr.get('caption')), iloc=_loc(hitdoc['path'], hit.get('pos'), nb), note='两份文件对同一项目的叫法不同，已按别名配对，但名称本身有差异'))
        la = norm_limit(sr.get('limit', ''), sr.get('leaf', ''))
        lb = norm_limit(hit.get('limit', ''), hit.get('leaf', ''))
        if la and lb and (la == lb):
            ra, rb = (_ws(sr.get('limit', '')), _ws(hit.get('limit', '')))
            if ra and rb and (ra != rb) and (nz(ra) == nz(rb)):
                stat['width'] = stat.get('width', 0) + 1
                issues.append(dict(stable=sr.get('caption', ''), level='全半角/标点不一致', cond=sr['cond'], batch=sr['batch'], spec=sr['spec'], time=sr['time'], item=sr['cat'] + '/' + sr['leaf'], sv=sr.get('limit', ''), iv=hit.get('limit', ''), file=hitdoc['file'], sloc=_loc(summary_path, sr.get('pos'), sr.get('limit', ''), sr.get('caption')), iloc=_loc(hitdoc['path'], hit.get('pos'), hit.get('limit', '')), note='限度文字仅全角/半角或标点不同'))
        if la and lb and (la != lb):
            lv, why = limit_nature(sr.get('limit', ''), hit.get('limit', ''), sr.get('leaf', ''), hit.get('leaf', ''))
            stat['limit' if lv == '限度表述不一致' else 'limitreal'] = stat.get('limit' if lv == '限度表述不一致' else 'limitreal', 0) + 1
            issues.append(dict(stable=sr.get('caption', ''), level=lv, cond=sr['cond'], batch=sr['batch'], spec=sr['spec'], time=sr['time'], item=sr['cat'] + '/' + sr['leaf'], sv=sr.get('limit', ''), iv=hit.get('limit', ''), file=hitdoc['file'], note=why, sloc=_loc(summary_path, sr.get('pos'), sr.get('limit', ''), sr.get('caption')), iloc=_loc(hitdoc['path'], hit.get('pos'), hit.get('limit', ''))))
    sidx = set()
    scope = set()
    for r in summ['records']:
        k = sk(r['spec'], r['batch'], r['cond'], r['time'])
        scope.add(k)
        for c in keyset(r):
            sidx.add((k, c))
    omit = {}
    orphan = {}
    for d in reports:
        targets = []
        if d['cond'] == 'base':
            for k in scope:
                if k[3] == 0.0 and k[1] in {nz(b) for b in d['batches']}:
                    targets.append(k)
        else:
            for b in d['batches']:
                k = sk(d['spec'], b, d['cond'], d['time'] if d['time'] is not None else -1)
                if k in scope:
                    targets.append(k)
        if not targets:
            g = (canon_spec(d['spec']) if use_spec else '', d['cond'], d['time'] if d['time'] is not None else -1)
            e = orphan.setdefault(g, dict(blocks=0, values=0, batches=[], files=[], path=d['path']))
            e['blocks'] += 1
            e['values'] += len([x for x in d['records'] if x.get('status', 'value') == 'value'])
            for b in d['batches']:
                if nz(b) and nz(b) not in e['batches']:
                    e['batches'].append(nz(b))
            if d['file'] not in e['files']:
                e['files'].append(d['file'])
            continue
        for ir in d['records']:
            if ir.get('status', 'value') != 'value':
                continue
            ks = keyset(ir)
            if any(((t, c) in sidx for t in targets for c in ks)):
                continue
            stat['omitted'] += 1
            ak = canon(ir['leaf']) or canon(ir['cat'])
            e = omit.setdefault(ak, dict(item=ir['cat'] + '/' + ir['leaf'], n=0, ex=[], iloc=_loc(d['path'], ir.get('pos'), ir['value'])))
            e['n'] += 1
            if len(e['ex']) < 3:
                e['ex'].append(d['file'][:34] + '=' + ir['value'][:18])
    for (gspec, gcond, gtime), e in sorted(orphan.items()):
        stat['orphan'] = stat.get('orphan', 0) + 1
        stat['orphan_values'] = stat.get('orphan_values', 0) + e['values']
        why = '汇总表里没有「%s%s %s月」这一组：报告单有 %d 个批号、%d 份文件、%d 个实测值，但汇总表既没有这个规格也没有这个时间点的表格，这批数据没有参与任何对账' % (gspec or '', COND_CN.get(gcond, gcond), '%g' % gtime if gtime >= 0 else '?', len(e['batches']), len(e['files']), e['values'])
        issues.append(dict(level='汇总表缺整组', cond=gcond, batch='、'.join(e['batches'][:6]), spec=gspec, time='%g' % gtime if gtime >= 0 else '?', item='整组数据', sv='汇总表无此组', iv='%d 个实测值' % e['values'], file='；'.join(e['files'][:3])[:80], note=why, sloc=None, iloc=_loc(e['path'])))
    for k, e in omit.items():
        issues.append(dict(level='汇总表未收录', cond='-', batch='-', spec='-', time='-', item=e['item'], sv='汇总表无此项', iv='%d 处，例：%s' % (e['n'], '；'.join(e['ex'])), file='（按项目聚合）', note='', sloc=None, iloc=e['iloc']))
    for h in check_confusables(sbl, summ['file']):
        stat['confuse'] = stat.get('confuse', 0) + 1
        h['sloc'] = _loc(summary_path, h.pop('pos', None), h.pop('q', ''))
        issues.append(h)
    for h in check_dupes(sbl):
        stat['dupe'] = stat.get('dupe', 0) + 1
        issues.append(dict(level=h['level'], cond='-', batch='-', spec='-', time='-', item='汇总表正文（两段雷同）', sv=h['text'][:200], iv=h['note'][:60], file=summ['file'], note=h['note'], sloc=_loc(summary_path, None, h['text'].split('\n')[0][2:])))
    for h in prose_hits:
        stat['prose'] = stat.get('prose', 0) + 1
        issues.append(dict(level=h['level'], cond='-', batch='-', spec='-', time='-', item='汇总表正文（%s章节）' % h['section'], sv=h['text'][:120], iv=h['note'], file=summ['file'], note=h['note'], sloc=_loc(summary_path, None, h['text'])))
    for h in check_arith(summ['records'], summ['file']):
        stat['arith'] = stat.get('arith', 0) + 1
        h['sloc'] = _loc(summary_path, h.pop('pos', None), h.pop('q', ''), h.get('stable'))
        issues.append(h)
    for h in trace_numbers(sbl, summ['file']):
        stat['numtrace'] = stat.get('numtrace', 0) + 1
        h['sloc'] = _loc(summary_path, None, h['sv'])
        issues.append(h)
    for d in reports:
        for c in d['conflicts']:
            issues.append(dict(level='元数据冲突', cond=d['cond'], batch=','.join(d['batches']), spec=d['spec'], time=d['time'], item='文件标识', sv='-', iv=c, file=d['file'], note='', sloc=None, iloc=_loc(d['path'])))
    return dict(name=name, summary=summ, reports=reports, issues=issues, stat=stat, use_spec=use_spec, coverage=_coverage(summ, coa_paths, file_diags, reports, stat, doc_count, doc_unconverted, coa_notes, revised))

def _coverage(summ, coa_paths, file_diags, reports, stat, doc_count=0, doc_unconverted=None, coa_notes=None, revised=None):
    empty = [d for d in file_diags if d['blocks'] == 0]
    broken = [d for d in empty if d.get('error')]
    unread = [d for d in empty if not d.get('error') and d['tables'] > 0]
    loose = [d for d in file_diags if d.get('loose_hit')]
    blocking, notes = ([], [])
    if not summ['records']:
        blocking.append('汇总表一条数据都没解析出来（%s）。它可能不是汇总表，或者题注/表头的写法工具认不出来——这次核对的结果不可信。' % summ['file'])
    doc_hint = '。目录里有 %d 个 .doc —— 工具只认 .docx，会先用本机的 Word / WPS / ONLYOFFICE / LibreOffice 自动转换，转不了时原因见注意事项' % doc_count if doc_count else ''
    if coa_paths and (not reports):
        blocking.append('%d 份检验报告单一个报告块都没解析出来，常见原因是表头不叫「检验项目 / 检验结果」%s' % (len(coa_paths), doc_hint or '。'))
    if not coa_paths:
        blocking.append('这个品种下面没有找到任何检验报告单 docx%s' % (doc_hint or '。'))
    if doc_unconverted:
        blocking.append('目录里有 %d 个 .doc 没有转成 .docx（例：%s%s）。工具只认 .docx，这些检验报告单一份都没读进来。自动转换需要本机装有 Word / WPS / ONLYOFFICE / LibreOffice 之一，没转成的原因见注意事项；装好后重新核对即可' % (len(doc_unconverted), '；'.join((x[:40] for x in doc_unconverted[:3])), '…' if len(doc_unconverted) > 3 else ''))
    for n in coa_notes or []:
        notes.append(n)
    if revised:
        s_files = [x for x in revised if x[3]]
        c_files = [x for x in revised if not x[3]]
        bits = []
        if s_files:
            bits.append('汇总表 %s 有 %d 处修订、涉及 %d 个表格单元格' % (s_files[0][0][:30], s_files[0][1], s_files[0][2]))
        if c_files:
            bits.append('%d 份报告单带修订（%s%s）' % (len(c_files), '；'.join(('%s %d 处' % (x[0][:30], x[1]) for x in c_files[:3])), '…' if len(c_files) > 3 else ''))
        notes.append('%d 份文件带未接受的修订（Word「修订」模式下删改的痕迹还留在文件里）：%s。工具按「接受全部修订」后的文字核对；请确认这些修订是不是定稿' % (len(revised), '；'.join(bits)))
    if unread and reports:
        notes.append('%d 份 docx 里有表格但没认出「项目 / 结果」表头，没有参与对账：%s' % (len(unread), '；'.join((d['file'][:34] for d in unread[:5])) + ('…' if len(unread) > 5 else '')))
    if broken:
        blocking.append('%d 份 docx 解析失败：%s' % (len(broken), '；'.join(('%s（%s）' % (d['file'][:30], d['error']) for d in broken[:3]))))
    if loose:
        notes.append('%d 份报告单是靠放宽表头同义词才认出来的（不是「检验项目 / 检验结果」），建议抽查一份确认列对得上：%s' % (len(loose), '；'.join((d['file'][:34] for d in loose[:3]))))
    if stat.get('orphan'):
        notes.append('%d 组报告单数据（%d 个实测值）在汇总表里找不到对应的表格，已列为「汇总表缺整组」' % (stat['orphan'], stat.get('orphan_values', 0)))
    suspect = [w for w in summ['warnings'] if w.startswith('疑似结果表未纳入对账')]
    if suspect:
        blocking.append('汇总表里有 %d 张表长得像结果表却没能纳入对账，题注的写法可能和工具预期的不一样：%s' % (len(suspect), suspect[0].split('：', 1)[-1][:90]))
    misread = [w for w in summ['warnings'] if w.startswith('疑似列错位')]
    if misread:
        blocking.append('汇总表里有 %d 张表的列没对上（一列实测值被当成了限度），已跳过不对账：%s' % (len(misread), misread[0].split('：', 1)[-1][:110]))
    for w in summ['warnings']:
        notes.append('汇总表解析：' + w)
    return {'summary_file': summ['file'], 'summary_records': len(summ['records']), 'summary_tables': len(summ['tables']), 'summary_tables_in': len([t for t in summ['tables'] if t.get('scope') == 'in']), 'coa_files': len(coa_paths), 'coa_files_empty': len(empty), 'coa_files_unread': [d['file'] for d in unread], 'coa_files_broken': [d['file'] for d in broken], 'loose_header': [d['file'] for d in loose], 'blocks': len(reports), 'doc_unconverted': list(doc_unconverted or []), 'revised': [dict(file=f, revisions=n, cells=c, summary=is_s) for f, n, c, is_s in revised or []], 'blocking': blocking, 'notes': notes}
