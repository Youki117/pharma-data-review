import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

def update_home(product):
    from updater import update_home as home
    return home(product)

def names(product):
    from updater import PRODUCTS
    return (PRODUCTS[product] + '.exe', '_internal', '使用说明.md')

def checked_tree(path):
    if path.is_symlink() or path.is_junction():
        raise ValueError('程序目录包含链接，请手动更新。')
    if path.is_dir():
        for child in path.rglob('*'):
            if child.is_symlink() or child.is_junction():
                raise ValueError('程序目录包含链接，请手动更新。')

def copy_item(source, target):
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)

def remove_item(path, parent, allowed):
    if path.parent.resolve() != parent.resolve() or path.name not in allowed:
        raise ValueError('更新文件超出程序范围。')
    checked_tree(path)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()

def validate_target(target, product):
    target = target.resolve()
    if target == Path(target.anchor) or not (target / names(product)[0]).is_file():
        raise ValueError('原程序位置无效，请手动下载新版。')
    for name in names(product):
        checked_tree(target / name)
    backup = target / '.review-backup'
    if backup.exists():
        checked_tree(backup)
        try:
            marker = json.loads((backup / '.backup.json').read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            raise ValueError('回退目录已有其他文件，请先移走 .review-backup 后重试。') from error
        if marker != {'product': product, 'target': str(target)} or any((p.name not in (*names(product), '.backup.json') for p in backup.iterdir())):
            raise ValueError('回退目录包含其他资料，更新不会清理它，请先移走后重试。')
    return backup

def wait_process(pid, timeout):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(1048576, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return True
        raise OSError('无法确认旧进程是否退出。')
    try:
        return kernel.WaitForSingleObject(handle, int(timeout * 1000)) == 0
    finally:
        kernel.CloseHandle(handle)

def start_and_wait(executable, product, version):
    home = update_home(product)
    home.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    ready = home / ('ready-' + token)
    process = subprocess.Popen([str(executable), '--update-token', token], cwd=executable.parent)
    try:
        deadline = time.monotonic() + 40
        while not ready.is_file():
            if process.poll() is not None or time.monotonic() >= deadline:
                raise ValueError('新版未成功打开。')
            time.sleep(0.15)
        if json.loads(ready.read_text(encoding='utf-8')) != {'version': version, 'pid': process.pid}:
            raise ValueError('新版启动确认不符。')
    except Exception:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        raise
    finally:
        ready.unlink(missing_ok=True)

def apply_package(source, target, product, version):
    source, target = (Path(source).resolve(), Path(target).resolve())
    backup = validate_target(target, product)
    managed = names(product)
    if source == target or target in source.parents or (not (source / managed[0]).is_file()) or (not (source / '_internal/python312.dll').is_file()):
        raise ValueError('更新准备目录不完整或与原程序冲突。')
    checked_tree(source)
    changed = False
    try:
        for name in managed:
            item = target / name
            files = item.rglob('*') if item.is_dir() else [item]
            for file in files:
                if file.is_file():
                    with file.open('r+b'):
                        pass
        if backup.exists():
            remove_item(backup, target, {'.review-backup'})
        backup.mkdir()
        (backup / '.backup.json').write_text(json.dumps({'product': product, 'target': str(target)}, ensure_ascii=False), encoding='utf-8')
        for name in managed:
            if (target / name).exists():
                copy_item(target / name, backup / name)
        changed = True
        for name in managed:
            remove_item(target / name, target, managed)
            if (source / name).exists():
                copy_item(source / name, target / name)
        start_and_wait(target / managed[0], product, version)
    except Exception as error:
        try:
            if changed:
                for name in managed:
                    remove_item(target / name, target, managed)
                    if (backup / name).exists():
                        copy_item(backup / name, target / name)
            subprocess.Popen([str(target / managed[0])], cwd=target)
        except Exception as restore_error:
            raise ValueError('更新失败，自动恢复未完成；请从原目录 .review-backup 恢复程序文件。') from restore_error
        raise ValueError('更新未完成，已恢复原程序；已保存的报告不受影响。') from error
    home = update_home(product)
    home.mkdir(parents=True, exist_ok=True)
    pending = home / 'fixed.pending'
    pending.write_text(json.dumps({'version': version, 'directory': str(target)}, ensure_ascii=False), encoding='utf-8')
    os.replace(pending, home / 'fixed.json')

def dispatch_helper(product):
    if '--apply-update' not in sys.argv:
        return False
    if not getattr(sys, 'frozen', False):
        raise ValueError('更新助手只能由打包程序启动。')
    plan_file = Path(sys.argv[sys.argv.index('--apply-update') + 1]).resolve()
    home = update_home(product).resolve()
    stage = plan_file.parent
    from updater import PRODUCTS, version_tuple
    plan = json.loads(plan_file.read_text(encoding='utf-8'))
    source = stage / 'package' / PRODUCTS[product]
    if stage.parent != home or not stage.name.startswith('pending-') or plan_file.name != 'plan.json' or (plan.get('product') != product) or (plan.get('pid') != os.getppid()) or (Path(sys.executable).resolve() != source / names(product)[0]):
        raise ValueError('更新助手启动参数不符。')
    version_tuple(plan['version'])
    target = Path(plan['target']).resolve()
    validate_target(target, product)
    try:
        ready = stage / 'helper-ready.pending'
        ready.write_text(str(os.getpid()), encoding='ascii')
        os.replace(ready, stage / 'helper-ready')
        if not wait_process(plan['pid'], 60):
            raise ValueError('旧程序尚未完全退出，本次没有替换文件。')
        apply_package(source, target, product, plan['version'])
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else '更新未完成，请重新打开原程序；回退文件位于 .review-backup。'
        ctypes.windll.user32.MessageBoxW(None, message, '软件更新', 16)
    finally:
        (stage / 'finished').write_text(str(os.getpid()), encoding='ascii')
    return True

def cleanup_finished(product):

    def clean():
        home = update_home(product).resolve()
        for stage in home.glob('pending-*'):
            try:
                if stage.resolve().parent != home or not stage.is_dir():
                    continue
                plan = json.loads((stage / 'plan.json').read_text(encoding='utf-8'))
                if plan.get('product') != product or Path(plan.get('target', '')).resolve() != Path(sys.executable).resolve().parent:
                    continue
                deadline = time.monotonic() + 90
                while not (stage / 'finished').exists() and time.monotonic() < deadline:
                    time.sleep(0.5)
                if (stage / 'finished').is_file() and wait_process(int((stage / 'finished').read_text()), 5):
                    checked_tree(stage)
                    shutil.rmtree(stage)
            except (OSError, ValueError):
                continue
    threading.Thread(target=clean, daemon=True).start()
