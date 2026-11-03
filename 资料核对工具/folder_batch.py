import copy
import html
import json
import os
import threading
from datetime import datetime
from pathlib import Path
BUSY = ('reading', 'ai', 'saving')
LABELS = {'ready': '待核对', 'running': '核对中', 'done': 'AI 已复核', 'local_done': '本地筛选完成', 'incomplete': '复核未完整', 'error': '失败', 'blocked': '需整理文件', 'cancelled': '已取消'}
UNSUPPORTED = {'.doc', '.xls', '.docm', '.xlsm', '.pdf', '.rtf'}

def scan_batches(root, kind, mode):
    if kind not in ('method', 'content') or mode not in ('subfolders', 'single'):
        raise ValueError('请选择按一级子目录分批，或整个目录作为一批。')
    if not isinstance(root, str) or not Path(root).is_dir():
        raise ValueError('请选择存在的资料文件夹。')
    base = Path(root).resolve()
    try:
        children = sorted(base.iterdir(), key=lambda p: p.name.casefold())
    except OSError:
        raise ValueError('无法读取所选文件夹，请检查访问权限。') from None
    roots = [(base, True)] if mode == 'single' else [(p, True) for p in children if p.is_dir()]
    if mode == 'subfolders' and any((p.is_file() for p in children)):
        roots.insert(0, (base, False))
    groups = []
    for directory, recursive in roots:
        files, ignored, blocking = ([], [], [])

        def onerror(error):
            blocking.append('无法读取子目录：' + str(error.filename))

        def linked(path):
            info = path.lstat()
            return path.is_symlink() or bool(getattr(info, 'st_file_attributes', 0) & 1024)
        try:
            if linked(directory):
                blocking.append('目录为链接或重解析点，未递归读取：' + str(directory))
            else:
                for current, dirs, names in os.walk(directory, onerror=onerror, followlinks=False):
                    if not recursive:
                        dirs[:] = []
                    for name in sorted(dirs[:]):
                        target = Path(current) / name
                        if linked(target):
                            blocking.append('未读取链接子目录：' + str(target))
                            dirs.remove(name)
                    dirs.sort(key=str.casefold)
                    for name in sorted(names, key=str.casefold):
                        path = Path(current) / name
                        if name.startswith('~$'):
                            ignored.append(str(path))
                        elif linked(path):
                            blocking.append('未读取链接文件：' + str(path))
                        elif path.suffix.lower() in ({'.docx', '.xlsx'} if kind == 'method' else {'.docx'}):
                            files.append(str(path))
                        elif path.suffix.lower() in UNSUPPORTED or (kind == 'content' and path.suffix.lower() == '.xlsx'):
                            blocking.append('当前页面未读取该格式，请转换或整理后重扫：' + str(path))
                        else:
                            ignored.append(str(path))
        except OSError:
            blocking.append('文件枚举未完成，请检查访问权限：' + str(directory))
        reports = [p for p in files if Path(p).suffix.lower() == '.docx']
        workbooks = [p for p in files if Path(p).suffix.lower() == '.xlsx']
        if kind == 'method' and (len(reports) != 1 or len(workbooks) != 1):
            blocking.append(f'需要唯一的一份 Word 报告和一份 Excel；现有 {len(reports)} 份 Word、{len(workbooks)} 份 Excel，未自动猜配。')
        if kind == 'content' and (not 1 <= len(reports) <= 10):
            blocking.append(f'每批需要 1～10 份 Word；当前有 {len(reports)} 份，请拆分批次。')
        name = directory.name if recursive else '根目录散放文件'
        groups.append({'id': f'G{len(groups) + 1:03}', 'name': name, 'directory': str(directory), 'files': files, 'reports': reports, 'workbooks': workbooks, 'ignored': ignored, 'blocking': blocking, 'status': 'blocked' if blocking else 'ready', 'error': '', 'counts': None, 'report': ''})
    if not groups:
        raise ValueError('未找到可分组的文件或子目录；可改选“整个目录作为一批”。')
    return {'root': str(base), 'mode': mode, 'groups': groups}

