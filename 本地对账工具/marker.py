import copy
import io
import os
import re
import time
import zipfile
import xml.etree.ElementTree as ET
W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
W = '{%s}' % W_NS
YELLOW = 'FFFF00'
OUT_DIR = os.path.join(os.environ.get('TEMP') or os.environ.get('TMP') or '.', '稳定性资料核对')

def _text_of_p(p):
    return ''.join((t.text or '' for t in p.iter(W + 't')))

def _nz(s):
    import unicodedata
    return re.sub('\\s+', '', unicodedata.normalize('NFKC', s or ''))

def _ns_decls(xml_bytes):
    return re.findall(b'xmlns:([\\w\\-.]+)="([^"]+)"', xml_bytes)

def _register_namespaces(xml_bytes):
    for prefix, uri in _ns_decls(xml_bytes):
        try:
            ET.register_namespace(prefix.decode(), uri.decode())
        except ValueError:
            pass

def _shade_cell(tc):
    pr = tc.find(W + 'tcPr')
    if pr is None:
        pr = ET.Element(W + 'tcPr')
        tc.insert(0, pr)
    old = pr.find(W + 'shd')
    if old is not None:
        pr.remove(old)
    shd = ET.Element(W + 'shd')
    shd.set(W + 'val', 'clear')
    shd.set(W + 'color', 'auto')
    shd.set(W + 'fill', YELLOW)
    before = {W + x for x in ('tcW', 'gridSpan', 'hMerge', 'vMerge', 'tcBorders')}
    idx = 0
    for k, ch in enumerate(list(pr)):
        if ch.tag in before:
            idx = k + 1
    pr.insert(idx, shd)

def _shade_para(p):
    pr = p.find(W + 'pPr')
    if pr is None:
        pr = ET.Element(W + 'pPr')
        p.insert(0, pr)
    old = pr.find(W + 'shd')
    if old is not None:
        pr.remove(old)
    shd = ET.Element(W + 'shd')
    shd.set(W + 'val', 'clear')
    shd.set(W + 'color', 'auto')
    shd.set(W + 'fill', YELLOW)
    before = {W + x for x in ('pStyle', 'keepNext', 'keepLines', 'pageBreakBefore', 'framePr', 'widowControl', 'numPr', 'suppressLineNumbers', 'pBdr')}
    idx = 0
    for k, ch in enumerate(list(pr)):
        if ch.tag in before:
            idx = k + 1
    pr.insert(idx, shd)

def _cell_at(tr, ci):
    col = 0
    for tc in tr.findall(W + 'tc'):
        span = 1
        pr = tc.find(W + 'tcPr')
        if pr is not None:
            gs = pr.find(W + 'gridSpan')
            if gs is not None:
                span = int(gs.get(W + 'val', '1'))
        if col <= ci < col + span:
            return tc
        col += span
    return None

def _para(text, bold=False, shade=None, page_break=False):
    p = ET.Element(W + 'p')
    if shade:
        pr = ET.SubElement(p, W + 'pPr')
        shd = ET.SubElement(pr, W + 'shd')
        shd.set(W + 'val', 'clear')
        shd.set(W + 'color', 'auto')
        shd.set(W + 'fill', shade)
    r = ET.SubElement(p, W + 'r')
    if bold:
        rpr = ET.SubElement(r, W + 'rPr')
        ET.SubElement(rpr, W + 'b')
    if page_break:
        br = ET.SubElement(r, W + 'br')
        br.set(W + 'type', 'page')
    else:
        t = ET.SubElement(r, W + 't')
        t.text = text
        t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    return p
STRIP = {W + x for x in ('bookmarkStart', 'bookmarkEnd', 'commentRangeStart', 'commentRangeEnd', 'commentReference', 'drawing')}

def _clone(el):
    c = copy.deepcopy(el)
    for parent in list(c.iter()):
        for ch in list(parent):
            if ch.tag in STRIP:
                parent.remove(ch)
            elif ch.tag == W + 'r' and ch.find(W + 'commentReference') is not None:
                parent.remove(ch)
    return c

def _vmerge(tc):
    pr = tc.find(W + 'tcPr')
    vm = pr.find(W + 'vMerge') if pr is not None else None
    if vm is None:
        return None
    return vm.get(W + 'val', 'continue')

def _resolve_merges(row_clone, rows, ri, included):
    col = 0
    for tc in row_clone.findall(W + 'tc'):
        span = 1
        pr = tc.find(W + 'tcPr')
        if pr is not None:
            gs = pr.find(W + 'gridSpan')
            if gs is not None:
                span = int(gs.get(W + 'val', '1'))
        if _vmerge(tc) == 'continue':
            origin = None
            for rj in range(ri - 1, -1, -1):
                up = _cell_at(rows[rj], col)
                if up is None:
                    break
                if _vmerge(up) != 'continue':
                    origin = up
                    break
            if origin is not None and all((r in included for r in range(rj, ri + 1))):
                col += span
                continue
            if origin is not None:
                for ch in list(tc):
                    if ch.tag != W + 'tcPr':
                        tc.remove(ch)
                for ch in origin:
                    if ch.tag != W + 'tcPr':
                        tc.append(copy.deepcopy(ch))
            if pr is not None:
                vm = pr.find(W + 'vMerge')
                if vm is not None:
                    pr.remove(vm)
        col += span
    return row_clone

