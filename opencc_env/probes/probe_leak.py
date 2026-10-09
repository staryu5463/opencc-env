"""活动网卡 DNS 与代理 DoH 检查，明确区分配置检查和泄漏验证。"""
import ipaddress
import json
import urllib.request
from opencc_env.core.base_probe import BaseProbe, CheckResult, Severity, Status
from opencc_env.core.proxy import get_proxy_endpoint, proxy_opener
from opencc_env.core.windows import run_powershell

DOMESTIC_DNS = {"114.114.114.114", "114.114.115.115", "223.5.5.5", "223.6.6.6", "180.76.76.76", "119.29.29.29"}


class LeakProbe(BaseProbe):
    id = "probe_leak"
    name = "DNS 与加密解析"
    category = "Leak"
    level = Severity.HIGH

    def _get_system_dns_servers(self):
        script = ('@(Get-NetAdapter | Where-Object {$_.Status -eq "Up"} | ForEach-Object {'
                  'Get-DnsClientServerAddress -InterfaceIndex $_.ifIndex'
                  '} | Select-Object -ExpandProperty ServerAddresses) | ConvertTo-Json -Compress')
        data = json.loads(run_powershell(script) or "[]")
        values = data if isinstance(data, list) else [data]
        return sorted(set(str(item) for item in values if item))

    def _test_remote_doh(self, endpoint):
        request = urllib.request.Request("https://cloudflare-dns.com/dns-query?name=claude.ai&type=A",
            headers={"Accept": "application/dns-json", "User-Agent": "OpenCC-Env/2"})
        with proxy_opener(endpoint).open(request, timeout=6) as response:
            data = json.loads(response.read(65536).decode("utf-8"))
        answers = [item["data"] for item in data.get("Answer", []) if item.get("type") in (1, 28)]
        if data.get("Status") != 0 or not answers:
            raise ValueError("DoH 返回失败状态或没有地址记录")
        for value in answers:
            ipaddress.ip_address(value)
        return answers

    def run_check(self):
        details = {"leak_test_performed": False, "ipv6_dns_configuration_checked": True,
                   "limitation": "未抓包或使用权威回显服务，不能据此宣称没有 DNS 泄露"}
        try:
            servers = self._get_system_dns_servers()
            if not servers:
                raise ValueError("活动网卡未返回 DNS 地址，或 DNS 由其他机制提供")
            details["dns_servers"] = servers
        except Exception as exc:
            details["dns_error"] = str(exc)
            return CheckResult(self.id, self.name, self.category, Status.ERROR, None,
                               "DNS 配置未能确认", "没有取得有效配置；不计为通过。", details=details)
        endpoint = get_proxy_endpoint()
        if not endpoint:
            return CheckResult(self.id, self.name, self.category, Status.ERROR, None,
                               "未执行代理 DoH 验证", "没有可连接的代理候选。", details=details)
        details["proxy"] = endpoint.display
        try:
            details["remote_doh_answers"] = self._test_remote_doh(endpoint)
            details["remote_doh_success"] = True
        except Exception as exc:
            details.update(remote_doh_success=False, doh_error=str(exc))
            return CheckResult(self.id, self.name, self.category, Status.ERROR, None,
                               "代理 DoH 验证失败", "未确认远端加密解析可用；不会给出满分。", details=details)
        domestic = sorted(DOMESTIC_DNS.intersection(servers))
        details["known_domestic_dns"] = domestic
        if domestic:
            return CheckResult(self.id, self.name, self.category, Status.WARN, 85,
                "代理 DoH 可用，需核对本地解析路由", "网卡配置包含国内公共 DNS；实际查询路径尚未验证。",
                details=details, remedy_guide="DNS 地址是配置线索，不是已发生泄漏的证据。需要进一步检查实际解析路由。")
        return CheckResult(self.id, self.name, self.category, Status.PASS, 100,
            "DNS 配置读取与代理 DoH 请求通过", "已读取活动网卡配置，代理加密解析返回有效记录。",
            details=details, remedy_guide="此结果仅覆盖配置与一次 DoH 请求；实际 DNS 泄漏、IPv6 流量路由尚未验证。")