class BatchQueue:

    def __init__(self, kind, controller):
        self._kind, self._api = (kind, controller)
        self._lock = threading.Lock()
        self._preview, self._run = (None, None)
        self._running, self._scanning = (False, False)
        self._results, self._revision = ({}, 0)
        self._summary, self._error, self._selected = ('', '', '')

    def busy(self):
        with self._lock:
            return self._running or self._scanning

    def scan(self, root, mode):
        with self._lock:
            if self._running or self._scanning or self._api.progress()['stage'] in BUSY:
                return {'ok': False, 'error': '请等待当前核对结束后再导入文件夹。'}
            self._scanning = True
        try:
            plan = scan_batches(root, self._kind, mode)
            with self._lock:
                self._preview = plan
            return {'ok': True, 'plan': copy.deepcopy(plan)}
        except ValueError as error:
            with self._lock:
                self._preview = None
            return {'ok': False, 'error': str(error)}
        finally:
            with self._lock:
                self._scanning = False

    def start(self):
        with self._lock:
            if self._running or self._scanning or self._api.progress()['stage'] in BUSY:
                return {'ok': False, 'error': '当前核对尚未结束。'}
            if not self._preview or not any((g['status'] == 'ready' for g in self._preview['groups'])):
                return {'ok': False, 'error': '没有可执行批次，请先扫描并整理文件。'}
            try:
                fresh = scan_batches(self._preview['root'], self._kind, self._preview['mode'])
            except ValueError as error:
                return {'ok': False, 'error': str(error)}
            if fresh != self._preview:
                self._preview = None
                return {'ok': False, 'error': '目录内容在预览后发生变化，请重新扫描确认批次。'}
            self._run = copy.deepcopy(self._preview)
            self._results, self._error, self._summary, self._selected = ({}, '', '', '')
            self._running = True
            self._revision += 1
            self._api._cancel.clear()
            with self._api._lock:
                self._api._result, self._api._report_file = (None, None)
                self._api._state.update(stage='reading', message='正在准备批量任务…', error='', stats={}, revision=self._api._state['revision'] + 1)
        threading.Thread(target=self._work, daemon=True).start()
        return {'ok': True}

    def status(self):
        with self._lock:
            groups = copy.deepcopy(self._run['groups']) if self._run else []
            return {'running': self._running, 'revision': self._revision, 'groups': groups, 'summary': self._summary, 'error': self._error, 'selected': self._selected, 'root': self._run['root'] if self._run else ''}

    def select(self, group_id):
        with self._lock:
            if self._running or self._scanning or self._api.progress()['stage'] in BUSY:
                return {'ok': False, 'error': '批量核对结束后可切换查看各批结果。'}
            if not isinstance(group_id, str) or group_id not in self._results:
                return {'ok': False, 'error': '该批尚无可查看的核对报告。'}
            result, path, stage, message = self._results[group_id]
            self._selected = group_id
            self._revision += 1
            self._api._finish(result, path, stage, message)
            return {'ok': True}

    def clear_selection(self):
        with self._lock:
            self._selected = ''
            self._revision += 1

    def open_summary(self):
        with self._lock:
            path = self._summary
        return self._api._open(path)

    def _save(self, folder):
        snapshot = self.status()
        rows = []
        for group in snapshot['groups']:
            report = Path(group['report']).relative_to(folder).as_posix() if group['report'] else ''
            link = f'<a href="{html.escape(report, quote=True)}">查看报告</a>' if report else '—'
            details = group['blocking'] + ([group['error']] if group['error'] else [])
            if group['ignored']:
                details.append(f"{len(group['ignored'])} 份其他格式或锁文件未读取，完整路径见 JSON 清单。")
            counts = group['counts']
            count_text = ' / '.join((f'{k} {v}' for k, v in counts.items())) if counts else '—'
            rows.append('<tr>' + ''.join((f'<td>{html.escape(str(x))}</td>' for x in (group['name'], LABELS[group['status']], count_text, '\n'.join(details)))) + f'<td>{link}</td></tr>')
        text = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>批量核对清单</title>\n<style>body{font:14px/1.8 "Microsoft YaHei",sans-serif;padding:24px;color:#243344}table{border-collapse:collapse;width:100%}td,th{border:1px solid #dde3e6;padding:10px;text-align:left;vertical-align:top;white-space:pre-wrap}a{color:#1b5e70}</style></head><body><h1>批量核对清单</h1>'
        text += '<p>' + html.escape(snapshot['root']) + '</p><p>本地筛选完成表示未调用 AI；AI 已复核表示已完成模型复核。均需查看问题及覆盖限制，不代表资料无误。</p>'
        if snapshot['error']:
            text += '<p>' + html.escape(snapshot['error']) + '</p>'
        text += '<table><tr><th>批次</th><th>状态</th><th>分级件数</th><th>说明</th><th>结果</th></tr>' + ''.join(rows) + '</table></body></html>'
        for filename, content in [('批量任务.html', text), ('批量任务.json', json.dumps(snapshot, ensure_ascii=False, indent=2))]:
            target = folder / filename
            temporary = target.with_suffix(target.suffix + '.tmp')
            temporary.write_text(content, encoding='utf-8')
            temporary.replace(target)

    def _work(self):
        api = self._api
        key, base, model, output = (api._key, api._base, api._model, api._output)
        folder = Path(output) / ('批量-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        try:
            folder.mkdir(parents=True, exist_ok=False)
            with self._lock:
                self._summary = str(folder / '批量任务.html')
            self._save(folder)
            for group in self._run['groups']:
                with self._lock:
                    if group['status'] == 'blocked':
                        continue
                    if api._cancel.is_set():
                        group['status'] = 'cancelled'
                        self._revision += 1
                        continue
                    group['status'] = 'running'
                    self._selected = group['id']
                    self._revision += 1
                with api._lock:
                    api._result, api._report_file = (None, None)
                    api._state.update(stage='reading', message='正在读取批次：' + group['name'], error='', stats={}, revision=api._state['revision'] + 1)
                self._save(folder)
                arguments = [group['reports'][0], group['workbooks'][0]] if self._kind == 'method' else [group['reports']]
                api._work(*arguments, key, base, model, str(folder / group['id']))
                with api._lock:
                    result, path = (api._result, api._report_file)
                    stage, message = (api._state['stage'], api._state['error'])
                with self._lock:
                    group['status'] = stage if stage in ('done', 'local_done', 'incomplete', 'error') else 'error'
                    group['error'] = message
                    if result is not None and path:
                        group['report'], group['counts'] = (str(path), dict(result['counts']))
                        self._results[group['id']] = (result, path, stage, message)
                    self._revision += 1
                self._save(folder)
        except Exception:
            with self._lock:
                self._error = '批量任务未完整结束，请检查输出路径和批次清单。'
                for group in self._run['groups']:
                    if group['status'] in ('ready', 'running'):
                        group['status'] = 'error'
                        group['error'] = self._error
            with api._lock:
                if api._state['stage'] in BUSY:
                    api._state.update(stage='error', error=self._error, message='批量任务未完成', revision=api._state['revision'] + 1)
        finally:
            key = ''
            with api._lock:
                if api._state['stage'] in BUSY:
                    api._state.update(stage='error', error='批量任务已取消或未完整结束，请查看批次清单。', message='批量任务未完成', revision=api._state['revision'] + 1)
            with self._lock:
                self._running = False
                self._revision += 1
            try:
                self._save(folder)
            except OSError:
                with self._lock:
                    self._error = '批量清单未能完整保存，请检查输出路径；各批报告可能已保存。'
