"""发现本机代理候选，并区分配置值、端口可连接与 HTTP 实测。"""
import json
import os
import socket
import urllib.request
import winreg
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

COMMON_PROXY_PORTS = (7897, 7890, 10809, 8080)


@dataclass(frozen=True)
class ProxyEndpoint:
    url: str
    source: str

    @property
    def host(self):
        return urlsplit(self.url).hostname

    @property
    def port(self):
        parsed = urlsplit(self.url)
        return parsed.port or (443 if parsed.scheme == "https" else 80)

    @property
    def display(self):
        parsed = urlsplit(self.url)
        host = "[" + parsed.hostname + "]" if ":" in parsed.hostname else parsed.hostname
        return parsed.scheme + "://" + host + ":" + str(self.port)


def parse_proxy(value, source):
    try:
        if not value:
            return None
        if "://" not in value:
            value = "http://" + value
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            return None
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            return None
        return ProxyEndpoint(value.rstrip("/"), source)
    except (ValueError, TypeError):
        return None


def port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def read_system_proxy():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            try:
                enabled = bool(winreg.QueryValueEx(key, "ProxyEnable")[0])
            except FileNotFoundError:
                enabled = False
            values = {"enabled": enabled, "server": "", "pac_url": ""}
            for name, target in (("ProxyServer", "server"), ("AutoConfigURL", "pac_url")):
                try:
                    values[target] = str(winreg.QueryValueEx(key, name)[0])
                except FileNotFoundError:
                    pass
            return values
    except OSError as exc:
        return {"enabled": None, "server": "", "pac_url": "", "error": str(exc)}


def proxy_candidates():
    candidates = []
    explicit = os.environ.get("OPENCC_PROXY")
    if explicit:
        item = parse_proxy(explicit, "工具指定代理")
        if item:
            yield item
        return
    try:
        settings = json.loads((Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8-sig"))
        for name in ("HTTPS_PROXY", "HTTP_PROXY"):
            candidates.append(parse_proxy(settings.get("env", {}).get(name), "Claude 用户设置"))
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    for name in ("HTTPS_PROXY", "HTTP_PROXY"):
        candidates.append(parse_proxy(os.environ.get(name), "当前进程环境"))
    system = read_system_proxy()
    if system["enabled"]:
        server = system["server"]
        pieces = server.split(";")
        for piece in sorted(pieces, key=lambda x: not x.startswith("https=")):
            candidates.append(parse_proxy(piece.split("=", 1)[-1], "Windows 系统代理"))
    for port in COMMON_PROXY_PORTS:
        candidates.append(ProxyEndpoint("http://127.0.0.1:" + str(port), "本机常用端口"))
    seen = set()
    for item in candidates:
        if item and item.url not in seen:
            seen.add(item.url)
            yield item


def get_proxy_endpoint():
    for endpoint in proxy_candidates():
        if port_open(endpoint.host, endpoint.port):
            return endpoint
    return None


class StrictProxyHandler(urllib.request.ProxyHandler):
    """检测请求固定经过指定代理，不继承系统或 NO_PROXY 的绕过规则。"""
    def proxy_open(self, request, proxy, protocol):
        import base64
        from urllib.parse import unquote
        original_type = request.type
        parsed = urlsplit(proxy)
        proxy_type = parsed.scheme or original_type
        if parsed.username is not None:
            pair = unquote(parsed.username) + ":" + unquote(parsed.password or "")
            credentials = base64.b64encode(pair.encode("utf-8")).decode("ascii")
            request.add_header("Proxy-authorization", "Basic " + credentials)
        request.set_proxy(parsed.netloc.rsplit("@", 1)[-1], proxy_type)
        if original_type == proxy_type or original_type == "https":
            return None
        return self.parent.open(request, timeout=request.timeout)


def proxy_opener(endpoint):
    """显式使用候选代理，不继承其他代理设置、不自动回退直连。"""
    return urllib.request.build_opener(StrictProxyHandler({"http": endpoint.url, "https": endpoint.url}))


def verify_http_proxy(endpoint):
    request = urllib.request.Request("https://api.ipify.org?format=json", headers={"User-Agent": "OpenCC-Env/2"})
    try:
        with proxy_opener(endpoint).open(request, timeout=6) as response:
            data = json.loads(response.read(65536).decode("utf-8"))
            import ipaddress
            ipaddress.ip_address(data["ip"])
        return True, "已通过此代理完成 HTTPS 请求"
    except Exception as exc:
        return False, "候选代理未通过 HTTP/HTTPS 实测：" + str(exc)
