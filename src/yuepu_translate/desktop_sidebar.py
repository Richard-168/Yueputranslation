"""A resizable history pane with a remembered width and animated toggle."""

from PySide6.QtCore import QEasingCurve, QSignalBlocker, Qt, QVariantAnimation, Signal
from PySide6.QtWidgets import QSizePolicy, QSplitter, QSplitterHandle


class HistoryHandle(QSplitterHandle):
    def __init__(self, orientation, splitter):
        super().__init__(orientation, splitter)
        self.setObjectName("historySplitterHandle")
        self.setAccessibleName("调整会话侧栏宽度")
        self.setToolTip("拖动或按左右方向键调整会话侧栏宽度")
        self.setFocusPolicy(Qt.StrongFocus)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            direction = -1 if event.key() == Qt.Key_Left else 1
            if self.isRightToLeft():
                direction *= -1
            self.splitter().resize_sidebar(direction * 16)
            event.accept()
        else:
            super().keyPressEvent(event)


class HistorySplitter(QSplitter):
    """Keep the user's preferred width independent of temporary window constraints."""

    sidebar_toggled = Signal(bool)
    sidebar_resized = Signal(int)

    DEFAULT_WIDTH = 328
    MIN_WIDTH = 204
    MAX_WIDTH = 520
    WORKSPACE_MIN_WIDTH = 540
    WIDTH_SETTING = "workspace/sidebarWidth"
    EXPANDED_SETTING = "workspace/sidebarExpanded"

    def __init__(self, sidebar, workspace, settings):
        super().__init__(Qt.Horizontal)
        self.setObjectName("historySplitter")
        self.sidebar = sidebar
        self.settings = settings
        try:
            saved_width = settings.value(self.WIDTH_SETTING, self.DEFAULT_WIDTH, type=int)
        except (TypeError, ValueError):
            saved_width = self.DEFAULT_WIDTH
        self._preferred_width = max(self.MIN_WIDTH, min(self.MAX_WIDTH, saved_width))
        self._expanded = settings.value(self.EXPANDED_SETTING, True, type=bool)
        self._reported_width = -1
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._apply_width)
        self._animation.finished.connect(self._finish_transition)

        self.setHandleWidth(6)
        self.setChildrenCollapsible(False)
        sidebar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        sidebar.setMinimumWidth(0)
        sidebar.setMaximumWidth(self.MAX_WIDTH)
        self.addWidget(sidebar)
        self.addWidget(workspace)
        self.setStretchFactor(0, 0)
        self.setStretchFactor(1, 1)
        self.splitterMoved.connect(self._on_splitter_moved)
        self._finish_transition()

    def createHandle(self):
        return HistoryHandle(self.orientation(), self)

    @property
    def sidebar_expanded(self):
        return self._expanded

    @property
    def sidebar_width(self):
        return self.sizes()[0] if self.sidebar.isVisibleTo(self) else 0

    def toggle_sidebar(self):
        self.set_sidebar_expanded(not self._expanded)

    def set_sidebar_expanded(self, expanded):
        if expanded == self._expanded:
            return
        current_width = self.sidebar_width
        self._animation.stop()
        self._expanded = expanded
        self.settings.setValue(self.EXPANDED_SETTING, expanded)
        self.sidebar_toggled.emit(expanded)
        self.sidebar.setMinimumWidth(0)
        self.sidebar.show()
        self._apply_width(current_width)
        target = self._bounded_width(self._preferred_width) if expanded else 0
        if self.isVisible() and current_width != target:
            self.handle(1).setEnabled(False)
            with QSignalBlocker(self._animation):
                self._animation.setStartValue(current_width)
                self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._finish_transition()

    def resize_sidebar(self, delta):
        if self._expanded:
            self._choose_width(self.sidebar_width + delta)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._animation.state() == QVariantAnimation.Running:
            self._apply_width(self._animation.currentValue())
        else:
            self._finish_transition()

    def _width_limit(self):
        available = self.contentsRect().width() - self.handleWidth() - self.WORKSPACE_MIN_WIDTH
        return min(self.MAX_WIDTH, max(0, available))

    def _bounded_width(self, width):
        return min(self._width_limit(), max(self.MIN_WIDTH, width))

    def _on_splitter_moved(self, position, index):
        if self._expanded:
            self._choose_width(self.sidebar_width)

    def _choose_width(self, width):
        self._animation.stop()
        self._preferred_width = max(self.MIN_WIDTH, self._bounded_width(width))
        self.settings.setValue(self.WIDTH_SETTING, self._preferred_width)
        self._finish_transition()

    def _finish_transition(self):
        minimum = min(self.MIN_WIDTH, self._width_limit()) if self._expanded else 0
        self.sidebar.setMinimumWidth(minimum)
        self.sidebar.setVisible(self._expanded)
        self.handle(1).setEnabled(self._expanded)
        self._apply_width(self._bounded_width(self._preferred_width) if self._expanded else 0)

    def _apply_width(self, width):
        width = min(self._width_limit(), max(0, int(width)))
        if self.sidebar.isVisibleTo(self):
            self.setSizes([width, max(0, self.contentsRect().width() - self.handleWidth() - width)])
        actual = self.sidebar_width
        if actual != self._reported_width:
            self._reported_width = actual
            self.sidebar_resized.emit(actual)
