import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
METHOD = Path(__file__).resolve().parents[1] / '方法验证核对'
sys.path.append(str(METHOD))
from core import norm, read_report
LABELS = ('包装', '包材', '内包材', '外包材', '包装形式', '包装规格', '规格', '剂型', '生产商', '生产企业', '生产厂家', '供应商', '厂家', '来源', '批号', '产品批号', '样品批号', '版本号', '贮藏', '贮存条件', '储存条件', '有效期', '装量', '批量', '检验依据', '执行标准', '质量标准', '溶剂', '稀释剂', '流动相', '检测波长', '柱温', '流速', '进样量', '进样体积', '色谱柱')
PRODUCT_LABELS = ('品名', '产品名称', '药品名称', '样品名称')
ENTITY = re.compile('杂质\\s*[A-Za-z](?![A-Za-z\\d])|(?:SM\\d+|AJHS(?:-\\d+)?)-IMP\\d+', re.I)
NUMBERS = re.compile('\\d+(?:\\.\\d+)?')

def entities(text):
    return tuple(sorted(set((norm(x).upper() for x in ENTITY.findall(text)))))

def clean_label(text):
    return norm(text).strip(':：')

def paragraph_body(text):
    return re.sub('^\\s*(?:\\d{1,2}[、．]|\\d{1,2}\\.(?!\\d)|[（(]\\d{1,2}[)）])\\s*', '', text)

def label_value(text):
    return norm(text).strip('（）()，,、；;。').replace('：', ':').replace('ml', 'mL')

def prepare_content(paths):
    if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= 10:
        raise ValueError('请选择 1～10 份 .docx 资料。')
    documents, index, warnings, blocking, canonical = ([], {}, [], [], set())
    paragraphs, tables = (0, 0)
    for path in paths:
        if not isinstance(path, str):
            raise ValueError('资料路径格式不正确。')
        file = Path(path).resolve()
        if file in canonical:
            warnings.append(f'重复选择的同一文件已合并：{file.name}')
            continue
        canonical.add(file)
        try:
            document = read_report(file)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError):
            blocking.append(f'未能读取「{file.name}」；请检查文件是否为有效的 .docx，或是否为扫描资料。')
            continue
        doc_id = f'D{len(documents) + 1:03}'
        local = document['index']
        product_values = set()
        for ref, cell in local.items():
            if cell['kind'] == 'report_cell' and clean_label(cell['text']) in PRODUCT_LABELS:
                next_ref = re.sub('C\\d+$', f"C{cell['col'] + 1:03}", ref)
                value = local.get(next_ref, {}).get('text', '').strip()
                if value and clean_label(value) not in PRODUCT_LABELS:
                    product_values.add(norm(value))
        product = next(iter(product_values)) if len(product_values) == 1 else ''
        subject = ()
        for ref, source in local.items():
            item = dict(source)
            own = entities(item['text'])
            if item['kind'] == 'paragraph' and own:
                subject = own
            item.update(document=document['name'], path=document['path'], doc_id=doc_id, product=product, subject=own or subject, local_ref=ref)
            index[doc_id + '-' + ref] = item
        text = re.sub('\\[((?:P\\d{4}|T\\d{4})(?:-R\\d{3})?(?:-C\\d{3})?)\\]', lambda m: '[' + doc_id + '-' + m[1] + ']', document['text'])
        documents.append({'id': doc_id, 'name': document['name'], 'path': document['path'], 'product': product, 'text': text})
        paragraphs += document['paragraphs']
        tables += document['tables']
        warnings.extend((f"{document['name']}：{w}" for w in document['warnings'] if not w.startswith('未识别出标准验证模块标题')))
    if not documents:
        raise ValueError('所选资料均未能读取。\n' + '\n'.join(blocking))
    for i, doc in enumerate(documents):
        for other in documents[:i]:
            a = re.sub('\\[D\\d+-', '[', doc['text'])
            b = re.sub('\\[D\\d+-', '[', other['text'])
            if a == b:
                warnings.append(f"「{doc['name']}」与「{other['name']}」正文相同，仍保留各自定位；图片和公式内容需另行核实。")
    text = '\n\n'.join((f"【资料 {d['id']}：{d['name']}】\n{d['text']}" for d in documents))
    if len(text) > 600000:
        blocking.append('整组资料超过单次 60 万字符范围；未发送 AI，请按相关业务主题拆分资料。')
    candidates = screen_content(index)
    return {'documents': documents, 'index': index, 'text': text, 'candidates': candidates, 'warnings': warnings, 'blocking': blocking, 'paragraph_count': paragraphs, 'table_count': tables, 'block_count': paragraphs + tables}

