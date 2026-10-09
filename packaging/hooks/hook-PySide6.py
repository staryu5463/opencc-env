"""收集 Qt 绑定所需文件；本工具不使用 Mesa 软件 OpenGL 渲染。"""
from pathlib import Path

from PyInstaller.utils.hooks.qt import ensure_single_qt_bindings_package, pyside6_library_info

ensure_single_qt_bindings_package("PySide6")
if pyside6_library_info.version is not None:
    hiddenimports = ["shiboken6", "inspect", "PySide6.support.deprecated"]
    binaries = [
        item for item in pyside6_library_info.collect_extra_binaries()
        if Path(item[0]).name.lower() != "opengl32sw.dll"
    ]
