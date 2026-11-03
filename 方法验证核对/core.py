import re
import sys
import zipfile
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from xml.etree import ElementTree as ET
sys.path.append(str(Path(__file__).resolve().parents[1] / '本地对账工具'))
import docxgrid
S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
MODULES = ('系统适用性', '专属性', '溶液稳定性', '线性与范围', '检测限与定量限', '精密度', '准确度', '耐用性')
NUMBER = re.compile('(?<![0-9A-Za-z_.])(\\d+(?:\\.\\d+)?(?:[Ee][+-]?\\d+)?)(\\s*[%％])?')
IDENTITY = re.compile('批号|编号|货号|文件号|分子式|CAS|日期|版本|仪器|色谱柱|厂家|供应商|来源|型号')
NOMINAL = re.compile('浓度等级|约相当于|理论浓度|设计浓度')
STANDARD = re.compile('可接受标准|接受标准|应不|不得|不低于|不高于|不小于|不大于|应符合')
CAP_SKIP = re.compile('方法开发历程|研究策略|试剂信息|试药|试剂|仪器|用具|供试品信息|对照品信息|基本信息|梯度|结构式|修订|方案|色谱系统和参数')
ALIASES = (('系统适用性', '系统适应性'), ('专属性',), ('溶液稳定性', '溶液的稳定性', '稳定性'), ('线性与范围', '线性和范围', '线性范围', '线性'), ('检测限与定量限', '检测限和定量限', '定量限和检测限', '定量限与检测限', '检测限', '定量限'), ('精密度', '重复性及中间精密度', '重复性和中间精密度', '重复性', '中间精密度'), ('准确度', '回收率'), ('耐用性', '耐用性研究'))

def clean_heading(text):
    return norm(re.sub('^[\\d.、\\s一二三四五六七八九十（）()]+', '', text))

def norm(text):
    return re.sub('\\s+', '', str(text)).replace('％', '%')

def column_number(label):
    n = 0
    for char in label:
        n = n * 26 + ord(char) - 64
    return n

def column_name(number):
    value = ''
    while number:
        number, digit = divmod(number - 1, 26)
        value = chr(65 + digit) + value
    return value

def numeric(text):
    value = norm(text)
    if not re.fullmatch('[+-]?\\d+(?:\\.\\d+)?(?:[Ee][+-]?\\d+)?%?', value):
        return None
    try:
        return Decimal(value.rstrip('%')) / (100 if value.endswith('%') else 1)
    except InvalidOperation:
        return None

def module_name(text):
    for pattern, module in (('系统适[用应]性', '系统适用性'), ('专属性', '专属性'), ('溶液.{0,2}稳定性|溶稳', '溶液稳定性'), ('线性', '线性与范围'), ('检测限|定量限|LOQ|LOD', '检测限与定量限'), ('精密度|重复性', '精密度'), ('准确度|回收率', '准确度'), ('耐用性', '耐用性')):
        if re.search(pattern, text, re.I):
            return module
    return '公共与总结'

