import os
import sys
import threading
from pathlib import Path
METHOD = Path(__file__).resolve().parents[1] / '方法验证核对'
sys.path.insert(0, str(METHOD))
from app import Api, place, resource, webview
from ai import Cancelled
from report import write_report
from content_core import prepare_content
from content_ai import assemble_content, request_content
from updater import launch_installed

class ContentApi(Api):

    def __init__(self):
        super().__init__()
        self._output = str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / '内容一致性核对' / '结果')

    def settings(self):
        values = super().settings()
        values.update(kind='content', title='内容一致性核对', subtitle='汇总与正文 · 单份及多文件核对')
        return values

    def pick(self, kind):
        if kind != 'documents':
            return super().pick(kind)
        if not self._window:
            return {'paths': []}
        selected = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=('Word 资料 (*.docx)',))
        return {'paths': list(selected or [])}

    def start(self, paths):
        if not isinstance(paths, list) or not 1 <= len(paths) <= 10 or (not all((isinstance(p, str) for p in paths))):
            return {'ok': False, 'error': '请选择 1～10 份 .docx 资料。'}
        with self._lock:
            if self._updater and self._updater.installing():
                return {'ok': False, 'error': '正在安装更新，请等待新版启动。'}
            if self._state['stage'] in ('reading', 'ai', 'saving'):
                return {'ok': False, 'error': '本次核对正在进行。'}
            args = (list(paths), self._key, self._base, self._model, self._output)
            self._cancel.clear()
            self._result, self._report_file = (None, None)
            self._state.update(stage='reading', message='正在读取审核资料…', error='', stats={})
        threading.Thread(target=self._work, args=args, daemon=True).start()
        return {'ok': True}

    def _work(self, paths, key, base, model, output):
        prepared = None
        try:
            prepared = prepare_content(paths)
            if not key.strip():
                if self._cancel.is_set():
                    raise Cancelled('本次核对已取消。')
                if prepared['blocking']:
                    raise ValueError('资料读取未完整。\n' + '\n'.join(prepared['blocking']))
                result = assemble_content(prepared, local_only=True)
                self._finish(result, write_report(result, output), 'local_done')
                return
            with self._lock:
                self._state.update(stage='ai', message='正在审核汇总、正文和跨文件内容…', stats={'document_count': len(prepared['documents']), 'block_count': prepared['block_count'], 'candidate_count': len(prepared['candidates']), 'report_tables': prepared['table_count']})
            response = request_content(prepared, key, base, model, self._progress, self._cancel)
            result = assemble_content(prepared, response, model=model)
            with self._lock:
                self._state.update(stage='saving', message='正在整理分级提要与原文引用…')
            self._finish(result, write_report(result, output), 'done')
        except Exception as error:
            message = str(error) if isinstance(error, (ValueError, Cancelled)) else '资料读取或报告保存失败，请检查文件和输出路径。'
            if key:
                message = message.replace(key, '（已隐藏）')
            if prepared is not None:
                try:
                    result = assemble_content(prepared, failure=message, model=model)
                    result['ai_diagnostics'] = getattr(error, 'diagnostics', {})
                    self._finish(result, write_report(result, output), 'incomplete', message)
                    return
                except Exception:
                    message = '本次未完成，且报告未能保存，请检查输出路径。'
            with self._lock:
                self._state.update(stage='error', error=message, message='本次核对未完成')
        finally:
            key = ''

    def evidence(self, side, ref):
        with self._lock:
            if self._result is None:
                return {'ok': False, 'error': '尚无可查看的原文。'}
            item = self._result['sources']['documents']['index'].get(ref)
            if item is None:
                return {'ok': False, 'error': '该位置不存在，引用尚未通过核实。'}
            return {'ok': True, 'name': item['document'], 'ref': ref, 'text': item['text'], 'context': item.get('context', ''), 'field': item.get('field', '')}

    def open_source(self, side, ref=None):
        with self._lock:
            item = (self._result or {}).get('sources', {}).get('documents', {}).get('index', {}).get(ref)
            if not item:
                return {'ok': False, 'error': '请从有效的原文定位打开对应资料。'}
            path = item['path']
        return self._open(path)

def main():
    if launch_installed('content'):
        return
    api = ContentApi()
    window = webview.create_window('内容一致性核对', url=resource('ui.html'), js_api=api, width=1220, height=800, min_size=(760, 480), background_color='#F4F6F7')
    api._attach(window)
    api._enable_updates('content', window)
    api._window.events.closed += api.close
    webview.start(place, api._window)
if __name__ == '__main__':
    main()
