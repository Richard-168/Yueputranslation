"""Neutral desktop themes shared by the workspace and its dialogs."""

from pathlib import Path

from PySide6.QtGui import QColor, QPalette

THEMES = {
    "dark": {
        "bg": "#191919",
        "panel": "#202020",
        "raised": "#2b2b2b",
        "field": "#242424",
        "paper": "#191919",
        "target": "#191919",
        "text": "#f7f7f7",
        "muted": "#bcbcbc",
        "border": "#383838",
        "control_border": "#747474",
        "accent": "#eaeaea",
        "accent_hover": "#ffffff",
        "accent_pressed": "#cccccc",
        "on_accent": "#191919",
        "hover": "#363636",
        "selected": "#3e3e3e",
        "error": "#ffb4ae",
        "success": "#abd9ba",
        "disabled": "#848484",
        "draft": "#bdbdbd",
    },
    "light": {
        "bg": "#ffffff",
        "panel": "#f5f5f5",
        "raised": "#eeeeee",
        "field": "#ffffff",
        "paper": "#ffffff",
        "target": "#ffffff",
        "text": "#191919",
        "muted": "#616161",
        "border": "#dfdfdf",
        "control_border": "#888888",
        "accent": "#242424",
        "accent_hover": "#424242",
        "accent_pressed": "#111111",
        "on_accent": "#ffffff",
        "hover": "#ececec",
        "selected": "#e4e4e4",
        "error": "#a32a25",
        "success": "#286344",
        "disabled": "#777777",
        "draft": "#5f5f5f",
    },
}