def read_report(path):
    if Path(path).suffix.lower() != '.docx':
        raise ValueError('报告请使用 .docx；.doc、PDF 请先转换并检查排版。')
    with zipfile.ZipFile(path) as archive:
        if archive.getinfo('word/document.xml').file_size > 50000000:
            raise ValueError('报告正文超过本版读取范围。')
        document = ET.fromstring(archive.read('word/document.xml'))
    body = document.find(docxgrid.W + 'body')
    if body is None:
        raise ValueError('报告缺少 Word 正文。')
    nested_tables = len(list(body.iter(docxgrid.W + 'tbl'))) - len(body.findall(docxgrid.W + 'tbl'))
    figures = len(list(body.iter(docxgrid.W + 'drawing'))) + len(list(body.iter(docxgrid.W + 'pict')))
    equations = len(list(body.iter('{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath')))
    blocks, info = docxgrid.parse_ex(path)
    index, texts, module = ({}, [], '公共与总结')
    heads, cursor = ({}, len(blocks))
    for key, aliases in reversed(list(zip(MODULES, ALIASES))):
        for position in range(cursor - 1, -1, -1):
            block = blocks[position]
            if block['type'] == 'p' and clean_heading(block['text']) in aliases:
                heads[position], cursor = (key, position)
                break
    first_module = min(heads, default=len(blocks))
    caption = ''
    paragraph = table = 0
    for position, block in enumerate(blocks):
        if position in heads:
            module = heads[position]
        if block['type'] == 'p':
            paragraph += 1
            ref, text = (f'P{paragraph:04}', block['text'])
            if re.match('^表\\s*\\d+', text) and len(text) < 100:
                caption = text
            elif len(text) > 100:
                caption = ''
            index[ref] = {'text': text, 'kind': 'paragraph', 'module': module}
            texts.append(f'[{ref}] {text}')
            continue
        table += 1
        rows = [[c['t'] for c in row] for row in block['grid']]
        header_rows = 0
        for row in rows[:3]:
            if any((len(c) > 30 or numeric(c) is not None for c in row if c)):
                break
            header_rows += 1
        header_rows = max(1, header_rows)
        table_ref = f'T{table:04}'
        row_texts = []
        for ri, row in enumerate(rows, 1):
            row_ref = f'{table_ref}-R{ri:03}'
            text = ' | '.join((f'{column_name(ci)}: {cell}' for ci, cell in enumerate(row, 1)))
            index[row_ref] = {'text': text, 'kind': 'report_row', 'module': module}
            row_texts.append(f'[{row_ref}] {text}')
            for ci, cell in enumerate(row, 1):
                if not cell:
                    continue
                ref = f'{row_ref}-C{ci:03}'
                header = ' '.join((r[ci - 1] for r in rows[:header_rows]))
                owner = module
                if position < first_module:
                    owner = module_name(row[0])
                skip = bool(CAP_SKIP.search(caption)) or (position < first_module and (not re.search('汇总|总结', caption)))
                index[ref] = {'text': cell, 'kind': 'report_cell', 'module': owner, 'label': row[0], 'field': header, 'row': ri, 'col': ci, 'context': text, 'table': table_ref, 'skip_screen': skip or ri <= header_rows}
        text = '\n'.join(row_texts)
        index[table_ref] = {'text': text, 'kind': 'report_table', 'module': module}
        texts.append(f'[{table_ref}] 表格 {table}\n{text}')
        caption = ''
    if not texts:
        raise ValueError('报告没有可读取的正文或表格，请检查是否为扫描文档。')
    warnings = []
    if nested_tables:
        warnings.append(f'报告有 {nested_tables} 张嵌套表格未展开读取，需人工核对。')
    if figures or equations:
        warnings.append(f'报告含 {figures} 个图片/绘图对象、{equations} 个公式对象；未识别其中的图像或公式内容，需人工核对。')
    if not heads:
        warnings.append('未识别出标准验证模块标题，整份报告仍送交 AI 复核，模块归属需人工判断。')
    if info['revisions']:
        warnings.append(f"报告含 {info['revisions']} 处未接受的修订；本次按接受修订后的文字读取。")
    return {'name': Path(path).name, 'path': str(Path(path).resolve()), 'index': index, 'text': '\n'.join(texts), 'tables': table, 'paragraphs': paragraph, 'warnings': warnings}

