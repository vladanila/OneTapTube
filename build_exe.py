import sys
import dis

orig_get_const_info = dis._get_const_info
def safe_get_const_info(const_index, const_list):
    try:
        if const_list is not None and const_index >= len(const_list):
            return const_index, repr(const_index)
        return orig_get_const_info(const_index, const_list)
    except IndexError:
        return const_index, repr(const_index)
dis._get_const_info = safe_get_const_info

import PyInstaller.__main__

if __name__ == '__main__':
    print("Building OneTapTube.exe with PyInstaller...")
    PyInstaller.__main__.run([
        '--noconsole',
        '--onefile',
        '--icon', 'icon.ico',
        '--add-data', 'icon.ico;.',
        '--add-data', 'app_icon.png;.',
        '--collect-all', 'customtkinter',
        '--collect-all', 'pystray',
        '--hidden-import', 'pystray._win32',
        '--hidden-import', 'unicodedata',
        '--hidden-import', 'sqlite3',
        '--hidden-import', 'ssl',
        '--hidden-import', 'hashlib',
        '--name', 'OneTapTube',
        '--clean',
        'gui_app.py'
    ])
