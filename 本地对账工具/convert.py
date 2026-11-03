import os
import subprocess
import time
DOCX_DIR = 'docx版'

def _rel_dir(pdir, doc_path):
    r = os.path.relpath(os.path.dirname(doc_path), pdir)
    return '' if r == '.' else r

def target_for(pdir, doc_path):
    stem = os.path.splitext(os.path.basename(doc_path))[0]
    return os.path.join(pdir, DOCX_DIR, _rel_dir(pdir, doc_path), stem + '.docx')

def list_docs(pdir):
    out = []
    for cur, subdirs, files in os.walk(pdir):
        subdirs[:] = sorted((d for d in subdirs if d != DOCX_DIR))
        for f in sorted(files):
            if f.lower().endswith('.doc') and (not f.startswith('~$')):
                out.append(os.path.join(cur, f))
    return out

def unconverted(pdir):
    docs = list_docs(pdir)
    stem_count = {}
    for d in docs:
        stem = os.path.splitext(os.path.basename(d))[0]
        stem_count[stem] = stem_count.get(stem, 0) + 1
    out = []
    for d in docs:
        stem = os.path.splitext(os.path.basename(d))[0]
        beside = os.path.join(os.path.dirname(d), stem + '.docx')
        flat = os.path.join(pdir, DOCX_DIR, stem + '.docx')
        if os.path.isfile(beside) or os.path.isfile(target_for(pdir, d)):
            continue
        if os.path.isfile(flat) and stem_count[stem] == 1:
            continue
        out.append(d)
    return out

