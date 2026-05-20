# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('index.html', '.'), ('welcome.html', '.'), ('select.html', '.'), ('douyin.html', '.'), ('bilibili.html', '.'), ('PNG', 'PNG'), ('fonts', 'fonts')]
binaries = []
hiddenimports = ['flask', 'flask_cors', 'jinja2', 'werkzeug', 'click', 'blinker', 'itsdangerous', 'markupsafe', 'lxml', 'lxml.etree', 'lxml._elementpath', 'openpyxl', 'requests', 'urllib3', 'websocket', 'psutil', 'charset_normalizer', 'idna', 'tldextract', 'colorama', 'et_xmlfile', 'filelock', 'requests_file']
tmp_ret = collect_all('DrissionPage')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('certifi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'test', 'unittest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='YapotatoTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['PNG\\logo.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='YapotatoTool',
)
