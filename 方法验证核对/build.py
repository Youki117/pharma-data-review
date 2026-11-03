import os
import subprocess
import sys
import zipfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
NAME = '方法验证资料核对'
sys.path.insert(0, str(HERE.parent / '资料核对工具'))
from updater import VERSION

def main():
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed', '--noupx', '--name', NAME, '--distpath', str(HERE / 'dist' / ('v' + VERSION)), '--add-data', str(HERE / 'ui.html') + os.pathsep + '.', '--add-data', str(HERE.parent / '资料核对工具' / 'update_ui.js') + os.pathsep + '.', '--icon', str(HERE.parent / '本地对账工具' / 'icon.ico'), '--paths', str(HERE.parent / '本地对账工具'), '--paths', str(HERE.parent / '资料核对工具'), str(HERE / 'app.py')], cwd=HERE, check=True)
    folder = HERE / 'dist' / ('v' + VERSION) / NAME
    (folder / '使用说明.md').write_text((HERE / 'README.md').read_text(encoding='utf-8'), encoding='utf-8')
    with zipfile.ZipFile(HERE / 'dist' / (NAME + '-v' + VERSION + '.zip'), 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in folder.rglob('*'):
            if path.is_file():
                archive.write(path, Path(NAME) / path.relative_to(folder))
    print(folder / (NAME + '.exe'))
if __name__ == '__main__':
    main()
