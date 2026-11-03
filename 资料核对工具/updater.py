import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
VERSION = '1.4.0'
REPOSITORY = 'Youki117/pharma-data-review'
PRODUCTS = {'suite': '资料核对工具', 'method': '方法验证资料核对', 'content': '内容一致性核对'}
MAX_DOWNLOAD = 200 * 1024 * 1024
MAX_EXTRACT = 600 * 1024 * 1024
from update_install import cleanup_finished, dispatch_helper, validate_target

def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch('v?\\d{1,6}\\.\\d{1,6}\\.\\d{1,6}', value):
        raise ValueError('发布版本号格式不正确。')
    return tuple(map(int, value.lstrip('v').split('.')))

def update_home(product):
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'pharma-data-review' / product

def executable(home, product, version):
    version_tuple(version)
    name = PRODUCTS[product]
    return home / 'versions' / version / name / (name + '.exe')

def launch_installed(product):
    if not getattr(sys, 'frozen', False):
        return False
    home = update_home(product)
    try:
        fixed = json.loads((home / 'fixed.json').read_text(encoding='utf-8'))
        name = PRODUCTS[product] + '.exe'
        target = Path(fixed['directory']) / name
        if version_tuple(fixed['version']) > version_tuple(VERSION) and target.is_file():
            subprocess.Popen([str(target)], cwd=target.parent)
            return True
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        active = json.loads((home / 'active.json').read_text(encoding='utf-8'))
        newer = active['version']
        target = executable(home, product, newer)
        if version_tuple(newer) > version_tuple(VERSION) and target.is_file():
            subprocess.Popen([str(target)], cwd=target.parent)
            return True
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return False

def release_info(data, product, current=VERSION):
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        raise ValueError('未取得正式发布版本。')
    tag = data.get('tag_name', '')
    version_tuple(tag)
    if version_tuple(tag) <= version_tuple(current):
        return None
    version = tag.lstrip('v')
    name = f'review-{product}-v{version}.zip'
    matches = [a for a in data.get('assets', []) if isinstance(a, dict) and a.get('name') == name]
    if len(matches) != 1:
        raise ValueError('新版尚未提供当前程序的完整更新包。')
    asset = matches[0]
    expected = f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}'
    size, digest = (asset.get('size'), asset.get('digest'))
    if asset.get('browser_download_url') != expected or not isinstance(size, int) or (not 0 < size <= MAX_DOWNLOAD):
        raise ValueError('更新包地址或大小不符合发布规则。')
    if not isinstance(digest, str) or not re.fullmatch('sha256:[0-9a-f]{64}', digest):
        raise ValueError('发布平台未提供有效的更新包校验值。')
    return {'version': version, 'url': expected, 'size': size, 'digest': digest, 'notes': str(data.get('body') or '')[:6000]}

