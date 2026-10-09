"""当前用户 Run 项：明确选择、备份、复查，不宣称覆盖所有启动链。"""
import re
import winreg
from pathlib import Path
from opencc_env.core.backup import BackupManager


class StartupFixer:
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    @staticmethod
    def scan_startup_entries():
        entries = []
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,StartupFixer.REG_PATH,0,winreg.KEY_READ)
        except FileNotFoundError:
            return entries
        with key:
            count = winreg.QueryInfoKey(key)[1]
            for idx in range(count):
                name,command,kind = winreg.EnumValue(key,idx)
                if "claude" not in name.lower() and "claude" not in str(command).lower():
                    continue
                match = re.match(r'\s*(?:"([^"]+)"|(\S+))',str(command))
                target = (match.group(1) or match.group(2)) if match else ""
                confirmed = Path(target).name.lower() == "claude.exe" and Path(target).is_file()
                entries.append({"name":name,"command":str(command),"type":kind,"target":target,
                    "confirmed_direct_target":confirmed,"scope":"当前用户 Run 注册表"})
        return entries

    @staticmethod
    def remove_unprotected_startup(selected_names=None):
        if not selected_names:
            return False,"请先选择要停用的当前用户 Run 启动项"
        removed = []
        try:
            available = {e["name"]:e for e in StartupFixer.scan_startup_entries()}
            if any(n not in available or not available[n]["confirmed_direct_target"] for n in selected_names):
                return False,"所选启动项未解析为真实 Claude.exe，停止修改"
            entries = [available[n] for n in dict.fromkeys(selected_names)]
            if not BackupManager.save_snapshot("startup",{"entries":entries}):
                return False,"快照保存失败，停止修改"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,StartupFixer.REG_PATH,0,winreg.KEY_SET_VALUE|winreg.KEY_QUERY_VALUE) as key:
                if any(winreg.QueryValueEx(key,e["name"]) != (e["command"],e["type"]) for e in entries):
                    raise ValueError("启动项在检测后发生变化")
                for item in entries:
                    winreg.DeleteValue(key,item["name"])
                    removed.append(item)
                for item in entries:
                    try:
                        winreg.QueryValueEx(key,item["name"])
                    except FileNotFoundError:
                        continue
                    raise ValueError("停用后启动项仍存在")
            return True,f"已停用并复查 {len(entries)} 项当前用户 Run 项；未修改计划任务、启动目录或其他用户配置"
        except Exception as exc:
            recovery = []
            if removed:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,StartupFixer.REG_PATH,0,winreg.KEY_SET_VALUE|winreg.KEY_QUERY_VALUE) as key:
                        for item in removed:
                            try:
                                winreg.QueryValueEx(key,item["name"])
                            except FileNotFoundError:
                                winreg.SetValueEx(key,item["name"],0,item["type"],item["command"])
                except Exception as error:
                    recovery.append(str(error))
            return False,"启动项修改未完成："+str(exc)+("；撤回错误："+"；".join(recovery) if recovery else "；已尝试撤回已停用项")
