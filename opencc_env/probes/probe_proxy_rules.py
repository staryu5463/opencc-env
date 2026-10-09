"""代理配置与网卡状态；网卡存在或 Up 不等于流量已被接管。"""
import json
from opencc_env.core.base_probe import BaseProbe, CheckResult, Severity, Status
from opencc_env.core.proxy import get_proxy_endpoint, read_system_proxy, verify_http_proxy
from opencc_env.core.windows import run_powershell


class ProxyRulesProbe(BaseProbe):
    id = "probe_proxy_rules"
    name = "代理与 TUN"
    category = "Proxy"
    level = Severity.HIGH

    def _check_tun_adapter(self):
        script = ('@(Get-NetAdapter -IncludeHidden | Where-Object {'
                  '$_.InterfaceDescription -match "Wintun|Clash|Meta|WireGuard" -or $_.Name -match "clash|meta|tun"'
                  '} | Select-Object Name,InterfaceDescription,Status) | ConvertTo-Json -Compress')
        data = json.loads(run_powershell(script) or "[]")
        adapters = data if isinstance(data, list) else [data]
        return {"has_tun": bool(adapters), "is_up": any(str(a.get("Status")).lower() == "up" for a in adapters),
                "adapters": adapters, "route_verified": False}

    def run_check(self):
        endpoint = get_proxy_endpoint()
        system = read_system_proxy()
        try:
            tun = self._check_tun_adapter()
        except Exception as exc:
            tun = {"has_tun": None, "is_up": None, "error": str(exc), "route_verified": False}
        details = {"registry_proxy": system, "tun_adapter": tun,
                   "proxy": endpoint.display if endpoint else None,
                   "proxy_source": endpoint.source if endpoint else None}
        if not endpoint:
            return CheckResult(self.id, self.name, self.category, Status.WARN, 50,
                "未发现可连接的代理候选", "可能使用自定义端口、PAC 或其他连接方式；未判定代理软件不存在。",
                details=details, remedy_guide="核对代理客户端端口。TUN 与系统代理是可选路由方式，不能只凭网卡名称断言生效。")
        ok, message = verify_http_proxy(endpoint)
        details["http_verified"] = ok
        if not ok:
            return CheckResult(self.id, self.name, self.category, Status.ERROR, None,
                "候选端口尚未通过代理验证", message, details=details)
        if system.get("error") or tun.get("error"):
            return CheckResult(self.id, self.name, self.category, Status.WARN, 90,
                "HTTP 代理可用，部分本机信息读取失败", "代理请求已通过；系统代理或 TUN 状态仍不完整。",
                details=details)
        return CheckResult(self.id, self.name, self.category, Status.PASS, 100,
            "HTTP 代理请求通过", endpoint.display + " · " + endpoint.source, details=details,
            remedy_guide="未启用 TUN 不会单独扣分。网卡运行状态仅作为信息，未验证全局路由、IPv6 或 UDP 接管。")
