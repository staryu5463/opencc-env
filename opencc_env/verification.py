"""无网络、无系统写入的打包与界面自检，演示数据有明确标记。"""
import json
import os
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from opencc_env.core.base_probe import CheckResult,Status
from opencc_env.core.engine import AuditEngine


def load_test_fonts():
    # Windows 的 offscreen 平台不会自动枚举全部字体，测试时显式加载。
    for name in ("segoeui.ttf","msyh.ttc","seguiemj.ttf"):
        path=Path(os.environ.get("WINDIR",r"C:\Windows"))/"Fonts"/name
        if path.exists():QFontDatabase.addApplicationFont(str(path))


def demo_report(timezone_value="Pacific Standard Time"):
    engine=AuditEngine();engine.auto_discover_probes()
    descriptions={
        "probe_network":(Status.PASS,100,"代理出口查询成功","203.0.113.10 · 界面演示",{"ip":"203.0.113.10","country":"演示数据","proxy":"http://127.0.0.1:8989","runtime_verified":False}),
        "probe_timezone":(Status.INFO,None,"已读取本机时区","界面演示",{"current_timezone":timezone_value,"utc_offset":"UTC-07:00","source":"演示输入"}),
        "probe_shortcut":(Status.PASS,100,"入口代理参数与候选一致","参数核对通过，运行效果未验证",{"target_path":"C:/Demo/Claude.exe","runtime_verified":False}),
        "probe_proxy_rules":(Status.PASS,100,"HTTP 代理请求通过","TUN 网卡信息仅供参考",{"proxy":"http://127.0.0.1:8989","tun_adapter":{"has_tun":True,"is_up":False,"route_verified":False}}),
        "probe_leak":(Status.WARN,85,"代理 DoH 可用，需核对本地解析路由","配置不等于实际泄漏证据",{"dns_servers":["223.5.5.5"],"remote_doh_success":True,"leak_test_performed":False}),
        "probe_cli_settings":(Status.WARN,60,"未设置显式 HTTP 代理","可按实际需要配置 Claude 专用代理",{"settings_path":"C:/Demo/.claude/settings.json","candidate_proxy":"http://127.0.0.1:8989","runtime_verified":False})}
    for probe in engine.probes:
        status,score,title,summary,details=descriptions[probe.id]
        engine.results[probe.id]=CheckResult(probe.id,probe.name,probe.category,status,score,title,summary,details,
            remedy_guide="这是明确标记的界面测试输入，不代表本机实测结论。",
            auto_fixable=probe.id=="probe_cli_settings")
    engine._compute_overall_metrics()
    return {**engine.metrics,"results":engine.results,"checked_at":"2026-10-09T00:00:00+00:00","duration_seconds":0}


def self_test(output_path):
    import uuid
    from PySide6.QtCore import QEventLoop,QTimer,QPoint
    from PySide6.QtWidgets import QStatusBar
    from opencc_env.ui.app_window import MainWindow
    from opencc_env.core.backup import BackupManager
    output=Path(output_path);output.parent.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([]);load_test_fonts()
    original_snapshot=BackupManager.SNAPSHOT_PATH
    BackupManager.SNAPSHOT_PATH=str(output.parent/("isolated-"+uuid.uuid4().hex+".json"))
    window=None
    try:
        window=MainWindow(auto_start=False,preferences_path=output.parent/("interface-"+uuid.uuid4().hex+".json"))
        initial_unknown="—" in window.banner.score_label.text()
        window._on_audit_finished(demo_report())
        window.last_checked.setText("界面演示数据 · 不代表本机实测")
        window.show();app.processEvents()
        screenshots={}
        def settle():
            loop=QEventLoop();QTimer.singleShot(120,loop.quit);loop.exec()
        def capture(name):
            settle();path=output.parent/(name+".png")
            if not window.grab().save(str(path)):raise OSError("截图保存失败")
            screenshots[name]=str(path)
        capture("overview")
        window.show_probe_detail("probe_timezone");app.processEvents()
        timezone_actual="Pacific Standard Time" in window.cards["probe_timezone"].evidence.toPlainText()
        window.collapse_details()
        window.show_probe_detail("probe_proxy_rules");app.processEvents()
        tun_not_running="网卡运行" in window.cards["probe_proxy_rules"].evidence.toPlainText() and "否" in window.cards["probe_proxy_rules"].evidence.toPlainText()
        window.collapse_details();window.show_probe_detail("probe_cli_settings");window.start_fix_single("probe_cli_settings")
        capture("expanded")
        card=window.cards["probe_cli_settings"]
        no_overlap=card.copy_button.mapTo(card.body,QPoint(0,0)).y()>=card.evidence.y()+card.evidence.height()-2
        window.collapse_details();window.toggle_scoring();capture("scoring")
        for index,name in ((1,"tools"),(2,"history"),(3,"settings")):
            window.navigate(index);capture(name)
        window.navigate(0);window.score_table.hide();window.toggle_theme();capture("dark")
        window.toggle_theme();window.resize(780,660);capture("compact")
        checks={"probes":len(window.engine.probes),"discovery_errors":window.engine.discovery_errors,
            "pages":window.pages.count(),"primary_navigation":len(window.nav_buttons),"cards":len(window.cards),
            "no_status_bar":not window.findChildren(QStatusBar),"initial_score_unknown":initial_unknown,
            "actual_timezone_rendered":timezone_actual,"tun_not_claimed_running":tun_not_running,
            "weights_accessible":window.score_table.rowCount()==6,
            "inline_preview":bool(window.preview_context),"compact_navigation":window.sidebar.width()==64}
        checks["inline_layout_no_overlap"]=no_overlap
        checks["passed"]=all((checks["probes"]==6,not checks["discovery_errors"],checks["pages"]==4,
            checks["primary_navigation"]==3,checks["cards"]==6,checks["no_status_bar"],checks["initial_score_unknown"],
            checks["actual_timezone_rendered"],checks["tun_not_claimed_running"],checks["weights_accessible"],
            checks["inline_preview"],checks["compact_navigation"],checks["inline_layout_no_overlap"]))
        output.write_text(json.dumps({"checks":checks,"screenshots":screenshots},ensure_ascii=False,indent=2),encoding="utf-8")
        return checks["passed"]
    finally:
        if window:window.close();app.processEvents()
        BackupManager.SNAPSHOT_PATH=original_snapshot
