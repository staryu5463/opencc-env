"""固定代理路由与异常回归；仅使用本机临时 HTTP 服务。"""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from opencc_env.core.proxy import ProxyEndpoint,parse_proxy,proxy_candidates,proxy_opener,verify_http_proxy
from opencc_env.core.engine import AuditEngine
from opencc_env.core.base_probe import Severity,Status
from test_engine import FakeProbe


class TestProxyRouting(unittest.TestCase):
    def test_no_proxy_star_does_not_bypass_selected_proxy(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(200);self.end_headers();self.wfile.write(b'{"ip":"203.0.113.1"}')
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            endpoint=ProxyEndpoint("http://127.0.0.1:"+str(server.server_port),"test")
            with patch.dict(os.environ,{"NO_PROXY":"*","no_proxy":"*"}):
                with proxy_opener(endpoint).open("http://example.invalid/route-check",timeout=2) as response:
                    self.assertEqual(json.loads(response.read())["ip"],"203.0.113.1")
            self.assertEqual(requests,["http://example.invalid/route-check"])
        finally:
            server.shutdown();server.server_close();thread.join(2)

    def test_explicit_proxy_returns_only_selected_endpoint(self):
        with patch.dict(os.environ,{"OPENCC_PROXY":"http://127.0.0.1:8989"}):
            endpoints=list(proxy_candidates())
        self.assertEqual(len(endpoints),1);self.assertEqual(endpoints[0].port,8989)

    def test_query_and_fragment_are_rejected(self):
        self.assertIsNone(parse_proxy("http://127.0.0.1:8989?config=1","test"))
        self.assertIsNone(parse_proxy("http://127.0.0.1:8989#fragment","test"))

    def test_failed_proxy_never_reports_verified(self):
        with patch("opencc_env.core.proxy.proxy_opener",side_effect=OSError("offline")):
            ok,_=verify_http_proxy(ProxyEndpoint("http://127.0.0.1:8989","test"))
        self.assertFalse(ok)

    def test_information_probe_error_suppresses_total(self):
        engine=AuditEngine();engine.register_probe(FakeProbe("pass"))
        engine.register_probe(FakeProbe("tz",Status.ERROR,None,Severity.INFO))
        report=engine.run_all()
        self.assertIsNone(report["overall_score"]);self.assertEqual(report["risk_level"],"INCOMPLETE")
