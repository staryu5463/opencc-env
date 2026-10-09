"""可重复构建。禁用 UPX、保持普通权限，EXE 自检通过后再发布到 dist。"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def build_executable(output_dir=None):
    output=Path(output_dir) if output_dir else ROOT/"dist"
    build_root=ROOT/"build"/("release-"+datetime.now().strftime("%Y%m%d-%H%M%S"))
    build_root.mkdir(parents=True,exist_ok=True)
    candidate_dir=build_root/"candidate"
    command=[sys.executable,"-m","PyInstaller","--name=OpenCC-Env","--onefile","--windowed",
        "--noupx","--noconfirm","--clean","--paths="+str(ROOT),"--collect-submodules=opencc_env",
        "--additional-hooks-dir="+str(ROOT/"packaging/hooks"),
        "--collect-data=opencc_env","--distpath="+str(candidate_dir),"--workpath="+str(build_root/"work"),
        "--specpath="+str(build_root),"--version-file="+str(ROOT/"version_info.txt"),str(ROOT/"opencc_env"/"main.py")]
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "licenses"):
        source=ROOT/name
        if source.exists():command.insert(-1,"--add-data="+str(source)+(";licenses" if name=="licenses" else ";."))
    # Qt 与 Python 自带 VC 运行库版本可能不同，根目录统一使用 Qt 附带的新版本。
    import PySide6
    qt_directory=Path(PySide6.__file__).parent
    for runtime in ("VCRUNTIME140.dll","VCRUNTIME140_1.dll","MSVCP140.dll","MSVCP140_1.dll","MSVCP140_2.dll"):
        source=qt_directory/runtime
        if source.exists():command.insert(-1,"--add-binary="+str(source)+";.")
    icon=ROOT/"opencc_env/resources/app.ico"
    if icon.exists():command.insert(-1,"--icon="+str(icon))
    build_environment=dict(os.environ)
    windows_directory=Path(os.environ.get("WINDIR",r"C:\Windows"))
    build_environment["PATH"]=os.pathsep.join((str(Path(sys.executable).parent),str(qt_directory),str(windows_directory/"System32"),str(windows_directory)))
    result=subprocess.run(command,cwd=ROOT,env=build_environment)
    if result.returncode:return False,"PyInstaller 构建失败"
    executable=candidate_dir/"OpenCC-Env.exe"
    report_path=build_root/"verification"/"exe-self-test.json"
    report_path.parent.mkdir(parents=True,exist_ok=True)
    try:
        result=subprocess.run([str(executable),"--self-test-output",str(report_path)],
                              timeout=60,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        if result.returncode or not report_path.exists():
            return False,"打包 EXE 自检未完成，未发布候选产物"
        report=json.loads(report_path.read_text(encoding="utf-8"))
        if not report["checks"]["passed"]:
            return False,"打包 EXE 自检不通过，未发布候选产物"
        output.mkdir(parents=True,exist_ok=True)
        target=output/"OpenCC-Env.exe"
        if target.exists():
            previous=output/"previous";previous.mkdir(exist_ok=True)
            shutil.copy2(target,previous/("OpenCC-Env-"+datetime.now().strftime("%Y%m%d-%H%M%S")+".exe"))
        with tempfile.NamedTemporaryFile(dir=output,prefix=".opencc-release-",suffix=".exe",delete=False) as stream:
            temporary=Path(stream.name)
        try:
            shutil.copy2(executable,temporary);os.replace(temporary,target)
        finally:
            if temporary.exists():temporary.unlink()
        print("EXE 自检通过，已发布："+str(target))
        print("自检报告："+str(report_path))
        return True,str(target)
    except (OSError,ValueError,KeyError,subprocess.TimeoutExpired) as exc:
        return False,"构建验证未完成："+str(exc)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output-dir");args=parser.parse_args()
    ok,message=build_executable(args.output_dir)
    if not ok:print(message);sys.exit(1)
