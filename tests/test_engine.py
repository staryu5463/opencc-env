"""引擎、异常判定及快照测试；所有写入限定在临时目录。"""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from opencc_env.core.base_probe import BaseProbe,CheckResult,Severity,Status
from opencc_env.core.backup import BackupManager
from opencc_env.core.engine import AuditEngine
from opencc_env.core.proxy import ProxyEndpoint
from opencc_env.probes.probe_timezone import TimezoneProbe
from opencc_env.probes.probe_leak import LeakProbe


class FakeProbe(BaseProbe):
    auto_fixable=True
    def __init__(self,pid,status=Status.PASS,score=100,level=Severity.HIGH):
        self.id=pid;self.name=pid;self.status=status;self.score=score;self.level=level
    def run_check(self):
        return CheckResult(self.id,self.name,"Test",self.status,self.score,"测试","测试",auto_fixable=True)
    def run_fix(self):
        return True,"命令返回成功"


class TestEngine(unittest.TestCase):
    def test_discovery_loads_six(self):
        engine=AuditEngine();engine.auto_discover_probes()
        self.assertEqual(len(engine.probes),6)
        self.assertEqual(engine.discovery_errors,[])

    def test_empty_engine_not_safe(self):
        result=AuditEngine().run_all()
        self.assertIsNone(result["overall_score"])
        self.assertEqual(result["risk_level"],"NOT_CHECKED")

    def test_failure_cannot_be_hidden_by_score(self):
        engine=AuditEngine()
        for i in range(5):engine.register_probe(FakeProbe(str(i)))
        engine.register_probe(FakeProbe("failure",Status.FAIL,40))
        result=engine.run_all()
        self.assertGreaterEqual(result["overall_score"],85)
        self.assertEqual(result["risk_level"],"ISSUES")

    def test_unknown_suppresses_total_score(self):
        engine=AuditEngine();engine.register_probe(FakeProbe("unknown",Status.ERROR,None))
        engine.register_probe(FakeProbe("pass"))
        result=engine.run_all()
        self.assertIsNone(result["overall_score"])
        self.assertEqual(result["risk_level"],"INCOMPLETE")

    def test_information_and_not_applicable_excluded(self):
        engine=AuditEngine();engine.register_probe(FakeProbe("pass"))
        engine.register_probe(FakeProbe("tz",Status.INFO,None,Severity.INFO))
        engine.register_probe(FakeProbe("absent",Status.NOT_APPLICABLE,None))
        result=engine.run_all()
        self.assertEqual(result["overall_score"],100)
        self.assertEqual(sum(r["weight_percent"] for r in result["scoring"]),100)
        self.assertFalse(result["scoring"][1]["included"])
        self.assertFalse(result["scoring"][2]["included"])

    def test_duplicate_id_rejected(self):
        engine=AuditEngine();engine.register_probe(FakeProbe("same"))
        with self.assertRaises(ValueError):engine.register_probe(FakeProbe("same"))

    def test_fix_requires_verified_pass(self):
        engine=AuditEngine();probe=FakeProbe("fail",Status.FAIL,0);engine.register_probe(probe);engine.run_all()
        ok,msg=engine.run_fix_single("fail")
        self.assertFalse(ok)
        self.assertIn("复查",msg)

    def test_batch_requires_explicit_selection(self):
        result=AuditEngine().run_fix_all()
        self.assertFalse(result[0]["success"])

    def test_timezone_failure_is_error(self):
        with patch("opencc_env.probes.probe_timezone.read_timezone",side_effect=OSError("denied")):
            result=TimezoneProbe().run_check()
        self.assertEqual(result.status,Status.ERROR);self.assertIsNone(result.score)

    def test_timezone_reports_actual_value_and_is_info(self):
        with patch("opencc_env.probes.probe_timezone.read_timezone",return_value="Pacific Standard Time"):
            result=TimezoneProbe().run_check()
        self.assertEqual(result.details["current_timezone"],"Pacific Standard Time")
        self.assertEqual(result.status,Status.INFO);self.assertFalse(result.auto_fixable)

    def test_dns_failure_not_full_marks(self):
        with patch.object(LeakProbe,"_get_system_dns_servers",return_value=[]):
            result=LeakProbe().run_check()
        self.assertEqual(result.status,Status.ERROR);self.assertIsNone(result.score)

    def test_doh_failure_not_pass(self):
        with patch.object(LeakProbe,"_get_system_dns_servers",return_value=["1.1.1.1"]),patch("opencc_env.probes.probe_leak.get_proxy_endpoint",return_value=ProxyEndpoint("http://127.0.0.1:8989","test")),patch.object(LeakProbe,"_test_remote_doh",side_effect=OSError("offline")):
            result=LeakProbe().run_check()
        self.assertEqual(result.status,Status.ERROR);self.assertFalse(result.details["remote_doh_success"])


class TestSnapshots(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/"snapshot.json"
        self.patcher=patch.object(BackupManager,"SNAPSHOT_PATH",str(self.path));self.patcher.start()
    def tearDown(self):
        self.patcher.stop();self.temp.cleanup()

    def test_history_preserves_every_capture(self):
        self.assertTrue(BackupManager.save_snapshot("same",{"value":1}))
        self.assertTrue(BackupManager.save_snapshot("same",{"value":2}))
        history=BackupManager.get_history()
        self.assertEqual(len(history),2);self.assertEqual(history[0]["data"],{"value":1})

    def test_parallel_saves_are_not_lost(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda i:BackupManager.save_snapshot("key",i),range(24)))
        self.assertTrue(all(results));self.assertEqual(len(BackupManager.get_history()),24)

    def test_corrupt_snapshot_blocks_write(self):
        self.path.write_text("broken",encoding="utf-8")
        self.assertFalse(BackupManager.save_snapshot("new",1))
        self.assertEqual(self.path.read_text(encoding="utf-8"),"broken")

    def test_legacy_snapshot_cannot_modify_registry(self):
        self.path.write_text(json.dumps({"cli_env":{"timestamp":"","data":{"HTTP_PROXY":"http://127.0.0.1:9999"}}}),encoding="utf-8")
        with patch("winreg.OpenKey") as writer:
            ok,msg=BackupManager.rollback_cli_env()
        self.assertFalse(ok);writer.assert_not_called()
        self.assertFalse(BackupManager.get_history()[0]["restorable"])
