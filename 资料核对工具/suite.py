import json
import os
import sys
import threading
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT / '方法验证核对'), str(ROOT / '内容一致性核对'), str(ROOT)]
from updater import Updater, launch_installed, dispatch_helper
if __name__ == '__main__' and dispatch_helper('suite'):
    raise SystemExit(0)
from app import Api as MethodApi, DPI, webview
from content_app import ContentApi
from 本地对账工具 import app as stability_app
from folder_batch import BatchQueue
from drop_support import deliver_drop, install_drop, paths_from_event
NAME = '资料核对工具'
AI_METHODS = {'settings', 'configure', 'pick', 'start', 'stop', 'progress', 'results', 'evidence', 'open_source', 'open_report', 'open_output', 'scan_folder', 'start_batch', 'batch_status', 'select_batch', 'open_batch_report'}
STABILITY_METHODS = {'pick', 'start', 'version', 'progress', 'results', 'export', 'open_loc', 'reveal', 'quit'}

class SuiteApi:

    def __init__(self):
        self._tasks = {'method': MethodApi(), 'stability': stability_app.Api(), 'content': ContentApi()}
        self._settings_lock = threading.Lock()
        output = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / NAME / '结果'
        self._tasks['method']._output = str(output / '方法验证')
        self._tasks['content']._output = str(output / '内容一致性')
        self._batches = {name: BatchQueue(name, self._tasks[name]) for name in ('method', 'content')}
        self._updater = Updater('suite', self._busy)

    def _busy(self):
        return any((queue.busy() for queue in self._batches.values())) or any((task.progress()['stage'] in ('reading', 'ai', 'saving', 'convert', 'discover', 'running') for task in self._tasks.values()))

    def update_status(self):
        return self._updater.status()

    def check_updates(self):
        return self._updater.check()

    def install_update(self):
        with self._settings_lock:
            return self._updater.install()

    def _attach(self, window):
        self._window = window
        for name in ('method', 'content'):
            self._tasks[name]._window = window
        if hasattr(window, 'events'):
            window.events.loaded += lambda: install_drop(window, self._on_drop)

    def _on_drop(self, event):
        task = event.get('task') or self._window.evaluate_js("document.querySelector('[aria-selected=true]').dataset.task")
        if task not in self._tasks:
            return
        try:
            running = self._tasks[task].progress()['stage'] in ('reading', 'ai', 'saving', 'discover', 'running', 'convert')
            if running or (task in self._batches and self._batches[task].busy()):
                raise ValueError('请等待当前核对结束后再拖入资料。')
            paths = paths_from_event(event)
        except ValueError as error:
            target = "document.getElementById('page-" + task + "').contentWindow"
            self._window.evaluate_js(target + '.receiveDroppedFiles(' + json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False) + ')')
            return
        deliver_drop(self._window, paths, task, frame=True)

    def invoke(self, task, method, args):
        if not isinstance(task, str) or not isinstance(method, str) or (not isinstance(args, list)):
            return {'ok': False, 'error': '页面请求格式不正确。'}
        allowed = STABILITY_METHODS if task == 'stability' else AI_METHODS
        if task not in self._tasks or method not in allowed:
            return {'ok': False, 'error': '该页面接口不可用。'}
        if task in self._batches:
            queue = self._batches[task]
            batch_methods = {'scan_folder': queue.scan, 'start_batch': queue.start, 'batch_status': queue.status, 'select_batch': queue.select, 'open_batch_report': queue.open_summary}
            if method in batch_methods:
                try:
                    if method in ('scan_folder', 'start_batch', 'select_batch'):
                        with self._settings_lock:
                            if method == 'start_batch' and self._updater.installing():
                                return {'ok': False, 'error': '正在安装更新，请等待新版启动。'}
                            return batch_methods[method](*args)
                    return batch_methods[method](*args)
                except (TypeError, ValueError):
                    return {'ok': False, 'error': '批量请求参数不正确。'}
            if method == 'settings':
                return dict(self._tasks[task].settings(), batch_supported=True)
            if method == 'pick' and args == ['folder']:
                return self._tasks[task].pick('output')
        if method == 'configure':
            return self._configure(task, args)
        if method == 'start':
            with self._settings_lock:
                if self._updater.installing():
                    return {'ok': False, 'error': '正在安装更新，请等待新版启动。'}
                if task in self._batches and self._batches[task].busy():
                    return {'ok': False, 'error': '请等待本页批量任务结束后再开始单次核对。'}
                result = self._call(task, method, args)
                if task in self._batches and result.get('ok'):
                    self._batches[task].clear_selection()
                return result
        return self._call(task, method, args)

    def _call(self, task, method, args):
        try:
            return getattr(self._tasks[task], method)(*args)
        except (TypeError, ValueError):
            return {'ok': False, 'error': '请求参数不正确，请重新操作。'}

    def _configure(self, task, args):
        if len(args) != 1 or not isinstance(args[0], dict):
            return {'ok': False, 'error': '设置格式不正确。'}
        with self._settings_lock:
            if any((self._batches[name].busy() or self._tasks[name].progress()['stage'] in ('reading', 'ai', 'saving') for name in ('method', 'content'))):
                return {'ok': False, 'error': '请等待方法验证和内容核对结束后再修改共用 AI 设置。'}
            result = self._tasks[task].configure(args[0])
            if not result['ok']:
                return result
            other = self._tasks['content' if task == 'method' else 'method']
            values = dict(args[0], output=other.settings()['output'])
            other.configure(values)
            return result

    def close(self):
        for name in ('method', 'content'):
            self._tasks[name].close()

