import html
import json
from datetime import datetime
from pathlib import Path

def esc(value):
    return html.escape(str(value), quote=True)

def write_report(result, output_dir):
    folder = Path(output_dir) / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder.mkdir(parents=True, exist_ok=False)
    blocks = []
    for side, source in result['sources'].items():
        items = []
        for ref, item in source['index'].items():
            location = item.get('document', '') + ' ' + item.get('sheet', '') + ' ' + item.get('address', '')
            items.append(f'''<div class="source" id="{esc(ref)}"><b>{esc(ref)} {esc(location)}</b><pre>{esc(item['text'])}</pre></div>''')
        blocks.append(f"<details><summary>{esc(source['name'])} · 原文索引</summary>{''.join(items)}</details>")
    sections = []
    for level, color in (('必看', 'red'), ('需确认', 'amber'), ('可选查看', 'gray')):
        cards = []
        for item in result['issues']:
            if item['level'] != level:
                continue
            refs = list(dict.fromkeys([item['report_ref'], item['excel_ref']] + item['related_report_refs']))
            links = ' '.join((f'<a href="#{esc(ref)}" onclick="openSource(this)">{esc(ref)}</a>' for ref in refs if ref))
            cards.append(f"""<article><h3>{esc(item['id'])} · {esc(item['title'])}</h3>\n<p>{esc(item['reason'])}</p><p class="muted">{esc(item['verification'])} · {esc(item['source'])}</p>\n<details><summary>查看证据与定位（{len(refs)} 处）</summary>\n<div class="pair"><div><b>{esc(result.get('left_label', '报告摘录'))}</b><pre>{esc(item['report_quote'])}</pre></div>\n<div><b>{esc(result.get('right_label', '计算表摘录'))}</b><pre>{esc(item['excel_quote'] or '尚无明确对应证据')}</pre></div></div><p>{links}</p></details></article>""")
        content = ''.join(cards) or '<p class="muted">本档暂无条目。</p>'
        body = f'''<section class="{color}"><h2>{level} · {result['counts'][level]} 件</h2>{content}</section>'''
        sections.append(f"<details><summary>可选查看 · {result['counts'][level]} 件</summary>{body}</details>" if level == '可选查看' else body)
    warnings = ''.join((f'<li>{esc(x)}</li>' for x in result['warnings']))
    incomplete = result['status'] == 'AI复核未完成'
    status = '<div class="incomplete">AI 复核未完成：当前结果仅供查看已筛选的候选，请补充完成复核。</div>' if incomplete else ''
    if result['status'] == '本地筛选完成':
        status = '<p class="muted">本次已完成本地筛选，未调用 AI。未筛出候选不代表完整审核通过。</p>'
    title = esc(result.get('title', '方法验证资料核对'))
    inputs = esc(result.get('input_label', result['report_name'] + ' ↔ ' + result['workbook_name']))
    coverage = esc(result.get('coverage_summary', f"报告 {result['report_tables']} 张表；计算表 {len(result['sheets'])} 个工作表；代码筛选 {result['checked_numbers']} 个数值，合并为 {result['candidate_count']} 件候选。"))
    grading = '内容推断按需确认与可选查看分级；引用存在不代表语义判断成立。' if result.get('kind') == 'content' else '必看为代码确认的同字段表格差异；需确认为有证据的复核事项；可选查看保留弱线索与口径解释。引用存在不代表语义判断成立。'
    text = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>\n<style>body{{font:16px/1.65 "Microsoft YaHei",sans-serif;color:#243344;background:#f3f5f7;margin:0}}main{{max-width:1060px;margin:auto;padding:32px 24px}}h1{{font-size:28px}}h2{{font-size:22px}}h3{{font-size:17px;margin:0}}section,body>details,main>details{{background:white;border-radius:10px;padding:18px 22px;margin:18px 0}}article{{border-top:1px solid #e1e6ea;padding:16px 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 "Microsoft YaHei",sans-serif;background:#f4f6f8;padding:12px;border-radius:6px}}summary{{cursor:pointer;font-weight:600}}a{{color:#175eac;margin-right:10px}}.muted{{color:#627182;font-size:14px}}.red{{border-left:5px solid #c35050}}.amber{{border-left:5px solid #d0a046}}.gray{{border-left:5px solid #9aa7b3}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.source{{scroll-margin:20px;border-bottom:1px solid #ddd;padding:12px}}.source:target{{background:#fff1b9}}.incomplete{{padding:14px;background:#ffebcf;color:#7b3e08;font-weight:bold}}@media(max-width:700px){{.pair{{grid-template-columns:1fr}}main{{padding:15px}}}}</style>\n</head><body><main><h1>{title}</h1><p>{inputs}</p>{status}\n<p><b>{esc(result['status'])}</b> · 模型 {esc(result['model'])} · 必看 {result['counts']['必看']} 件 / 需确认 {result['counts']['需确认']} 件 / 可选查看 {result['counts']['可选查看']} 件</p>\n<p class="muted">{grading}</p>\n{''.join(sections)}<section><h2>覆盖情况</h2><p>{coverage}</p><ul>{warnings}</ul></section>\n<details><summary>原文索引 · 点击问题定位可展开对应原文</summary>{''.join(blocks)}</details>\n<p class="muted">结果用于人工复核。原始资料保持原样；本报告保存在本机。</p></main>\n<script>function openSource(link){{const el=document.getElementById(link.hash.slice(1));if(!el)return;for(let p=el.parentElement;p;p=p.parentElement){{if(p.tagName==='DETAILS')p.open=true;}}}}</script></body></html>"""
    destination = folder / '核对报告.html'
    destination.write_text(text, encoding='utf-8')
    (folder / '核对结果.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return destination
