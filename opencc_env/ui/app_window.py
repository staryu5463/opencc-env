"""状态驱动的桌面工作台：统一导航、参数证据、评分明细、修复预览和逐次快照。"""
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt,QThread,Signal,QTimer,QUrl,QPoint
from PySide6.QtGui import QShortcut,QKeySequence,QDesktopServices
from PySide6.QtWidgets import (QMainWindow,QWidget,QFrame,QHBoxLayout,QVBoxLayout,QStackedWidget,
    QPushButton,QButtonGroup,QLabel,QScrollArea,QTextBrowser,QTreeWidget,QTreeWidgetItem,QTableWidget,QApplication,
    QTableWidgetItem,QHeaderView,QSplitter,QAbstractItemView,QMessageBox,QCheckBox,QFileDialog)
from opencc_env.core.base_probe import Status
from opencc_env.core.engine import AuditEngine
from opencc_env.core.backup import BackupManager
from opencc_env.core.windows import is_admin
from opencc_env.remediation.cache_cleaner import CacheCleaner
from opencc_env.remediation.startup_fixer import StartupFixer
from opencc_env.remediation.guides import ExpertGuideManager
from opencc_env.ui.components import ScoreBanner,ProbeCard,OutputConsole,STATE_TEXT,label
from opencc_env.ui.theme import theme_qss,PALETTES
from opencc_env.ui.icons import icon
from opencc_env.ui.cards import ProbeCard
from opencc_env.ui.preferences import Preferences

KEY_NAMES={"shortcut":"客户端入口","cli_settings":"Claude 用户配置","cli_env":"用户代理变量",
           "timezone":"系统时区","cache":"渲染缓存隔离","startup":"当前用户启动项"}
PRIORITY={Status.FAIL:0,Status.ERROR:1,Status.WARN:2,Status.PASS:3,Status.INFO:4,Status.NOT_APPLICABLE:5}


def safe_text(value):
    text=json.dumps(value,ensure_ascii=False,indent=2,default=str) if not isinstance(value,str) else value
    return re.sub(r"(https?://)[^\s/\"]+@",r"\1***@",text)



FIELD_NAMES={"ip":"出口 IP","country":"地区","city":"城市","org":"网络归属","proxy":"代理地址",
"proxy_source":"代理来源","candidate_proxy":"代理候选","candidate_source":"候选来源","query_service":"查询服务",
"current_timezone":"系统时区","utc_offset":"UTC 偏移","source":"数据来源","target_path":"启动目标",
"arguments":"启动参数","shortcut_path":"快捷方式路径","all_shortcuts":"找到的入口","runtime_verified":"已验证应用实际流量",
"route_verified":"已验证流量路由","direct_fallback":"允许直连回退","limitation":"验证范围",
"dns_servers":"网卡 DNS 地址","remote_doh_success":"代理 DoH 验证通过","remote_doh_answers":"DoH 地址记录",
"known_domestic_dns":"国内公共 DNS 配置","leak_test_performed":"已完成泄漏验证","ipv6_dns_configuration_checked":"已检查 IPv6 DNS 配置",
"settings_path":"用户配置文件","settings_exists":"配置文件存在","cli_found":"找到 CLI","lookup":"查找范围",
"proxy_values":"当前代理变量","no_proxy":"代理绕过设置","http_verified":"HTTP 代理实测通过",
"registry_proxy":"Windows 系统代理","enabled":"启用状态","server":"代理地址","pac_url":"PAC 地址",
"tun_adapter":"TUN 网卡信息","has_tun":"发现候选网卡","is_up":"网卡运行","adapters":"网卡列表",
"error":"读取错误","dns_error":"DNS 读取错误","doh_error":"DoH 请求错误"}


def parameter_rows(data,prefix=""):
    rows=[]
    for key,value in data.items():
        name=FIELD_NAMES.get(key,key);name=prefix+name
        if isinstance(value,dict):
            rows.extend(parameter_rows(value,name+" / "))
        else:
            if isinstance(value,bool):text="是" if value else "否"
            elif value is None:text="未取得"
            elif isinstance(value,list):text="；".join(safe_text(v) for v in value) or "无"
            else:text=safe_text(str(value)) or "未设置"
            rows.append((name,text))
    return rows


def html_table(rows,color):
    return '<table width="100%" cellspacing="0" cellpadding="7">'+"".join(
        '<tr><td width="32%" style="color:'+color+'">'+html.escape(str(name))+
        '</td><td>'+html.escape(str(value))+'</td></tr>' for name,value in rows)+"</table>"

