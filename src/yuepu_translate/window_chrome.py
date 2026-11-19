"""Windows caption controls integrated into the Qt application header."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPalette, QPen, QShowEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QWidget,
)

_WM_NCCALCSIZE = 0x0083
_WM_NCHITTEST = 0x0084
_HTCLIENT = 1
_HTCAPTION = 2
_RESIZE_HIT_TEST = {
    (-1, 0): 10,  # HTLEFT
    (1, 0): 11,  # HTRIGHT
    (0, -1): 12,  # HTTOP
    (-1, -1): 13,  # HTTOPLEFT
    (1, -1): 14,  # HTTOPRIGHT
    (0, 1): 15,  # HTBOTTOM
    (-1, 1): 16,  # HTBOTTOMLEFT
    (1, 1): 17,  # HTBOTTOMRIGHT
}
_MONITOR_DEFAULTTONEAREST = 2
_SM_CXSIZEFRAME = 32
_SM_CYSIZEFRAME = 33
_SM_CXPADDEDBORDER = 92
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_BORDER_COLOR = 34
_DWMWCP_DONOTROUND = 1
_DWMWCP_ROUND = 2
_DWMWA_COLOR_NONE = 0xFFFFFFFE


class _MonitorInfo(ctypes.Structure):
    _fields_ = (
        ("size", wintypes.DWORD),
        ("monitor", wintypes.RECT),
        ("work", wintypes.RECT),
        ("flags", wintypes.DWORD),
    )


class _DwmMargins(ctypes.Structure):
    _fields_ = (
        ("left", ctypes.c_int),
        ("right", ctypes.c_int),
        ("top", ctypes.c_int),
        ("bottom", ctypes.c_int),
    )


if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.IsZoomed.argtypes = [wintypes.HWND]
    _user32.IsZoomed.restype = wintypes.BOOL
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    _user32.ScreenToClient.restype = wintypes.BOOL
    _user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
    _user32.MonitorFromRect.restype = wintypes.HMONITOR
    _user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL
    _user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    _user32.GetDpiForWindow.restype = wintypes.UINT
    _user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
    _user32.GetSystemMetricsForDpi.restype = ctypes.c_int
    _dwmapi = ctypes.WinDLL("dwmapi")
    _dwmapi.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _dwmapi.DwmSetWindowAttribute.restype = wintypes.LONG
    _dwmapi.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.POINTER(_DwmMargins)]
    _dwmapi.DwmExtendFrameIntoClientArea.restype = wintypes.LONG
else:
    _user32 = None
    _dwmapi = None


def _set_dwm_attribute(hwnd: int, attribute: int, value: int) -> bool:
    setting = wintypes.DWORD(value)
    return (
        _dwmapi.DwmSetWindowAttribute(
            hwnd, attribute, ctypes.byref(setting), ctypes.sizeof(setting)
        )
        == 0
    )


class _CaptionButton(QPushButton):
    def __init__(self, symbol: str, label: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("windowClose" if symbol == "close" else "windowControl")
        self.setFixedWidth(42)
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.set_symbol(symbol, label)

    def set_symbol(self, symbol: str, label: str) -> None:
        self._symbol = symbol
        self.setAccessibleName(label)
        self.setToolTip(label)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        pen = QPen(self.palette().color(QPalette.ColorRole.ButtonText))
        pen.setWidthF(1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if self._symbol == "minimize":
            painter.drawLine(QPointF(-5, 0), QPointF(5, 0))
        elif self._symbol == "maximize":
            painter.drawRect(QRectF(-5, -5, 10, 10))
        elif self._symbol == "restore":
            painter.drawLine(QPointF(-2, -6), QPointF(6, -6))
            painter.drawLine(QPointF(6, -6), QPointF(6, 2))
            painter.drawRect(QRectF(-5, -3, 8, 8))
        else:
            painter.drawLine(QPointF(-5, -5), QPointF(5, 5))
            painter.drawLine(QPointF(-5, 5), QPointF(5, -5))


class ChromeWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._integrated_caption = _user32 is not None and QApplication.platformName() == "windows"
        self._caption_areas: tuple[QWidget, ...] = ()
        self._maximize_button: _CaptionButton | None = None
        self._paint_frame = False

    def set_caption_area(self, *areas: QWidget) -> None:
        """Allow window dragging from the blank space and labels in these widgets."""
        self._caption_areas = areas

    def caption_controls(self, parent: QWidget) -> QWidget:
        controls = QWidget(parent)
        if not self._integrated_caption:
            controls.hide()
            return controls

        controls.setProperty("noCaptionDrag", True)
        controls.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        minimize = _CaptionButton("minimize", "最小化", controls)
        minimize.clicked.connect(self.showMinimized)
        self._maximize_button = _CaptionButton("maximize", "最大化", controls)
        self._maximize_button.clicked.connect(self._toggle_maximized)
        close = _CaptionButton("close", "关闭窗口", controls)
        close.clicked.connect(self.close)
        for button in (minimize, self._maximize_button, close):
            row.addWidget(button)
        self._update_maximize_button()
        return controls

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _update_maximize_button(self) -> None:
        if self._maximize_button is None:
            return
        if self.isMaximized():
            self._maximize_button.set_symbol("restore", "还原窗口")
        else:
            self._maximize_button.set_symbol("maximize", "最大化")

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._update_maximize_button()
        if event.type() in (QEvent.Type.WindowStateChange, QEvent.Type.PaletteChange):
            if self.isVisible():
                self._update_window_frame()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._update_window_frame()

    def _frame_color(self) -> QColor:
        background = self.palette().color(QPalette.ColorRole.Window)
        return QColor("#454545" if background.lightness() < 128 else "#c8c8c8")

    def _update_window_frame(self) -> None:
        if not self._integrated_caption:
            return
        hwnd = int(self.winId())
        restored = not (self.isMaximized() or self.isFullScreen())
        color = self._frame_color()
        colorref = color.red() | (color.green() << 8) | (color.blue() << 16)
        native_border = _set_dwm_attribute(
            hwnd, _DWMWA_BORDER_COLOR, colorref if restored else _DWMWA_COLOR_NONE
        )
        _set_dwm_attribute(
            hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND if restored else _DWMWCP_DONOTROUND
        )
        if not native_border:
            # Earlier Windows versions can still provide a shadow for a small extended frame.
            margins = _DwmMargins(bottom=int(restored))
            _dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        self._paint_frame = restored and not native_border
        inset = int(self._paint_frame)
        self.setContentsMargins(inset, inset, inset, inset)
        if self._paint_frame:
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self._paint_frame:
            with QPainter(self) as painter:
                painter.setPen(self._frame_color())
                painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def nativeEvent(self, event_type, message):
        if not self._integrated_caption or event_type != b"windows_generic_MSG":
            return super().nativeEvent(event_type, message)

        native = wintypes.MSG.from_address(int(message))
        if native.message == _WM_NCCALCSIZE:
            # Keep the real window styles so Win32 still handles snap, drag and resizing.
            if _user32.IsZoomed(native.hWnd):
                self._fit_maximized_client(native.lParam)
            return True, 0
        if native.message == _WM_NCHITTEST:
            return True, self._hit_test(native.hWnd, native.lParam)
        return super().nativeEvent(event_type, message)

    @staticmethod
    def _fit_maximized_client(address: int) -> None:
        # Both WM_NCCALCSIZE parameter forms start with the proposed client RECT.
        rect = wintypes.RECT.from_address(address)
        monitor = _user32.MonitorFromRect(ctypes.byref(rect), _MONITOR_DEFAULTTONEAREST)
        info = _MonitorInfo(ctypes.sizeof(_MonitorInfo))
        if _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            rect.left = max(rect.left, info.work.left)
            rect.top = max(rect.top, info.work.top)
            rect.right = min(rect.right, info.work.right)
            rect.bottom = min(rect.bottom, info.work.bottom)

    def _hit_test(self, hwnd: int, position: int) -> int:
        # lParam stores signed screen coordinates, including negative monitor origins.
        point = wintypes.POINT(
            ctypes.c_short(position & 0xFFFF).value,
            ctypes.c_short((position >> 16) & 0xFFFF).value,
        )
        if not (_user32.IsZoomed(hwnd) or self.isFullScreen()):
            rect = wintypes.RECT()
            if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                dpi = _user32.GetDpiForWindow(hwnd) or 96
                padding = _user32.GetSystemMetricsForDpi(_SM_CXPADDEDBORDER, dpi)
                width = _user32.GetSystemMetricsForDpi(_SM_CXSIZEFRAME, dpi) + padding
                height = _user32.GetSystemMetricsForDpi(_SM_CYSIZEFRAME, dpi) + padding
                x_edge = int(point.x >= rect.right - width) - int(point.x < rect.left + width)
                y_edge = int(point.y >= rect.bottom - height) - int(point.y < rect.top + height)
                edge = _RESIZE_HIT_TEST.get((x_edge, y_edge))
                if edge is not None:
                    return edge

        if _user32.ScreenToClient(hwnd, ctypes.byref(point)):
            scale = self.devicePixelRatioF()
            logical_position = QPoint(int(point.x // scale), int(point.y // scale))
            if self._is_caption_position(logical_position):
                return _HTCAPTION
        return _HTCLIENT

    def _is_caption_position(self, position: QPoint) -> bool:
        widget = self.childAt(position)
        while widget is not None and widget is not self:
            if (
                isinstance(widget, QAbstractButton)
                or widget.property("noCaptionDrag")
                or widget.focusPolicy() != Qt.FocusPolicy.NoFocus
            ):
                return False
            if widget in self._caption_areas:
                return True
            widget = widget.parentWidget()
        return False