def stylesheet(name="dark"):
    colors = THEMES[name]
    assets = Path(__file__).with_name("assets")
    return """
    QWidget {{ color:{text}; font-family:'Microsoft YaHei UI'; font-size:18px;
        font-weight:500; }}
    QMainWindow, QDialog, #host, #header, #workarea, #languages, #statusbar {{
        background:{bg}; }}
    #sidebar {{ background:{panel}; }}
    QSplitter#historySplitter::handle {{ background:{panel};
        border-right:1px solid {border}; }}
    QSplitter#historySplitter::handle:hover, QSplitter#historySplitter::handle:pressed {{
        background:{hover}; border-right-color:{control_border}; }}
    #composer {{ background:{field}; border:1px solid {border}; border-radius:16px; }}
    QLabel {{ background:transparent; border:0; }}
    QLabel#brand {{ font-size:20px; font-weight:600; }}
    QLabel#title {{ font-size:24px; font-weight:600; padding:0 10px 5px; }}
    QLabel#welcomeTitle {{ font-family:'SimSun'; font-size:36px; font-weight:400; }}
    QLabel#welcomeTitle[compact="true"] {{ font-size:32px; }}
    QLabel#muted, QLabel#section, QLabel#count, QLabel#statusLabel, QLabel#state {{
        color:{muted}; font-size:15px; }}
    QLabel#section {{ font-weight:600; }}
    QLabel#panelTitle {{ font-size:18px; font-weight:600; }}
    QLabel#pill {{ background:{panel}; color:{muted}; padding:4px 8px;
        border-radius:6px; font-size:15px; }}
    QLabel[severity="error"] {{ color:{error}; }}
    QLabel#dialogTitle {{ font-size:25px; font-weight:600; }}
    QLabel#dialogSection {{ font-size:18px; font-weight:600; }}
    QLabel#dialogDescription, QLabel#dialogHint, QLabel#dialogFeedback {{
        color:{muted}; font-size:15px; }}
    QLabel#dialogError, QLabel#dialogFeedback[severity="error"], QLabel#dialogHint[severity="error"] {{
        color:{error}; }}
    QLabel#dialogFeedback[severity="success"] {{ color:{success}; }}
    #dialogFooter {{ border-top:1px solid {border}; }}
    #dialogCard {{ background:{panel}; border:1px solid {border}; border-radius:10px; }}
    QScrollArea#dialogScroll {{ background:{bg}; border:0; }}

    QPushButton, QToolButton {{ background:{raised}; border:1px solid transparent;
        border-radius:6px; padding:5px 10px; min-height:22px; }}
    QPushButton:hover, QToolButton:hover {{ background:{hover}; }}
    QPushButton:pressed, QToolButton:pressed, QToolButton:checked {{
        background:{selected}; }}
    QPushButton:focus, QToolButton:focus {{ border-color:{text}; }}
    QToolButton#sidebarToggle, QPushButton#windowControl, QPushButton#windowClose {{
        background:transparent; padding:0; min-height:0; }}
    QToolButton#sidebarToggle:hover, QPushButton#windowControl:hover, QPushButton#windowClose:hover {{
        background:{hover}; }}
    QToolButton#sidebarToggle:pressed, QPushButton#windowControl:pressed, QPushButton#windowClose:pressed {{
        background:{selected}; }}
    QPushButton:disabled, QToolButton:disabled {{
        background:{panel}; color:{disabled}; border-color:transparent; }}
    QPushButton#primary, QToolButton#primary {{
        background:{accent}; color:{on_accent}; font-weight:600; }}
    QPushButton#primary:hover, QToolButton#primary:hover {{ background:{accent_hover}; }}
    QPushButton#primary:pressed, QToolButton#primary:pressed {{ background:{accent_pressed}; }}
    QPushButton#primary:focus, QToolButton#primary:focus {{ border-color:{control_border}; }}
    QPushButton#primary:disabled, QToolButton#primary:disabled {{
        background:{raised}; color:{disabled}; border-color:transparent; }}
    QPushButton#quiet, QToolButton#quiet, QPushButton#tool, QToolButton#tool {{
        background:transparent; color:{muted}; }}
    QPushButton#quiet:hover, QToolButton#quiet:hover, QPushButton#tool:hover,
        QToolButton#tool:hover {{ background:{hover}; color:{text}; }}
    QPushButton#quiet:pressed, QToolButton#quiet:pressed, QPushButton#tool:pressed,
        QToolButton#tool:pressed {{ background:{selected}; }}
    QPushButton#quiet:disabled, QToolButton#quiet:disabled, QPushButton#tool:disabled,
        QToolButton#tool:disabled {{ background:transparent; color:{disabled}; }}
    QPushButton#historyNew {{ text-align:left; padding:8px 12px; font-weight:600; }}
    QToolButton#audioMenu, QToolButton#tool {{ padding-right:27px; }}
    QToolButton#audioMenu::menu-indicator, QToolButton#tool::menu-indicator {{
        image:url("{arrow_down}"); width:14px; height:14px;
        subcontrol-origin:padding; subcontrol-position:right center; right:7px; }}

    QComboBox, QSpinBox, QLineEdit {{ background:{field}; border:1px solid {control_border};
        border-radius:8px; padding:6px 10px; min-height:24px;
        selection-background-color:{selected}; selection-color:{text}; }}
    QComboBox, QSpinBox {{ padding-right:32px; }}
    QComboBox {{ combobox-popup:0; }}
    QSpinBox > QLineEdit {{ background:transparent; border:0; border-radius:0;
        padding:0; min-height:0; }}
    QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled {{
        color:{disabled}; background:{panel}; border-color:{border}; }}
    QComboBox:focus, QComboBox:on, QSpinBox:focus, QLineEdit:focus {{ border-color:{text}; }}
    QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button {{
        subcontrol-origin:padding; subcontrol-position:top right;
        width:28px; background:transparent; border:0; }}
    QSpinBox::down-button {{ subcontrol-position:bottom right; }}
    QComboBox::down-arrow {{ image:url("{arrow_down}"); width:16px; height:16px; }}
    QSpinBox::up-arrow {{ image:url("{arrow_up}"); width:12px; height:12px; }}
    QSpinBox::down-arrow {{ image:url("{arrow_down}"); width:12px; height:12px; }}
    QComboBox QFrame {{ background:{panel}; border:0; }}
    QComboBox QAbstractItemView {{ background:{panel}; color:{text};
        border:1px solid {control_border}; border-radius:8px; outline:0;
        selection-background-color:{selected}; selection-color:{text}; padding:4px; }}
    QComboBox QAbstractItemView::item {{ padding:5px 8px; border-radius:5px; }}
    QComboBox QAbstractItemView::item:hover {{ background:{hover}; }}
    QComboBox QAbstractItemView::item:selected {{ background:{selected}; color:{text}; }}
    QCheckBox {{ spacing:8px; background:transparent; min-height:24px;
        border:1px solid transparent; padding:2px; }}
    QCheckBox:focus {{ border-color:{text}; }}
    QCheckBox:disabled {{ color:{disabled}; }}
    QCheckBox::indicator {{ width:16px; height:16px; border:1px solid {control_border};
        border-radius:3px; background:{field}; }}
    QCheckBox::indicator:hover {{ border-color:{text}; }}
    QCheckBox::indicator:checked {{ background:#d4d4d4; border-color:{control_border};
        image:url("{checkmark}"); }}
    QCheckBox::indicator:disabled {{ background:{raised}; border-color:{disabled}; }}
    QPlainTextEdit {{ background:{field}; border:1px solid {control_border};
        border-radius:5px; padding:8px;
        selection-background-color:{selected}; selection-color:{text}; }}
    QPlainTextEdit:focus {{ border-color:{text}; }}
    QPlainTextEdit#composerInput, QPlainTextEdit#composerInput:focus {{
        background:transparent; font-size:19px; border:0; padding:5px; }}
    QPlainTextEdit#composerInput:disabled {{ color:{muted}; }}

    QListView {{ background:{paper}; border:1px solid transparent; outline:0; }}
    QListView:focus {{ border-color:{control_border}; }}
    QListWidget#historyList {{ background:{panel}; }}
    QListWidget#historyList::item {{ border-radius:8px; }}
    QListWidget#historyList::item:hover {{ background:{hover}; }}
    QListWidget#historyList::item:selected {{ background:{selected}; color:{text}; }}
    QScrollBar:vertical {{ background:transparent; width:9px; margin:0; }}
    QScrollBar::handle:vertical {{ background:{control_border}; min-height:30px;
        border:2px solid transparent; border-radius:4px; }}
    QScrollBar::handle:vertical:hover {{ background:{muted}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:transparent; }}

    QMenu {{ background:{panel}; border:1px solid {control_border}; border-radius:8px;
        padding:5px; }}
    QMenu#settingsMenu {{ min-width:160px; }}
    QMenu#audioOptions {{ padding:2px; }}
    QMenu::item {{ padding:7px 26px; border-radius:5px; }}
    QMenu::item:selected {{ background:{selected}; }}
    QMenu::item:disabled {{ color:{disabled}; }}
    QMenu::separator {{ height:1px; background:{border}; margin:4px 8px; }}
    QTabWidget#dialogNavigation::pane {{ border:0; }}
    QTabWidget#dialogNavigation QTabBar::tab {{
        background:transparent; color:{muted}; border:1px solid transparent;
        border-radius:7px; padding:7px 13px; margin:0 4px 0 0; }}
    QTabWidget#dialogNavigation QTabBar::tab:hover {{ background:{hover}; color:{text}; }}
    QTabWidget#dialogNavigation QTabBar::tab:selected {{
        background:{selected}; color:{text}; font-weight:600; }}
    QTabWidget#dialogNavigation QTabBar::tab:focus {{ border-color:{text}; }}
    #dialogNavigation QPushButton {{ background:transparent; color:{muted}; }}
    #dialogNavigation QPushButton:hover {{ background:{hover}; color:{text}; }}
    #dialogNavigation QPushButton:checked {{ background:{selected}; color:{text}; font-weight:600; }}
    QToolTip {{ background:{text}; color:{bg}; border:0; padding:6px; }}
    """.format(
        **colors,
        checkmark=(assets / "checkmark.svg").as_posix(),
        arrow_up=(assets / f"chevron-up-{name}.svg").as_posix(),
        arrow_down=(assets / f"chevron-down-{name}.svg").as_posix(),
    )


def palette(name):
    colors = THEMES[name]
    result = QPalette()
    for role, token in (
        (QPalette.Window, "bg"),
        (QPalette.WindowText, "text"),
        (QPalette.Base, "field"),
        (QPalette.AlternateBase, "panel"),
        (QPalette.Text, "text"),
        (QPalette.Button, "raised"),
        (QPalette.ButtonText, "text"),
        (QPalette.Highlight, "selected"),
        (QPalette.HighlightedText, "text"),
        (QPalette.PlaceholderText, "muted"),
        (QPalette.ToolTipBase, "text"),
        (QPalette.ToolTipText, "bg"),
    ):
        result.setColor(role, QColor(colors[token]))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        result.setColor(QPalette.Disabled, role, QColor(colors["disabled"]))
    return result


STYLE = stylesheet("dark")