class GitHubRedirect(urllib.request.HTTPRedirectHandler):

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlsplit(newurl)
        if host.scheme != 'https' or host.hostname not in ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'):
            raise ValueError('更新下载跳转到未授权地址。')
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def download(info, destination, progress, cancelled):
    request = urllib.request.Request(info['url'], headers={'User-Agent': 'pharma-data-review/' + VERSION})
    opener = urllib.request.build_opener(GitHubRedirect())
    size, digest = (0, hashlib.sha256())
    with opener.open(request, timeout=25) as response, destination.open('wb') as output:
        while True:
            if cancelled.is_set():
                raise ValueError('更新已取消。')
            chunk = response.read(128 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > info['size'] or size > MAX_DOWNLOAD:
                raise ValueError('更新包超过发布大小。')
            output.write(chunk)
            digest.update(chunk)
            progress(f"正在下载更新：{size * 100 // info['size']}%")
    if size != info['size'] or 'sha256:' + digest.hexdigest() != info['digest']:
        raise ValueError('更新包下载不完整或校验不符，请重试。')

def extract_package(archive, directory, product):
    name = PRODUCTS[product]
    with zipfile.ZipFile(archive) as package:
        members = package.infolist()
        if len(members) > 10000 or sum((m.file_size for m in members)) > MAX_EXTRACT:
            raise ValueError('更新包解压大小超限。')
        seen = set()
        for member in members:
            path = PurePosixPath(member.filename)
            if '\\' in member.orig_filename or ':' in member.filename or path.is_absolute() or ('..' in path.parts) or (not path.parts) or (path.parts[0] != name) or (member.external_attr >> 16 & 61440 == 40960):
                raise ValueError('更新包含不安全路径。')
            normalized = '/'.join(path.parts).casefold()
            if normalized in seen:
                raise ValueError('更新包存在重复路径。')
            seen.add(normalized)
        required = {name + '/' + name + '.exe', name + '/_internal/python312.dll'}
        if not required.issubset({m.filename for m in members}):
            raise ValueError('更新包缺少程序或运行环境，不能安装。')
        package.extractall(directory)

class Updater:

    def __init__(self, product, busy=lambda: False):
        self.product, self.busy = (product, busy)
        self._lock, self._cancel = (threading.Lock(), threading.Event())
        self._state = {'stage': 'idle', 'message': '启动后自动检查更新', 'current': VERSION, 'version': '', 'notes': '', 'installable': bool(getattr(sys, 'frozen', False))}
        self._release, self._window = (None, None)

    def attach(self, window):
        self._window = window

        def loaded():
            assets = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
            window.evaluate_js((assets / 'update_ui.js').read_text(encoding='utf-8'))
            if '--update-token' in sys.argv:
                token = sys.argv[sys.argv.index('--update-token') + 1:][:1]
                if token and re.fullmatch('[0-9a-f]{32}', token[0]):
                    home = update_home(self.product)
                    home.mkdir(parents=True, exist_ok=True)
                    ready = home / ('ready-' + token[0])
                    pending = ready.with_suffix('.pending')
                    pending.write_text(json.dumps({'version': VERSION, 'pid': os.getpid()}), encoding='utf-8')
                    os.replace(pending, ready)
            cleanup_finished(self.product)
            self.check()
        window.events.loaded += loaded
        window.events.closed += self._cancel.set

    def status(self):
        with self._lock:
            return dict(self._state)

    def installing(self):
        return self.status()['stage'] == 'installing'

    def _message(self, message):
        with self._lock:
            self._state['message'] = message

    def check(self):
        with self._lock:
            if self._state['stage'] in ('checking', 'installing'):
                return {'ok': False, 'error': '更新检查或安装正在进行。'}
            self._state.update(stage='checking', message='正在检查更新…')
        threading.Thread(target=self._check, daemon=True).start()
        return {'ok': True}

    def _check(self):
        try:
            request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/releases/latest', headers={'User-Agent': 'pharma-data-review/' + VERSION, 'Accept': 'application/vnd.github+json'})
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = response.read(1000001)
            if len(raw) > 1000000:
                raise ValueError('版本信息过大。')
            info = release_info(json.loads(raw), self.product)
            with self._lock:
                self._release = info
                self._state.update(stage='available' if info else 'latest', message='发现新版本 v' + info['version'] if info else '已是最新正式版', version=info['version'] if info else '', notes=info['notes'] if info else '')
        except Exception:
            with self._lock:
                self._release = None
                self._state.update(stage='error', message='暂时无法检查更新，可继续使用；稍后可手动重试。')

    def install(self):
        with self._lock:
            if not self._state['installable']:
                return {'ok': False, 'error': '源码运行请从仓库更新；自动安装仅用于打包程序。'}
            if self._state['stage'] != 'available' or self._release is None:
                return {'ok': False, 'error': '请先检查可用更新。'}
            if self.busy():
                return {'ok': False, 'error': '请等待全部核对任务结束后再更新。'}
            info = dict(self._release)
            self._state.update(stage='installing', message='正在下载完整更新包…')
        threading.Thread(target=self._install, args=(info,), daemon=True).start()
        return {'ok': True}

    def _install(self, info):
        process, stage, handed_off = (None, None, False)
        try:
            target = Path(sys.executable).resolve().parent
            validate_target(target, self.product)
            with tempfile.TemporaryFile(dir=target):
                pass
            home = update_home(self.product)
            home.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix='pending-', dir=home))
            archive = stage / 'update.zip'
            download(info, archive, self._message, self._cancel)
            self._message('正在准备更新并检查原程序位置…')
            extract_package(archive, stage / 'package', self.product)
            if self._cancel.is_set():
                raise ValueError('更新已取消。')
            plan = stage / 'plan.json'
            plan.write_text(json.dumps({'product': self.product, 'target': str(target), 'version': info['version'], 'pid': os.getpid()}, ensure_ascii=False), encoding='utf-8')
            helper = stage / 'package' / PRODUCTS[self.product] / (PRODUCTS[self.product] + '.exe')
            process = subprocess.Popen([str(helper), '--apply-update', str(plan)], cwd=helper.parent)
            deadline = time.monotonic() + 20
            while not (stage / 'helper-ready').is_file():
                if process.poll() is not None or time.monotonic() >= deadline or self._cancel.is_set():
                    raise ValueError('更新助手未能启动，原程序仍可使用。')
                time.sleep(0.15)
            if int((stage / 'helper-ready').read_text(encoding='ascii')) != process.pid:
                raise ValueError('更新助手启动确认不符。')
            if not self._window:
                raise ValueError('未连接程序窗口，不能完成重启。')
            self._message('正在关闭旧程序，随后替换原位置并重启…')
            self._window.destroy()
            handed_off = True
        except Exception as error:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            with self._lock:
                self._state.update(stage='available', message=str(error) if isinstance(error, ValueError) else '更新准备未完成，请检查目录写权限或稍后重试；原程序可继续使用。')
        finally:
            if stage and (not handed_off):
                try:
                    if stage.resolve().parent == update_home(self.product).resolve():
                        shutil.rmtree(stage)
                except OSError:
                    pass
