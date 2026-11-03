import re
TIERS = [('crit', '必看'), ('warn', '需确认'), ('count', '数量差异'), ('note', '可抽查')]
LEVELS = [('明确不一致', 'crit', '两侧数值或结论实质不同'), ('表内数据矛盾', 'crit', '汇总表同一张表内部算术不成立，如单项杂质大于总杂'), ('考察状态不一致', 'crit', '一侧标"本时间点不考察"，另一侧却有实测结果'), ('元数据冲突', 'crit', '同一份报告单里试验条件或批号自相矛盾'), ('项目对应存疑', 'warn', '低置信配对（按关键词匹配上的），需先确认两项是不是同一个考察项目'), ('报告限写成未检出', 'warn', '报告单写"＜报告限(X%)"，汇总表写"未检出"。需求方只确认过写成数值 X 的写法，这种没确认'), ('定性/定量不对应', 'warn', '一侧只写"符合规定"，另一侧是具体数值，无法互相溯源'), ('项目名称不一致', 'warn', '两份文件对同一项目叫法不同'), ('限度实质不一致', 'warn', '两份文件的限度阈值或适用范围不同，不只是措辞差异'), ('单位口径不同', 'warn', '两侧数值带的单位不同，不在同一个量纲上，没有可比性'), ('文本待复核', 'warn', '两侧都是自由文本且不等价，需人工判断'), ('正文数据对不上表格', 'warn', '正文写「X→Y」，但结果表里没有哪一行是 X 在前、Y 在后'), ('正文数字无出处', 'warn', '正文在复述表格数据，但其中某个数字在全部表格里都找不到'), ('正文与表格矛盾', 'warn', '正文的说法与它自己的表格对不上。这条是按句子结构推出来的，请对照原文确认'), ('正文段内矛盾', 'warn', '同一段话里前后自相矛盾。这条是按句子结构推出来的，请对照原文确认'), ('形近字符', 'warn', '数值里混进了长得像数字的字母，如 0.lg 的 l 其实该是 1'), ('正文段落雷同', 'warn', '两段话除了开头之外一字不差，多半是复制上一段后忘了改正文'), ('正文格式硬伤', 'warn', '正文里的录入错误，如连续两个百分号、数字里两个小数点'), ('缺少源文件', 'count', '汇总表有这一组数据，但这批文件里没有对应的检验报告单'), ('汇总表缺整组', 'count', '报告单有整整一组数据，汇总表里没有对应表格'), ('汇总表未收录', 'count', '报告单检了这个项目，汇总表没有收录'), ('源报告无此项', 'count', '汇总表填了这个项目的值，报告单里却没有这个考察项目——数据来源在别处'), ('报告限写成数值', 'note', '报告单写"＜报告限/检测限(X%)"，汇总表直接写 X。需求方 2026-09-16 反馈里把报告限的这两种写法当作一致；检测限/定量限按同一口径处理，待需求方确认'), ('单杂＞总杂（报告限写法）', 'note', '单杂那一格写的是报告限数值（报告单为"＜报告限(X%)"），不是实测值；它比总杂大只是两个报告限的高低，不是数据错'), ('写法不一致', 'note', '同一结论不同记法，如"＜10cfu/g"与"小于10 cfu/g"'), ('限度表述不一致', 'note', '汇总表"限度要求"与报告单"标准规定"文字不同'), ('全半角/标点不一致', 'note', '限度文字仅全角半角或标点不同')]
LEVEL_ORDER = [x[0] for x in LEVELS]
LEVEL_TIER = {x[0]: x[1] for x in LEVELS}
LEVEL_DESC = {x[0]: x[2] for x in LEVELS}
TIER_RANK = {t: n for n, (t, _cn) in enumerate(TIERS)}
TIER_CN = dict(TIERS)

def _g(i, k):
    return str(i.get(k, '') or '')

def fmt_time(t):
    s = str(t if t is not None else '')
    if re.match('^-?\\d+(?:\\.\\d+)?$', s):
        f = float(s)
        return '%d' % f if f == int(f) else '%g' % f
    return s