def _extract_rows(tbl, rows, hdr, take):
    t = ET.Element(W + 'tbl')
    for ch in tbl:
        if ch.tag in (W + 'tblPr', W + 'tblGrid'):
            t.append(copy.deepcopy(ch))
    hdr = max(0, min(hdr, len(rows) - 1))
    idx = list(range(max(0, hdr - 3), hdr + 1)) + [r for r in take if r > hdr]
    for r in idx:
        t.append(_resolve_merges(copy.deepcopy(rows[r]), rows, r, set(idx)))
    return _clone(t)

def make_marked_copy(loc):
    src = loc['file']
    z = zipfile.ZipFile(src)
    xml = z.read('word/document.xml')
    _register_namespaces(xml)
    root = ET.fromstring(xml)
    body = root.find(W + 'body')
    if body is None:
        raise ValueError('document.xml 没有 body')
    kids = list(body)
    pos = loc.get('pos')
    q = str(loc.get('q') or '').split('\n')[0].strip()
    head_items = []
    what = ''
    if pos:
        ti, ri, ci = (pos[0], pos[1], pos[2])
        tables = [k for k in kids if k.tag == W + 'tbl']
        if ti >= len(tables):
            raise ValueError('文档里只有 %d 张表，找不到第 %d 张' % (len(tables), ti + 1))
        tbl = tables[ti]
        rows = tbl.findall(W + 'tr')
        if ri >= len(rows):
            raise ValueError('第 %d 张表只有 %d 行' % (ti + 1, len(rows)))
        tc = _cell_at(rows[ri], ci)
        if tc is None:
            raise ValueError('第 %d 张表第 %d 行没有第 %d 列' % (ti + 1, ri + 1, ci + 1))
        nq = _nz(q)
        tc_ri = ri
        if nq and nq not in _nz(_text_of_p(tc)):
            for rj in range(ri, max(-1, ri - 40), -1):
                hit = [x for x in rows[rj].findall(W + 'tc') if nq in _nz(_text_of_p(x))]
                if hit:
                    tc, tc_ri = (hit[0], rj)
                    break
        _shade_cell(tc)
        k = kids.index(tbl)
        cap = None
        for j in range(k - 1, max(-1, k - 6), -1):
            if kids[j].tag == W + 'p' and _text_of_p(kids[j]).strip():
                cap = kids[j]
                break
        what = '下面摘出原文第 %d 张表的表头和问题所在的那一行（原表第 %d 行），黄色格就是' % (ti + 1, tc_ri + 1)
        what += '，内容「%s」' % q if q else ''
        if cap is not None:
            head_items.append(_clone(cap))
        hdr = pos[4] if len(pos) > 4 else 1
        head_items.append(_extract_rows(tbl, rows, hdr, sorted({tc_ri, ri})))
    elif q:
        target = None
        nq = _nz(q)
        for k in kids:
            if k.tag == W + 'p' and nq and (nq in _nz(_text_of_p(k))):
                target = k
                break
        if target is None:
            raise ValueError('正文里找不到「%s」' % q[:30])
        _shade_para(target)
        what = '下面这段正文是问题所在（已涂黄）'
        head_items.append(_clone(target))
    else:
        raise ValueError('这条问题只记了文件，没有位置')
    banner = [_para('【稳定性资料核对 · 定位标记】' + what + '。', bold=True, shade=YELLOW), _para('这是带标记的副本，原文件没有改动：%s' % src), _para('后面从下一页起是原文全文，对应位置同样涂黄。要修改请回原文件改，改在这份副本上会丢。')]
    tail = [_para('', page_break=True)]
    for i, el in enumerate(banner + head_items + tail):
        body.insert(i, el)
    out = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    m_old = re.search(b'<w:document\\b[^>]*>', xml)
    m_new = re.search(b'<w:document\\b[^>]*>', out)
    if m_old and m_new:
        tag = m_old.group(0)
        have = {p for p, _ in _ns_decls(tag)}
        extra = b''.join((b' xmlns:%s="%s"' % (p, u) for p, u in _ns_decls(m_new.group(0)) if p not in have))
        tag = tag[:-1] + extra + b'>'
        out = out[:m_new.start()] + tag + out[m_new.end():]
    os.makedirs(OUT_DIR, exist_ok=True)
    _sweep(OUT_DIR)
    base, ext = os.path.splitext(os.path.basename(src))
    dst = os.path.join(OUT_DIR, '%s【核对标记 %s】%s' % (base[:60], time.strftime('%H%M%S'), ext))
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zo:
        for item in z.infolist():
            data = out if item.filename == 'word/document.xml' else z.read(item.filename)
            zo.writestr(item, data)
    return (dst, what)

def _sweep(d, older_than=86400):
    now = time.time()
    try:
        for f in os.listdir(d):
            p = os.path.join(d, f)
            try:
                if now - os.path.getmtime(p) > older_than:
                    os.remove(p)
            except OSError:
                pass
    except OSError:
        pass
