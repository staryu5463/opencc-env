"""使用真实桌面路径查找入口；保留原目标和其他参数，不强制语言。"""
import os
import re
from pathlib import Path
from opencc_env.core.base_probe import BaseProbe, CheckResult, Severity, Status
from opencc_env.core.backup import BackupManager
from opencc_env.core.proxy import get_proxy_endpoint, parse_proxy, verify_http_proxy
from opencc_env.core.windows import actual_desktop, read_shortcut, write_shortcut, no_reparse_path

PROXY_FLAG = re.compile(r"--proxy-server(?:=|\s+)(\"[^\"]*\"|'[^']*'|\S+)", re.IGNORECASE)


class ShortcutProbe(BaseProbe):
    id = "probe_shortcut"
    name = "桌面客户端入口"
    category = "Client"
    level = Severity.HIGH
    auto_fixable = True

    def _get_search_paths(self):
        desktop = actual_desktop()
        return [desktop/"dd",desktop,Path(os.environ.get("PUBLIC",r"C:\Users\Public"))/"Desktop",
            Path(os.environ.get("APPDATA",""))/"Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"))/"Microsoft/Windows/Start Menu/Programs"]

    def _find_claude_shortcuts(self):
        found,seen = [],set()
        for folder in self._get_search_paths():
            if folder.is_dir():
                for path in folder.rglob("*.lnk"):
                    normalized = str(path.absolute()).casefold()
                    if "claude" in path.name.lower() and normalized not in seen:
                        seen.add(normalized)
                        found.append(str(path))
        return found

    def _read_shortcut_info(self,path):
        return read_shortcut(path)

    def _locate_claude_exe(self):
        local = Path(os.environ.get("LOCALAPPDATA",""))
        for root in (local/"AnthropicClaude",local/"Programs/claude",local/"Claude"):
            candidates = [root/"claude.exe"]
            if root.is_dir():
                candidates.extend(sorted(root.glob("app-*/claude.exe"),reverse=True))
            for path in candidates:
                if path.is_file():
                    return str(path)
        return None

    def run_check(self):
        try:
            paths = self._find_claude_shortcuts()
            executable = self._locate_claude_exe()
            candidate = get_proxy_endpoint()
            if not paths:
                if not executable:
                    return CheckResult(self.id,self.name,self.category,Status.NOT_APPLICABLE,None,
                        "常见位置未发现桌面入口","未找到不代表没有安装；MSIX、重命名及自定义目录尚未覆盖。",
                        details={"shortcuts_found":0,"search_paths":[str(p) for p in self._get_search_paths()]})
                return CheckResult(self.id,self.name,self.category,Status.WARN,70,
                    "找到客户端，未发现入口","可在真实桌面的 dd 文件夹创建专用代理入口。",
                    details={"claude_exe":executable,"candidate_proxy":candidate.display if candidate else None},auto_fixable=candidate is not None)
            path = paths[0]
            info = self._read_shortcut_info(path)
            details = {"shortcut_path":path,"target_path":info["target_path"],"arguments":info["arguments"],
                       "all_shortcuts":paths,"runtime_verified":False,"candidate_proxy":candidate.display if candidate else None}
            target = Path(info["target_path"])
            if target.name.lower() != "claude.exe":
                return CheckResult(self.id,self.name,self.category,Status.INFO,None,
                    "入口通过启动器或其他机制启动","未确认参数转发，不自动改写该入口。",details=details)
            if not target.is_file():
                return CheckResult(self.id,self.name,self.category,Status.ERROR,None,
                    "启动目标不存在或无法访问","不通过修改参数掩盖目标文件问题。",details=details)
            match = PROXY_FLAG.search(info["arguments"])
            configured = parse_proxy(match.group(1).strip("\"'"),"快捷方式") if match else None
            if configured and candidate and configured.display == candidate.display:
                return CheckResult(self.id,self.name,self.category,Status.PASS,100,
                    "入口代理参数与候选一致","参数核对通过；客户端是否实际采用参数尚未验证。",details=details)
            return CheckResult(self.id,self.name,self.category,Status.WARN,70,
                "入口未显式指向本轮可用代理","系统代理或 TUN 可能仍提供连接，不能直接推断直连。",
                details=details,remedy_title="配置专用代理入口",
                remedy_guide="仅调整代理参数，保留其他参数；不添加未经验证的防封标记。",auto_fixable=candidate is not None)
        except Exception as exc:
            return CheckResult(self.id,self.name,self.category,Status.ERROR,None,
                "客户端入口读取失败","未能完成查找或读取，不能判定客户端未安装。",details={"error":str(exc)})

    def run_fix(self):
        try:
            endpoint = get_proxy_endpoint()
            if not endpoint:
                return False,"未找到可连接代理，停止修改入口"
            ok,message = verify_http_proxy(endpoint)
            if not ok:
                return False,message
            paths = self._find_claude_shortcuts()
            if paths:
                path = no_reparse_path(paths[0])
                original = self._read_shortcut_info(path)
                if Path(original["target_path"]).name.lower() != "claude.exe" or not Path(original["target_path"]).is_file():
                    return False,"启动目标未确认，不自动改写"
                existed = True
            else:
                executable = self._locate_claude_exe()
                if not executable:
                    return False,"未找到可确认的安装文件"
                path = no_reparse_path(actual_desktop()/"dd"/"Claude.lnk")
                if path.exists():
                    return False,"目标入口已存在，停止以避免覆盖"
                original = {"target_path":executable,"arguments":"","working_directory":str(Path(executable).parent)}
                existed = False
            flag = '--proxy-server="'+endpoint.url+'"'
            arguments = PROXY_FLAG.sub(lambda _:flag,original["arguments"]) if PROXY_FLAG.search(original["arguments"]) else (original["arguments"]+" "+flag).strip()
            if not BackupManager.save_snapshot("shortcut",{"path":str(path),"existed":existed,"info":original,"after_arguments":arguments}):
                return False,"快照保存失败，停止修改入口"
            path.parent.mkdir(parents=True,exist_ok=True)
            if not write_shortcut(path,{**original,"arguments":arguments}):
                return False,"保存后的快捷方式属性核对失败"
            return True,"入口参数已保存；实际客户端连接路径需另行验证"
        except Exception as exc:
            return False,"入口修改未完成："+str(exc)