def screen_content(index):
    candidates = []
    labels = {}
    pattern = re.compile('(?:^|[\\s，,；;、（(])(' + '|'.join(sorted(LABELS, key=len, reverse=True)) + ')\\s*[:：为]\\s*([^\\n；;。]{1,100})')
    for ref, item in index.items():
        values = []
        if item['kind'] == 'paragraph':
            values = [(m[1], m[2].strip(), ref) for m in pattern.finditer(item['text'])]
        elif item['kind'] == 'report_cell' and clean_label(item['text']) in LABELS:
            next_ref = re.sub('C\\d+$', f"C{item['col'] + 1:03}", ref)
            value = index.get(next_ref, {}).get('text', '').strip()
            if value and clean_label(value) not in LABELS and (len(value) <= 100):
                values = [(clean_label(item['text']), value, next_ref)]
        for label, value, location in values:
            scope = (item['product'] or item['doc_id'], item['subject'], label)
            labels.setdefault(scope, []).append((label_value(value), location, value))
    for (owner, subject, label), values in labels.items():
        unique = {value for value, ref, raw in values}
        if len(unique) < 2:
            continue
        refs = list(dict.fromkeys((ref for value, ref, raw in values)))
        table_only = all((index[ref]['kind'] == 'report_cell' for ref in refs))
        if table_only:
            continue
        candidates.append({'type': '同名字段取值不同', 'title': f'「{label}」出现不同取值', 'refs': refs, 'module': '字段与口径', 'numeric': False, 'reason': '同一主体下的同名字段取值不同；需排除记录、条件或版本不同的正常差异。'})
    paragraphs = [(ref, item) for ref, item in index.items() if item['kind'] == 'paragraph' and 30 <= len(item['text']) <= 1600]
    bodies = [paragraph_body(item['text']) for ref, item in paragraphs]
    shingles = [set((norm(text)[i:i + 3] for i in range(max(0, len(norm(text)) - 2)))) for text in bodies]
    parents = list(range(len(paragraphs)))
    numeric_groups = set()

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for i, (ref, left) in enumerate(paragraphs):
        for j in range(i):
            right = paragraphs[j][1]
            if left['doc_id'] != right['doc_id'] and (not (left['product'] and left['product'] == right['product'])):
                continue
            if left['subject'] and right['subject'] and (left['subject'] != right['subject']):
                continue
            a, b = (shingles[i], shingles[j])
            if not a or not b or a == b:
                continue
            if min(len(a), len(b)) / max(len(a), len(b)) < 0.72:
                continue
            overlap = len(a & b) / len(a | b)
            if overlap < 0.72:
                continue
            parents[root(i)] = root(j)
            if NUMBERS.findall(bodies[i]) != NUMBERS.findall(bodies[j]):
                numeric_groups.update((i, j))
    groups = {}
    for i, (ref, item) in enumerate(paragraphs):
        groups.setdefault(root(i), []).append(i)
    for group in groups.values():
        if len(group) < 2:
            continue
        numeric = any((i in numeric_groups for i in group))
        refs = [paragraphs[i][0] for i in group]
        candidates.append({'type': '相似段落数值差异' if numeric else '相似段落措辞差异', 'title': '相似段落中的数值不同' if numeric else '相似段落的表述需复核', 'refs': refs, 'module': '段落与总结', 'numeric': numeric, 'reason': '段落高度相似但内容不同，可能涉及复制后未改完整；需结合对象和上下文确认。'})
    candidates.sort(key=lambda c: not c['numeric'])
    for number, item in enumerate(candidates, 1):
        item['id'] = f'C{number:03}'
        item['quotes'] = [index[ref]['text'] for ref in item['refs']]
    return candidates
