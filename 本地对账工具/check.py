import sys, os, io, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from discover import discover
from reconcile import run, COND_CN
from opener import describe
import convert
from summarize import summarize, tier_counts, count_rollup, LEVEL_ORDER, TIERS, TIER_CN, LEVEL_DESC, fmt_time
ORDER = LEVEL_ORDER
HEADER = ['产品', '问题类型', '试验条件', '批号', '规格', '时间点(月)', '考察项目', '汇总表内容', '检验报告单内容', '配对依据', '说明', '汇总表位置', '汇总表定位', '来源文件', '报告单定位']
SUM_HEADER = ['档', '问题类型', '产品', '考察项目', '汇总表内容', '检验报告单内容', '出现次数', '涉及范围', '说明']

def usage(msg=''):
    if msg:
        print('错误：' + msg + '\n')
    print(__doc__)
    sys.exit(1)

def parse_args(argv):
    if not argv:
        usage('缺少数据根目录')
    opt = dict(root=argv[0], out=None, product=None, detail=False, limit=20)
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ('-o', '--out'):
            i += 1
            opt['out'] = argv[i]
        elif a in ('-p', '--product'):
            i += 1
            opt['product'] = argv[i]
        elif a in ('-d', '--detail'):
            opt['detail'] = True
        elif a in ('-n', '--limit'):
            i += 1
            opt['limit'] = int(argv[i])
        elif a in ('-h', '--help'):
            usage()
        else:
            usage('无法识别的参数：' + a)
        i += 1
    return opt

def where(i):
    return '%s %s %s %s月' % (COND_CN.get(i['cond'], i['cond']), i['batch'], i['spec'] or '', fmt_time(i['time']))

def print_detail(issues, limit):
    by = {}
    for i in issues:
        by.setdefault(i['level'], []).append(i)
    for lv in ORDER:
        lst = by.get(lv, [])
        if not lst:
            continue
        agg = {}
        for i in lst:
            key = (i['item'], str(i['sv']), str(i['iv']))
            e = agg.setdefault(key, dict(n=0, where=[], file=i['file']))
            e['n'] += 1
            if len(e['where']) < 3:
                e['where'].append(where(i))
        print('  -- %s：%d 条 / %d 类' % (lv, len(lst), len(agg)))
        for (item, sv, iv), e in sorted(agg.items(), key=lambda x: -x[1]['n'])[:limit]:
            print('     x%-3d %-30s 汇总[%s] 报告[%s]' % (e['n'], item[:30], sv[:34].replace('\n', '/'), iv[:40].replace('\n', '/')))
            print('          %s | %s' % ('，'.join(e['where']), e['file'][:44]))
        if len(agg) > limit:
            print('     ... 其余 %d 类略' % (len(agg) - limit))

def print_summary(summary):
    cnt = tier_counts(summary)
    print('\n---- 要人看的：%d 件事（对应明细 %d 条）' % (len(summary), sum((g['n'] for g in summary))))
    for key, cn in TIERS:
        c = cnt.get(key)
        if not c:
            continue
        print('  【%s】%d 件 / %d 条' % (cn, c['groups'], c['rows']))
        if key == 'count':
            for line in count_rollup(summary):
                print('     ' + line)
            continue
        for g in [x for x in summary if x['tier'] == key][:6]:
            head = '%s ×%d' % (g['level'], g['n']) if g['n'] > 1 else g['level']
            print('     %-20s %s' % (head, (g['item'] or '-')[:28]))
            print('       汇总[%s] 报告[%s]' % (g['sv'][:28].replace('\n', ' '), g['iv'][:28].replace('\n', ' ')))
            if g['scope']:
                print('       %s' % g['scope'][:70])
        more = c['groups'] - 6
        if more > 0:
            print('     … 其余 %d 件见摘要 CSV' % more)

def print_health(blocking, notes):
    print('\n' + '=' * 70)
    if blocking:
        print('!! 体检不通过：有资料没有被读进来，下面的统计和问题清单都不完整 !!')
        print('=' * 70)
        for b in blocking:
            print('  [阻断] ' + b)
    else:
        print('体检通过：所有品种的汇总表和检验报告单都成功解析并参与了对账。')
        print('=' * 70)
    for n in notes:
        print('  [注意] ' + n)