def read_workbook(path):
    if Path(path).suffix.lower() != '.xlsx':
        raise ValueError('计算表请使用 .xlsx；旧版 .xls 请先另存为 .xlsx。')
    sheets, index, warnings, formula_count, missing = ([], {}, [], 0, 0)
    with zipfile.ZipFile(path) as archive:
        xmls = [x for x in archive.infolist() if x.filename.startswith('xl/') and x.filename.endswith('.xml')]
        if sum((x.file_size for x in xmls)) > 200000000:
            raise ValueError('计算表解压后内容过大，超过本版读取范围。')
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings = [''.join((t.text or '' for t in si.iter(S + 't'))) for si in root]
        percent_styles = set()
        if 'xl/styles.xml' in archive.namelist():
            styles = ET.fromstring(archive.read('xl/styles.xml'))
            formats = {int(n.get('numFmtId')): n.get('formatCode', '') for n in styles.findall(S + 'numFmts/' + S + 'numFmt')}
            for i, xf in enumerate(styles.findall(S + 'cellXfs/' + S + 'xf')):
                fmt = int(xf.get('numFmtId', 0))
                code = re.sub('"[^"]*"|\\\\.', '', formats.get(fmt, ''))
                if fmt in (9, 10) or '%' in code:
                    percent_styles.add(i)
        rels = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        targets = {r.get('Id'): r.get('Target') for r in rels}
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        for si, sheet in enumerate(workbook.findall(S + 'sheets/' + S + 'sheet'), 1):
            name = sheet.get('name', '')
            target = targets[sheet.get(R + 'id')]
            member = target.lstrip('/') if target.startswith('/') else 'xl/' + target
            root = ET.fromstring(archive.read(member))
            cells, row_map = ([], {})
            for c in root.iter(S + 'c'):
                address, kind = (c.get('r'), c.get('t'))
                value = c.findtext(S + 'v', '')
                formula = c.find(S + 'f') is not None
                formula_count += int(formula)
                if formula and value == '':
                    missing += 1
                if kind == 's':
                    value = strings[int(value)] if value else ''
                elif kind == 'inlineStr':
                    value = ''.join((t.text or '' for t in c.iter(S + 't')))
                if not value and (not formula):
                    continue
                if not address or not re.fullmatch('[A-Z]+[1-9]\\d*', address):
                    raise ValueError(f'工作表 {name} 有无法定位的单元格。')
                raw = value
                if kind not in ('s', 'inlineStr', 'str', 'e', 'b') and value:
                    try:
                        number = Decimal(value)
                        percent = int(c.get('s', 0)) in percent_styles
                        if percent:
                            number *= 100
                        value = format(Decimal(format(number, '.15g')).normalize(), 'f') + ('%' if percent else '')
                    except InvalidOperation:
                        raise ValueError(f'工作表 {name} 的 {address} 数值无法读取。') from None
                ref = f'X{si:03}-{address}'
                item = {'text': value or '（公式无缓存值）', 'raw': raw, 'kind': 'excel_cell', 'sheet': name, 'address': address, 'formula': formula, 'module': module_name(name), 'ref': ref}
                index[ref] = item
                cells.append(item)
                row = int(re.search('\\d+', address)[0])
                row_map.setdefault(row, []).append(item)
            lines = []
            for row, items in row_map.items():
                items.sort(key=lambda c: column_number(re.match('[A-Z]+', c['address'])[0]))
                label = items[0]['text']
                for item in items:
                    item['label'] = label
                    col = re.match('[A-Z]+', item['address'])[0]
                    item['field'] = index.get(f'X{si:03}-{col}1', {}).get('text', '')
                line = ' | '.join((f"[{c['ref']}] {c['text']}" for c in items))
                lines.append(line)
            if not cells:
                warnings.append(f'工作表「{name}」无可读取的单元格。')
            merges = [c.get('ref', '') for c in root.findall(S + 'mergeCells/' + S + 'mergeCell')]
            prefix = '合并区域：' + '、'.join(merges) + '\n' if merges else ''
            sheets.append({'name': name, 'text': prefix + '\n'.join(lines), 'cells': len(cells)})
    if not index:
        raise ValueError('计算表未读到任何单元格，不能进行核对。')
    if missing:
        warnings.append(f'{missing} 个公式单元格没有缓存值，未参与数值筛选；请用 Excel 重算保存后再核对。')
    if formula_count:
        warnings.append(f'读取了 {formula_count} 个公式的缓存结果；本工具不执行 Excel 公式重算。')
    return {'name': Path(path).name, 'path': str(Path(path).resolve()), 'index': index, 'sheets': sheets, 'text': '\n\n'.join((f"工作表：{s['name']}\n{s['text']}" for s in sheets)), 'formulas': formula_count, 'missing_cache': missing, 'warnings': warnings}

