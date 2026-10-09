"""紧凑状态组件：主画面展示问题，证据与评分按需查看。"""
from datetime import datetime
from PySide6.QtCore import Qt,Signal
from PySide6.QtWidgets import QFrame,QHBoxLayout,QVBoxLayout,QLabel,QPushButton,QTextEdit,QSizePolicy
from opencc_env.core.base_probe import Status

STATE_TEXT={Status.PASS:"通过",Status.WARN:"需注意",Status.FAIL:"有问题",Status.ERROR:"未完成",Status.INFO:"信息",Status.NOT_APPLICABLE:"不适用"}
STATE_TONE={Status.PASS:"pass",Status.WARN:"warn",Status.FAIL:"fail",Status.ERROR:"info",Status.INFO:"info",Status.NOT_APPLICABLE:"info"}


def label(text,role=None,wrap=False):
    widget=QLabel(text)
    if role:widget.setProperty("role",role)
    widget.setWordWrap(wrap)
    return widget


def set_tone(widget,tone):
    widget.setProperty("tone",tone);widget.style().unpolish(widget);widget.style().polish(widget)


class ScoreBanner(QFrame):
    audit_requested=Signal()
    fix_all_requested=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.setProperty("role","panel")
        layout=QHBoxLayout(self);layout.setContentsMargins(22,18,22,18);layout.setSpacing(18)
        main=QVBoxLayout();main.setSpacing(6)
        self.level_badge=label("尚未检测","status");self.count_label=label("检测只读取本机配置；不会自动修改系统。","muted",True)
        main.addWidget(self.level_badge);main.addWidget(self.count_label);layout.addLayout(main,1)
        aside=QVBoxLayout();aside.setSpacing(4)
        self.score_label=label("参考评分 — / 100","subheading")
        self.score_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.model_label=label("配置参考 · 不代表封号概率","small")
        self.model_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        aside.addWidget(self.score_label);aside.addWidget(self.model_label)
        layout.addLayout(aside)
        # 保持统一信号接口；按钮由页面头部呈现。
        self.btn_audit=QPushButton("开始检测");self.btn_audit.setProperty("role","primary")
        self.btn_audit.clicked.connect(self.audit_requested.emit)
        self.btn_fix_all=QPushButton("查看可修复项");self.btn_fix_all.clicked.connect(self.fix_all_requested.emit)

    def update_metrics(self,score,level,counts=None):
        titles={"READY":"本轮配置检查完成","ATTENTION":"有配置需要留意","ISSUES":"发现需要处理的问题",
                "INCOMPLETE":"部分检测未完成","NOT_CHECKED":"尚未检测"}
        tones={"READY":"pass","ATTENTION":"warn","ISSUES":"fail","INCOMPLETE":"info","NOT_CHECKED":"info"}
        self.level_badge.setText(titles.get(level,level));set_tone(self.level_badge,tones.get(level,"info"))
        self.score_label.setText("参考评分 "+(str(score) if score is not None else "—")+" / 100")
        if counts:
            parts=[title+" "+str(counts.get(key,0)) for key,title in (("PASS","通过"),("WARN","需注意"),("FAIL","问题"),("ERROR","未完成")) if counts.get(key,0)]
            information=counts.get("INFO",0)+counts.get("NOT_APPLICABLE",0)
            if information:parts.append("信息 / 不适用 "+str(information))
            self.count_label.setText(" · ".join(parts) or "本轮没有结果")
        else:self.count_label.setText("正在读取配置，尚未形成完整结论。")


class ProbeCard(QFrame):
    details_requested=Signal(str)
    fix_single_requested=Signal(str)
    def __init__(self,result,parent=None):
        super().__init__(parent);self.result=result;self.setProperty("role","row")
        layout=QHBoxLayout(self);layout.setContentsMargins(4,13,4,13);layout.setSpacing(16)
        self.dot_label=label("●");set_tone(self.dot_label,STATE_TONE[result.status]);layout.addWidget(self.dot_label)
        text=QVBoxLayout();text.setSpacing(5)
        name=label(result.probe_name,"subheading")
        summary=label(result.title,"muted",True);summary.setToolTip(result.summary)
        name.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Preferred)
        text.addWidget(name);text.addWidget(summary);layout.addLayout(text,1)
        state=label(STATE_TEXT[result.status]);set_tone(state,STATE_TONE[result.status]);layout.addWidget(state)
        button=QPushButton("查看");button.setProperty("role","quiet")
        button.clicked.connect(lambda:self.details_requested.emit(result.probe_id));layout.addWidget(button)


class OutputConsole(QTextEdit):
    def __init__(self,parent=None):
        super().__init__(parent);self.setObjectName("output");self.setReadOnly(True)
        self.document().setMaximumBlockCount(800)
    def log(self,message,level="INFO"):
        self.moveCursor(__import__("PySide6.QtGui",fromlist=["QTextCursor"]).QTextCursor.MoveOperation.End)
        self.insertPlainText("["+datetime.now().strftime("%H:%M:%S")+"] "+level+"  "+str(message)+"\n")
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
