"""仅打包本工作台使用的图形插件，避免引入虚拟键盘和 PDF 渲染器。"""
from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [
    item for item in binaries
    if Path(item[0]).name.lower() not in {"qtvirtualkeyboardplugin.dll", "qpdf.dll"}
]
