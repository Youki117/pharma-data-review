import os
import subprocess
import sys
import zipfile
from pathlib import Path
from updater import VERSION
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NAME = '资料核对工具'

def main():
    import win32com.client
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed', '--noupx', '--name', NAME, '--distpath', str(HERE / 'dist' / ('v' + VERSION)), '--icon', str(ROOT / '本地对账工具' / 'icon.ico'), '--paths', str(ROOT), '--paths', str(ROOT / '方法验证核对'), '--paths', str(ROOT / '内容一致性核对'), '--paths', str(ROOT / '本地对账工具'), '--hidden-import', 'win32com.client.dynamic', '--hidden-import', 'pythoncom', '--hidden-import', 'pywintypes', '--add-data', str(HERE / 'shell.html') + os.pathsep + '.', '--add-data', str(HERE / 'update_ui.js') + os.pathsep + '.']
    for name, folder in [('method', '方法验证核对'), ('stability', '本地对账工具'), ('content', '方法验证核对')]:
        command.extend(['--add-data', str(ROOT / folder / 'ui.html') + os.pathsep + 'pages/' + name])
    subprocess.run(command + [str(HERE / 'suite.py')], cwd=HERE, check=True)
    folder = HERE / 'dist' / ('v' + VERSION) / NAME
    (folder / '使用说明.md').write_text((HERE / 'README.md').read_text(encoding='utf-8'), encoding='utf-8')
    with zipfile.ZipFile(HERE / 'dist' / (NAME + '-v' + VERSION + '.zip'), 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in folder.rglob('*'):
            if path.is_file():
                archive.write(path, Path(NAME) / path.relative_to(folder))
    print(folder / (NAME + '.exe'))
if __name__ == '__main__':
    main()
