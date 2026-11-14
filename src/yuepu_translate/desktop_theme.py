"""Industrial terminal presentation; all desktop colors have one owner."""

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

THEMES = {
    "dark": {
        "bg": "#141618",
        "panel": "#1c1f22",
        "raised": "#25292d",
        "field": "#171a1d",
        "paper": "#1b1e21",
        "target": "#202427",
        "text": "#f0f1eb",
        "muted": "#a9b0b4",
        "border": "#41484d",
        "control_border": "#727d83",
        "accent": "#f3ce49",
        "accent_hover": "#ffe379",
        "accent_pressed": "#d8b532",
        "on_accent": "#1c1c16",
        "hover": "#343b40",
        "selected": "#40402d",
        "error": "#ffaaa0",
        "success": "#a9d9c2",
        "grid": "#292e32",
        "disabled": "#80888d",
        "draft": "#acb8bf",
    },
    "light": {
        "bg": "#e7e8e3",
        "panel": "#f4f4ef",
        "raised": "#e4e6e0",
        "field": "#fafaf6",
        "paper": "#fafaf6",
        "target": "#f0f2ec",
        "text": "#24292b",
        "muted": "#566167",
        "border": "#9ca5a6",
        "control_border": "#748083",
        "accent": "#f3ce49",
        "accent_hover": "#ffe379",
        "accent_pressed": "#d8b532",
        "on_accent": "#1c1c16",
        "hover": "#d6dad3",
        "selected": "#eee3ac",
        "error": "#a52c23",
        "success": "#24644e",
        "grid": "#dfe3dc",
        "disabled": "#687278",
        "draft": "#53646c",
    },
}


