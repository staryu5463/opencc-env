"""Windows 原生接口。统一编码、超时和错误处理，不修改执行策略。"""
import ctypes
import json
import os
import subprocess
from pathlib import Path

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_command(args, timeout=12):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW)


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_powershell(script, timeout=12):
    prefix = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
    result = run_command(["powershell", "-NoProfile", "-NonInteractive", "-Command", prefix + script], timeout)
    if result.returncode:
        raise OSError(result.stderr.strip() or "PowerShell 查询失败")
    return result.stdout.strip()


def read_timezone():
    result = run_command(["tzutil", "/g"])
    value = result.stdout.strip()
    if result.returncode or not value:
        raise OSError(result.stderr.strip() or "未能读取系统时区")
    return value


def actual_desktop():
    value = run_powershell("[Environment]::GetFolderPath('Desktop')")
    if not value:
        raise OSError("Windows 未返回当前用户桌面路径")
    return Path(value)


def read_shortcut(path):
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" + ps_literal(path) + "); "
              "[pscustomobject]@{target_path=$s.TargetPath;arguments=$s.Arguments;"
              "working_directory=$s.WorkingDirectory;icon_location=$s.IconLocation;description=$s.Description}"
              " | ConvertTo-Json -Compress")
    data = json.loads(run_powershell(script))
    if not data.get("target_path"):
        raise ValueError("快捷方式启动目标为空")
    return data


def write_shortcut(path, info):
    script = "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" + ps_literal(path) + "); "
    properties = {"target_path": "TargetPath", "arguments": "Arguments", "working_directory": "WorkingDirectory",
                  "icon_location": "IconLocation", "description": "Description"}
    for key, prop in properties.items():
        if key in info:
            script += "$s." + prop + "=" + ps_literal(info[key]) + "; "
    run_powershell(script + "$s.Save()")
    actual = read_shortcut(path)
    return all(actual.get(key, "") == str(value) for key, value in info.items() if key in properties)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def notify_environment_change():
    try:
        result = ctypes.c_size_t()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 2000, ctypes.byref(result))
    except (AttributeError, OSError):
        pass


def no_reparse_path(path):
    """不在符号链接或 Windows 重解析目录中执行移动、写入或还原。"""
    candidate = Path(path).absolute()
    for parent in [candidate, *candidate.parents]:
        if parent.exists():
            stat = parent.lstat()
            if parent.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise ValueError("路径包含链接或重解析点：" + str(parent))
    return candidate
