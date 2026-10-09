"""可键盘展开的检测行，证据、预览和结果始终位于当前项目。"""
import math
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QFrame, QPushButton, QLabel, QHBoxLayout, QVBoxLayout, QTextBrowser
from opencc_env.core.base_probe import Status
from opencc_env.ui.components import label, set_tone, STATE_TEXT, STATE_TONE


class FlowBrowser(QTextBrowser):
    """文档随内容增高，由外层页面统一滚动，避免嵌套滚动。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setObjectName("evidence")
        self.document().documentLayout().documentSizeChanged.connect(self._fit)

    def _fit(self, *args):
        height = max(48, math.ceil(self.document().size().height()) + 20)
        if abs(self.height() - height) > 1:
            self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.document().setTextWidth(max(100, self.viewport().width()))
        self._fit()


class ProbeCard(QFrame):
    expanded = Signal(str, bool)
    raw_requested = Signal(str)
    full_requested = Signal(str)
    copy_requested = Signal(str)
    path_requested = Signal(str)
    fix_requested = Signal(str)
    apply_requested = Signal(str)
    history_requested = Signal(str)

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.result = result
        self.setProperty("role", "probe")
        self.raw = False
        self.full = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = QPushButton()
        self.header.setCheckable(True)
        self.header.setMinimumHeight(84)
        self.header.setProperty("role", "rowHeader")
        self.header.setAccessibleName(result.probe_name + "，展开参数与评分依据")
        row = QHBoxLayout(self.header)
        row.setContentsMargins(8, 17, 8, 17)
        row.setSpacing(14)
        dot = label("●", "dot")
        set_tone(dot, STATE_TONE[result.status])
        row.addWidget(dot)
        texts = QVBoxLayout()
        texts.setSpacing(5)
        self.name_label = label(result.probe_name, "subheading")
        self.summary_label = label(result.title, "muted", True)
        texts.addWidget(self.name_label)
        texts.addWidget(self.summary_label)
        row.addLayout(texts, 1)
        self.status_label = label(STATE_TEXT[result.status], "small")
        set_tone(self.status_label, STATE_TONE[result.status])
        row.addWidget(self.status_label)
        self.arrow = label("›", "chevron")
        row.addWidget(self.arrow)
        for widget in (dot, self.name_label, self.summary_label, self.status_label, self.arrow):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.header.toggled.connect(self._toggle)
        layout.addWidget(self.header)

        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(24, 2, 8, 20)
        body.setSpacing(12)
        self.evidence = FlowBrowser()
        body.addWidget(self.evidence)
        actions = QHBoxLayout()
        self.copy_button = QPushButton("复制参数")
        self.raw_button = QPushButton("原始数据")
        self.full_button = QPushButton("完整参数")
        self.path_button = QPushButton("打开所在目录")
        for button in (self.copy_button, self.full_button, self.raw_button):
            button.setProperty("role", "quiet")
            actions.addWidget(button)
        actions.addStretch()
        self.fix_button = QPushButton("预览修改")
        self.fix_button.setVisible(result.auto_fixable and result.status in (Status.WARN, Status.FAIL))
        tools=QHBoxLayout();self.path_button.setProperty("role","quiet")
        tools.addWidget(self.path_button);tools.addStretch();tools.addWidget(self.fix_button)
        self.path_button.setVisible(any(result.details.get(key) for key in ("settings_path", "shortcut_path", "target_path")))
        body.addLayout(actions)
        body.addLayout(tools)
        self.copy_button.clicked.connect(lambda: self.copy_requested.emit(result.probe_id))
        self.raw_button.clicked.connect(lambda: self.raw_requested.emit(result.probe_id))
        self.full_button.clicked.connect(lambda: self.full_requested.emit(result.probe_id))
        self.path_button.clicked.connect(lambda: self.path_requested.emit(result.probe_id))
        self.fix_button.clicked.connect(lambda: self.fix_requested.emit(result.probe_id))

        self.preview = QFrame()
        self.preview.setProperty("role", "preview")
        preview_layout = QVBoxLayout(self.preview)
        preview_layout.setContentsMargins(18, 16, 18, 16)
        preview_layout.addWidget(label("修改预览", "subheading"))
        self.preview_text = label("", None, True)
        self.preview_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview_text.setTextFormat(Qt.TextFormat.PlainText)
        preview_layout.addWidget(self.preview_text)
        buttons = QHBoxLayout()
        self.apply_button = QPushButton("保存配置并复查")
        self.apply_button.setProperty("role", "primary")
        self.cancel_button = QPushButton("取消")
        self.apply_button.clicked.connect(lambda: self.apply_requested.emit(result.probe_id))
        self.cancel_button.clicked.connect(self.preview.hide)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        preview_layout.addLayout(buttons)
        body.addWidget(self.preview)
        self.preview.hide()

        self.operation_label = label("", None, True)
        self.operation_label.setTextFormat(Qt.TextFormat.PlainText)
        self.operation_label.hide()
        body.addWidget(self.operation_label)
        self.history_button = QPushButton("查看本项备份与还原")
        self.history_button.setProperty("role", "quiet")
        self.history_button.clicked.connect(lambda: self.history_requested.emit(result.probe_id))
        self.history_button.hide()
        body.addWidget(self.history_button)
        layout.addWidget(self.body)
        self.body.hide()

    def _toggle(self, value):
        self.body.setVisible(value)
        self.arrow.setText("−" if value else "›")
        self.expanded.emit(self.result.probe_id, value)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,"header"):
            height=max(84,self.header.layout().heightForWidth(self.width()))
            if self.header.minimumHeight()!=height:self.header.setMinimumHeight(height)

    def set_expanded(self, value):
        self.header.setChecked(value)

    def set_busy(self, value):
        self.fix_button.setEnabled(not value)
        self.apply_button.setEnabled(not value)

    def set_operation(self, message, success):
        self.operation_label.setText(message)
        set_tone(self.operation_label, "pass" if success else "warn")
        self.operation_label.show()
        self.history_button.show()
