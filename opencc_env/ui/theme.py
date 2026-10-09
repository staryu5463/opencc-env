"""统一浅色与深色设计变量，参考用户提供的桌面侧栏与内容层次。"""
PALETTES = {
    "light": {"bg":"#ffffff","sidebar":"#f7f9fc","soft":"#f5f7f9","fg":"#20262d","muted":"#73808c","border":"#e4e9ee","hover":"#edf1f5","selected":"#e7edf3","button":"#273440","button_fg":"#ffffff","pass":"#287853","warn":"#a86b15","fail":"#b34444","info":"#668096"},
    "dark": {"bg":"#202428","sidebar":"#191d21","soft":"#292f35","fg":"#e4e8ec","muted":"#98a3ad","border":"#363d44","hover":"#303840","selected":"#39434d","button":"#e2e8ee","button_fg":"#20262d","pass":"#81cba6","warn":"#e6b96c","fail":"#ec9494","info":"#96b5d1"}
}


def theme_qss(mode="light"):
    p = PALETTES[mode]
    return f"""
QWidget {{ color:{p['fg']}; font-family:"Segoe UI","Microsoft YaHei UI"; font-size:14px; background:transparent; }}
QMainWindow, QWidget#root {{ background:{p['bg']}; }}
QFrame#sidebar {{ background:{p['sidebar']}; border:none; }}
QLabel[role="brand"] {{ font-size:23px; font-weight:600; }}
QLabel[role="heading"] {{ font-size:27px; font-weight:600; }}
QLabel[role="subheading"] {{ font-size:16px; font-weight:600; }}
QLabel[role="muted"] {{ color:{p['muted']}; font-size:13px; }}
QLabel[role="small"] {{ color:{p['muted']}; font-size:12px; }}
QLabel[role="status"] {{ font-size:22px; font-weight:600; }}
QLabel[tone="pass"] {{ color:{p['pass']}; }}
QLabel[tone="warn"] {{ color:{p['warn']}; }}
QLabel[tone="fail"] {{ color:{p['fail']}; }}
QLabel[tone="info"] {{ color:{p['info']}; }}
QFrame[role="panel"] {{ background:transparent; border:none; }}
QFrame[role="probe"] {{ border-bottom:1px solid {p['border']}; }}
QFrame[role="preview"] {{ background:{p['soft']}; border:1px solid {p['border']}; border-radius:12px; }}
QLabel[role="chevron"] {{ font-size:23px; color:{p['muted']}; }}
QLabel[role="dot"] {{ font-size:10px; }}
QFrame[role="row"] {{ border-bottom:1px solid {p['border']}; }}
QPushButton, QToolButton {{ background:{p['bg']}; border:1px solid {p['border']}; border-radius:8px; padding:8px 14px; }}
QPushButton:hover, QToolButton:hover {{ background:{p['hover']}; }}
QPushButton:disabled, QToolButton:disabled {{ color:{p['muted']}; background:{p['soft']}; }}
QPushButton[role="primary"] {{ background:{p['button']}; color:{p['button_fg']}; border:1px solid {p['button']}; }}
QPushButton[role="primary"]:disabled {{ background:{p['selected']}; color:{p['muted']}; border-color:{p['border']}; }}
QPushButton[role="nav"] {{ background:transparent; border:none; text-align:left; padding:10px 16px; border-radius:9px; font-size:14px; }}
QPushButton[role="nav"]:hover {{ background:{p['hover']}; }}
QPushButton[role="nav"]:checked {{ background:{p['selected']}; }}
QPushButton[role="nav"][compact="true"] {{ padding:10px 8px; }}
QPushButton[role="rowHeader"] {{ border:none; background:transparent; padding:0; text-align:left; border-radius:8px; }}
QPushButton[role="rowHeader"]:hover {{ background:{p['soft']}; }}
QPushButton[role="rowHeader"]:checked {{ background:transparent; }}
QPushButton:focus {{ border:1px solid {p['muted']}; }}
QPushButton[role="quiet"] {{ background:transparent; border:none; padding:6px 10px; color:{p['muted']}; }}
QPushButton[role="quiet"]:hover {{ background:{p['hover']}; color:{p['fg']}; }}
QScrollArea {{ border:none; }}
QTreeWidget,QTableWidget,QTextBrowser,QTextEdit {{ background:{p['bg']}; border:1px solid {p['border']}; border-radius:9px; selection-background-color:{p['selected']}; selection-color:{p['fg']}; }}
QTreeWidget::item {{ padding:8px 5px; }}
QTreeWidget::item:selected,QTableWidget::item:selected {{ background:{p['selected']}; color:{p['fg']}; }}
QHeaderView::section {{ background:{p['soft']}; color:{p['muted']}; border:none; border-bottom:1px solid {p['border']}; padding:10px; font-weight:500; }}
QTableWidget {{ gridline-color:{p['border']}; }}
QTextBrowser {{ padding:12px; }}
QTextBrowser#evidence {{ border:none; background:transparent; padding:0; font-size:14px; }}
QTextEdit#output {{ background:{p['soft']}; font-family:"Consolas","Microsoft YaHei UI"; font-size:12px; padding:10px; }}
QCheckBox {{ spacing:9px; }}
QCheckBox::indicator {{ width:16px; height:16px; border:1px solid {p["muted"]}; border-radius:4px; background:{p["bg"]}; }}
QCheckBox::indicator:checked {{ background:{p["button"]}; border-color:{p["button"]}; }}
QSplitter::handle {{ background:{p['border']}; width:1px; }}
QStatusBar {{ background:{p['bg']}; border-top:1px solid {p['border']}; padding:4px 12px; }}
QStatusBar QLabel {{ font-size:12px; color:{p['muted']}; padding-right:14px; }}
QScrollBar:vertical {{ width:9px; background:transparent; margin:3px; }}
QScrollBar::handle:vertical {{ background:{p['border']}; border-radius:3px; min-height:24px; }}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{ height:0; }}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {{ background:transparent; }}
QMessageBox,QDialog {{ background:{p['bg']}; }}
"""
