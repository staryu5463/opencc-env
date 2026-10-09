"""通过已发现的代理查询出口信息，不回退直连、不推断 IP 独享或信誉。"""
import ipaddress
import json
import urllib.request
from opencc_env.core.base_probe import BaseProbe, CheckResult, Severity, Status
from opencc_env.core.proxy import get_proxy_endpoint, proxy_opener


class NetworkProbe(BaseProbe):
    id = "probe_network"
    name = "代理出口"
    category = "Network"
    level = Severity.CRITICAL

    def run_check(self):
        endpoint = get_proxy_endpoint()
        if not endpoint:
            return CheckResult(self.id, self.name, self.category, Status.ERROR, None,
                "没有可连接的代理候选", "未执行出口请求；不会自动回退到直连。",
                details={"source": "本机代理发现", "direct_fallback": False},
                remedy_guide="先检查代理客户端的实际 HTTP/Mixed 端口。可通过 OPENCC_PROXY 指定代理。")
        try:
            request = urllib.request.Request("https://ipinfo.io/json", headers={"User-Agent": "OpenCC-Env/2"})
            with proxy_opener(endpoint).open(request, timeout=6) as response:
                data = json.loads(response.read(65536).decode("utf-8"))
            ipaddress.ip_address(data["ip"])
            country = data.get("country", "未知")
            details = {"ip": data["ip"], "country": country, "city": data.get("city", ""),
                       "org": data.get("org", ""), "proxy": endpoint.display, "proxy_source": endpoint.source,
                       "query_service": "https://ipinfo.io/json", "direct_fallback": False,
                       "limitation": "只验证此查询经过该代理；未验证 Claude 分流、IP 独享或账号状态"}
            return CheckResult(self.id, self.name, self.category, Status.PASS, 100,
                "代理出口查询成功", data["ip"] + " · " + country + " · " + data.get("city", ""),
                details=details, remedy_guide="地理信息由第三方返回。它不证明 IP 是住宅、独享或可信，也不代表服务使用资格。")
        except Exception as exc:
            return CheckResult(self.id, self.name, self.category, Status.ERROR, None,
                "出口查询未完成", "代理请求或返回数据验证失败。", details={"proxy": endpoint.display, "error": str(exc)},
                remedy_guide="检查代理、TLS 和查询服务可用性。检测失败不等于出口位于某个地区。")