def _x2t_path():
    cands = []
    for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
        if base:
            cands.append(os.path.join(base, 'ONLYOFFICE', 'DesktopEditors', 'converter', 'x2t.exe'))
            cands.append(os.path.join(base, 'ONLYOFFICE', 'DesktopEditors', 'x2t.exe'))
    la = os.environ.get('LOCALAPPDATA')
    if la:
        cands.append(os.path.join(la, 'Programs', 'ONLYOFFICE', 'DesktopEditors', 'converter', 'x2t.exe'))
        cands.append(os.path.join(la, 'ONLYOFFICE', 'DesktopEditors', 'converter', 'x2t.exe'))
    for p in cands:
        if os.path.isfile(p):
            return p
    try:
        import winreg
    except ImportError:
        return None
    roots = [(winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall'), (winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall'), (winreg.HKEY_CURRENT_USER, 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall')]
    for hive, sub in roots:
        try:
            key = winreg.OpenKey(hive, sub)
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                try:
                    k2 = winreg.OpenKey(key, name)
                    disp = winreg.QueryValueEx(k2, 'DisplayName')[0]
                    if 'ONLYOFFICE' not in str(disp).upper():
                        continue
                    dirs = []
                    for val in ('InstallLocation', 'DisplayIcon'):
                        try:
                            v = str(winreg.QueryValueEx(k2, val)[0]).strip('"')
                        except OSError:
                            continue
                        if val == 'DisplayIcon':
                            v = v.split(',')[0].strip('"')
                            v = os.path.dirname(v)
                        if v:
                            dirs.append(v)
                    for d in dirs:
                        for rel in (('converter', 'x2t.exe'), ('x2t.exe',)):
                            p = os.path.join(d, *rel)
                            if os.path.isfile(p):
                                return p
                except OSError:
                    continue
        finally:
            winreg.CloseKey(key)
    return None

def _soffice_path():
    for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
        if base:
            p = os.path.join(base, 'LibreOffice', 'program', 'soffice.exe')
            if os.path.isfile(p):
                return p
    return None
COM_PROGIDS = (('word', 'Word.Application'), ('wps', 'KWPS.Application'), ('wps', 'wps.Application'))
WD_FORMAT_DOCX = 16
WD_FORMAT_XML_DOCUMENT = 12
WD_DO_NOT_SAVE = 0

def _com_app(progid):
    from win32com.client import dynamic
    app = dynamic.Dispatch(progid)
    try:
        app.Visible = False
    except Exception:
        pass
    try:
        app.DisplayAlerts = 0
    except Exception:
        pass
    return app

class _ComEngine(object):

    def __init__(self, name, progid, app):
        self.name, self.progid, self.app = (name, progid, app)

    def convert(self, src, dst):
        doc = self.app.Documents.Open(os.path.normpath(src), False, True, False)
        try:
            try:
                doc.SaveAs2(os.path.normpath(dst), WD_FORMAT_DOCX)
            except Exception:
                doc.SaveAs(os.path.normpath(dst), WD_FORMAT_XML_DOCUMENT)
        finally:
            try:
                doc.Close(WD_DO_NOT_SAVE)
            except Exception:
                pass

    def close(self):
        try:
            self.app.Quit()
        except Exception:
            pass

class _ExeEngine(object):

    def __init__(self, name, exe):
        self.name, self.exe = (name, exe)

    def convert(self, src, dst):
        if self.name == 'x2t':
            cmd = [self.exe, src, dst]
        else:
            cmd = [self.exe, '--headless', '--convert-to', 'docx', '--outdir', os.path.dirname(dst), src]
        r = subprocess.run(cmd, capture_output=True, timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if r.returncode != 0:
            raise RuntimeError('退出码 %d：%s' % (r.returncode, (r.stderr or r.stdout or b'').decode('utf-8', 'replace')[:160].strip()))
        if not os.path.isfile(dst):
            raise RuntimeError('程序退出了但没有生成文件')

    def close(self):
        pass

def find_engine(order=None):
    tried = []
    for name in order or ('word', 'wps', 'x2t', 'soffice'):
        if name in ('word', 'wps'):
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except Exception as e:
                tried.append('%s：本机没有 COM 支持（%s）' % (name, e))
                continue
            for n, pid in COM_PROGIDS:
                if n != name:
                    continue
                try:
                    return (_ComEngine(name, pid, _com_app(pid)), tried)
                except Exception as e:
                    tried.append('%s（%s）：%s' % (name, pid, str(e)[:80]))
        elif name == 'x2t':
            p = _x2t_path()
            if p:
                return (_ExeEngine('x2t', p), tried)
            tried.append('x2t：没找到 ONLYOFFICE 的 x2t.exe')
        elif name == 'soffice':
            p = _soffice_path()
            if p:
                return (_ExeEngine('soffice', p), tried)
            tried.append('soffice：没找到 LibreOffice')
    return (None, tried)
ENGINE_CN = {'word': 'Word', 'wps': 'WPS', 'x2t': 'ONLYOFFICE', 'soffice': 'LibreOffice'}
NO_ENGINE_HINT = '本机没有找到能把 .doc 转成 .docx 的软件（按顺序找了 Word、WPS、ONLYOFFICE、LibreOffice）。装其中任意一个再重新核对；或者用 Word 把这些 .doc 逐份「另存为」.docx，放在原文件旁边或品种目录的 docx版/ 里'

def convert_all(pdir, docs=None, on_progress=None, engine=None):
    docs = list(docs) if docs is not None else unconverted(pdir)
    res = {'engine': None, 'converted': [], 'failed': [], 'reason': '', 'seconds': 0.0}
    if not docs:
        return res
    t0 = time.time()
    own = engine is None
    if own:
        engine, tried = find_engine()
        if engine is None:
            res['reason'] = NO_ENGINE_HINT + '。' + '；'.join(tried)
            res['failed'] = [(d, '没有转换引擎') for d in docs]
            return res
    res['engine'] = engine.name
    try:
        for i, d in enumerate(docs, 1):
            if on_progress:
                on_progress(i - 1, len(docs), os.path.basename(d))
            dst = target_for(pdir, d)
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                engine.convert(d, dst)
                if not os.path.isfile(dst) or os.path.getsize(dst) < 100:
                    raise RuntimeError('转换后的文件不存在或为空')
                res['converted'].append((d, dst))
            except Exception as e:
                res['failed'].append((d, str(e)[:160]))
        if on_progress:
            on_progress(len(docs), len(docs), '')
    finally:
        if own:
            engine.close()
    res['seconds'] = time.time() - t0
    return res

def describe(res, pdir=''):
    if not res['converted'] and (not res['failed']):
        return ''
    bits = []
    if res['converted']:
        bits.append('已用 %s 把 %d 份 .doc 转成 .docx（%.0f 秒），存放在 %s' % (ENGINE_CN.get(res['engine'], res['engine']), len(res['converted']), res['seconds'], os.path.join(os.path.basename(pdir) or '品种目录', DOCX_DIR)))
    if res['failed'] and res['engine']:
        bits.append('%d 份转换失败（%s%s）' % (len(res['failed']), '；'.join(('%s：%s' % (os.path.basename(a)[:30], b[:60]) for a, b in res['failed'][:3])), '…' if len(res['failed']) > 3 else ''))
    return '。'.join(bits)
if __name__ == '__main__':
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    pdir = sys.argv[1]
    todo = unconverted(pdir)
    print('没转过的 .doc：%d 份' % len(todo))
    r = convert_all(pdir, todo, on_progress=lambda i, n, f: print('  %d/%d %s' % (i, n, f)))
    print(describe(r, pdir) or r['reason'])
