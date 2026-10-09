"""统一的单色线条图标，不依赖 Emoji 或外部字体。"""
from PySide6.QtCore import QByteArray,Qt
from PySide6.QtGui import QIcon,QPixmap,QPainter
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    "sidebar":'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>',
    "settings":'<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
    "overview":'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "environment":'<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18M5 6h14M5 18h14"/>',
    "repair":'<path d="M14 6a5 5 0 0 0-6 6L3 17a3 3 0 0 0 4 4l5-5a5 5 0 0 0 6-6l-3 3-4-4 3-3z"/>',
    "history":'<path d="M4 7a9 9 0 1 1-1 8M4 3v5h5M12 7v6l4 2"/>',
    "help":'<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 4M12 17h.01"/>',
    "refresh":'<path d="M20 10a8 8 0 0 0-14-4L3 9M3 4v5h5M4 14a8 8 0 0 0 14 4l3-3M21 20v-5h-5"/>',
    "theme":'<path d="M20 15A8.5 8.5 0 0 1 9 4a8.5 8.5 0 1 0 11 11z"/>',
    "check":'<path d="M5 12l4 4L19 6"/>',
    "arrow":'<path d="M9 5l7 7-7 7"/>',
    "download":'<path d="M12 3v12M7 10l5 5 5-5M4 17v4h16v-4"/>'
}


def icon(name,color="#657483",size=20):
    content='<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="'+color+'" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'+PATHS[name]+'</g></svg>'
    renderer=QSvgRenderer(QByteArray(content.encode("utf-8")))
    pixmap=QPixmap(size*2,size*2);pixmap.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pixmap);renderer.render(painter);painter.end();pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)
