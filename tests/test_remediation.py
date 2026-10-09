"""配置、缓存和原生快捷方式的隔离修改—复查—还原测试。"""
import codecs
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from opencc_env.core.backup import BackupManager
from opencc_env.core.proxy import ProxyEndpoint
from opencc_env.core.windows import read_shortcut,write_shortcut,ps_literal
from opencc_env.probes.probe_cli_settings import CliSettingsProbe
from opencc_env.probes.probe_shortcut import ShortcutProbe
from opencc_env.core.base_probe import Status
from opencc_env.remediation.cache_cleaner import CacheCleaner
from opencc_env.remediation.startup_fixer import StartupFixer
from opencc_env.remediation.guides import ExpertGuideManager

ENDPOINT=ProxyEndpoint("http://127.0.0.1:8989","隔离测试")


class TestRemediation(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.snapshot_patch=patch.object(BackupManager,"SNAPSHOT_PATH",str(self.root/"snapshots.json"));self.snapshot_patch.start()
        self.env_patch=patch.dict(os.environ,{"HTTP_PROXY":"","HTTPS_PROXY":"","NO_PROXY":"","APPDATA":str(self.root/"Roaming"),"LOCALAPPDATA":str(self.root/"Local")});self.env_patch.start()
    def tearDown(self):
        self.env_patch.stop();self.snapshot_patch.stop();self.temp.cleanup()

    def cli(self):
        path=self.root/".claude"/"settings.json";path.parent.mkdir(exist_ok=True)
        probe=CliSettingsProbe(path)
        return path,probe

    def test_cli_fix_and_byte_exact_restore(self):
        path,probe=self.cli()
        original=codecs.BOM_UTF8+b'{\r\n  "other": true,\r\n  "env": {"NO_PROXY": "localhost,.claude.ai"}\r\n}\r\n'
        path.write_bytes(original)
        with patch.object(probe,"_is_cli_installed",return_value=True),patch("opencc_env.probes.probe_cli_settings.get_proxy_endpoint",return_value=ENDPOINT),patch("opencc_env.probes.probe_cli_settings.verify_http_proxy",return_value=(True,"ok")):
            ok,msg=probe.run_fix();self.assertTrue(ok,msg)
            self.assertEqual(probe.run_check().status,Status.PASS)
        current=path.read_bytes();self.assertTrue(current.startswith(codecs.BOM_UTF8));self.assertIn(b"\r\n",current)
        self.assertTrue(json.loads(current.decode("utf-8-sig"))["other"])
        ok,msg=BackupManager.rollback_cli_settings();self.assertTrue(ok,msg)
        self.assertEqual(path.read_bytes(),original)

    def test_cli_backup_failure_prevents_write(self):
        path,probe=self.cli()
        with patch.object(probe,"_is_cli_installed",return_value=True),patch("opencc_env.probes.probe_cli_settings.get_proxy_endpoint",return_value=ENDPOINT),patch("opencc_env.probes.probe_cli_settings.verify_http_proxy",return_value=(True,"ok")),patch.object(BackupManager,"save_snapshot",return_value=False):
            self.assertFalse(probe.run_fix()[0])
        self.assertFalse(path.exists())

    def test_cli_external_change_blocks_restore(self):
        path,probe=self.cli()
        with patch.object(probe,"_is_cli_installed",return_value=True),patch("opencc_env.probes.probe_cli_settings.get_proxy_endpoint",return_value=ENDPOINT),patch("opencc_env.probes.probe_cli_settings.verify_http_proxy",return_value=(True,"ok")):
            self.assertTrue(probe.run_fix()[0])
        path.write_text('{"later":true}',encoding="utf-8")
        self.assertFalse(BackupManager.rollback_cli_settings()[0]);self.assertIn("later",path.read_text(encoding="utf-8"))

    def test_mismatched_https_is_not_pass(self):
        path,probe=self.cli()
        path.write_text(json.dumps({"env":{"HTTP_PROXY":ENDPOINT.url,"HTTPS_PROXY":"http://127.0.0.1:9999"}}),encoding="utf-8")
        with patch.object(probe,"_is_cli_installed",return_value=True),patch("opencc_env.probes.probe_cli_settings.get_proxy_endpoint",return_value=ENDPOINT):
            result=probe.run_check()
        self.assertEqual(result.status,Status.WARN)

    def test_no_cli_not_applicable(self):
        _,probe=self.cli()
        with patch.object(probe,"_is_cli_installed",return_value=False):
            result=probe.run_check()
        self.assertEqual(result.status,Status.NOT_APPLICABLE);self.assertFalse(result.auto_fixable)

    def test_missing_desktop_does_not_raise(self):
        probe=ShortcutProbe()
        with patch.object(probe,"_find_claude_shortcuts",return_value=[]),patch.object(probe,"_locate_claude_exe",return_value=None),patch.object(probe,"_get_search_paths",return_value=[]):
            result=probe.run_check()
        self.assertEqual(result.status,Status.NOT_APPLICABLE)

    def test_native_shortcut_fix_restore_preserves_other_arguments(self):
        exe=self.root/"claude.exe";exe.write_bytes(b"not executed")
        path=self.root/"Claude.lnk";original={"target_path":str(exe),"arguments":"--original=value --lang=zh-CN","working_directory":str(self.root)}
        self.assertTrue(write_shortcut(path,original))
        probe=ShortcutProbe()
        with patch.object(probe,"_find_claude_shortcuts",return_value=[str(path)]),patch("opencc_env.probes.probe_shortcut.get_proxy_endpoint",return_value=ENDPOINT),patch("opencc_env.probes.probe_shortcut.verify_http_proxy",return_value=(True,"ok")):
            ok,msg=probe.run_fix();self.assertTrue(ok,msg)
            self.assertEqual(probe.run_check().status,Status.PASS)
        self.assertIn("--original=value",read_shortcut(path)["arguments"])
        ok,msg=BackupManager.rollback_shortcut();self.assertTrue(ok,msg)
        restored=read_shortcut(path)
        self.assertEqual(restored["target_path"],str(exe));self.assertEqual(restored["arguments"],original["arguments"])

    def test_ps_literal_escapes_quote(self):
        self.assertEqual(ps_literal("C:/O'Brien"),"'C:/O''Brien'")

    def make_cache(self):
        folder=self.root/"Roaming"/"Claude"/"GPUCache";folder.mkdir(parents=True);(folder/"data").write_bytes(b"original")
        return folder

    def test_cache_isolated_and_restored_with_original_data(self):
        folder=self.make_cache()
        with patch.object(CacheCleaner,"is_claude_running",return_value=False):
            ok,msg=CacheCleaner.clean_cache();self.assertTrue(ok,msg);self.assertFalse(folder.exists())
            ok,msg=BackupManager.rollback_cache();self.assertTrue(ok,msg)
        self.assertEqual((folder/"data").read_bytes(),b"original")

    def test_failed_cache_move_not_reported_success(self):
        folder=self.make_cache()
        with patch.object(CacheCleaner,"is_claude_running",return_value=False),patch("opencc_env.remediation.cache_cleaner.shutil.move",return_value=None):
            ok,msg=CacheCleaner.clean_cache()
        self.assertFalse(ok);self.assertTrue(folder.exists())

    def test_running_client_prevents_cache_operation(self):
        folder=self.make_cache()
        with patch.object(CacheCleaner,"is_claude_running",return_value=True):
            self.assertFalse(CacheCleaner.clean_cache()[0])
        self.assertTrue(folder.exists());self.assertEqual(BackupManager.get_history(),[])

    def test_new_cache_blocks_restore(self):
        folder=self.make_cache()
        with patch.object(CacheCleaner,"is_claude_running",return_value=False):
            self.assertTrue(CacheCleaner.clean_cache()[0]);folder.mkdir();(folder/"new").write_bytes(b"new")
            self.assertFalse(BackupManager.rollback_cache()[0])
        self.assertEqual((folder/"new").read_bytes(),b"new")

    def test_startup_no_selection_cannot_write(self):
        with patch("winreg.DeleteValue") as mutation:
            self.assertFalse(StartupFixer.remove_unprotected_startup()[0])
        mutation.assert_not_called()

    def test_guides_no_fake_statistics(self):
        guides=ExpertGuideManager.get_all_guides();self.assertEqual(len(guides),4)
        self.assertNotIn("95%",str(guides));self.assertNotIn("Business Trip",str(guides))