def render_shell():
    frozen = getattr(sys, '_MEIPASS', None)
    assets = Path(frozen) if frozen else HERE
    pages = {}
    for name, source in [('method', ROOT / '方法验证核对' / 'ui.html'), ('stability', ROOT / '本地对账工具' / 'ui.html'), ('content', ROOT / '方法验证核对' / 'ui.html')]:
        path = assets / 'pages' / name / 'ui.html' if frozen else source
        html = path.read_text(encoding='utf-8')
        bridge = "<script>\ndocument.documentElement.classList.add('embedded');\nwindow.pywebview={api:new Proxy({}, {get:(_,method)=>(...args)=>parent.pywebview.api.invoke(TASK,method,args)})};\nwindow.addEventListener('suiteactivate',async()=>{\n  if(typeof updateSettings==='function'){\n    try{updateSettings(await window.pywebview.api.settings());}\n    catch(e){error('共用设置读取失败，请重新打开工具。');}\n  }\n});\n</script>".replace('TASK', json.dumps(name))
        if name == 'stability':
            bridge += "<script>window.receiveDroppedFiles=function(result){\n              if(!result.ok){const error=document.getElementById('err');error.textContent=result.error;error.hidden=false;return;}\n              const input=document.getElementById('path');input.value=result.path;input.dispatchEvent(new Event('input'));\n              let note=document.getElementById('dropNotice');if(!note){note=document.createElement('span');note.id='dropNotice';note.style.cssText='font-size:12px;color:var(--muted)';document.querySelector('header').append(note);}\n              note.textContent='目录已导入';note.title=result.notice||'资料目录已导入，点击开始核对。';\n            };</script>"
        if '<script>' not in html:
            raise ValueError('页面缺少初始化脚本：' + name)
        pages[name] = html.replace('<script>', bridge + '<script>', 1)
    shell = (assets / 'shell.html').read_text(encoding='utf-8')
    return shell.replace('__PAGES__', json.dumps(pages, ensure_ascii=False).replace('<', '\\u003c'))

def place(window):
    try:
        screen = webview.screens[0]
        sw, sh = (screen.width / DPI, screen.height / DPI)
        width, height = (min(1280, int(sw * 0.85)), min(880, int(sh * 0.88)))
        window.resize(width, height)
        window.move(max(0, int((sw - width) / 2)), max(0, int((sh - height) / 2) - 20))
    except (IndexError, AttributeError):
        pass

def main():
    if launch_installed('suite'):
        return
    api = SuiteApi()
    window = webview.create_window(NAME, html=render_shell(), js_api=api, width=1280, height=880, min_size=(760, 620), background_color='#F4F6F7')
    api._attach(window)
    api._updater.attach(window)
    window.events.closed += api.close
    webview.start(place, window)
if __name__ == '__main__':
    main()
