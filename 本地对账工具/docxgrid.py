import zipfile, re, json, sys
import xml.etree.ElementTree as ET
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

def _text_of_p(p):
    parts = []
    for node in p.iter():
        t = node.tag
        if t == W + 't':
            parts.append(node.text or '')
        elif t == W + 'tab':
            parts.append('\t')
        elif t == W + 'br':
            parts.append('\n')
    return ''.join(parts)

def _cell_text(tc):
    return '\n'.join((_text_of_p(p) for p in tc.findall(W + 'p'))).strip()

def parse_table(tbl):
    raw_rows = []
    for tr in tbl.findall(W + 'tr'):
        cells = []
        for tc in tr.findall(W + 'tc'):
            pr = tc.find(W + 'tcPr')
            span = 1
            vmerge = None
            if pr is not None:
                gs = pr.find(W + 'gridSpan')
                if gs is not None:
                    span = int(gs.get(W + 'val', '1'))
                vm = pr.find(W + 'vMerge')
                if vm is not None:
                    vmerge = vm.get(W + 'val', 'continue')
            cells.append({'t': _cell_text(tc), 'span': span, 'vmerge': vmerge})
        raw_rows.append(cells)
    width = max((sum((c['span'] for c in r)) for r in raw_rows), default=0)
    grid = []
    for ri, cells in enumerate(raw_rows):
        row = [None] * width
        col = 0
        for c in cells:
            for k in range(c['span']):
                if col >= width:
                    break
                if c['vmerge'] == 'continue':
                    above = grid[ri - 1][col] if ri > 0 and grid[ri - 1][col] else {'t': '', 'hm': False, 'vm': True}
                    row[col] = {'t': above['t'], 'hm': k > 0, 'vm': True}
                else:
                    row[col] = {'t': c['t'], 'hm': k > 0, 'vm': False}
                col += 1
        for i in range(width):
            if row[i] is None:
                row[i] = {'t': '', 'hm': False, 'vm': False}
        grid.append(row)
    return grid

def _revisions(body):
    n = 0
    cells = 0
    paras = 0
    for tag in ('ins', 'del'):
        n += sum((1 for _ in body.iter(W + tag)))
    if not n:
        return {'revisions': 0, 'revised_cells': 0, 'revised_paras': 0}
    for tc in body.iter(W + 'tc'):
        if tc.find('.//' + W + 'ins') is not None or tc.find('.//' + W + 'del') is not None:
            cells += 1
    for p in body.findall(W + 'p'):
        if p.find('.//' + W + 'ins') is not None or p.find('.//' + W + 'del') is not None:
            paras += 1
    return {'revisions': n, 'revised_cells': cells, 'revised_paras': paras}

def parse_ex(path):
    z = zipfile.ZipFile(path)
    xml = z.read('word/document.xml')
    root = ET.fromstring(xml)
    body = root.find(W + 'body')
    blocks = []
    ti = 0
    for child in body:
        if child.tag == W + 'p':
            t = _text_of_p(child).strip()
            if t:
                blocks.append({'type': 'p', 'text': t})
        elif child.tag == W + 'tbl':
            blocks.append({'type': 'table', 'grid': parse_table(child), 'ti': ti})
            ti += 1
    return (blocks, _revisions(body))

def parse(path):
    return parse_ex(path)[0]
if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    blocks = parse(sys.argv[1])
    if len(sys.argv) > 2 and sys.argv[2] == '--json':
        print(json.dumps(blocks, ensure_ascii=False))
    else:
        for b in blocks:
            if b['type'] == 'p':
                print('P: ' + b['text'][:160])
            else:
                print('TABLE %dx%d' % (len(b['grid']), len(b['grid'][0]) if b['grid'] else 0))
                for r in b['grid'][:40]:
                    print('   | ' + ' | '.join((c['t'].replace('\n', '⏎')[:26] + ('·' if c['hm'] or c['vm'] else '') for c in r)))
