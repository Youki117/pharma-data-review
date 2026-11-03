import sys, os, io, csv, json, threading, traceback
BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

def res_path(name):
    return os.path.join(getattr(sys, '_MEIPASS', BASE), name)

def _dpi_scale():
    if sys.platform != 'win32':
        return 1.0
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            return 1.0
    try:
        return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
    except Exception:
        try:
            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
            ctypes.windll.user32.ReleaseDC(0, hdc)
            return max(1.0, dpi / 96.0)
        except Exception:
            return 1.0
DPI = _dpi_scale()
import webview
from discover import discover
from reconcile import run, COND_CN
from opener import open_at, describe
import convert
APP_TITLE = '稳定性资料核对'
APP_VERSION = '1.3.0（2026-09-22）'
from summarize import LEVELS, LEVEL_ORDER, LEVEL_TIER, TIERS, summarize, tier_counts, count_rollup, fmt_time
STATE = {'stage': 'idle', 'done': 0, 'total': 0, 'current': '', 'error': '', 'results': None, 'root': ''}
LOCK = threading.Lock()

def _rel(loc, root):
    if not loc or not loc.get('file'):
        return loc
    d = dict(loc)
    try:
        d['file'] = os.path.relpath(d['file'], root)
    except ValueError:
        pass
    return d

def _work(root):
    try:
        with LOCK:
            STATE.update(stage='discover', done=0, total=0, current='', error='', results=None, root=root)
        found = discover(root)
        conv_notes = _convert_docs(found)
        if conv_notes:
            found = discover(root)
        sets = {k: v for k, v in found.items() if v['summary']}
        blocking, notes = ([], [])
        for k, v in found.items():
            if v['summary']:
                continue
            d = v['diag']
            msg = '「%s」下面没有找到汇总表：目录里有 %d 个 docx' % (k, d['docx_total'])
            if d['rejected']:
                msg += '，其中 %d 个做了内容校验但都不像汇总表' % len(d['rejected'])
            if d['doc_only']:
                msg += '。另有 %d 个 .doc —— 工具只认 .docx；自动转换要本机装有 Word / WPS / ONLYOFFICE / LibreOffice 之一' % d['doc_only']
            for n in conv_notes.get(k, []):
                msg += '。' + n
            blocking.append(msg)
        if not sets:
            with LOCK:
                STATE.update(stage='error', error='这个目录下没有找到任何品种的汇总表。\n\n' + '\n'.join(('· ' + b for b in blocking[:6])) + '\n\n推荐的目录结构：\n  数据根目录 / 品种目录 / 汇总表.docx\n                        / 任意子目录 / 检验报告单.docx\n（汇总表放在品种目录的子目录里、或品种上面再套一层分类目录，也都能识别）')
            return
        total = sum((len(v['coas']) + 1 for v in sets.values()))
        with LOCK:
            STATE.update(stage='running', total=total)
        base = [0]
        products, issues = ([], [])
        for name, v in sets.items():

            def prog(i, t, fn, _b=base):
                with LOCK:
                    STATE.update(done=_b[0] + i, current=fn)
            r = run(name, v['summary'], v['coas'], on_progress=prog, doc_count=v['diag'].get('doc_only', 0), doc_unconverted=v['diag'].get('doc_unconverted'), coa_notes=conv_notes.get(name, []) + list(v['diag'].get('coa_notes') or []))
            base[0] += len(v['coas']) + 1
            st = r['stat']
            cov = r['coverage']
            products.append({'name': name, 'summary_file': os.path.basename(v['summary']), 'files': len(v['coas']), 'records': len(r['summary']['records']), 'blocks': len(r['reports']), 'compared': st['compared'], 'same': st['same'], 'tables': cov['summary_tables'], 'tables_in': cov['summary_tables_in'], 'warnings': r['summary']['warnings']})
            blocking += ['【%s】%s' % (name, x) for x in cov['blocking']]
            notes += ['【%s】%s' % (name, x) for x in cov['notes']]
            for i in r['issues']:
                issues.append({'product': name, 'level': i['level'], 'tier': LEVEL_TIER.get(i['level'], 'note'), 'cond': COND_CN.get(i['cond'], i['cond']), 'batch': str(i['batch']), 'spec': str(i['spec']), 'time': fmt_time(i['time']), 'item': i['item'], 'sv': str(i['sv']).replace('\n', ' / '), 'iv': str(i['iv']).replace('\n', ' / '), 'match': i.get('match', ''), 'note': i['note'], 'stable': str(i.get('stable', ''))[:80], 'file': i['file'], 'sloc': _rel(i.get('sloc'), root), 'iloc': _rel(i.get('iloc'), root)})
        rank = {lv: n for n, lv in enumerate(LEVEL_ORDER)}
        issues.sort(key=lambda x: (rank.get(x['level'], 99), x['product'], x['item']))
        with LOCK:
            summary = summarize(issues)
            STATE.update(stage='done', current='', results={'products': products, 'issues': issues, 'summary': summary, 'count_rollup': count_rollup(summary), 'tiers': [{'key': k, 'name': n} for k, n in TIERS], 'tier_counts': tier_counts(summary), 'health': {'blocking': blocking, 'notes': notes}, 'levels': [{'name': a, 'tier': b, 'desc': c} for a, b, c in LEVELS]})
    except Exception:
        with LOCK:
            STATE.update(stage='error', error=traceback.format_exc()[-1500:])

