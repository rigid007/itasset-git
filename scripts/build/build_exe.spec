# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包规格（IT 资产与运维管理平台）。

用法（在 D:\asset 根目录执行）：
    pyinstaller scripts/build/build_exe.spec

产物：dist/ITAssetPlatform/ITAssetPlatform.exe  （onedir 模式，双击即运行）

说明
----
- 本项目所有蓝图为静态导入，run_app.py -> import app 即可被 PyInstaller 收集；
  这里再用 collect_submodules 对 blueprints/models/utils/tasks/services 兜底。
- templates / static / uploads / instance / alembic.ini 作为数据文件一并冻结，
  Flask 在运行时从 sys._MEIPASS（onedir 下即 exe 同级目录）读取。
- 可写数据（SQLite / 上传 / 日志）由 run_app.py 重定向到 exe 同级目录，避免
  写入临时目录导致数据丢失。

若要改为单文件 EXE（onefile），见本文件末尾注释。
"""
import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(os.path.dirname(SPECPATH), '..', '..'))


def _add_data(rel_src, dst):
    """仅当源目录/文件存在时加入 datas，避免 PyInstaller 因缺失报错。"""
    s = os.path.join(ROOT, rel_src)
    if os.path.exists(s):
        datas_list.append((s, dst))


datas_list = []
_add_data('templates', 'templates')      # 240 个 Jinja2 模板
_add_data('static', 'static')            # babylon.js / echarts / css
_add_data('uploads', 'uploads')          # 用户上传（初始可能为空）
_add_data('instance', 'instance')        # 初始数据库（若有）
if os.path.exists(os.path.join(ROOT, 'alembic.ini')):
    datas_list.append((os.path.join(ROOT, 'alembic.ini'), '.'))


# 隐藏导入兜底：第三方动态/延迟加载包 + 本项目全部子包
hiddenimports = [
    'flask_login', 'flask_wtf', 'flask_mail', 'flask_migrate', 'flask_socketio',
    'flask_sqlalchemy', 'waitress', 'apscheduler', 'apscheduler.schedulers.background',
    'socketio', 'engineio', 'simple_websocket', 'redis',
    'pysnmp', 'pysnmp.entity', 'pysnmp.entity.config', 'pysmi', 'pyasn1', 'pyasn1.codec',
    'netmiko', 'paramiko', 'ncclient', 'puresnmp', 'ping3',
    'realtime', 'app_init', 'scheduler', 'tasks', 'services',
]
hiddenimports += collect_submodules('blueprints')
hiddenimports += collect_submodules('models')
hiddenimports += collect_submodules('utils')
hiddenimports += collect_submodules('tasks')
hiddenimports += collect_submodules('services')

# 排除仅用于测试/开发的重型依赖，显著减小体积
excludes_list = ['pytest', 'coverage', 'ipython', 'ruff']

a = Analysis(
    [os.path.join(ROOT, 'run_app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=datas_list,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes_list,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name='ITAssetPlatform',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # 保留控制台窗口，便于查看启动日志与排错
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ITAssetPlatform',
)

# =====================================================================
# 若需"单文件 EXE"（一个 ITAssetPlatform.exe，双击运行）：
#   1) 把上方 EXE 的 exclude_binaries 改为 False，删除 COLLECT 块；
#   2) 把 a.binaries / a.datas 直接传给 EXE（见 PyInstaller 文档 onefile 模板）。
#   注意：onefile 每次启动会把全部内容解压到 %TEMP% 临时目录，启动较慢，
#   且 SQLite 数据库需写到 exe 同级目录（run_app.py 已处理），否则数据不持久。
#   本项目数据持久化优先，推荐 onedir（当前默认）。
# =====================================================================