class TaskWorker(QThread):
    completed=Signal(object)
    failed=Signal(str)
    progress=Signal(object)
    def __init__(self,action,parent=None):
        super().__init__(parent);self.action=action
    def run(self):
        try:self.completed.emit(self.action())
        except Exception as exc:self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def toggle_sidebar(self):
        self.sidebar_collapsed=not self.sidebar_collapsed
        self._update_sidebar()

    def _update_sidebar(self):
        compact=self.sidebar_collapsed or self.width()<900
        self.sidebar.setFixedWidth(64 if compact else 204)
        self.brand.setVisible(not compact)
        for button,(title,_) in zip(self.nav_buttons,self.nav_specs):
            button.setText("" if compact else title)
            button.setProperty("compact",compact);button.style().unpolish(button);button.style().polish(button)
        self.settings_button.setText("" if compact else "设置与帮助")
        self.settings_button.setProperty("compact",compact);self.settings_button.style().unpolish(self.settings_button);self.settings_button.style().polish(self.settings_button)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,"sidebar"):self._update_sidebar()

    def collapse_details(self):
        for card in self.cards.values():
            card.preview.hide();card.set_expanded(False)
        self.score_table.hide();self.weight_button.setText("评分依据")

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:
            self.collapse_details();event.accept();return
        super().keyPressEvent(event)

    def toggle_scoring(self):
        visible=not self.score_table.isVisible()
        self.score_table.setVisible(visible)
        self.weight_button.setText("收起评分" if visible else "评分依据")

    def _render_cards(self):
        position=self.scroll_area.verticalScrollBar().value()
        while self.rows_layout.count():
            item=self.rows_layout.takeAt(0)
            if item.widget():item.widget().hide();item.widget().deleteLater()
        self.cards={}
        ordered=sorted(self.report["results"].values(),key=lambda r:(PRIORITY[r.status],r.probe_name))
        for result in ordered:
            pid=result.probe_id;card=ProbeCard(result);self.cards[pid]=card
            card.expanded.connect(self._expanded)
            card.raw_requested.connect(self.toggle_evidence)
            card.full_requested.connect(self.toggle_full_parameters)
            card.copy_requested.connect(self.copy_parameters)
            card.path_requested.connect(self.open_parameter_directory)
            card.fix_requested.connect(self.start_fix_single)
            card.apply_requested.connect(self._apply_preview)
            card.history_requested.connect(self.show_item_history)
            self.rows_layout.addWidget(card);card.set_busy(self._busy)
            if pid in self.operation_results:card.set_operation(*self.operation_results[pid])
            if pid in self.expanded_ids:card.set_expanded(True)
        if not ordered:self.rows_layout.addWidget(label("本轮没有加载检测项目。","muted"))
        QTimer.singleShot(0,lambda:self.scroll_area.verticalScrollBar().setValue(position))

    def _expanded(self,pid,value):
        if value:
            self.expanded_ids.add(pid);self._display_evidence(pid)
        else:self.expanded_ids.discard(pid)

    def toggle_full_parameters(self,pid):
        card=self.cards[pid];card.full=not card.full
        card.full_button.setText("关键参数" if card.full else "完整参数")
        self._display_evidence(pid)

    def copy_parameters(self,pid):
        if self.report and pid in self.report["results"]:
            QApplication.clipboard().setText(safe_text(self.report["results"][pid].details))
            self.cards[pid].copy_button.setText("已复制")

    def open_parameter_directory(self,pid):
        result=self.report["results"].get(pid) if self.report else None
        if not result:return
        value=next((result.details.get(k) for k in ("settings_path","shortcut_path","target_path") if result.details.get(k)),None)
        if not value:return
        folder=Path(value).parent
        if folder.is_dir():QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        else:
            card=self.cards[pid];card.operation_label.setText("所在目录不存在或无法访问。");card.operation_label.show()

    def show_item_history(self,pid):
        self.navigate(2)
        key={"probe_cli_settings":"cli_settings","probe_shortcut":"shortcut"}.get(pid)
        for index in range(self.snapshot_tree.topLevelItemCount()):
            item=self.snapshot_tree.topLevelItem(index)
            entry=self.snapshot_entries[item.data(0,Qt.ItemDataRole.UserRole)]
            if entry["key"]==key:self.snapshot_tree.setCurrentItem(item);break

    def _apply_preview(self,pid):
        if self._busy or pid not in self.preview_context:return
        card=self.cards.get(pid)
        if not card or not card.preview.isVisible():return
        expected=self.preview_context[pid]
        def action():
            from opencc_env.core.proxy import get_proxy_endpoint
            candidate=get_proxy_endpoint()
            if not candidate or (expected and candidate.display!=expected):
                return [{"probe_id":pid,"success":False,"message":"代理候选已变化，请重新检测并预览。"}]
            # 校验预览与应用间的变化；探针自身仍负责快照、写入核对与复查。
            probe=next(p for p in self.engine.probes if p.id==pid)
            latest=probe.run_check()
            previous=self.report["results"][pid]
            if latest.details!=previous.details or latest.status!=previous.status:
                return [{"probe_id":pid,"success":False,"message":"配置已发生变化，请重新检测并预览。"}]
            ok,message=self.engine.run_fix_single(pid)
            return [{"probe_id":pid,"success":ok,"message":message}]
        self._launch(action,self._on_fix_finished)

    def __init__(self,auto_start=True,preferences_path=None):
        super().__init__();self.setWindowTitle("OpenCC-Env · 环境工作台")
        self.preferences=Preferences(preferences_path)
        pref=self.preferences.values
        self.mode=pref.get("theme","light") if pref.get("theme") in ("light","dark") else "light"
        self.sidebar_collapsed=bool(pref.get("sidebar_collapsed",False))
        self.setMinimumSize(620,520)
        width=pref.get("width",1180);height=pref.get("height",820)
        self.resize(width if isinstance(width,int) and 620<=width<=2400 else 1180,
                    height if isinstance(height,int) and 520<=height<=1600 else 820)
        self.engine=AuditEngine();self.engine.auto_discover_probes()
        self.report=None;self.audit_thread=None;self.fix_thread=None
        self._worker=None;self._busy=False;self._close_requested=False
        self.operation_buttons=[];self.fix_checks={};self.snapshot_entries={}
        self.raw_evidence=False;self._selected_probe=None
        self.cards={};self.expanded_ids=set();self.operation_results={}
        self.preview_context={};self._completed_count=0;self._audit_running=False
        self._init_layout();self._apply_theme();self._refresh_snapshots()
        self._update_sidebar()
        self.shortcuts=[]
        for keys,action in (("F5",self.start_audit),("Esc",self.collapse_details),("Ctrl+E",self.export_report)):
            shortcut=QShortcut(QKeySequence(keys),self);shortcut.activated.connect(action);self.shortcuts.append(shortcut)
        if auto_start:QTimer.singleShot(150,self.start_audit)

    def _page(self,title,subtitle):
        page=QWidget();outer=QHBoxLayout(page);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        body=QWidget();body.setMaximumWidth(1000)
        outer.addStretch(1);outer.addWidget(body,100);outer.addStretch(1)
        layout=QVBoxLayout(body);layout.setContentsMargins(32,32,32,24);layout.setSpacing(20)
        heading=QHBoxLayout();text=QVBoxLayout();text.setSpacing(7)
        text.addWidget(label(title,"heading"));text.addWidget(label(subtitle,"muted",True));heading.addLayout(text,1)
        layout.addLayout(heading)
        return page,layout,heading

    def _init_layout(self):
        root=QWidget();root.setObjectName("root");self.setCentralWidget(root)
        layout=QHBoxLayout(root);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        self.sidebar=QFrame();self.sidebar.setObjectName("sidebar")
        side=QVBoxLayout(self.sidebar);side.setContentsMargins(12,20,12,16);side.setSpacing(8)
        self.sidebar_toggle=QPushButton();self.sidebar_toggle.setProperty("role","quiet")
        self.sidebar_toggle.setToolTip("展开 / 收起导航");self.sidebar_toggle.setAccessibleName("展开或收起导航")
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        self.brand=label("OpenCC","brand")
        top=QHBoxLayout();top.addWidget(self.brand,1);top.addWidget(self.sidebar_toggle);side.addLayout(top);side.addSpacing(20)
        self.nav_buttons=[];self.btn_group=QButtonGroup(self);self.btn_group.setExclusive(True)
        self.nav_specs=[("检测","environment"),("工具","repair"),("历史","history")]
        for index,(title,name) in enumerate(self.nav_specs):
            button=QPushButton(title);button.setProperty("role","nav");button.setCheckable(True);button.setMinimumHeight(44)
            button.setToolTip(title);button.setAccessibleName(title)
            self.btn_group.addButton(button);button.clicked.connect(lambda checked=False,i=index:self.navigate(i))
            self.nav_buttons.append(button);side.addWidget(button)
        side.addStretch()
        self.settings_button=QPushButton("设置与帮助");self.settings_button.setProperty("role","nav")
        self.settings_button.setToolTip("设置与帮助");self.settings_button.setAccessibleName("设置与帮助")
        self.settings_button.clicked.connect(lambda:self.navigate(3));side.addWidget(self.settings_button)
        layout.addWidget(self.sidebar)
        self.pages=QStackedWidget()
        self.pages.addWidget(self._build_audit_page())
        self.pages.addWidget(self._build_cure_page())
        self.pages.addWidget(self._build_snapshot_page())
        self.pages.addWidget(self._build_guides_page())
        layout.addWidget(self.pages,1);self.nav_buttons[0].setChecked(True)
        # 整个窗口不创建状态栏；环境参数只属于检测结果。

    def _build_audit_page(self):
        page,layout,heading=self._page("环境检测","查看配置，按需处理问题。")
        self.banner=ScoreBanner()
        self.banner.audit_requested.connect(self.start_audit)
        self.banner.fix_all_requested.connect(lambda:self.navigate(1))
        self.banner.btn_audit.setToolTip("重新检测 · F5")
        heading.addWidget(self.banner.btn_audit);self.operation_buttons.append(self.banner.btn_audit)
        self.scroll_area=QScrollArea();self.scroll_area.setWidgetResizable(True);self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_container=QWidget();self.cards_layout=QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0,0,0,0);self.cards_layout.setSpacing(0)
        self.cards_layout.addWidget(self.banner)
        meta=QHBoxLayout();self.last_checked=label("尚未检测","small");meta.addWidget(self.last_checked,1)
        self.weight_button=QPushButton("评分依据");self.weight_button.setProperty("role","quiet")
        self.weight_button.clicked.connect(self.toggle_scoring);meta.addWidget(self.weight_button)
        self.export_button=QPushButton("导出报告");self.export_button.setProperty("role","quiet")
        self.export_button.setToolTip("导出报告 · Ctrl+E");self.export_button.clicked.connect(self.export_report);self.export_button.setEnabled(False)
        meta.addWidget(self.export_button);self.cards_layout.addLayout(meta)
        self.score_table=QTableWidget(0,5)
        self.score_table.setHorizontalHeaderLabels(["检测项目","状态","权重","单项分","扣分"])
        self.score_table.verticalHeader().hide();self.score_table.setShowGrid(False)
        self.score_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.score_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.score_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for col in range(1,5):self.score_table.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeMode.ResizeToContents)
        self.score_table.cellClicked.connect(self._table_selected)
        self.cards_layout.addWidget(self.score_table);self.score_table.hide()
        self.rows_layout=QVBoxLayout();self.rows_layout.setContentsMargins(0,12,0,0);self.rows_layout.setSpacing(0)
        self.empty_label=label("开始一次检测，查看本机环境。","muted",True);self.rows_layout.addWidget(self.empty_label)
        self.cards_layout.addLayout(self.rows_layout);self.cards_layout.addStretch()
        self.scroll_area.setWidget(self.cards_container);layout.addWidget(self.scroll_area,1)
        self.console=OutputConsole();self.console.hide()
        self.log_button=QPushButton("查看检测日志");self.log_button.setProperty("role","quiet");self.log_button.clicked.connect(self.toggle_log)
        layout.addWidget(self.log_button,0,Qt.AlignmentFlag.AlignLeft)
        self.console.setMinimumHeight(120);self.console.setMaximumHeight(220);layout.addWidget(self.console)
        return page


    def _build_cure_page(self):
        page,layout,_=self._page("维护工具","按需维护桌面客户端。")
        self.tools_result=label("",None,True);self.tools_result.setTextFormat(Qt.TextFormat.PlainText);self.tools_result.hide();layout.addWidget(self.tools_result)
        area=QScrollArea();area.setWidgetResizable(True);content=QWidget()
        inner=QVBoxLayout(content);inner.setContentsMargins(0,0,0,0);inner.setSpacing(18)
        inner.addWidget(label("渲染缓存","subheading"))
        inner.addWidget(label("将缓存移入可还原的隔离目录。操作前请关闭 Claude。","muted",True))
        self.cache_stats_label=label("尚未扫描","muted",True);inner.addWidget(self.cache_stats_label)
        row=QHBoxLayout()
        self.btn_scan_maintenance=QPushButton("扫描维护项目");self.btn_scan_maintenance.clicked.connect(self._scan_maintenance)
        self.btn_cache=QPushButton("预览缓存隔离");self.btn_cache.clicked.connect(self._cure_blank_screen)
        row.addWidget(self.btn_scan_maintenance);row.addWidget(self.btn_cache);row.addStretch();inner.addLayout(row)
        self.operation_buttons.extend([self.btn_scan_maintenance,self.btn_cache])
        inner.addSpacing(20);inner.addWidget(label("启动项","subheading"))
        inner.addWidget(label("仅显示当前用户 Run 项；未确认的启动链保留不动。","muted",True))
        self.startup_tree=QTreeWidget();self.startup_tree.setHeaderLabels(["启动项","命令 / 说明"])
        self.startup_tree.setRootIsDecorated(False);self.startup_tree.setMinimumHeight(180)
        self.startup_tree.header().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch);inner.addWidget(self.startup_tree)
        self.btn_startup=QPushButton("预览所选启动项");self.btn_startup.clicked.connect(self._cure_startup_entries);inner.addWidget(self.btn_startup)
        self.operation_buttons.append(self.btn_startup);inner.addStretch();area.setWidget(content);layout.addWidget(area,1)
        return page

    def _build_snapshot_page(self):
        page,layout,heading=self._page("历史与还原","查看修改前的备份，按需恢复。")
        button=QPushButton("刷新记录");button.clicked.connect(self._refresh_snapshots);heading.addWidget(button)
        self.snap_info_label=label("正在读取本机快照。","muted",True);layout.addWidget(self.snap_info_label)
        self.snapshot_tree=QTreeWidget();self.snapshot_tree.setHeaderLabels(["时间","操作","可还原状态"])
        self.snapshot_tree.setRootIsDecorated(False);self.snapshot_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.snapshot_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.snapshot_tree.itemSelectionChanged.connect(self._snapshot_selected)
        layout.addWidget(self.snapshot_tree,1)
        self.snapshot_detail=label("选择一条记录查看其影响范围。","muted",True);layout.addWidget(self.snapshot_detail)
        self.btn_restore=QPushButton("预览并还原所选记录");self.btn_restore.setProperty("role","primary");self.btn_restore.clicked.connect(self._rollback_selected)
        self.operation_buttons.append(self.btn_restore);layout.addWidget(self.btn_restore);self.btn_restore.setEnabled(False)
        return page

    def _build_guides_page(self):
        page,layout,_=self._page("设置与帮助","界面偏好与检测说明。")
        row=QHBoxLayout();row.addWidget(label("外观","subheading"));row.addStretch()
        self.theme_button=QPushButton("切换深色");self.theme_button.clicked.connect(self.toggle_theme);row.addWidget(self.theme_button);layout.addLayout(row)
        layout.addWidget(label("OpenCC-Env 0.3 · "+("管理员权限" if is_admin() else "标准用户权限"),"small"))
        layout.addWidget(label("开源软件 · 项目采用 MIT；包含 LGPLv3 的 PySide6 / Qt。许可与源码见下方说明。","small",True))
        splitter=QSplitter(Qt.Orientation.Vertical);tree=QTreeWidget();tree.setHeaderHidden(True);tree.setRootIsDecorated(False)
        self.guide_viewer=QTextBrowser();self.guide_viewer.setOpenExternalLinks(True)
        for guide in ExpertGuideManager.get_all_guides():
            item=QTreeWidgetItem([guide["title"]]);item.setData(0,Qt.ItemDataRole.UserRole,guide["content"]);tree.addTopLevelItem(item)
        resource_root=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[2]))
        notice=resource_root/"THIRD_PARTY_NOTICES.md"
        if notice.is_file():
            item=QTreeWidgetItem(["开源许可与第三方源码"])
            item.setData(0,Qt.ItemDataRole.UserRole,notice.read_text(encoding="utf-8"));tree.addTopLevelItem(item)
        tree.currentItemChanged.connect(lambda current,previous:self.guide_viewer.setMarkdown(current.data(0,Qt.ItemDataRole.UserRole)) if current else None)
        splitter.addWidget(tree);splitter.addWidget(self.guide_viewer);splitter.setSizes([140,400]);layout.addWidget(splitter,1)
        if tree.topLevelItemCount():tree.setCurrentItem(tree.topLevelItem(0))
        return page

    def _init_status_bar(self):
        pass

    def _apply_theme(self):
        self.setStyleSheet(theme_qss(self.mode));palette=PALETTES[self.mode]
        for button,(_,name) in zip(self.nav_buttons,self.nav_specs):button.setIcon(icon(name,palette["fg"]))
        self.sidebar_toggle.setIcon(icon("sidebar",palette["muted"]))
        self.settings_button.setIcon(icon("settings",palette["fg"]))
        self.banner.btn_audit.setIcon(icon("refresh",palette["button_fg"]))
        self.theme_button.setIcon(icon("theme",palette["muted"]));self.setWindowIcon(icon("environment",palette["fg"]))
        self.theme_button.setText("切换深色" if self.mode=="light" else "切换浅色")
        for pid,card in self.cards.items():
            if card.header.isChecked():self._display_evidence(pid)

    def toggle_theme(self):
        self.mode="dark" if self.mode=="light" else "light";self._apply_theme()

    def toggle_log(self):
        visible=not self.console.isVisible();self.console.setVisible(visible)
        self.log_button.setText("收起操作日志" if visible else "显示操作日志")

    def navigate(self,index):
        self.pages.setCurrentIndex(index)
        self.btn_group.setExclusive(False)
        for i,button in enumerate(self.nav_buttons):button.setChecked(i==index)
        self.btn_group.setExclusive(True)
        if index==2:self._refresh_snapshots()

    def _set_busy(self,value):
        self._busy=value
        for button in self.operation_buttons:button.setEnabled(not value)
        for card in self.cards.values():card.set_busy(value)
        self.banner.btn_audit.setText("检测中…" if self._audit_running else ("处理中…" if value else ("重新检测" if self.report else "开始检测")))
        self._snapshot_selected()

    def _launch(self,action,on_result,kind="operation",on_progress=None):
        if self._busy:return False
        worker=TaskWorker(action,self);self._worker=worker;self._set_busy(True)
        if kind=="audit":self.audit_thread=worker
        else:self.fix_thread=worker
        worker.completed.connect(on_result);worker.failed.connect(self._on_worker_error)
        if on_progress:worker.progress.connect(on_progress)
        worker.finished.connect(lambda:self._worker_finished(worker))
        worker.start();return True

    def _worker_finished(self,worker):
        self._worker=None;self._set_busy(False);worker.deleteLater()
        if self.audit_thread is worker:self.audit_thread=None
        if self.fix_thread is worker:self.fix_thread=None
        if self._close_requested:QTimer.singleShot(0,self.close)

    def _on_worker_error(self,message):
        self.console.log("操作未完成："+message,"ERROR")
        self.last_checked.setText("本轮未完成 · "+message)
        if self._audit_running:
            self._audit_running=False;self.banner.update_metrics(None,"INCOMPLETE")

    def start_audit(self):
        if self._busy:return
        self._audit_running=True;self._completed_count=0
        self.preview_context.clear()
        self.operation_results.clear()
        for card in self.cards.values():card.preview.hide()
        self.banner.update_metrics(None,"NOT_CHECKED")
        self.banner.level_badge.setText("正在检测环境")
        self.last_checked.setText("本轮完成 0 / "+str(len(self.engine.probes))+(" · 下方保留上次结果" if self.report else ""))
        self.console.log("开始只读检测","SYSTEM")
        self._launch(lambda:self.engine.run_all(on_result=lambda result:self._worker.progress.emit(result)),
                     self._on_audit_finished,"audit",self._on_probe_received)

    def _on_probe_received(self,result):
        self.console.log(result.probe_name+"："+result.title,STATE_TEXT[result.status])
        if self._audit_running:
            self._completed_count+=1
            self.last_checked.setText("本轮完成 "+str(self._completed_count)+" / "+str(len(self.engine.probes))+(" · 下方保留上次结果" if self.report else ""))

    def _on_audit_finished(self,result):
        self._audit_running=False;self.report=result
        self.banner.update_metrics(result["overall_score"],result["risk_level"],result["counts"])
        self._render_cards();self._update_score_table();self.export_button.setEnabled(True)
        timestamp=result.get("checked_at")
        text=datetime.fromisoformat(timestamp).astimezone().strftime("%m-%d %H:%M") if timestamp else "本轮"
        self.last_checked.setText("检测于 "+text+" · "+str(result.get("duration_seconds",0))+" 秒")
        self.console.log("本轮配置检测完成","SYSTEM");self._refresh_snapshots()

    def _update_score_table(self):
        rows=self.report["scoring"];self.score_table.setRowCount(len(rows))
        for index,row in enumerate(rows):
            result=self.report["results"].get(row["probe_id"])
            values=[row["name"],STATE_TEXT[result.status] if result else "未检测",
                    f'{row["weight_percent"]:.1f}%' if row["included"] else "不计分",
                    str(row["score"]) if row["score"] is not None else "—",
                    f'{row["deduction"]:.2f}' if row["deduction"] is not None else "—"]
            for col,value in enumerate(values):
                item=QTableWidgetItem(value);item.setData(Qt.ItemDataRole.UserRole,row["probe_id"]);self.score_table.setItem(index,col,item)
            self.score_table.setRowHeight(index,36)
        self.score_table.setFixedHeight(44+len(rows)*36)

    def _table_selected(self,row,column):
        item=self.score_table.item(row,0)
        if item and self.report:self.show_probe_detail(item.data(Qt.ItemDataRole.UserRole))

    def show_probe_detail(self,pid):
        self.navigate(0)
        card=self.cards.get(pid)
        if card:
            card.set_expanded(True);self._display_evidence(pid)
            QTimer.singleShot(0,lambda:self.scroll_area.verticalScrollBar().setValue(card.mapTo(self.cards_container,QPoint(0,0)).y()))

    def _display_evidence(self,pid):
        if not self.report or pid not in self.report["results"]:return
        card=self.cards.get(pid)
        if not card:return
        self.evidence=card.evidence;self.raw_evidence=card.raw
        self._selected_probe=pid
        result=self.report["results"][pid]
        scoring=next((r for r in self.report["scoring"] if r["probe_id"]==pid),{})
        if self.raw_evidence:
            description={"检测结论":result.title,"说明":result.summary,"实际参数与范围":result.details,
                         "评分依据":scoring,"建议":result.remedy_guide}
            self.evidence.setHtml("<h3>"+html.escape(result.probe_name)+"</h3><pre style='white-space:pre-wrap;font-size:13px'>"+html.escape(safe_text(description))+"</pre>")
            return
        color=PALETTES[self.mode]["muted"]
        included=scoring.get("included",False)
        score_rows=[("原始权重",str(scoring.get("weight",0)) if included else "不计分"),
                    ("归一化占比",f'{scoring.get("weight_percent",0):.2f}%' if included else "不计分"),
                    ("单项配置分",str(result.score) if result.score is not None else "未计分"),
                    ("对总分的扣分",f'{scoring["deduction"]:.2f}' if scoring.get("deduction") is not None else "未计分")]
        content="<p>"+html.escape(result.summary)+"</p>"
        primary={"probe_network":("ip","country","city","proxy","limitation"),
                 "probe_timezone":("current_timezone","utc_offset"),
                 "probe_cli_settings":("settings_path","proxy_values","candidate_proxy","no_proxy","runtime_verified","error"),
                 "probe_shortcut":("shortcut_path","target_path","arguments","candidate_proxy","runtime_verified","error"),
                 "probe_leak":("dns_servers","remote_doh_success","leak_test_performed","dns_error","doh_error","error"),
                 "probe_proxy_rules":("proxy","http_verified","tun_adapter","error")}
        details=result.details if card.full else {key:value for key,value in result.details.items() if key in primary.get(pid,result.details) or key.endswith("error")}
        if not card.full and isinstance(details.get("tun_adapter"),dict):
            details={**details,"tun_adapter":{key:value for key,value in details["tun_adapter"].items() if key in ("has_tun","is_up","route_verified")}}
        content+="<h4>实际参数与验证范围</h4>"+html_table(parameter_rows(details),color)
        content+="<h4>评分依据</h4><p>"+" · ".join(html.escape(name)+"："+html.escape(value) for name,value in score_rows)+"</p>"
        if result.remedy_guide:content+="<h4>说明与建议</h4><p>"+html.escape(result.remedy_guide).replace("\n","<br>")+"</p>"
        self.evidence.setHtml(content)

    def toggle_evidence(self,pid=None):
        pid=pid or self._selected_probe
        card=self.cards.get(pid)
        if card:
            card.raw=not card.raw;card.raw_button.setText("参数视图" if card.raw else "原始数据")
            self._display_evidence(pid)

    def _build_fix_options(self):
        pass

    def _preview_fix(self,ids):
        descriptions=[]
        for pid in ids:
            result=self.report["results"][pid]
            if pid=="probe_cli_settings":
                details=result.details
                descriptions.append("文件："+str(details.get("settings_path","settings.json"))+"\n当前代理："+safe_text(details.get("proxy_values",{}))+"\n修改后 HTTP_PROXY / HTTPS_PROXY："+safe_text(details.get("candidate_proxy","未取得"))+"\n仅移除 Claude 相关或全局 NO_PROXY 绕过项；保留其他配置。")
            elif pid=="probe_shortcut":
                descriptions.append("入口："+str(result.details.get("shortcut_path") or "真实桌面的 dd/Claude.lnk")+"\n当前参数："+safe_text(result.details.get("arguments","未设置"))+"\n代理参数将指向："+safe_text(result.details.get("candidate_proxy","未取得"))+"\n保留启动目标和其他参数。")
        descriptions.append("每项先保存独立快照，备份失败停止；完成后复查配置。客户端实际效果仍需另行验证。")
        return "\n\n".join(descriptions)

    def start_fix_single(self,pid):
        if self._busy:return
        card=self.cards.get(pid);result=self.report["results"].get(pid) if self.report else None
        if not card or not result or not result.auto_fixable or result.status not in (Status.WARN,Status.FAIL):return
        card.set_expanded(True)
        candidate=result.details.get("candidate_proxy")
        message=self._preview_fix([pid])
        if candidate:message="建议代理："+safe_text(candidate)+"\n\n"+message
        card.preview_text.setText(message);card.preview.show()
        # 点击保存时重新读取候选；若与本轮检测不一致，要求重新检测和预览。
        self.preview_context[pid]=candidate

    def start_fix_all(self):
        for pid,card in self.cards.items():
            if card.fix_button.isVisible():self.start_fix_single(pid);break

    def _start_selected_fix(self,ids):
        for pid in ids:self.start_fix_single(pid)

    def _on_fix_finished(self,reports):
        for item in reports:
            pid=item["probe_id"];self.operation_results[pid]=(item["message"],item["success"])
            self.console.log(item["message"],"通过" if item["success"] else "未完成")
        report={**self.engine.metrics,"results":dict(self.engine.results),
                "checked_at":self.report.get("checked_at") if self.report else None,"duration_seconds":self.report.get("duration_seconds",0) if self.report else 0}
        self.report=report;self.banner.update_metrics(report["overall_score"],report["risk_level"],report["counts"])
        self._render_cards();self._update_score_table();self._refresh_snapshots()
        self.last_checked.setText("所选配置已复查 · 其他项保留原检测结果")

    def _audit_when_idle(self):
        if self._busy:QTimer.singleShot(100,self._audit_when_idle)
        elif not self._close_requested:self.start_audit()

    def _scan_maintenance(self):
        def action():
            scan=CacheCleaner.scan_cache_size()
            try:entries=StartupFixer.scan_startup_entries();error=""
            except Exception as exc:entries=[];error=str(exc)
            return {"cache":scan,"entries":entries,"startup_error":error}
        self._launch(action,self._maintenance_finished)

    def _maintenance_finished(self,data):
        scan=data["cache"]
        self.cache_stats_label.setText("候选渲染缓存 "+str(scan["total_size_mb"])+" MB · "+str(scan["total_files"])+" 个文件"+
                                      (" · 部分目录读取失败" if scan["errors"] else ""))
        self.startup_tree.clear()
        if data["startup_error"]:
            self.startup_tree.addTopLevelItem(QTreeWidgetItem(["读取失败",data["startup_error"]]));return
        for entry in data["entries"]:
            item=QTreeWidgetItem([entry["name"],entry["command"]])
            item.setData(0,Qt.ItemDataRole.UserRole,entry)
            if entry["confirmed_direct_target"]:
                item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(0,Qt.CheckState.Unchecked)
            else:item.setText(1,entry["command"]+" · 启动链未确认，不自动修改")
            self.startup_tree.addTopLevelItem(item)
        if not data["entries"]:self.startup_tree.addTopLevelItem(QTreeWidgetItem(["未发现匹配项","仅覆盖当前用户 Run，其他启动来源未检测"]))

    def _cure_blank_screen(self):
        if self._busy:return
        message="仅隔离已列出的桌面渲染缓存，可在操作历史中还原。不会删除 CLI 数据或强杀进程。请先关闭 Claude。\n\n隔离成功不代表白屏已恢复。"
        if QMessageBox.question(self,"隔离缓存范围",message,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self._launch(CacheCleaner.clean_cache,self._operation_finished)

    def _cure_startup_entries(self):
        if self._busy:return
        entries=[]
        for index in range(self.startup_tree.topLevelItemCount()):
            item=self.startup_tree.topLevelItem(index)
            if item.checkState(0)==Qt.CheckState.Checked and item.data(0,Qt.ItemDataRole.UserRole):entries.append(item.data(0,Qt.ItemDataRole.UserRole))
        if not entries:return
        message="仅停用所选的当前用户 Run 项；先保存可还原快照。\n\n"+"\n".join(e["name"]+"\n"+e["command"] for e in entries)
        if QMessageBox.question(self,"启动项修改范围",message,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self._launch(lambda:StartupFixer.remove_unprotected_startup([e["name"] for e in entries]),self._operation_finished)

    def _operation_finished(self,result):
        ok,message=result;self.console.log(message,"通过" if ok else "未完成");self._refresh_snapshots()
        target=self.snapshot_detail if self.pages.currentIndex()==2 else self.tools_result
        target.setText(message);target.show()
        from opencc_env.ui.components import set_tone
        set_tone(target,"pass" if ok else "warn")

    def _refresh_snapshots(self):
        if not hasattr(self,"snapshot_tree"):return
        self.snapshot_tree.clear();self.snapshot_entries={}
        try:
            entries=BackupManager.get_history()
            for entry in reversed(entries):
                stamp=entry.get("timestamp","")
                try:stamp=datetime.fromisoformat(stamp).astimezone().strftime("%m-%d %H:%M:%S")
                except ValueError:pass
                supported=entry["key"] in KEY_NAMES
                trusted=entry.get("restorable",False) and supported and entry.get("origin")=="opencc-env/2"
                item=QTreeWidgetItem([stamp,KEY_NAMES.get(entry["key"],entry["key"]),"可预览还原" if trusted else "旧版 / 不支持，仅查看"])
                item.setData(0,Qt.ItemDataRole.UserRole,entry["id"]);self.snapshot_entries[entry["id"]]=entry
                self.snapshot_tree.addTopLevelItem(item)
            legacy=sum(e.get("origin")=="legacy" for e in entries)
            self.snap_info_label.setText(str(len(entries))+" 条快照"+(" · "+str(legacy)+" 条旧版记录未经核验，自动还原已禁用" if legacy else ""))
        except Exception as exc:self.snap_info_label.setText("快照读取失败，未把失败当作无记录："+str(exc))
        self._snapshot_selected()

    def _snapshot_selected(self):
        if not hasattr(self,"btn_restore"):return
        selected=self.snapshot_tree.selectedItems()
        entry=self.snapshot_entries.get(selected[0].data(0,Qt.ItemDataRole.UserRole)) if selected else None
        trusted=bool(entry and entry.get("restorable") and entry.get("origin")=="opencc-env/2" and entry["key"] in KEY_NAMES)
        self.btn_restore.setEnabled(trusted and not self._busy)
        if entry:
            data=entry["data"]
            scope=data.get("path","") if isinstance(data,dict) else ""
            self.snapshot_detail.setText(KEY_NAMES.get(entry["key"],entry["key"])+" · "+str(scope)+"\n"+
                ("还原前会检查后续变化，冲突时停止覆盖。" if trusted else "这份旧版记录来源不可靠，保留查看，不执行还原。"))
        else:self.snapshot_detail.setText("选择一条记录查看影响范围。")

    def _rollback_selected(self):
        if self._busy:return
        selected=self.snapshot_tree.selectedItems()
        if not selected:return
        entry=self.snapshot_entries[selected[0].data(0,Qt.ItemDataRole.UserRole)]
        methods={"shortcut":BackupManager.rollback_shortcut,"cli_settings":BackupManager.rollback_cli_settings,
                 "cli_env":BackupManager.rollback_cli_env,"timezone":BackupManager.rollback_timezone,
                 "cache":BackupManager.rollback_cache,"startup":BackupManager.rollback_startup}
        if not entry.get("restorable") or entry["key"] not in methods:return
        message="还原所选 "+KEY_NAMES[entry["key"]]+" 记录。发生外部变化时停止覆盖；结果会读取确认。\n\n"+self.snapshot_detail.text()
        if QMessageBox.question(self,"确认还原范围",message,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            def action():
                ok,report=methods[entry["key"]](entry["id"])
                pid={"cli_settings":"probe_cli_settings","shortcut":"probe_shortcut","timezone":"probe_timezone"}.get(entry["key"])
                if ok and pid:
                    probe=next((p for p in self.engine.probes if p.id==pid),None)
                    if probe:
                        checked=self.engine._checked(probe);self.engine.results[pid]=checked;self.engine._compute_overall_metrics()
                        report+="；还原后的配置复查："+checked.title
                return ok,report
            self._launch(action,self._restore_finished)

    def _restore_finished(self,result):
        self._operation_finished(result)
        if self.report and self.engine.results:
            self.report={**self.report,**self.engine.metrics,"results":dict(self.engine.results)}
            self.operation_results.clear();self._render_cards();self._update_score_table()
            self.banner.update_metrics(self.report["overall_score"],self.report["risk_level"],self.report["counts"])
            self.last_checked.setText("还原项已复查 · 其他项保留原检测结果")

    def export_report(self):
        if not self.report:return
        path,_=QFileDialog.getSaveFileName(self,"导出检测报告","OpenCC-Env-report.json","JSON (*.json)")
        if not path:return
        serial={k:v for k,v in self.report.items() if k!="results"}
        serial["results"]={pid:{"name":r.probe_name,"status":r.status.value,"score":r.score,"title":r.title,"summary":r.summary,"details":r.details} for pid,r in self.report["results"].items()}
        try:Path(path).write_text(safe_text(serial),encoding="utf-8")
        except OSError as exc:QMessageBox.warning(self,"导出未完成",str(exc))

    def closeEvent(self,event):
        if self._worker and self._worker.isRunning():
            self._close_requested=True;self.last_checked.setText("正在等待本轮操作安全结束…");event.ignore();return
        try:self.preferences.save({"theme":self.mode,"sidebar_collapsed":self.sidebar_collapsed,
                                   "width":self.width(),"height":self.height()})
        except OSError:pass
        event.accept()
