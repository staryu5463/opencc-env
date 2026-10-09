"""真实按钮与临时配置闭环；网络、启动目录及用户偏好完全隔离。"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
os.environ["QT_QPA_PLATFORM"]="offscreen"
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QMessageBox,QFileDialog,QStatusBar
from PySide6.QtTest import QTest
from opencc_env.core.backup import BackupManager
from opencc_env.core.base_probe import Status
from opencc_env.core.proxy import ProxyEndpoint
from opencc_env.probes.probe_cli_settings import CliSettingsProbe
from opencc_env.ui.app_window import MainWindow
from opencc_env.verification import demo_report,load_test_fonts


class TestUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);load_test_fonts()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.snapshot_patch=patch.object(BackupManager,"SNAPSHOT_PATH",str(self.root/"snap.json"));self.snapshot_patch.start()
        self.window=MainWindow(auto_start=False,preferences_path=self.root/"interface.json")
        self.window.show();self.window.activateWindow();self.app.processEvents();QTest.qWait(5)

    def tearDown(self):
        self.wait_idle();self.window.close();self.app.processEvents();self.snapshot_patch.stop();self.temp.cleanup()

    def click(self,widget):
        self.app.processEvents()
        if self.window.cards_container.isAncestorOf(widget):
            self.window.scroll_area.ensureWidgetVisible(widget,0,20)
        self.app.processEvents()
        QTest.mouseClick(widget,Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def wait_idle(self):
        deadline=time.monotonic()+8
        while self.window._busy and time.monotonic()<deadline:QTest.qWait(10)
        self.assertFalse(self.window._busy)

    def display(self,report=None):
        report=report or demo_report()
        self.window.engine.results=dict(report["results"]);self.window.engine._compute_overall_metrics()
        self.window._on_audit_finished(report);self.app.processEvents()
        return report

    def test_no_status_bar_and_initial_score_unknown(self):
        self.assertFalse(self.window.findChildren(QStatusBar))
        self.assertIn("—",self.window.banner.score_label.text());self.assertFalse(self.window.console.isVisible())

    def test_three_primary_pages_and_settings(self):
        self.assertEqual([b.text() for b in self.window.nav_buttons],["检测","工具","历史"])
        for index,button in enumerate(self.window.nav_buttons):
            self.click(button);self.assertEqual(self.window.pages.currentIndex(),index)
        self.click(self.window.settings_button)
        self.assertEqual(self.window.pages.currentIndex(),3)

    def test_whole_row_expands_without_navigation(self):
        self.display();card=self.window.cards["probe_leak"]
        self.click(card.header)
        self.assertTrue(card.body.isVisible());self.assertEqual(self.window.pages.currentIndex(),0)
        self.assertIn("223.5.5.5",card.evidence.toPlainText())
        self.assertIn("归一化占比",card.evidence.toPlainText())
        self.assertGreater(card.name_label.height(),0)
        self.click(card.header);self.assertFalse(card.body.isVisible())

    def test_actual_timezone_and_tun_remain_in_details(self):
        self.display();self.window.show_probe_detail("probe_timezone")
        self.assertIn("Pacific Standard Time",self.window.cards["probe_timezone"].evidence.toPlainText())
        self.window.show_probe_detail("probe_proxy_rules")
        text=self.window.cards["probe_proxy_rules"].evidence.toPlainText()
        self.assertIn("网卡运行",text);self.assertIn("否",text)

    def test_scoring_and_raw_evidence_remain_accessible(self):
        self.display();self.click(self.window.weight_button)
        self.assertTrue(self.window.score_table.isVisible());self.assertEqual(self.window.score_table.rowCount(),6)
        self.window.show_probe_detail("probe_leak");card=self.window.cards["probe_leak"]
        self.click(card.raw_button)
        self.assertIn("weight_percent",card.evidence.toPlainText())

    def test_full_parameters_are_available_on_request(self):
        report=demo_report();report["results"]["probe_network"].details["query_service"]="https://example.invalid/evidence"
        self.display(report);self.window.show_probe_detail("probe_network");card=self.window.cards["probe_network"]
        self.assertNotIn("https://example.invalid/evidence",card.evidence.toPlainText())
        self.click(card.full_button)
        self.assertIn("https://example.invalid/evidence",card.evidence.toPlainText())

    def test_escape_collapses_details(self):
        self.display();self.window.show_probe_detail("probe_cli_settings")
        QTest.keyClick(self.window,Qt.Key.Key_Escape)
        self.assertFalse(self.window.cards["probe_cli_settings"].body.isVisible())

    def test_keyboard_space_opens_focused_row(self):
        self.display();card=self.window.cards["probe_leak"];card.header.setFocus()
        QTest.keyClick(card.header,Qt.Key.Key_Space)
        self.assertTrue(card.body.isVisible())

    def test_copy_parameters_redacts_credentials(self):
        report=demo_report();report["results"]["probe_network"].details["proxy"]="http://user:secret@127.0.0.1:8989"
        self.display(report);clipboard=Mock()
        self.window.show_probe_detail("probe_network")
        with patch.object(QApplication,"clipboard",return_value=clipboard):
            self.click(self.window.cards["probe_network"].copy_button)
        copied=clipboard.setText.call_args.args[0]
        self.assertNotIn("secret",copied);self.assertIn("127.0.0.1",copied)

    def test_open_configuration_directory(self):
        report=demo_report();report["results"]["probe_cli_settings"].details["settings_path"]=str(self.root/"settings.json")
        self.display(report);self.window.show_probe_detail("probe_cli_settings")
        with patch("opencc_env.ui.app_window.QDesktopServices.openUrl",return_value=True) as action:
            self.click(self.window.cards["probe_cli_settings"].path_button)
        self.assertEqual(Path(action.call_args.args[0].toLocalFile()),self.root)

    def test_preview_and_cancel_do_not_write(self):
        self.display();self.window.show_probe_detail("probe_cli_settings");card=self.window.cards["probe_cli_settings"]
        with patch.object(self.window.engine,"run_fix_single") as action:
            self.click(card.fix_button)
            self.assertTrue(card.preview.isVisible());self.assertIn("8989",card.preview_text.text())
            self.click(card.cancel_button)
        action.assert_not_called();self.assertFalse(card.preview.isVisible())

    def test_candidate_change_blocks_application(self):
        self.display();self.window.show_probe_detail("probe_cli_settings");self.window.start_fix_single("probe_cli_settings")
        with patch("opencc_env.core.proxy.get_proxy_endpoint",return_value=ProxyEndpoint("http://127.0.0.1:8990","test")),patch.object(self.window.engine,"run_fix_single") as action:
            self.click(self.window.cards["probe_cli_settings"].apply_button);self.wait_idle()
        action.assert_not_called();self.assertIn("代理候选已变化",self.window.cards["probe_cli_settings"].operation_label.text())

    def test_temp_configuration_fix_recheck_and_restore_full_flow(self):
        path=self.root/"settings.json";original=b'{"model":"preserved"}\r\n';path.write_bytes(original)
        probe=CliSettingsProbe(path);endpoint=ProxyEndpoint("http://127.0.0.1:8989","test")
        self.window.engine.probes=[probe]
        with patch.object(probe,"_is_cli_installed",return_value=True),patch("opencc_env.probes.probe_cli_settings.get_proxy_endpoint",return_value=endpoint),patch("opencc_env.core.proxy.get_proxy_endpoint",return_value=endpoint),patch("opencc_env.probes.probe_cli_settings.verify_http_proxy",return_value=(True,"fixture")),patch.dict(os.environ,{"HTTP_PROXY":"","HTTPS_PROXY":"","NO_PROXY":""}):
            self.display(self.window.engine.run_all());self.window.show_probe_detail(probe.id)
            self.click(self.window.cards[probe.id].fix_button)
            self.click(self.window.cards[probe.id].apply_button);self.wait_idle()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["env"]["HTTPS_PROXY"],endpoint.url)
            self.assertEqual(self.window.report["results"][probe.id].status,Status.PASS)
            self.assertTrue(self.window.cards[probe.id].body.isVisible())
            self.click(self.window.cards[probe.id].history_button)
            self.assertEqual(self.window.pages.currentIndex(),2);self.assertTrue(self.window.btn_restore.isEnabled())
            with patch.object(QMessageBox,"question",return_value=QMessageBox.StandardButton.Yes):
                self.click(self.window.btn_restore);self.wait_idle()
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(self.window.report["results"][probe.id].status,Status.WARN)

    def test_recheck_labels_previous_results_and_blocks_modification(self):
        self.display();self.window.show_probe_detail("probe_cli_settings");self.window.start_fix_single("probe_cli_settings")
        with patch.object(self.window.engine,"run_all",side_effect=lambda **kwargs:(time.sleep(.08) or demo_report())):
            self.window.start_audit()
            self.assertIn("上次结果",self.window.last_checked.text())
            self.assertFalse(self.window.cards["probe_cli_settings"].preview.isVisible())
            self.assertFalse(self.window.cards["probe_cli_settings"].fix_button.isEnabled());self.wait_idle()

    def test_f5_and_double_click_start_only_once(self):
        with patch.object(self.window.engine,"run_all",side_effect=lambda **kwargs:(time.sleep(.05) or demo_report())) as action:
            QTest.keyClick(self.window,Qt.Key.Key_F5);self.assertTrue(self.window._busy)
            self.window.start_audit();self.wait_idle()
        self.assertEqual(action.call_count,1)

    def test_worker_failure_recovers_controls(self):
        with patch.object(self.window.engine,"run_all",side_effect=OSError("injected failure")):
            self.window.start_audit();self.wait_idle()
        self.assertTrue(self.window.banner.btn_audit.isEnabled());self.assertIn("未完成",self.window.last_checked.text())

    def test_expansion_survives_refresh(self):
        self.display();self.window.show_probe_detail("probe_leak");self.display()
        self.assertTrue(self.window.cards["probe_leak"].body.isVisible())

    def test_expanded_evidence_does_not_overlap_actions(self):
        from PySide6.QtCore import QPoint
        self.display();self.window.show_probe_detail("probe_cli_settings");QTest.qWait(150)
        card=self.window.cards["probe_cli_settings"]
        self.assertGreaterEqual(card.copy_button.mapTo(card.body,QPoint(0,0)).y(),card.evidence.y()+card.evidence.height()-2)
        self.window.collapse_details();QTest.qWait(150)
        self.assertLess(card.height(),110)

    def test_narrow_window_collapses_navigation(self):
        self.display();self.window.resize(780,660);self.app.processEvents()
        self.assertEqual(self.window.sidebar.width(),64);self.assertEqual(self.window.nav_buttons[0].text(),"")
        self.assertGreater(self.window.cards["probe_leak"].name_label.height(),0)
        self.window.resize(1180,820);self.app.processEvents();self.assertEqual(self.window.sidebar.width(),204)

    def test_legacy_snapshot_restore_is_disabled(self):
        Path(BackupManager.SNAPSHOT_PATH).write_text(json.dumps({"cli_env":{"data":{"HTTP_PROXY":"http://127.0.0.1:9999"}}}),encoding="utf-8")
        self.window.navigate(2);self.window.snapshot_tree.setCurrentItem(self.window.snapshot_tree.topLevelItem(0))
        self.app.processEvents();self.assertFalse(self.window.btn_restore.isEnabled())

    def test_preferences_persist_only_in_supplied_path(self):
        self.window.toggle_theme();self.window.toggle_sidebar();self.window.close()
        data=json.loads((self.root/"interface.json").read_text(encoding="utf-8"))
        self.assertEqual(data["theme"],"dark");self.assertTrue(data["sidebar_collapsed"])
        new=MainWindow(False,self.root/"interface.json")
        self.assertEqual(new.mode,"dark");self.assertTrue(new.sidebar_collapsed);new.close()

    def test_theme_and_log_toggle(self):
        self.window.toggle_theme();self.assertEqual(self.window.mode,"dark")
        self.click(self.window.log_button);self.assertTrue(self.window.console.isVisible())
        self.click(self.window.log_button);self.assertFalse(self.window.console.isVisible())

    def test_export_contains_actual_parameters(self):
        self.display();path=self.root/"report.json"
        with patch.object(QFileDialog,"getSaveFileName",return_value=(str(path),"JSON")):
            self.window.export_report()
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["results"]["probe_timezone"]["details"]["current_timezone"],"Pacific Standard Time")
