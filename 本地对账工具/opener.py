import os
import sys
import time
import threading
PROGIDS = ('Word.Application', 'KWPS.Application', 'wps.Application')
WD_FIND_STOP = 0
WD_COLLAPSE_END = 0
WD_WINDOW_NORMAL = 0
WD_WINDOW_MINIMIZE = 2

def _clean_q(q):
    q = str(q or '').split('\n')[0].strip()
    if '^' in q:
        q = q.split('^')[0].strip()
    return q[:80]

def _find_in(rng, q, want_row=None, limit=60):
    start, end = (rng.Start, rng.End)
    f = rng.Find
    f.ClearFormatting()
    f.Text = q
    f.Forward = True
    f.Wrap = WD_FIND_STOP
    f.MatchCase = False
    f.MatchWildcards = False
    try:
        f.MatchByte = False
    except Exception:
        pass
    hits = []
    while f.Execute():
        if rng.Start < start or rng.Start >= end:
            break
        if want_row is None:
            return rng
        try:
            ri = rng.Cells(1).RowIndex
        except Exception:
            ri = None
        if ri == want_row:
            return rng
        hits.append((ri, rng.Duplicate))
        if len(hits) >= limit:
            break
        rng.Collapse(WD_COLLAPSE_END)
    if not hits:
        return None
    above = [h for h in hits if h[0] is not None and h[0] <= want_row]
    if above:
        return max(above, key=lambda h: h[0])[1]
    known = [h for h in hits if h[0] is not None]
    if known:
        return min(known, key=lambda h: abs(h[0] - want_row))[1]
    return hits[0][1]

def _table_matches(doc, tbl, pos, cap):
    if len(pos) > 3:
        try:
            if tbl.Rows.Count != pos[3]:
                return False
        except Exception:
            pass
    if cap:
        try:
            s = tbl.Range.Start
            before = doc.Range(max(0, s - 600), s)
            if _find_in(before, cap) is None:
                return False
        except Exception:
            pass
    return True

def _table_by_caption(doc, cap, pos):
    rng = doc.Content
    end = rng.End
    for _ in range(20):
        hit = _find_in(rng, cap)
        if hit is None:
            return None
        try:
            after = doc.Range(hit.End, end)
            if after.Tables.Count:
                t = after.Tables(1)
                if len(pos) <= 3 or t.Rows.Count == pos[3]:
                    return t
        except Exception:
            pass
        rng = doc.Range(hit.End, end)
    return None

def _connect():
    import win32com.client
    from win32com.client import dynamic
    for pid in PROGIDS:
        try:
            return (win32com.client.GetActiveObject(pid), pid)
        except Exception:
            pass
    last = None
    for pid in PROGIDS:
        try:
            return (dynamic.Dispatch(pid), pid)
        except Exception as e:
            last = e
    raise RuntimeError('没有可用的 Word / WPS：%s' % last)

def _to_front(app):
    try:
        if app.WindowState == WD_WINDOW_MINIMIZE:
            app.WindowState = WD_WINDOW_NORMAL
    except Exception:
        pass
    try:
        app.Activate()
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.SetForegroundWindow(app.ActiveWindow.Hwnd)
    except Exception:
        pass

def _open_com(loc):
    import pythoncom
    pythoncom.CoInitialize()
    try:
        app, pid = _connect()
        app.Visible = True
        try:
            app.DisplayAlerts = 0
        except Exception:
            pass
        path = os.path.normpath(loc['file'])
        doc = app.Documents.Open(path, False, False, False)
        q = _clean_q(loc.get('q'))
        cap = _clean_q(loc.get('cap'))
        pos = loc.get('pos')
        hit, tbl, how = (None, None, 'open')
        if pos:
            t, r = (pos[0], pos[1])
            try:
                if doc.Tables.Count > t:
                    tbl = doc.Tables(t + 1)
            except Exception:
                tbl = None
            if tbl is not None and (not _table_matches(doc, tbl, pos, cap)):
                tbl = None
            if tbl is None and cap:
                tbl = _table_by_caption(doc, cap, pos)
            if tbl is not None and q:
                hit = _find_in(tbl.Range, q, want_row=r + 1)
                if hit is not None:
                    how = 'cell'
        if hit is None and q:
            hit = _find_in(doc.Content, q)
            if hit is not None:
                how = 'found' if pos else 'cell'
        if hit is not None:
            hit.Select()
        elif tbl is not None:
            try:
                tbl.Range.Cells(1).Range.Select()
                how = 'table'
            except Exception:
                tbl.Range.Select()
                how = 'table'
        try:
            app.ActiveWindow.ScrollIntoView(app.Selection.Range)
        except Exception:
            pass
        _to_front(app)
        return {'ok': True, 'how': how, 'app': pid.split('.')[0]}
    finally:
        pythoncom.CoUninitialize()

def _raise_window(name, timeout=12):
    if sys.platform != 'win32':
        return

    def work():
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        found = []

        def cb(h, _):
            if u.IsWindowVisible(h):
                n = u.GetWindowTextLengthW(h)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    u.GetWindowTextW(h, buf, n + 1)
                    if name in buf.value:
                        found.append(h)
            return True
        end = time.time() + timeout
        while time.time() < end:
            found[:] = []
            u.EnumWindows(proto(cb), 0)
            if found:
                h = found[0]
                if u.IsIconic(h):
                    u.ShowWindow(h, 9)
                u.SetForegroundWindow(h)
                return
            time.sleep(0.5)
    threading.Thread(target=work, daemon=True).start()

def _log(loc, r):
    try:
        from marker import OUT_DIR
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, '打开记录.log'), 'a', encoding='utf-8') as f:
            f.write('%s\t%s\t%s\t%s\t%s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), r.get('how'), os.path.basename(str((loc or {}).get('file', ''))), r.get('copy', ''), str(r.get('error', ''))[:300]))
    except Exception:
        pass

def open_at(loc):
    r = _open_at(loc)
    _log(loc, r)
    return r

def _open_at(loc):
    if not loc or not loc.get('file'):
        return {'ok': False, 'how': 'fail', 'error': '这条问题没有记录文件位置'}
    path = loc['file']
    if not os.path.exists(path):
        return {'ok': False, 'how': 'fail', 'error': '文件不存在：' + path}
    if sys.platform == 'win32':
        try:
            return _open_com(loc)
        except Exception as e:
            com_err = str(e)[:200]
    else:
        com_err = '非 Windows'
    try:
        from marker import make_marked_copy
        dst, what = make_marked_copy(loc)
        os.startfile(dst)
        _raise_window(os.path.basename(dst))
        return {'ok': True, 'how': 'marked', 'app': '', 'copy': dst, 'what': what, 'error': com_err}
    except Exception as e:
        mark_err = str(e)[:200]
    try:
        os.startfile(path)
        _raise_window(os.path.basename(path))
        return {'ok': True, 'how': 'shell', 'app': '', 'error': '%s｜%s' % (com_err, mark_err)}
    except Exception as e:
        return {'ok': False, 'how': 'fail', 'error': '打不开文件：%s' % e}

def describe(loc):
    if not loc or not loc.get('pos'):
        return ''
    t, r, c = loc['pos'][:3]
    return '第 %d 张表 第 %d 行 第 %d 列' % (t + 1, r + 1, c + 1)