def _convert_docs(found):
    todo = [(k, v) for k, v in found.items() if v['diag'].get('doc_unconverted')]
    if not todo:
        return {}
    total = sum((len(v['diag']['doc_unconverted']) for _k, v in todo))
    with LOCK:
        STATE.update(stage='convert', done=0, total=total, current='')
    base = [0]
    out = {}
    engine = None
    try:
        for k, v in todo:
            docs = [os.path.join(v['dir'], x) for x in v['diag']['doc_unconverted']]

            def prog(i, t, fn, _b=base):
                with LOCK:
                    STATE.update(done=_b[0] + i, current=fn)
            if engine is None:
                engine, _tried = convert.find_engine()
            res = convert.convert_all(v['dir'], docs, on_progress=prog, engine=engine)
            base[0] += len(docs)
            line = convert.describe(res, v['dir'])
            out[k] = [line] if line else []
            if res['reason']:
                out[k].append(res['reason'])
    finally:
        if engine is not None:
            engine.close()
    return out

class Api(object):

    def pick(self, title=''):
        w = webview.windows[0]
        r = w.create_file_dialog(webview.FOLDER_DIALOG)
        if not r:
            return {'path': ''}
        return {'path': r[0] if isinstance(r, (list, tuple)) else str(r)}

    def start(self, root):
        root = (root or '').strip().strip('"')
        if not os.path.isdir(root):
            return {'ok': False, 'error': '目录不存在：' + root}
        with LOCK:
            if STATE['stage'] in ('convert', 'discover', 'running'):
                return {'ok': False, 'error': '正在核对中'}
        threading.Thread(target=_work, args=(root,), daemon=True).start()
        return {'ok': True}

    def version(self):
        return {'version': APP_VERSION}

    def progress(self):
        with LOCK:
            return {k: STATE[k] for k in ('stage', 'done', 'total', 'current', 'error', 'root')}

    def results(self):
        with LOCK:
            return STATE.get('results') or {}

    def export(self, out_dir):
        try:
            res = STATE.get('results')
            if not res:
                return {'ok': False, 'error': '还没有可导出的结果'}
            if not out_dir or not os.path.isdir(out_dir):
                return {'ok': False, 'error': '导出目录无效'}
            path = os.path.join(out_dir, '对账问题清单.csv')
            with io.open(path, 'w', encoding='utf-8-sig', newline='') as f:
                w = csv.writer(f)
                w.writerow(['产品', '问题类型', '试验条件', '批号', '规格', '时间点(月)', '考察项目', '汇总表内容', '检验报告单内容', '配对依据', '说明', '汇总表位置', '汇总表定位', '来源文件', '报告单定位'])
                for i in res['issues']:
                    w.writerow([i['product'], i['level'], i['cond'], i['batch'], i['spec'], i['time'], i['item'], i['sv'], i['iv'], i['match'], i['note'], i.get('stable', ''), describe(i.get('sloc')), i['file'], describe(i.get('iloc'))])
            sp = os.path.join(out_dir, '对账问题摘要.csv')
            with io.open(sp, 'w', encoding='utf-8-sig', newline='') as f:
                w = csv.writer(f)
                w.writerow(['档', '问题类型', '产品', '考察项目', '汇总表内容', '检验报告单内容', '出现次数', '涉及范围', '说明'])
                cn = dict(TIERS)
                for g in res.get('summary', []):
                    w.writerow([cn.get(g['tier'], g['tier']), g['level'], g['product'], g['item'], g['sv'], g['iv'], g['n'], g['scope'], g['note']])
            return {'ok': True, 'path': sp, 'path2': path}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def open_loc(self, loc):
        try:
            if loc and loc.get('file') and (not os.path.isabs(loc['file'])):
                loc = dict(loc, file=os.path.join(STATE.get('root', ''), loc['file']))
            return open_at(loc)
        except Exception as e:
            return {'ok': False, 'how': 'fail', 'error': str(e)[:300]}

    def reveal(self, path):
        try:
            if sys.platform == 'win32' and os.path.exists(path):
                os.system('explorer /select,"%s"' % os.path.normpath(path))
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def quit(self):
        for w in list(webview.windows):
            try:
                w.destroy()
            except Exception:
                pass
        return {'ok': True}

def _place(window):
    try:
        sc = webview.screens[0]
        sw, sh = (sc.width / DPI, sc.height / DPI)
        w = min(1140, int(sw * 0.76))
        h = min(740, int(sh * 0.82))
        window.resize(w, h)
        window.move(int((sw - w) / 2), max(0, int((sh - h) / 2) - 24))
    except Exception:
        pass

def main():
    win = webview.create_window(APP_TITLE, url=res_path('ui.html'), js_api=Api(), width=1140, height=740, min_size=(760, 520), background_color='#F4F6F7')
    try:
        webview.start(_place, win, icon=res_path('icon.ico'))
    except Exception:
        webview.start(_place, win)
    os._exit(0)
if __name__ == '__main__':
    main()
