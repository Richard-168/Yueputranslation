from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QTransform
from PySide6.QtWidgets import QPlainTextEdit
from shiboken6 import isValid

_GEOMETRY_EVENTS = {
    QEvent.Type.DevicePixelRatioChange,
    QEvent.Type.LayoutRequest,
    QEvent.Type.Move,
    QEvent.Type.Resize,
    QEvent.Type.WindowStateChange,
}


class ComposerInput(QPlainTextEdit):
    """Keep the input method anchored to the caret through window and layout changes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ime_targets = []
        self._ime_timer = QTimer(self)
        self._ime_timer.setSingleShot(True)
        self._ime_timer.timeout.connect(self._update_ime_geometry)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if not self._ime_targets:
            widget = self
            while widget is not None:
                self._ime_targets.append(widget)
                if widget.isWindow():
                    break
                widget = widget.parentWidget()
            if window_handle := self.window().windowHandle():
                self._ime_targets.append(window_handle)
            for target in self._ime_targets:
                target.installEventFilter(self)
        self.refresh_ime_geometry()

    def focusOutEvent(self, event):
        self._ime_timer.stop()
        for target in self._ime_targets:
            if isValid(target):
                target.removeEventFilter(self)
        self._ime_targets.clear()
        super().focusOutEvent(event)

    def eventFilter(self, watched, event):
        if event.type() in _GEOMETRY_EVENTS and watched in getattr(self, "_ime_targets", ()):
            self.refresh_ime_geometry()
        return super().eventFilter(watched, event)

    def refresh_ime_geometry(self):
        if self.hasFocus():
            self._ime_timer.start(0)

    def _update_ime_geometry(self):
        if QGuiApplication.focusObject() is not self or not self.isVisible():
            return
        # Qt updates this transform when the editor itself moves. An ancestor
        # can move the caret in window coordinates without moving the editor locally.
        position = self.mapTo(self.window(), QPoint())
        input_method = QGuiApplication.inputMethod()
        input_method.setInputItemRectangle(QRectF(self.rect()))
        input_method.setInputItemTransform(QTransform.fromTranslate(position.x(), position.y()))
        input_method.update(
            Qt.InputMethodQuery.ImCursorRectangle
            | Qt.InputMethodQuery.ImAnchorRectangle
            | Qt.InputMethodQuery.ImInputItemClipRectangle
        )