GROUP = {'明确不一致': lambda i: (_g(i, 'item'), _g(i, 'sv'), _g(i, 'iv')), '表内数据矛盾': lambda i: (_g(i, 'item'), _g(i, 'sv'), _g(i, 'iv'), _g(i, 'batch'), _g(i, 'time'), _g(i, 'spec')), '单杂＞总杂（报告限写法）': lambda i: (_g(i, 'item'),), '项目对应存疑': lambda i: (_g(i, 'item'), _g(i, 'sv'), _g(i, 'iv')), '考察状态不一致': lambda i: (_g(i, 'item'), _g(i, 'batch'), _g(i, 'time')), '元数据冲突': lambda i: (_g(i, 'file'), _g(i, 'iv')), '正文与表格矛盾': lambda i: (_g(i, 'note'), _g(i, 'sv')[:40]), '正文段内矛盾': lambda i: (_g(i, 'note'), _g(i, 'sv')[:40]), '形近字符': lambda i: (_g(i, 'sv'), _g(i, 'iv')), '正文段落雷同': lambda i: (_g(i, 'sv')[:80],), '正文格式硬伤': lambda i: (_g(i, 'note'), _g(i, 'sv')[:40]), '正文数据对不上表格': lambda i: (_g(i, 'sv')[:60], _g(i, 'iv')), '正文数字无出处': lambda i: (_g(i, 'sv')[:60],), '缺少源文件': lambda i: (_g(i, 'spec'), _g(i, 'cond'), _g(i, 'time')), '汇总表缺整组': lambda i: (_g(i, 'spec'), _g(i, 'cond'), _g(i, 'time')), '源报告无此项': lambda i: (_g(i, 'item').split('/')[0],), '汇总表未收录': lambda i: (_g(i, 'item'),), '报告限写成数值': lambda i: (_g(i, 'item'), _g(i, 'sv'), _g(i, 'iv')), '报告限写成未检出': lambda i: (_g(i, 'item'), _g(i, 'sv'), _g(i, 'iv')), '定性/定量不对应': lambda i: (_g(i, 'item'), _g(i, 'sv'), _g(i, 'iv')), '项目名称不一致': lambda i: (_g(i, 'sv'), _g(i, 'iv')), '单位口径不同': lambda i: (_g(i, 'item'), _g(i, 'sv'), _g(i, 'iv')), '文本待复核': lambda i: (_g(i, 'sv'), _g(i, 'iv')), '写法不一致': lambda i: (_g(i, 'sv'), _g(i, 'iv')), '限度表述不一致': lambda i: (_g(i, 'sv'), _g(i, 'iv')), '限度实质不一致': lambda i: (_g(i, 'sv'), _g(i, 'iv')), '全半角/标点不一致': lambda i: (_g(i, 'sv'), _g(i, 'iv'))}
DEFAULT_GROUP = lambda i: (_g(i, 'item'), _g(i, 'sv'), _g(i, 'iv'))

def _scope(rows):
    conds = sorted({_g(r, 'cond') for r in rows} - {'', '-'})
    specs = sorted({_g(r, 'spec') for r in rows} - {'', '-'})
    bats = sorted({_g(r, 'batch') for r in rows} - {'', '-'})
    times = sorted({_g(r, 'time') for r in rows} - {'', '-'}, key=lambda x: float(x) if re.match('^[\\d.]+$', x) else 1000000000.0)
    parts = []
    if specs:
        parts.append('/'.join(specs[:3]) + ('…' if len(specs) > 3 else ''))
    if conds:
        parts.append('/'.join(conds[:3]) + ('…' if len(conds) > 3 else ''))
    if bats:
        parts.append('%d 个批号' % len(bats) if len(bats) > 3 else '、'.join(bats))
    if times:
        parts.append('%s月' % '/'.join(times[:5]) + ('…' if len(times) > 5 else ''))
    return '\u3000'.join(parts)

def summarize(issues):
    groups = {}
    for i in issues:
        lv = i['level']
        key = (i.get('product', ''), lv) + GROUP.get(lv, DEFAULT_GROUP)(i)
        g = groups.setdefault(key, {'product': i.get('product', ''), 'level': lv, 'tier': LEVEL_TIER.get(lv, 'note'), 'rows': [], 'gid': ''})
        g['rows'].append(i)
    out = []
    for n, (key, g) in enumerate(groups.items()):
        rows = g['rows']
        first = rows[0]
        out.append({'gid': 'g%d' % n, 'product': g['product'], 'tier': g['tier'], 'level': g['level'], 'n': len(rows), 'item': _g(first, 'item'), 'sv': _g(first, 'sv'), 'iv': _g(first, 'iv'), 'scope': _scope(rows), 'note': _g(first, 'note'), 'file': _g(first, 'file')})
        for r in rows:
            r['gid'] = 'g%d' % n
    rank = {lv: k for k, lv in enumerate(LEVEL_ORDER)}
    out.sort(key=lambda x: (TIER_RANK.get(x['tier'], 9), rank.get(x['level'], 99), -x['n'], x['product']))
    return out

def count_rollup(summary):
    by = {}
    for g in summary:
        if g['tier'] != 'count':
            continue
        by.setdefault(g['level'], []).append(g)
    lines = []
    for lv, gs in by.items():
        prods = sorted({g['product'] for g in gs})
        who = prods[0][:16] + ('等 %d 个品种' % len(prods) if len(prods) > 1 else '')
        if lv == '缺少源文件':
            lines.append('汇总表有 %d 组数据（%s）在这批文件里找不到对应的检验报告单' % (len(gs), who))
        elif lv == '汇总表缺整组':
            vals = 0
            for g in gs:
                m = re.search('(\\d+)\\s*个实测值', g['iv'])
                if m:
                    vals += int(m.group(1))
            lines.append('检验报告单有 %d 组数据（%d 个实测值，%s）汇总表里没有对应表格' % (len(gs), vals, who))
        elif lv == '汇总表未收录':
            lines.append('检验报告单检了 %d 个项目（%s），汇总表没有收录' % (len(gs), who))
        elif lv == '源报告无此项':
            rows = sum((g['n'] for g in gs))
            lines.append('汇总表有 %d 个考察项目（%s，共 %d 格）在检验报告单里没有同名项目，这些值的来源不在这批报告单里' % (len(gs), who, rows))
        else:
            lines.append('%s %d 件' % (lv, len(gs)))
    lines.append('以上都是两边资料量本身的差异，按「只核双方都有的部分」的口径不参与对账')
    return lines

def tier_counts(summary):
    c = {}
    for s in summary:
        e = c.setdefault(s['tier'], {'groups': 0, 'rows': 0})
        e['groups'] += 1
        e['rows'] += s['n']
    return c
