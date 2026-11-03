import hashlib
import os
import re
MAX_DEPTH = 3
MAX_VALIDATE = 8
_SUMMARY_NAME = re.compile('稳定性|3[-.\\s]*2[-.\\s]*[pP][-.\\s]*8|3[-.\\s]*2[-.\\s]*[sS][-.\\s]*7')

def _is_docx(f):
    return f.lower().endswith('.docx') and (not f.startswith('~$'))

def _walk_docx(d, maxdepth=MAX_DEPTH):
    out = []
    base = os.path.abspath(d)
    for cur, subdirs, files in os.walk(d):
        depth = os.path.relpath(os.path.abspath(cur), base).count(os.sep) + 1
        if depth > maxdepth:
            subdirs[:] = []
            continue
        subdirs.sort()
        for f in sorted(files):
            if _is_docx(f):
                out.append((depth, os.path.join(cur, f)))
    return out

def _rank(item):
    depth, path = item
    name = os.path.basename(path)
    return (0 if _SUMMARY_NAME.search(name) else 1, depth, name)

def _pick_summary(pdir, validate):
    cands = sorted(_walk_docx(pdir), key=_rank)
    diag = {'candidates': [os.path.basename(p) for _, p in cands[:MAX_VALIDATE]], 'rejected': [], 'docx_total': len(cands), 'doc_only': 0, 'pick_reason': ''}
    for cur, _sub, files in os.walk(pdir):
        diag['doc_only'] += sum((1 for f in files if f.lower().endswith('.doc') and (not f.startswith('~$'))))
    for depth, path in cands[:MAX_VALIDATE]:
        try:
            ok = validate(path)
        except Exception as e:
            diag['rejected'].append('%s（解析失败：%s）' % (os.path.basename(path), e))
            continue
        if ok:
            diag['pick_reason'] = '第 %d 层的「%s」，内容校验通过' % (depth, os.path.basename(path))
            return (path, diag)
        diag['rejected'].append(os.path.basename(path))
    return (None, diag)

def _sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as fp:
        for chunk in iter(lambda: fp.read(1 << 16), b''):
            h.update(chunk)
    return h.hexdigest()

def _coas(pdir, exclude):
    ex = {os.path.abspath(p) for p in exclude}
    ex_hash = set()
    for p in exclude:
        try:
            ex_hash.add(_sha1(p))
        except OSError:
            pass
    coas, notes = ([], [])
    seen_hash = {}
    seen_name = {}
    dup_copies = []
    for cur, subdirs, files in os.walk(pdir):
        subdirs.sort()
        for f in sorted(files):
            if not _is_docx(f):
                continue
            p = os.path.join(cur, f)
            if os.path.abspath(p) in ex:
                continue
            try:
                h = _sha1(p)
            except OSError as e:
                notes.append('读不了 %s（%s），已跳过' % (os.path.relpath(p, pdir), e))
                continue
            if h in ex_hash:
                continue
            if h in seen_hash:
                dup_copies.append((os.path.relpath(p, pdir), os.path.relpath(seen_hash[h], pdir)))
                continue
            seen_hash[h] = p
            if f in seen_name:
                notes.append('「%s」有两份同名但内容不同的文件，两份都已纳入对账：%s ／ %s' % (f, os.path.relpath(seen_name[f], pdir), os.path.relpath(p, pdir)))
            else:
                seen_name[f] = p
            coas.append(p)
    if dup_copies:
        notes.append('%d 份内容完全相同的副本已跳过（不是漏读）：%s' % (len(dup_copies), '；'.join(('%s = %s' % (a, b) for a, b in dup_copies[:3])) + ('…' if len(dup_copies) > 3 else '')))
    return (coas, notes)

def _doc_unconverted(pdir):
    from convert import unconverted
    return [os.path.relpath(p, pdir) for p in unconverted(pdir)]

def _default_validate(path):
    from docxgrid import parse
    from extract import is_summary
    return is_summary(parse(path))

def _subdirs(d):
    return [x for x in sorted(os.listdir(d)) if os.path.isdir(os.path.join(d, x))]

def _resolve(pdir, validate, depth):
    summary, diag = _pick_summary(pdir, validate)
    name = os.path.basename(os.path.normpath(pdir))
    if not summary:
        return [(name, pdir, None, diag)]
    if os.path.dirname(os.path.abspath(summary)) == os.path.abspath(pdir):
        diag['layout'] = '汇总表在品种目录第一层'
        return [(name, pdir, summary, diag)]
    if depth >= 2:
        diag['layout'] = '汇总表在子目录里（已达最大下探层数）'
        return [(name, pdir, summary, diag)]
    subs = _subdirs(pdir)
    hits = []
    for j in subs:
        s2, _ = _pick_summary(os.path.join(pdir, j), validate)
        if s2:
            hits.append(j)
    if len(hits) >= 2:
        out = []
        for j in subs:
            out += _resolve(os.path.join(pdir, j), validate, depth + 1)
        return out
    if len(hits) == 1:
        inner = os.path.abspath(os.path.join(pdir, hits[0]))
        outside = [p for _dep, p in _walk_docx(pdir) if not os.path.abspath(p).startswith(inner + os.sep)]
        if not outside:
            return _resolve(os.path.join(pdir, hits[0]), validate, depth + 1)
    diag['layout'] = '汇总表放在品种目录的子目录里'
    return [(name, pdir, summary, diag)]

def discover(root, validate=None):
    validate = validate or _default_validate
    found = []
    for d in sorted(os.listdir(root)):
        pdir = os.path.join(root, d)
        if os.path.isdir(pdir):
            found += _resolve(pdir, validate, 0)
    if not any((s for _n, _d, s, _g in found)):
        s, diag = _pick_summary(root, validate)
        if s:
            diag['layout'] = '数据根目录本身就是品种目录'
            found = [(os.path.basename(os.path.normpath(root)), root, s, diag)]
    sets = {}
    for name, pdir, summary, diag in found:
        key = name if name not in sets else '%s（%s）' % (name, os.path.basename(os.path.dirname(os.path.normpath(pdir))))
        coas, notes = _coas(pdir, [summary] if summary else [])
        diag['coa_notes'] = notes
        diag['doc_unconverted'] = _doc_unconverted(pdir)
        sets[key] = {'summary': summary, 'dir': pdir, 'diag': diag, 'coas': coas}
    return sets
if __name__ == '__main__':
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    base = sys.argv[1]
    for k, v in discover(base).items():
        s = os.path.basename(v['summary']) if v['summary'] else '（未找到）'
        print('%-34s 汇总表: %-40s 报告单: %d 份' % (k[:34], s[:40], len(v['coas'])))
        if not v['summary']:
            d = v['diag']
            print('      候选 %d 个，全部未通过内容校验：%s' % (d['docx_total'], '；'.join(d['rejected'][:4]) or '（目录下没有 docx）'))
            if d['doc_only']:
                print('      目录里还有 %d 个 .doc，需要先批量转成 .docx' % d['doc_only'])
