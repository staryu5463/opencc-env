"""检测用户级 Claude 配置和继承环境；修复仅作用于 Claude 用户设置。"""
import base64
import codecs
import hashlib
import json
import os
import shutil
from pathlib import Path
from opencc_env.core.base_probe import BaseProbe, CheckResult, Severity, Status
from opencc_env.core.backup import BackupManager, atomic_bytes
from opencc_env.core.proxy import get_proxy_endpoint, parse_proxy, verify_http_proxy


def claude_bypass(value):
    tokens = value.replace(",", " ").split()
    return [t for t in tokens if t == "*" or any(t.lstrip("*.").lower() == d or t.lstrip("*.").lower().endswith("." + d)
            for d in ("claude.ai", "anthropic.com"))]


class CliSettingsProbe(BaseProbe):
    id = "probe_cli_settings"
    name = "Claude Code 配置"
    category = "CLI"
    level = Severity.HIGH
    auto_fixable = True

    def __init__(self, settings_path=None):
        self.settings_path = Path(settings_path) if settings_path else Path.home()/".claude"/"settings.json"

    def _is_cli_installed(self):
        return shutil.which("claude") is not None

    def _read_settings(self):
        existed = self.settings_path.exists()
        original = self.settings_path.read_bytes() if existed else b""
        data = json.loads(original.decode("utf-8-sig")) if original.strip() else {}
        if not isinstance(data, dict) or not isinstance(data.get("env", {}), dict):
            raise ValueError("settings.json 或 env 字段不是对象")
        return data, original, existed

    def run_check(self):
        if not self._is_cli_installed():
            return CheckResult(self.id,self.name,self.category,Status.NOT_APPLICABLE,None,
                "未在 PATH 中找到 Claude Code","此项不计分；只使用桌面端时无需修改。",
                details={"cli_found":False,"lookup":"当前进程 PATH","settings_path":str(self.settings_path)})
        try:
            data, _, existed = self._read_settings()
        except Exception as exc:
            return CheckResult(self.id,self.name,self.category,Status.ERROR,None,"Claude 配置读取失败",
                "停止自动写入，避免覆盖原配置。",details={"error":str(exc),"settings_path":str(self.settings_path)})
        env = data.get("env", {})
        effective = {n:str(env.get(n,os.environ.get(n,""))) for n in ("HTTPS_PROXY","HTTP_PROXY","NO_PROXY")}
        configured = [(k,parse_proxy(v,"配置")) for k,v in effective.items() if k != "NO_PROXY" and v]
        candidate = get_proxy_endpoint()
        details = {"cli_found":True,"settings_path":str(self.settings_path),"settings_exists":existed,
            "proxy_values":{k:(parse_proxy(v,"配置").display if parse_proxy(v,"配置") else "格式无效") for k,v in effective.items() if k != "NO_PROXY" and v},
            "proxy_source":"Claude 用户设置 + 当前进程继承环境","no_proxy":effective["NO_PROXY"],
            "candidate_proxy":candidate.display if candidate else None,"candidate_source":candidate.source if candidate else None,
            "runtime_verified":False,"limitation":"未读取其他项目或组织托管设置；未观察已运行 Claude 进程的实际请求"}
        can_fix = candidate is not None
        def result(status,score,title,summary):
            return CheckResult(self.id,self.name,self.category,status,score,title,summary,details=details,
                remedy_title="配置 Claude 专用代理",remedy_guide="仅修改用户级 settings.json 的代理及相关绕过项，不改 Windows 全局变量。",
                auto_fixable=can_fix and status != Status.PASS)
        if claude_bypass(effective["NO_PROXY"]):
            return result(Status.FAIL,30,"配置会绕过目标服务代理","NO_PROXY 包含全局或 Claude 服务的绕过项。")
        if not configured:
            return result(Status.WARN,60,"未设置显式 HTTP 代理","TUN 或其他机制可能提供连接，尚未验证实际路径。")
        if any(p is None for _,p in configured):
            return result(Status.FAIL,40,"代理变量格式无效","需要可验证的 HTTP/HTTPS 代理配置。")
        if len({p.display for _,p in configured}) > 1:
            return result(Status.WARN,65,"HTTP 与 HTTPS 代理不一致","两个变量可能使用不同连接路径。")
        chosen = configured[0][1]
        if not candidate or chosen.display != candidate.display:
            return result(Status.WARN,65,"配置代理未能与可连接候选对应","本轮未确认配置中的地址可连接。")
        return result(Status.PASS,100,"用户级代理配置一致",chosen.display+"；配置检查通过，运行中的实际流量未验证。")

    def run_fix(self):
        try:
            if not self._is_cli_installed():
                return False,"未找到 Claude Code，不修改配置"
            endpoint = get_proxy_endpoint()
            if not endpoint:
                return False,"没有可连接的代理候选，不修改配置"
            ok,message = verify_http_proxy(endpoint)
            if not ok:
                return False,message
            data,original,existed = self._read_settings()
            env = data.setdefault("env",{})
            bypass = str(env.get("NO_PROXY",os.environ.get("NO_PROXY","")))
            excluded = set(claude_bypass(bypass))
            env.update(HTTP_PROXY=endpoint.url,HTTPS_PROXY=endpoint.url)
            if excluded:
                env["NO_PROXY"] = ",".join(t for t in bypass.replace(","," ").split() if t not in excluded)
            text = json.dumps(data,ensure_ascii=False,indent=2)+"\n"
            if b"\r\n" in original:
                text = text.replace("\n","\r\n")
            content = (codecs.BOM_UTF8 if original.startswith(codecs.BOM_UTF8) else b"")+text.encode("utf-8")
            snapshot = {"path":str(self.settings_path),"existed":existed,
                "content_base64":base64.b64encode(original).decode("ascii"),"after_sha256":hashlib.sha256(content).hexdigest()}
            if not BackupManager.save_snapshot("cli_settings",snapshot):
                return False,"快照保存失败，已停止写入 Claude 配置"
            atomic_bytes(self.settings_path,content)
            if self.settings_path.read_bytes() != content:
                return False,"写入后的配置内容核对失败"
            return True,"已写入 Claude 用户级代理配置；未改 Windows 全局变量，现有会话需重启"
        except Exception as exc:
            return False,"配置修改未完成："+str(exc)