def stylesheet(name="dark"):
    c = THEMES[name]
    return """
    QWidget {{ color:{text}; font-family:'Microsoft YaHei UI'; font-size:14px; }}
    QMainWindow, QDialog, QWidget#host {{ background:{bg}; }}
    QLabel {{ background:transparent; border:0; }}
    QFrame#header {{ background:{panel}; border-bottom:1px solid {border}; }}
    QFrame#sidebar {{ background:{panel}; border:1px solid {border}; }}
    QScrollArea#controlScroll, QWidget#controlFields {{ background:{panel}; border:0; }}
    QFrame#workarea {{ background:{paper}; border:1px solid {border}; }}
    QFrame#languages {{ background:{raised}; border-bottom:1px solid {border}; }}
    QFrame#statusbar {{ background:{panel}; border-top:1px solid {border}; }}
    QLabel#brand {{ font-size:20px; font-weight:700; letter-spacing:2px; }}
    QLabel#brandMark {{ background:{accent}; color:{on_accent}; font-family:'Bahnschrift';
        font-size:20px; font-weight:700; padding:6px; }}
    QLabel#eyebrow {{ color:{muted}; font-family:'Consolas'; font-size:11px;
        letter-spacing:2px; }}
    QLabel#muted {{ color:{muted}; font-size:12px; }}
    QLabel#section {{ color:{muted}; font-size:12px; font-weight:600; }}
    QLabel#title {{ font-size:28px; font-weight:700; letter-spacing:2px; }}
    QLabel#panelTitle {{ font-size:17px; font-weight:700; }}
    QLabel#emptyTitle {{ font-size:23px; font-weight:700; letter-spacing:2px; }}
    QLabel#pill {{ background:{raised}; color:{success}; padding:7px 10px;
        border:1px solid {border}; font-size:12px; }}
    QLabel#state {{ color:{success}; font-family:'Consolas'; font-size:12px; }}
    QLabel#state[severity="error"], QLabel#muted[severity="error"] {{ color:{error}; }}
    QLabel#count {{ background:{raised}; color:{text}; padding:6px 10px; font-size:12px; }}
    QPushButton {{ background:{raised}; border:1px solid {control_border}; border-radius:0;
        padding:9px 13px; min-height:20px; }}
    QPushButton:hover {{ background:{hover}; }}
    QPushButton:pressed {{ background:{selected}; }}
    QPushButton:focus, QComboBox:focus, QSpinBox:focus, QLineEdit:focus,
    QPlainTextEdit:focus {{ border:2px solid {text}; }}
    QPushButton:disabled {{ background:{panel}; color:{disabled}; border-color:{border}; }}
    QPushButton#primary {{ background:{accent}; color:{on_accent}; border-color:{accent};
        font-weight:700; }}
    QPushButton#primary:hover {{ background:{accent_hover}; border-color:{accent_hover}; }}
    QPushButton#primary:pressed {{ background:{accent_pressed}; }}
    QPushButton#primary:focus {{ border:2px solid {text}; }}
    QPushButton#primary:disabled {{ background:{raised}; color:{disabled};
        border-color:{border}; }}
    QPushButton#quiet {{ background:transparent; border:1px solid transparent; color:{muted}; }}
    QPushButton#quiet:hover {{ background:{hover}; color:{text}; }}
    QPushButton#quiet:disabled {{ color:{disabled}; }}
    QPushButton#quiet:focus {{ border:2px solid {text}; }}
    QPushButton#swap {{ padding:6px 8px; font-size:12px; font-weight:600; }}
    QPushButton#swap:hover {{ background:{hover}; border-color:{accent}; }}
    QPushButton#tab {{ background:transparent; border:0; border-bottom:3px solid transparent;
        padding:12px 18px; color:{muted}; }}
    QPushButton#tab:checked {{ color:{text}; background:{raised}; border-bottom-color:{accent}; }}
    QPushButton#tab:focus {{ border:2px solid {text}; }}
    QPushButton#theme {{ padding:5px 10px; font-size:12px; }}
    QPushButton#theme[appearance="dark"] {{ background:{dark_swatch}; color:{dark_swatch_text}; }}
    QPushButton#theme[appearance="light"] {{ background:{light_swatch}; color:{light_swatch_text}; }}
    QPushButton#theme:hover {{ border-color:{accent}; }}
    QPushButton#theme:checked {{ border:2px solid {accent}; font-weight:700; }}
    QPushButton#theme:focus {{ border:2px dotted {control_border}; }}
    QPushButton#theme:checked:focus {{ border:2px solid {accent}; }}
    QComboBox, QSpinBox, QLineEdit {{ background:{field}; border:1px solid {control_border};
        border-radius:0; padding:8px 10px; min-height:22px; selection-background-color:{selected}; }}
    QComboBox:disabled {{ color:{disabled}; background:{raised}; }}
    QComboBox::drop-down {{ border:0; width:24px; }}
    QComboBox QAbstractItemView {{ background:{panel}; color:{text};
        selection-background-color:{selected}; selection-color:{text}; padding:5px; }}
    QCheckBox {{ spacing:10px; background:transparent; min-height:28px;
        border:1px solid transparent; padding:2px; }}
    QCheckBox:focus {{ border:1px dotted {text}; }}
    QCheckBox:disabled {{ color:{disabled}; }}
    QCheckBox::indicator {{ width:20px; height:20px; border:2px solid {control_border};
        border-radius:0; background:{field}; }}
    QCheckBox::indicator:unchecked:hover {{ border-color:{text}; background:{hover}; }}
    QCheckBox::indicator:checked {{ background:{accent}; border-color:{on_accent};
        image:url("{checkmark}"); }}
    QCheckBox::indicator:checked:hover {{ background:{accent_hover}; }}
    QCheckBox::indicator:pressed {{ background:{selected}; }}
    QCheckBox::indicator:checked:pressed {{ background:{accent_pressed}; }}
    QCheckBox::indicator:disabled {{ background:{raised}; border-color:{disabled}; }}
    QCheckBox::indicator:checked:disabled {{ background:{control_border};
        border-color:{disabled}; }}
    QPlainTextEdit {{ background:{field}; border:1px solid {control_border}; border-radius:0;
        padding:12px; selection-background-color:{selected}; selection-color:{text}; }}
    QListView {{ background:{paper}; border:0; outline:0; }}
    QListView:focus {{ border:1px solid {border}; }}
    QScrollBar:vertical {{ background:{panel}; width:10px; margin:0; }}
    QScrollBar::handle:vertical {{ background:{border}; min-height:36px; }}
    QScrollBar::handle:vertical:hover {{ background:{muted}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:transparent; }}
    QMenu {{ background:{panel}; border:1px solid {border}; padding:6px; }}
    QMenu::item {{ padding:9px 25px; }}
    QMenu::item:selected {{ background:{selected}; }}
    QToolTip {{ background:{text}; color:{bg}; border:0; padding:8px; }}
    """.format(
        **c,
        checkmark=(Path(__file__).parent / "assets" / "checkmark.svg").as_posix(),
        dark_swatch=THEMES["dark"]["panel"],
        dark_swatch_text=THEMES["dark"]["text"],
        light_swatch=THEMES["light"]["panel"],
        light_swatch_text=THEMES["light"]["text"],
    )


