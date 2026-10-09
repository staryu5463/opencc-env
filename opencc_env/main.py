"""普通用户启动；仅明确请求的操作才写入配置，不自动请求 UAC。"""
import argparse
import os
import sys
import traceback
from pathlib import Path

ROOT_DIR=str(Path(__file__).resolve().parent.parent)
if ROOT_DIR not in sys.path:sys.path.insert(0,ROOT_DIR)


def main():
    parser=argparse.ArgumentParser(description="OpenCC-Env Windows 环境诊断")
    parser.add_argument("--self-test-output",help="隔离界面与打包自检报告路径；不联网、不修改系统")
    args=parser.parse_args()
    if args.self_test_output:
        os.environ["QT_QPA_PLATFORM"]="offscreen"
        try:
            from opencc_env.verification import self_test
            return 0 if self_test(args.self_test_output) else 1
        except Exception:
            output=Path(args.self_test_output)
            output.parent.mkdir(parents=True,exist_ok=True)
            output.with_suffix(".error.txt").write_text(traceback.format_exc(),encoding="utf-8")
            return 1
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from opencc_env.ui.app_window import MainWindow
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app=QApplication(sys.argv);app.setApplicationName("OpenCC-Env");app.setOrganizationName("OpenCC")
    window=MainWindow();window.show()
    return app.exec()


if __name__=="__main__":
    sys.exit(main())
