# 第三方软件与许可

OpenCC-Env 的原创项目代码采用 MIT 许可证，版权声明见根目录 LICENSE。第三方组件仍适用各自许可证，MIT 不替换其许可条件。

## 本次 Windows x64 发布使用的组件

| 组件 | 版本 | 许可与说明 |
| --- | --- | --- |
| PySide6 / Shiboken6 | 6.12.0 | 使用 LGPL-3.0 许可选项，库未修改 |
| Qt Core / Gui / Widgets / Network / SVG / Image Formats | 6.12.0 | 使用 LGPL-3.0 许可选项；内部第三方代码保留各自许可，库未修改 |
| CPython | 3.11.9 | PSF 及随附许可；许可证包含其第三方归属声明 |
| OpenSSL | 3.0.13 | Apache-2.0 |
| libffi | Python 3.11.9 随附版本 | MIT 类许可 |
| Microsoft Visual C++ Runtime | Python / Qt 随附版本 | Microsoft 可再分发运行库条款 |
| PyInstaller | 6.22.3 | 构建工具；其 bootloader 例外允许按项目和依赖的许可发布 EXE |

此程序没有采用 Qt 商业许可。分发包不包含 GPL-only 的 Qt Virtual Keyboard 模块；不使用的 PDF、QML/Quick 与 Mesa 软件 OpenGL 依赖亦不主动打包。

## 许可文本与对应源码

原始许可证、归属信息以及下载校验记录保存在项目的 `licenses/` 目录，并内嵌于单文件 EXE。PyInstaller 运行时会把资源解压到临时 `_MEI…` 目录；完整发布 ZIP 中亦包含可直接阅读的副本。

- [完整许可文本与归属文件](https://github.com/staryu5463/opencc-env/tree/main/licenses)
- [本次发布及下载文件](https://github.com/staryu5463/opencc-env/releases/tag/v0.3.0)
- [Qt for Python / PySide6 / Shiboken6 6.12.0 官方源码](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/pyside-setup-everywhere-src-6.12.0.tar.xz)
- [Qt Base 6.12.0 官方源码](https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/qtbase-everywhere-src-6.12.0.tar.xz)
- [Qt SVG 6.12.0 官方源码](https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/qtsvg-everywhere-src-6.12.0.tar.xz)
- [Qt Image Formats 6.12.0 官方源码](https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/qtimageformats-everywhere-src-6.12.0.tar.xz)

本次发布同时提供 `OpenCC-Env-0.3.0-third-party-sources.zip`，包含上述四份完整、未修改的对应库源码和 SHA-256 清单，可与 EXE 一起下载。每份源码已核对 Qt 官方发布的 SHA-256。源码归档也包含未被本程序使用的文件和许可，不能据此推断这些组件已被链接。

## 修改、替换与重新构建

允许为修改本程序使用的 LGPL 库而进行调试、反向工程、替换和重新链接；本项目没有施加额外限制。Qt / PySide6 库采用动态链接，未作修改。

完整应用源码、构建脚本和打包钩子均在仓库中。使用 README 的 Python 3.11 构建步骤可以生成新 EXE。需要使用修改后的 Qt / PySide6 时，从本次发布对应源码构建兼容绑定，替换构建环境中的库后运行 `python build.py`；无需原作者密钥或许可。也可以直接从源码运行，使用自己构建的兼容 PySide6。单文件模式仍通过解压后的 DLL 动态加载组件。

## 上游说明

- [Qt LGPL 分发义务](https://www.qt.io/development/open-source-lgpl-obligations)
- [Qt for Python 许可证](https://doc.qt.io/qtforpython-6/licenses.html)
- [Qt 第三方归属信息](https://doc.qt.io/qt-6/licenses-used-in-qt.html)
- [PyInstaller 许可证及 bootloader 例外](https://pyinstaller.org/en/stable/license.html)
- [Microsoft Visual C++ Runtime 许可条款](https://visualstudio.microsoft.com/license-terms/vs2022-cruntime/)