def palette(name):
    c = THEMES[name]
    p = QPalette()
    for role, token in (
        (QPalette.Window, "bg"),
        (QPalette.WindowText, "text"),
        (QPalette.Base, "field"),
        (QPalette.AlternateBase, "target"),
        (QPalette.Text, "text"),
        (QPalette.Button, "raised"),
        (QPalette.ButtonText, "text"),
        (QPalette.Highlight, "selected"),
        (QPalette.HighlightedText, "text"),
        (QPalette.PlaceholderText, "muted"),
        (QPalette.ToolTipBase, "text"),
        (QPalette.ToolTipText, "bg"),
    ):
        p.setColor(role, QColor(c[token]))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(c["disabled"]))
    return p


class SignalMark(QWidget):
    """Original vector signal emblem, painted at native resolution."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = "dark"
        self.setFixedSize(180, 120)
        self.setAccessibleName("双语信号标记")

    def paintEvent(self, event):
        c = THEMES[self.theme]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(c["border"]), 1))
        diamond = QPolygonF([QPointF(90, 8), QPointF(155, 60), QPointF(90, 112), QPointF(25, 60)])
        p.drawPolygon(diamond)
        p.drawLine(5, 44, 5, 26)
        p.drawLine(5, 26, 25, 26)
        p.drawLine(175, 76, 175, 94)
        p.drawLine(175, 94, 155, 94)
        p.setPen(QPen(QColor(c["text"]), 3))
        for i, height in enumerate([12, 26, 44, 22, 54, 34, 16]):
            x = 54 + i * 12
            p.drawLine(QPointF(x, 60 - height / 2), QPointF(x, 60 + height / 2))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["accent"]))
        p.drawPolygon(
            QPolygonF([QPointF(128, 80), QPointF(145, 80), QPointF(135, 91), QPointF(118, 91)])
        )


class TerminalEmpty(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = "dark"
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addStretch()
        self.mark = SignalMark()
        layout.addWidget(self.mark, 0, Qt.AlignHCenter)
        self.title = QLabel("等待接入语音")
        self.title.setObjectName("emptyTitle")
        self.subtitle = QLabel("让语言相通，让交流继续。")
        self.subtitle.setObjectName("muted")
        self.steps = QLabel("01  选择音源与方向    /    02  加载模型    /    03  开始收音")
        self.steps.setObjectName("muted")
        self.steps.setWordWrap(True)
        for label in (self.title, self.subtitle, self.steps):
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label)
        layout.addSpacing(12)
        self.signature = QLabel("YUEPU  /  LANGUAGE BRIDGE")
        self.signature.setObjectName("eyebrow")
        self.signature.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.signature)
        layout.addStretch()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.mark.setVisible(self.height() >= 340)
        self.signature.setVisible(self.height() >= 400)

    def set_theme(self, theme):
        self.theme = self.mark.theme = theme
        self.mark.update()
        self.update()

    def paintEvent(self, event):
        c = THEMES[self.theme]
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(c["paper"]))
        p.setPen(QPen(QColor(c["grid"]), 1))
        for x in range(0, self.width(), 32):
            for y in range(0, self.height(), 32):
                p.drawPoint(x, y)
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawLine(self.width() // 2, 0, self.width() // 2, 24)
        p.drawLine(self.width() // 2, self.height() - 24, self.width() // 2, self.height())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["grid"]))
        path = QPainterPath()
        path.moveTo(self.width() - 150, self.height())
        path.lineTo(self.width(), self.height() - 150)
        path.lineTo(self.width(), self.height())
        path.closeSubpath()
        p.drawPath(path)
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawRect(QRectF(16, 16, 6, 6))


STYLE = stylesheet("dark")