def main(argv):
    opt = parse_args(argv)
    root = os.path.abspath(opt['root'])
    if not os.path.isdir(root):
        usage('数据根目录不存在：' + root)
    out_dir = os.path.abspath(opt['out']) if opt['out'] else os.path.join(os.path.dirname(root), '对账结果')
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    sets = discover(root)
    if not sets:
        usage('在 %s 下没有找到任何子目录' % root)
    conv_notes = {}
    engine = None
    for name, v in sets.items():
        if opt['product'] and opt['product'] not in name:
            continue
        docs = v['diag'].get('doc_unconverted') or []
        if not docs:
            continue
        if engine is None:
            engine, tried = convert.find_engine()
            if engine is None:
                print('有 .doc 要转换，但 %s' % convert.NO_ENGINE_HINT)
                break
            print('用 %s 转换 .doc…' % convert.ENGINE_CN.get(engine.name, engine.name))
        res = convert.convert_all(v['dir'], [os.path.join(v['dir'], x) for x in docs], engine=engine, on_progress=lambda i, t, fn: print('  [%d/%d] %s' % (i, t, fn)) if fn else None)
        line = convert.describe(res, v['dir'])
        conv_notes[name] = [line] if line else []
    if engine is not None:
        engine.close()
    if conv_notes:
        sets = discover(root)
    rows, issues = ([], [])
    total = dict(summary=0, reports=0, files=0, compared=0, same=0)
    blocking, notes = ([], [])
    ran = 0
    for name, v in sets.items():
        if opt['product'] and opt['product'] not in name:
            continue
        if not v['summary']:
            d = v['diag']
            msg = '「%s」下面没有找到汇总表。目录里有 %d 个 docx' % (name, d['docx_total'])
            if d['rejected']:
                msg += '，其中 %d 个做了内容校验但都不像汇总表（%s）' % (len(d['rejected']), '；'.join(d['rejected'][:3]))
            if d['doc_only']:
                msg += '。另有 %d 个 .doc 文件——工具只认 .docx；自动转换要本机装有 Word / WPS / ONLYOFFICE / LibreOffice 之一' % d['doc_only']
            for n in conv_notes.get(name, []):
                msg += '。' + n
            blocking.append(msg)
            print('跳过 %s：没有找到汇总表' % name)
            continue
        ran += 1
        r = run(name, v['summary'], v['coas'], doc_count=v['diag'].get('doc_only', 0), doc_unconverted=v['diag'].get('doc_unconverted'), coa_notes=conv_notes.get(name, []) + list(v['diag'].get('coa_notes') or []))
        st = r['stat']
        cov = r['coverage']
        print('\n======== %s' % name)
        print('  汇总表 %s' % os.path.basename(v['summary']))
        print('  数据点 %d 条（%d/%d 张表纳入对账）/ 报告块 %d（来自 %d 份 docx）/ 规格是否入主键=%s' % (cov['summary_records'], cov['summary_tables_in'], cov['summary_tables'], cov['blocks'], cov['coa_files'], r['use_spec']))
        print('  可比较 %d：一致 %d，明确不一致 %d，报告限表述 %d，定性/定量 %d，写法 %d，限度表述 %d' % (st['compared'], st['same'], st['diff'], st.get('rl', 0), st.get('qual', 0), st.get('style', 0), st.get('limit', 0)))
        print('  项目名称不一致 %d，全半角/标点 %d｜两边均不考察 %d，考察状态不一致 %d' % (st.get('name', 0), st.get('width', 0), st.get('nottested', 0), st.get('teststate', 0)))
        print('  项目对应存疑 %d（低置信配对，不足以断定数值不一致）' % st.get('uncertain', 0))
        print('  缺源文件 %d 组，汇总表缺整组 %d（%d 个实测值），源报告无此项 %d，汇总表未收录 %d' % (st['nosrc'], st.get('orphan', 0), st.get('orphan_values', 0), st['noitem'], st['omitted']))
        for b in cov['blocking']:
            blocking.append('【%s】%s' % (name, b))
            print('  [阻断] ' + b)
        for n in cov['notes']:
            notes.append('【%s】%s' % (name, n))
            print('  [注意] ' + n[:150])
        total['summary'] += cov['summary_records']
        total['reports'] += cov['blocks']
        total['files'] += cov['coa_files']
        total['compared'] += st['compared']
        total['same'] += st['same']
        if opt['detail']:
            print_detail(r['issues'], opt['limit'])
        for i in r['issues']:
            d = dict(product=name, level=i['level'], cond=COND_CN.get(i['cond'], i['cond']), batch=str(i['batch']), spec=str(i['spec']), time=fmt_time(i['time']), item=i['item'], sv=str(i['sv']).replace('\n', ' / '), iv=str(i['iv']).replace('\n', ' / '), match=i.get('match', ''), note=i['note'], stable=str(i.get('stable', ''))[:80], file=i['file'])
            issues.append(d)
            rows.append([name, i['level'], d['cond'], d['batch'], d['spec'], d['time'], d['item'], d['sv'], d['iv'], d['match'], d['note'], d['stable'], describe(i.get('sloc')), d['file'], describe(i.get('iloc'))])
    if not ran and opt['product']:
        usage('没有品种匹配 -p %s' % opt['product'])
    csv_path = os.path.join(out_dir, '对账问题清单.csv')
    with io.open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    summary = summarize(issues)
    sum_path = os.path.join(out_dir, '对账问题摘要.csv')
    with io.open(sum_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(SUM_HEADER)
        for g in summary:
            w.writerow([TIER_CN.get(g['tier'], g['tier']), g['level'], g['product'], g['item'], g['sv'], g['iv'], g['n'], g['scope'], g['note']])
    pct = 100.0 * total['same'] / total['compared'] if total['compared'] else 0.0
    print('\n======== 合计（%d 个品种）' % ran)
    print('  汇总表数据点 %d，报告块 %d（来自 %d 份 docx）' % (total['summary'], total['reports'], total['files']))
    print('  可比较 %d 对，完全一致 %d 对（%.1f%%）' % (total['compared'], total['same'], pct))
    print_summary(summary)
    print('\n  摘要 %d 件 -> %s' % (len(summary), sum_path))
    print('  明细 %d 条 -> %s' % (len(rows), csv_path))
    if not ran:
        blocking.insert(0, '一个品种都没有跑起来——没有任何目录被识别成品种目录。')
    print_health(blocking, notes)
    return 2 if blocking else 0
if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
