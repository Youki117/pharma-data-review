import json
import os
import sys
import threading
import webbrowser
from pathlib import Path
BASE = Path(__file__).resolve().parent
sys.path.append(str(BASE.parent / '资料核对工具'))
from updater import VERSION, Updater, launch_installed, dispatch_helper
if __name__ == '__main__' and dispatch_helper('method'):
    raise SystemExit(0)
from ai import Cancelled, DEFAULT_BASE, DEFAULT_MODEL, assemble, request_review
from core import prepare
from report import write_report

def dpi_scale():
    if sys.platform != 'win32':
        return 1.0
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except OSError:
        ctypes.windll.user32.SetProcessDPIAware()
    try:
        return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
    except AttributeError:
        return 1.0
DPI = dpi_scale()
import webview
from drop_support import deliver_drop, install_drop, paths_from_event

def resource(name):
    return str(Path(getattr(sys, '_MEIPASS', BASE)) / name)

class Api:

    def __init__(self):
        self._window = None
        self._lock, self._cancel = (threading.RLock(), threading.Event())
        self._updater = None
        self._key = os.environ.get('DEEPSEEK_API_KEY', '')
        self._base = os.environ.get('DEEPSEEK_BASE_URL', DEFAULT_BASE)
        self._model = os.environ.get('DEEPSEEK_MODEL', DEFAULT_MODEL)
        self._output = str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / '方法验证核对' / '结果')
        self._state = {'stage': 'idle', 'message': '', 'error': '', 'revision': 0, 'stats': {}}
        self._result, self._report_file = (None, None)

    def _attach(self, window):
        self._window = window
        window.events.loaded += lambda: install_drop(window, self._on_drop)

    def _on_drop(self, event):
        kind = self.settings().get('kind', 'method')
        try:
            if self.progress()['stage'] in ('reading', 'ai', 'saving'):
                raise ValueError('请等待当前核对结束后再拖入资料。')
            paths = paths_from_event(event)
        except ValueError as error:
            self._window.evaluate_js('receiveDroppedFiles(' + json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False) + ')')
            return
        deliver_drop(self._window, paths, kind)

    def settings(self):
        return {'base': self._base, 'model': self._model, 'output': self._output, 'has_key': bool(self._key), 'version': VERSION}

    def _enable_updates(self, product, window):
        self._updater = Updater(product, lambda: self.progress()['stage'] in ('reading', 'ai', 'saving'))
        self._updater.attach(window)

    def update_status(self):
        return self._updater.status()

    def guide_status(self):
        return self._updater.guide_status()

    def guide_complete(self):
        return self._updater.guide_complete()

    def check_updates(self):
        return self._updater.check()

    def install_update(self):
        with self._lock:
            return self._updater.install()

    def configure(self, values):
        if not isinstance(values, dict) or not all((isinstance(values.get(k, ''), str) for k in ('base', 'model', 'output', 'key'))):
            return {'ok': False, 'error': '设置格式不正确。'}
        with self._lock:
            if self._state['stage'] in ('reading', 'ai', 'saving'):
                return {'ok': False, 'error': '请等待本次核对结束后再修改设置。'}
            base, model, output = (values.get(k, '').strip() for k in ('base', 'model', 'output'))
            if not output or not isinstance(values.get('clear_key', False), bool):
                return {'ok': False, 'error': '请填写结果文件夹，并检查密钥设置。'}
            self._base, self._model, self._output = (base or DEFAULT_BASE, model or DEFAULT_MODEL, output)
            if values.get('clear_key'):
                self._key = ''
            elif values.get('key', '').strip():
                self._key = values['key'].strip()
        return {'ok': True, 'has_key': bool(self._key)}

    def pick(self, kind):
        if not self._window:
            return {'path': ''}
        if kind == 'output':
            selected = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        elif kind in ('report', 'workbook'):
            file_type = 'Word 报告 (*.docx)' if kind == 'report' else 'Excel 计算表 (*.xlsx)'
            selected = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False, file_types=(file_type,))
        else:
            return {'path': ''}
        return {'path': str(selected[0]) if selected else ''}

    def start(self, report, workbook):
        if not all((isinstance(p, str) and Path(p).is_file() for p in (report, workbook))):
            return {'ok': False, 'error': '请选择有效的报告和计算表。'}
        if Path(report).suffix.lower() != '.docx' or Path(workbook).suffix.lower() != '.xlsx':
            return {'ok': False, 'error': '报告需使用 .docx，计算表需使用 .xlsx。'}
        with self._lock:
            if self._updater and self._updater.installing():
                return {'ok': False, 'error': '正在安装更新，请等待新版启动。'}
            if self._state['stage'] in ('reading', 'ai', 'saving'):
                return {'ok': False, 'error': '本次核对正在进行。'}
            args = (report, workbook, self._key, self._base, self._model, self._output)
            self._cancel.clear()
            self._result, self._report_file = (None, None)
            self._state.update(stage='reading', message='正在读取报告和计算表…', error='', stats={})
        threading.Thread(target=self._work, args=args, daemon=True).start()
        return {'ok': True}

    def _work(self, report, workbook, key, base, model, output):
        prepared = None
        try:
            prepared = prepare(report, workbook)
            if not key.strip():
                if self._cancel.is_set():
                    raise Cancelled('本次核对已取消。')
                result = assemble(prepared, local_only=True)
                self._finish(result, write_report(result, output), 'local_done')
                return
            with self._lock:
                self._state.update(stage='ai', message='资料已读取，正在交由 AI 复核…', stats={'report_tables': prepared['report']['tables'], 'sheets': len(prepared['workbook']['sheets']), 'candidate_count': len(prepared['candidates']), 'checked_numbers': prepared['checked']})
            response = request_review(prepared, key, base, model, self._progress, self._cancel)
            result = assemble(prepared, response, model=model)
            with self._lock:
                self._state.update(stage='saving', message='正在整理分级提要和证据…')
            path = write_report(result, output)
            self._finish(result, path, 'done')
        except Exception as error:
            message = str(error) if isinstance(error, (ValueError, Cancelled)) else '文件读取或结果保存失败，请检查文件格式、路径及写入权限。'
            if key:
                message = message.replace(key, '（已隐藏）')
            if prepared is not None:
                try:
                    result = assemble(prepared, failure=message, model=model)
                    result['ai_diagnostics'] = getattr(error, 'diagnostics', {})
                    path = write_report(result, output)
                    self._finish(result, path, 'incomplete', message)
                    return
                except Exception:
                    message = '本次未完成，且结果文件未能保存。请检查输出文件夹。'
            with self._lock:
                self._state.update(stage='error', error=message, message='本次核对未完成')
        finally:
            key = ''

    def _finish(self, result, path, stage, error=''):
        with self._lock:
            self._result, self._report_file = (result, path)
            self._state.update(stage=stage, message=result['status'], error=error, revision=self._state['revision'] + 1)

    def _progress(self, message):
        with self._lock:
            self._state['message'] = '正在取消，请等待当前请求结束…' if self._cancel.is_set() else message

    def progress(self):
        with self._lock:
            return dict(self._state)

    def stop(self):
        self._cancel.set()
        with self._lock:
            if self._state['stage'] in ('reading', 'ai', 'saving'):
                self._state['message'] = '正在取消，请等待当前请求结束…'
        return {'ok': True}

    def results(self):
        with self._lock:
            return {k: v for k, v in (self._result or {}).items() if k != 'sources'}

    def evidence(self, side, ref):
        with self._lock:
            if side not in ('report', 'workbook') or self._result is None:
                return {'ok': False, 'error': '尚无可查看的原文。'}
            source = self._result['sources'][side]
            item = source['index'].get(ref)
            if item is None:
                return {'ok': False, 'error': '未找到该位置，引用尚未通过核实。'}
            return {'ok': True, 'name': source['name'], 'ref': ref, 'text': item['text'], 'context': item.get('context', ''), 'sheet': item.get('sheet', ''), 'address': item.get('address', ''), 'field': item.get('field', '')}

    def _open(self, path):
        if not path or not Path(path).exists():
            return {'ok': False, 'error': '文件或文件夹已移动，无法打开。'}
        try:
            if sys.platform == 'win32':
                os.startfile(str(path))
            else:
                webbrowser.open(Path(path).resolve().as_uri())
            return {'ok': True}
        except OSError:
            return {'ok': False, 'error': '打开失败，请检查默认关联程序。'}

    def open_source(self, side, ref=None):
        with self._lock:
            if side not in ('report', 'workbook') or self._result is None:
                return {'ok': False, 'error': '尚无可打开的资料。'}
            path = self._result['sources'][side]['path']
        return self._open(path)

    def open_report(self):
        return self._open(self._report_file)

    def open_output(self):
        return self._open(self._report_file.parent if self._report_file else self._output)

    def close(self):
        self._cancel.set()
        self._key = ''

def place(window):
    try:
        screen = webview.screens[0]
        sw, sh = (screen.width / DPI, screen.height / DPI)
        width, height = (min(1220, int(sw * 0.82)), min(800, int(sh * 0.86)))
        window.resize(width, height)
        window.move(int((sw - width) / 2), max(0, int((sh - height) / 2) - 20))
    except (IndexError, AttributeError):
        pass

def main():
    if launch_installed('method'):
        return
    api = Api()
    window = webview.create_window('方法验证资料核对', url=resource('ui.html'), js_api=api, width=1220, height=800, min_size=(760, 480), background_color='#F4F6F7')
    api._attach(window)
    api._enable_updates('method', window)
    api._window.events.closed += api.close
    webview.start(place, api._window)
if __name__ == '__main__':
    main()
