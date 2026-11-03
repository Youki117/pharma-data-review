import json
import os
from pathlib import Path
from folder_batch import scan_batches

def paths_from_event(event):
    files = event.get('dataTransfer', {}).get('files', [])
    if not files or any((not isinstance(file.get('pywebviewFullPath'), str) for file in files)):
        raise ValueError('未取得完整的本地路径，请重新拖入或使用浏览按钮。')
    return [file['pywebviewFullPath'] for file in files]

def classify_paths(paths, kind):
    if kind not in ('method', 'content', 'stability') or not isinstance(paths, list) or (not paths):
        raise ValueError('请选择有效的本地文件或文件夹。')
    if not all((isinstance(p, str) and Path(p).is_absolute() and Path(p).exists() for p in paths)):
        raise ValueError('拖入项目不存在或不是完整的本地路径。')
    selected = list(dict.fromkeys((str(Path(p).resolve()) for p in paths)))
    directories = [p for p in selected if Path(p).is_dir()]
    if directories:
        if len(selected) != 1:
            raise ValueError('请一次拖入一个文件夹；多批资料可拖入它们的共同上级目录。')
        folder = directories[0]
        if kind == 'stability':
            return {'ok': True, 'kind': 'folder', 'path': folder}
        plan = scan_batches(folder, kind, 'single')
        group = plan['groups'][0]
        direct_word = any((p.suffix.lower() == '.docx' for p in Path(folder).iterdir() if p.is_file()))
        child_count = sum((p.is_dir() for p in Path(folder).iterdir()))
        single = len(group['reports']) == 1 and len(group['workbooks']) == 1 if kind == 'method' else direct_word or child_count <= 1
        return {'ok': True, 'kind': 'folder', 'path': folder, 'mode': 'single' if single else 'subfolders', 'single_ready': single and (not group['blocking']), 'reports': group['reports'], 'workbooks': group['workbooks'], 'blocking': group['blocking']}
    if kind == 'stability':
        if any((Path(p).suffix.lower() not in ('.doc', '.docx') for p in selected)):
            raise ValueError('稳定性页面请拖入 Word 资料或资料文件夹。')
        return {'ok': True, 'kind': 'folder', 'path': os.path.commonpath([str(Path(p).parent) for p in selected]), 'notice': '已选择文件所在目录，请确认其中包含对应汇总表和报告单。'}
    if any((Path(p).suffix.lower() not in (('.docx', '.xlsx') if kind == 'method' else ('.docx',)) for p in selected)):
        raise ValueError('方法验证支持 .docx 与 .xlsx；内容一致性支持 .docx，请先转换其他格式。')
    reports = [p for p in selected if Path(p).suffix.lower() == '.docx']
    workbooks = [p for p in selected if Path(p).suffix.lower() == '.xlsx']
    if kind == 'method' and (len(reports) > 1 or len(workbooks) > 1):
        raise ValueError('一次请拖入唯一的一份 Word、一份 Excel，或分别拖入；多批请拖文件夹。')
    if kind == 'content' and len(reports) > 10:
        raise ValueError('内容核对每批最多 10 份 Word；请按相关主题分批导入。')
    return {'ok': True, 'kind': 'files', 'reports': reports, 'workbooks': workbooks}

def install_drop(window, callback):
    from webview.dom import DOMEventHandler
    window.dom.body.events.drop += DOMEventHandler(callback, prevent_default=True)
    window.evaluate_js('(() => {\n      function setup(win, task) {\n        const doc=win.document;if(!doc.body||doc.body.dataset.fileDropReady)return;\n        doc.body.dataset.fileDropReady=\'1\';\n        const hint=doc.createElement(\'div\');hint.textContent=\'释放以导入文件或文件夹\';\n        Object.assign(hint.style,{display:\'none\',position:\'fixed\',inset:\'8px\',zIndex:\'99999\',\n          background:\'#e4eef1ee\',border:\'3px dashed #1b5e70\',borderRadius:\'10px\',color:\'#1b5e70\',\n          alignItems:\'center\',justifyContent:\'center\',font:\'600 20px "Microsoft YaHei",sans-serif\',pointerEvents:\'none\'});\n        doc.body.append(hint);\n        doc.addEventListener(\'dragover\',e=>{if([...e.dataTransfer.types].includes(\'Files\')){e.preventDefault();e.dataTransfer.dropEffect=\'copy\';hint.style.display=\'flex\';}});\n        doc.addEventListener(\'dragleave\',e=>{if(!e.relatedTarget)hint.style.display=\'none\';});\n        doc.addEventListener(\'drop\',e=>{\n          e.preventDefault();hint.style.display=\'none\';if(win===window)return;\n          const files=[...e.dataTransfer.files];if(!files.length)return;\n          window.chrome.webview.postMessageWithAdditionalObjects(\'FilesDropped\',files);\n          window.pywebview._jsApiCallback(\'pywebviewEventHandler\',{nodeId:\'body\',event:{type:\'drop\',task,\n            dataTransfer:{files:files.map(f=>({name:f.name,size:f.size,type:f.type}))}}},\'eventHandler\');\n        });\n      }\n      setup(window,null);\n      for(const frame of document.querySelectorAll(\'iframe[id^="page-"]\')){\n        const task=frame.id.slice(5);frame.addEventListener(\'load\',()=>setup(frame.contentWindow,task));\n        setup(frame.contentWindow,task);\n      }\n    })()')

def deliver_drop(window, paths, kind, frame=False):
    try:
        result = classify_paths(paths, kind)
    except (ValueError, OSError) as error:
        result = {'ok': False, 'error': str(error) if isinstance(error, ValueError) else '拖入目录读取失败，请检查访问权限。'}
    target = "document.getElementById('page-" + kind + "').contentWindow" if frame else 'window'
    window.evaluate_js(target + '.receiveDroppedFiles(' + json.dumps(result, ensure_ascii=False) + ')')