def screen(report, workbook):
    values = []
    for cell in workbook['index'].values():
        for match in NUMBER.finditer(cell['text']):
            values.append(Decimal(match[1]) / (100 if match[2] else 1))
    pools = {}
    for precision in range(11):
        step = Decimal(1).scaleb(-precision)
        pools[precision] = {v.quantize(step, rounding=ROUND_HALF_UP) for v in values if abs(v) < Decimal('1e20')}
    thresholds = set()
    for cell in report['index'].values():
        if cell['kind'] == 'report_cell' and '接受标准' in cell.get('field', '') or (cell['kind'] == 'paragraph' and STANDARD.search(cell['text']) and (len(cell['text']) < 150)):
            thresholds.update((Decimal(m[1]) for m in NUMBER.finditer(cell['text'])))
    candidates, groups, checked = ([], {}, 0)
    for ref, cell in report['index'].items():
        if cell['kind'] not in ('report_cell', 'paragraph'):
            continue
        text = cell['text']
        if cell.get('skip_screen'):
            continue
        if cell['kind'] == 'paragraph' and (not re.match('^(结论|综上|以上结果|结果与结论)', text)):
            continue
        context = cell.get('label', '') + ' ' + cell.get('field', '')
        if IDENTITY.search(context) or NOMINAL.search(context) or '接受标准' in context:
            continue
        screened = re.sub('\\d{4}[.\\-/]\\d{1,2}[.\\-/]\\d{1,2}', ' ', text)
        screened = re.sub('\\b[A-Za-z][A-Za-z0-9_-]*(?:[-/]\\d+)+\\b', ' ', screened)
        screened = re.sub('(?:大于|小于|不低于|不高于|不小于|不大于|不得过|应在|[＜＞<>≤≥])\\s*\\d+(?:\\.\\d+)?[%％]?(?:[~～\\-]\\d+(?:\\.\\d+)?[%％]?)?', ' ', screened)
        for match in NUMBER.finditer(screened):
            raw, pct = (match[1], bool(match[2]) or '%' in context or '％' in context)
            if re.fullmatch('\\d{1,2}|\\d{5,}', raw):
                continue
            value = Decimal(raw)
            if value in thresholds:
                continue
            precision = min(max(0, -value.as_tuple().exponent), 10)
            checked += 1
            step = Decimal(1).scaleb(-precision)
            exists = value.quantize(step, rounding=ROUND_HALF_UP) in pools[precision]
            if pct:
                p = min(precision + 2, 10)
                exists |= (value / 100).quantize(Decimal(1).scaleb(-p), rounding=ROUND_HALF_UP) in pools[p]
            if exists:
                continue
            key = (cell['module'], raw, pct)
            if key not in groups:
                candidate = {'id': f'C{len(candidates) + 1:03}', 'module': cell['module'], 'value': raw + ('%' if pct else ''), 'refs': [], 'quotes': [], 'reason': '按显示精度在计算表中未找到该数值，需结合取值口径和来源复核。'}
                candidates.append(candidate)
                groups[key] = candidate
            candidate = groups[key]
            candidate['refs'].append(ref)
            candidate['quotes'].append(text)
    return (candidates, checked)

def prepare(report_path, workbook_path):
    report, workbook = (read_report(report_path), read_workbook(workbook_path))
    candidates, checked = screen(report, workbook)
    if len(report['text']) + len(workbook['text']) > 600000:
        raise ValueError('本组资料超过单次核对范围（60万字符），请按验证模块拆分后核对。')
    warnings = report['warnings'] + workbook['warnings']
    warnings.append('数值筛选覆盖结果表格与结论段中的小数及部分整数；数值能找到不代表对应关系正确，AI 仍核对全部提供内容。')
    return {'report': report, 'workbook': workbook, 'candidates': candidates, 'checked': checked, 'warnings': warnings}
