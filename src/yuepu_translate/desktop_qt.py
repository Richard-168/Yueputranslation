"""Qt desktop client. Real local engine; session-only paired transcript."""

from __future__ import annotations

import queue
import threading
import time
from collections import OrderedDict, deque
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    QSettings,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from .cloud_config import CloudConfig, load_settings
from .cloud_dialog import CloudDialog
from .desktop_engine import AudioPlayer, Cancelled, Engine, Microphone, Request, SystemAudio
from .desktop_theme import STYLE, THEMES, TerminalEmpty, palette, stylesheet
from .inference_control import InferenceCancelled
from .live_session import LiveSession, make_live_stream
from .paths import DATA_DIR
from .song_pipeline import SongFile, SongSession
from .transcript_model import TranscriptEntry, TranscriptModel

ROOT = DATA_DIR
NAMES = {"zh": "普通话", "yue": "粤语", "en": "英文"}


class PairDelegate(QStyledItemDelegate):
    """Only visible rows are painted; paired columns always share one row height."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.font_size = 15
        self.colors = THEMES["dark"]
        self.cache = OrderedDict()
        self.heights = OrderedDict()

    def documents(self, entry, width):
        key = (entry.key, entry.revision, width, self.font_size)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        docs = []
        active = entry.status in {"识别中", "翻译中"}
        source = entry.source or ("正在识别…" if active else "未完成有效语句识别")
        target = entry.target or (entry.status + "…" if active else entry.status)
        for text, confirmed in ((source, entry.source_confirmed), (target, entry.target_confirmed)):
            doc = QTextDocument()
            doc.setDocumentMargin(0)
            doc.setDefaultFont(QFont("Microsoft YaHei UI", self.font_size))
            option = QTextOption()
            option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
            doc.setDefaultTextOption(option)
            cursor = QTextCursor(doc)
            fixed, draft = QTextCharFormat(), QTextCharFormat()
            fixed.setForeground(QColor(self.colors["text"]))
            draft.setForeground(QColor(self.colors["draft"]))
            cursor.insertText(text[:confirmed], fixed)
            cursor.insertText(text[confirmed:], draft)
            doc.setTextWidth(max(80, (width // 2) - 58))
            docs.append(doc)
        height = max(104, int(max(d.size().height() for d in docs)) + 66)
        self.cache[key] = (docs, height)
        self.heights[(entry.key, width, self.font_size)] = (entry.revision, height)
        while len(self.cache) > 600:
            self.cache.popitem(last=False)
        while len(self.heights) > 20000:
            self.heights.popitem(last=False)
        return docs, height

    def sizeHint(self, option, index):
        entry = index.data(Qt.UserRole)
        if entry is None:
            return QSize(100, 104)
        width = max(300, self.view.viewport().width())
        key = (entry.key, width, self.font_size)
        cached = self.heights.get(key)
        height = cached[1] if cached is not None and cached[0] == entry.revision else None
        return QSize(width, height if height is not None else self.documents(entry, width)[1])

    def paint(self, painter, option, index):
        entry = index.data(Qt.UserRole)
        if entry is None:
            return
        rect = option.rect
        docs, height = self.documents(entry, rect.width())
        painter.save()
        painter.setClipRect(rect)
        selected = self.view.selectionModel().isSelected(index)
        painter.fillRect(
            rect, QColor(self.colors["selected"] if selected else self.colors["paper"])
        )
        middle = rect.left() + rect.width() // 2
        if not selected:
            painter.fillRect(
                middle, rect.top(), rect.width() // 2, rect.height(), QColor(self.colors["target"])
            )
        painter.setPen(QColor(self.colors["border"]))
        painter.drawLine(middle, rect.top(), middle, rect.bottom())
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        painter.setPen(QColor(self.colors["muted"]))
        painter.drawText(
            rect.left() + 26,
            rect.top() + 25,
            f"{entry.timestamp}   ·   {NAMES.get(entry.source_language, entry.source_language)}",
        )
        painter.setPen(QColor(self.colors["muted"]))
        painter.drawText(
            middle + 26,
            rect.top() + 25,
            f"{NAMES.get(entry.target_language, entry.target_language)}   ·   {entry.status}",
        )
        for x, doc, is_target in ((rect.left() + 26, docs[0], False), (middle + 26, docs[1], True)):
            painter.save()
            painter.translate(x, rect.top() + 42)
            context = doc.documentLayout().PaintContext()
            context.palette.setColor(
                context.palette.ColorRole.Text,
                QColor(self.colors["text"] if is_target and entry.target else self.colors["draft"]),
            )
            doc.documentLayout().draw(painter, context)
            painter.restore()
        painter.restore()


class SmoothTranscriptView(QListView):
    position_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setResizeMode(QListView.Adjust)
        self.setLayoutMode(QListView.Batched)
        self.setBatchSize(128)
        self.setSpacing(0)
        self.follow_tail = True
        self.smooth = True
        self.interaction_serial = 0
        self.animation = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.finished.connect(self._settled)
        self.verticalScrollBar().sliderPressed.connect(self.interrupt)
        self.verticalScrollBar().sliderReleased.connect(self._settled)
        self.verticalScrollBar().rangeChanged.connect(self._range_changed)
        self.paint_times = deque(maxlen=600)

    def interrupt(self):
        self.interaction_serial += 1
        self.animation.stop()
        self.follow_tail = False
        self.position_changed.emit()

    def _settled(self):
        bar = self.verticalScrollBar()
        if bar.maximum() - bar.value() <= 4:
            self.follow_tail = True
        self.position_changed.emit()

    def _range_changed(self, *args):
        # Batched row layout can finish after the insertion event. Follow its
        # final range while preserving any intervening user scroll gesture.
        if self.follow_tail:
            QTimer.singleShot(0, self._follow_layout)

    def _follow_layout(self):
        if self.follow_tail:
            self.animate_to(self.verticalScrollBar().maximum(), 230)

    def animate_to(self, target, duration=200):
        bar = self.verticalScrollBar()
        target = max(bar.minimum(), min(bar.maximum(), int(target)))
        self.animation.stop()
        if not self.smooth or abs(target - bar.value()) < 2:
            bar.setValue(target)
            self._settled()
            return
        self.animation.setDuration(duration)
        self.animation.setStartValue(bar.value())
        self.animation.setEndValue(target)
        self.animation.start()

    def latest(self):
        self.follow_tail = True
        self.animate_to(self.verticalScrollBar().maximum(), 240)

    def wheelEvent(self, event):
        bar = self.verticalScrollBar()
        pixel = event.pixelDelta().y()
        current_target = (
            self.animation.endValue()
            if self.animation.state() == QAbstractAnimation.Running
            else bar.value()
        )
        self.interrupt()
        if pixel:
            # Precision touchpads already provide native smooth pixel deltas.
            bar.setValue(bar.value() - pixel)
            self._settled()
        else:
            self.animate_to(int(current_target) - event.angleDelta().y() / 120 * 90, 160)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (
            Qt.Key_Up,
            Qt.Key_Down,
            Qt.Key_PageUp,
            Qt.Key_PageDown,
            Qt.Key_Home,
            Qt.Key_End,
        ):
            self.interrupt()
        super().keyPressEvent(event)
        self._settled()

    def paintEvent(self, event):
        started = time.perf_counter()
        super().paintEvent(event)
        self.paint_times.append((time.perf_counter() - started) * 1000)


class Window(QMainWindow):
    def __init__(self, muted=False):
        super().__init__()
        self.preferences = QSettings(
            QSettings.IniFormat, QSettings.UserScope, "YuePuTranslate", "Desktop"
        )
        self.theme = "dark"
        self.setWindowTitle("粤普随译 · YUEPU TERMINAL")
        self.resize(1240, 850)
        self.setMinimumSize(960, 700)
        self.events = queue.Queue()
        self.jobs = queue.Queue(maxsize=2)
        self.cancel = threading.Event()
        self.engine = Engine()
        self.player = AudioPlayer(
            lambda message: self.events.put((self.epoch, 0, "audio_error", message)), muted=muted
        )
        self.microphone = None
        self.song_session = None
        self.song_keys = {}
        self.live_versions = {}
        self.song_final_block = -1
        self.song_file_vocals = False
        self.cloud_enabled = False
        self.network_mode = "offline"
        self.cloud_config = CloudConfig()
        self.cloud_remember = False
        cloud_warning = ""
        try:
            self.cloud_config, self.cloud_remember = load_settings()
        except (RuntimeError, OSError) as exc:
            cloud_warning = str(exc)
        self.epoch = self.pending = 0
        self.sequence = 0
        self.ready = self.listening = self.closing = False
        self.model = TranscriptModel()
        self.active_ids = set()
        self.unread = 0
        self._build()
        self.apply_theme(self.preferences.value("appearance", "dark"), persist=False)
        self.source_changed()
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(25)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.translate_input)
        QShortcut(QKeySequence("Esc"), self, activated=self.stop)
        copy_shortcut = QShortcut(QKeySequence.Copy, self.view, activated=self.copy_records)
        copy_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._buttons()
        if cloud_warning:
            self.status(cloud_warning, True)

    def button(self, text, callback, kind="", parent=None):
        button = QPushButton(text, parent)
        if kind:
            button.setObjectName(kind)
        button.clicked.connect(callback)
        button.setCursor(Qt.PointingHandCursor)
        return button

    def _build(self):
        host = QWidget()
        host.setObjectName("host")
        root = QVBoxLayout(host)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(host)
        header = QFrame()
        header.setObjectName("header")
        top = QHBoxLayout(header)
        top.setContentsMargins(22, 12, 22, 12)
        top.setSpacing(12)
        mark = QLabel("YP / ")
        mark.setObjectName("brandMark")
        top.addWidget(mark)
        branding = QVBoxLayout()
        branding.setSpacing(2)
        brand = QLabel("粤普随译")
        brand.setObjectName("brand")
        branding.addWidget(brand)
        branding.addWidget(self.label("YUEPU  /  INTERPRETATION TERMINAL", "eyebrow"))
        top.addLayout(branding)
        top.addStretch()
        self.dark_button = self.button("深色", lambda: self.apply_theme("dark"), "theme")
        self.light_button = self.button("浅色", lambda: self.apply_theme("light"), "theme")
        self.dark_button.setProperty("appearance", "dark")
        self.light_button.setProperty("appearance", "light")
        self.dark_button.setAccessibleName("切换深色主题")
        self.light_button.setAccessibleName("切换浅色主题")
        for button in (self.dark_button, self.light_button):
            button.setCheckable(True)
            top.addWidget(button)
        top.addSpacing(8)
        self.cloud_button = self.button("联网设置", self.cloud_settings, "quiet")
        top.addWidget(self.cloud_button)
        top.addWidget(self.button("设置", self.settings, "quiet"))
        root.addWidget(header)

        content = QWidget()
        shell = QHBoxLayout(content)
        shell.setContentsMargins(22, 20, 22, 20)
        shell.setSpacing(22)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(238)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(18, 20, 18, 18)
        sidebar_layout.setSpacing(10)
        control_scroll = QScrollArea()
        control_scroll.setObjectName("controlScroll")
        control_scroll.setWidgetResizable(True)
        control_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        control_scroll.setFrameShape(QFrame.NoFrame)
        control_fields = QWidget()
        control_fields.setObjectName("controlFields")
        controls = QVBoxLayout(control_fields)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(10)
        controls.addWidget(self.label("CONTROL / 控制台", "eyebrow"))
        controls.addWidget(self.label("会话控制", "panelTitle"))
        controls.addSpacing(12)
        controls.addWidget(self.label("01 / 输入通道", "section"))
        self.source_box = QComboBox()
        self.source_box.addItems(["麦克风", "设备播放声音"])
        self.source_box.setAccessibleName("声音来源")
        self.source_box.currentTextChanged.connect(self.source_changed)
        controls.addWidget(self.source_box)
        controls.addSpacing(8)
        direction_heading = QHBoxLayout()
        direction_heading.addWidget(self.label("02 / 翻译方向", "section"))
        direction_heading.addStretch()
        self.swap_button = self.button("交换方向", self.swap, "swap")
        self.swap_button.setAccessibleName("交换翻译方向")
        self.swap_button.setToolTip("交换粤语与普通话的翻译方向")
        direction_heading.addWidget(self.swap_button)
        controls.addLayout(direction_heading)
        self.direction_box = QComboBox()
        self.direction_box.addItems(["粤语 → 普通话", "普通话 → 粤语"])
        self.direction_box.setAccessibleName("翻译方向")
        self.direction_box.currentIndexChanged.connect(self.direction_changed)
        controls.addWidget(self.direction_box)
        controls.addSpacing(8)
        controls.addWidget(self.label("03 / 识别与播报", "section"))
        self.profile_box = QComboBox()
        self.profile_box.addItems(["会话（实时字幕）", "段落修订（实验）"])
        self.profile_box.setAccessibleName("识别模式")
        self.profile_box.setToolTip(
            "会话：边说边显示原文，翻译随后更新。\n段落修订：使用较大的模型复核整段，等待较长。"
        )
        self.profile_box.currentIndexChanged.connect(self.source_changed)
        controls.addWidget(self.profile_box)
        self.auto_box = QCheckBox("自动播报译音")
        self.auto_box.setChecked(True)
        controls.addWidget(self.auto_box)
        controls.addStretch()
        self.mode_hint = self.label("", "muted")
        self.mode_hint.setWordWrap(True)
        controls.addWidget(self.mode_hint)
        control_scroll.setWidget(control_fields)
        sidebar_layout.addWidget(control_scroll, 1)
        sidebar_layout.addSpacing(8)
        self.network_pill = self.label("本地离线", "pill")
        self.network_pill.setToolTip("默认仅使用本地模型；联网增强需手动开启。")
        sidebar_layout.addWidget(self.network_pill)
        self.load_button = self.button("加载离线模型", self.load, "primary")
        sidebar_layout.addWidget(self.load_button)
        self.record_button = self.button("开始收音", self.toggle_capture, "primary")
        sidebar_layout.addWidget(self.record_button)
        self.stop_button = self.button("停止任务    Esc", self.stop)
        sidebar_layout.addWidget(self.stop_button)
        shell.addWidget(self.sidebar)

        body = QVBoxLayout()
        body.setSpacing(16)
        heading = QHBoxLayout()
        title = QVBoxLayout()
        title.setSpacing(4)
        title.addWidget(self.label("实时同传", "title"))
        title.addWidget(self.label("LIVE INTERPRETATION  /  双语会话工作区", "eyebrow"))
        heading.addLayout(title)
        heading.addStretch()
        self.count_label = self.label("0 条字幕", "count")
        heading.addWidget(self.count_label, 0, Qt.AlignTop)
        body.addLayout(heading)

        tabs = QHBoxLayout()
        tabs.setSpacing(0)
        self.live_tab = self.button("实时字幕", lambda: self.show_composer(False), "tab")
        self.text_tab = self.button("文字输入", lambda: self.show_composer(True), "tab")
        for tab in (self.live_tab, self.text_tab):
            tab.setCheckable(True)
            tabs.addWidget(tab)
        self.live_tab.setChecked(True)
        tabs.addStretch()
        self.file_button = self.button("导入音频", self.open_audio, "quiet")
        tabs.addWidget(self.file_button)
        self.replay_button = self.button("播报选中句", self.replay, "quiet")
        self.replay_button.setToolTip("播报选中的译文；未选中时播报最后一句")
        tabs.addWidget(self.replay_button)
        body.addLayout(tabs)
        work = QFrame()
        work.setObjectName("workarea")
        area = QVBoxLayout(work)
        area.setContentsMargins(1, 1, 1, 1)
        area.setSpacing(0)
        language_bar = QFrame()
        language_bar.setObjectName("languages")
        languages = QHBoxLayout(language_bar)
        languages.setContentsMargins(26, 16, 26, 16)
        languages.setSpacing(0)
        self.source_header = QLabel("原文 / 粤语")
        self.target_header = QLabel("译文 / 普通话")
        for label in (self.source_header, self.target_header):
            label.setObjectName("panelTitle")
            languages.addWidget(label, 1)
        self.target_header.setContentsMargins(26, 0, 0, 0)
        area.addWidget(language_bar)
        self.view = SmoothTranscriptView()
        self.view.setModel(self.model)
        self.delegate = PairDelegate(self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.setAccessibleName("按时间排列的原文与译文字幕，左右对应，可滚动回看")
        self.view.position_changed.connect(self.position_changed)
        area.addWidget(self.view, 1)
        self.empty = TerminalEmpty(self.view.viewport())
        foot = QHBoxLayout()
        foot.setContentsMargins(18, 10, 18, 11)
        self.cache_label = QLabel("仅本次会话 · 退出前请导出")
        self.cache_label.setWordWrap(True)
        self.cache_label.setToolTip("最多保留 10,000 条 / 原文译文合计 200 万字符")
        self.cache_label.setObjectName("muted")
        foot.addWidget(self.cache_label, 1)
        self.latest_button = self.button("回到最新 ↓", self.go_latest, "quiet")
        self.latest_button.hide()
        foot.addWidget(self.latest_button)
        self.copy_button = self.button("复制", self.copy_records, "quiet")
        self.copy_button.setToolTip("复制选中的双语记录；未选中时复制全部记录")
        self.clear_button = self.button("清空", self.clear_records, "quiet")
        foot.addWidget(self.copy_button)
        foot.addWidget(self.clear_button)
        self.export_button = self.button("导出记录  ↗", self.export_records)
        foot.addWidget(self.export_button)
        area.addLayout(foot)
        body.addWidget(work, 1)
        self.composer = QWidget()
        compose = QHBoxLayout(self.composer)
        compose.setContentsMargins(0, 0, 0, 0)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("输入短句，Ctrl + Enter 翻译（每次最多 120 字）")
        self.input.setMaximumHeight(92)
        self.input.setAccessibleName("要翻译的短句")
        compose.addWidget(self.input, 1)
        self.translate_button = self.button("翻译输入", self.translate_input, "primary")
        compose.addWidget(self.translate_button)
        body.addWidget(self.composer)
        self.composer.hide()
        shell.addLayout(body, 1)
        root.addWidget(content, 1)
        statusbar = QFrame()
        statusbar.setObjectName("statusbar")
        bottom = QHBoxLayout(statusbar)
        bottom.setContentsMargins(22, 9, 22, 9)
        bottom.setSpacing(16)
        self.state_label = self.label("待机 / STANDBY", "state")
        bottom.addWidget(self.state_label)
        self.status_label = QLabel("先加载离线模型，再开始交流。")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("muted")
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.label("Ctrl + Enter  翻译   /   Esc  停止", "muted"))
        root.addWidget(statusbar)
        self.number_mode = "original"
        self.model.rowsInserted.connect(self._model_changed)
        self.model.rowsRemoved.connect(self._model_changed)
        self.model.modelReset.connect(self._model_changed)
        self.view.selectionModel().selectionChanged.connect(lambda: self._buttons())

    @staticmethod
    def label(text, kind):
        label = QLabel(text)
        label.setObjectName(kind)
        return label

    def apply_theme(self, theme, *, persist=True):
        self.theme = theme if isinstance(theme, str) and theme in THEMES else "dark"
        app = QApplication.instance()
        app.setPalette(palette(self.theme))
        app.setStyleSheet(stylesheet(self.theme))
        self.dark_button.setChecked(self.theme == "dark")
        self.light_button.setChecked(self.theme == "light")
        self.delegate.colors = THEMES[self.theme]
        self.delegate.cache.clear()
        self.empty.set_theme(self.theme)
        self.view.viewport().update()
        if persist:
            self.preferences.setValue("appearance", self.theme)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "empty"):
            QTimer.singleShot(0, self._resize_empty)

    def _resize_empty(self):
        self.empty.setGeometry(self.view.viewport().rect())

    def _model_changed(self, *args):
        count = self.model.rowCount()
        self.empty.setVisible(count == 0)
        self._resize_empty()
        self.count_label.setText(f"{count:,} 条字幕")
        if self.model.evicted:
            self.cache_label.setText(
                f"已达缓存上限，最早 {self.model.evicted:,} 条已移出 · 请及时导出"
            )
        else:
            self.cache_label.setText("仅本次会话 · 退出前请导出")
        self._buttons()

    def source_language(self):
        return "yue" if self.direction_box.currentIndex() == 0 else "zh"

    def direction_changed(self):
        source = self.source_language()
        self.source_header.setText(f"原文 / {NAMES[source]}")
        self.target_header.setText(f"译文 / {NAMES['zh' if source == 'yue' else 'yue']}")

    def swap(self):
        if not self.pending and not self.listening:
            self.direction_box.setCurrentIndex(1 - self.direction_box.currentIndex())

    def source_changed(self):
        if hasattr(self, "profile_box") and self.profile_box.currentIndex() == 1:
            self.mode_hint.setText(
                "前文已固定，末尾仍可修订；只翻译新增内容，长讲话分段保留。"
                + (
                    "设备收音期间仅字幕。"
                    if self.source_box.currentIndex() == 1
                    else "句末确认后播报译音。"
                )
            )
        elif self.source_box.currentIndex() == 1:
            self.mode_hint.setText("设备声音：原文随听随更新，末尾仍可修订。收音期间仅字幕。")
        else:
            self.mode_hint.setText("边说边显示原文，末尾仍可修订。停顿后确认并播报。")
        if self.cloud_enabled:
            self.mode_hint.setText(
                self.mode_hint.text()
                + (
                    " 本次任务已回退本地，不再上传；再次开始任务才尝试联网。"
                    if self.network_mode == "fallback"
                    else " 已开启联网增强，会上传近期音频和待翻译文字；失败后本次任务转为本地处理。"
                )
            )
        self._buttons()

    def show_composer(self, show):
        self.composer.setVisible(show)
        self.text_tab.setChecked(show)
        self.live_tab.setChecked(not show)
        self._update_empty()
        if show:
            self.input.setFocus()

    def status(self, text, error=False):
        self.status_label.setText(text)
        for label in (self.status_label, self.state_label):
            label.setProperty("severity", "error" if error else "normal")
            label.style().unpolish(label)
            label.style().polish(label)
        self._update_state()

    def _update_state(self):
        if self.closing:
            text = "退出 / CLOSING"
        elif self.listening:
            text = "收音中 / LIVE"
        elif self.pending:
            text = "处理中 / BUSY"
        elif self.status_label.property("severity") == "error":
            text = "异常 / ERROR"
        elif self.ready:
            text = "就绪 / READY"
        else:
            text = "待机 / STANDBY"
        self.state_label.setText(text)

    def _update_empty(self):
        if self.text_tab.isChecked():
            self.empty.title.setText("从一句话开始")
            self.empty.subtitle.setText("在下方输入短句，原文与译文将在这里配对显示。")
            self.empty.steps.setText(
                "输入 1–120 字  /  Ctrl + Enter 翻译"
                if self.ready
                else "先加载左侧离线模型，再输入短句。"
            )
        elif self.listening:
            self.empty.title.setText("正在聆听")
            self.empty.subtitle.setText("等待有效语音，识别结果将在这里显示。")
            self.empty.steps.setText("再次点击收音按钮确认末尾  /  Esc 取消任务")
        elif self.pending:
            self.empty.title.setText("正在准备会话")
            self.empty.subtitle.setText("任务处理中，请稍候。")
            self.empty.steps.setText("Esc 可停止当前任务")
        else:
            self.empty.title.setText("语音通道已就绪" if self.ready else "等待接入语音")
            self.empty.subtitle.setText("让语言相通，让交流继续。")
            self.empty.steps.setText(
                "点击左侧「开始收音」，或导入音频。"
                if self.ready
                else "01  选择音源与方向  /  02  加载模型  /  03  开始收音"
            )

    def _buttons(self):
        if not hasattr(self, "load_button"):
            return
        idle = self.pending == 0 and not self.closing
        self.load_button.setEnabled(idle and not self.ready)
        self.load_button.setVisible(not self.ready)
        self.record_button.setVisible(self.ready)
        self.record_button.setEnabled(
            not self.closing and (self.listening or (self.ready and idle))
        )
        self.record_button.setText(
            "停止收音"
            if self.listening
            else "翻译设备声音"
            if self.source_box.currentIndex() == 1
            else "开始收音"
        )
        self.stop_button.setEnabled(bool(self.pending or self.listening or self.player.busy))
        for box in (self.direction_box, self.source_box, self.swap_button, self.profile_box):
            box.setEnabled(idle and not self.listening)
        self.profile_box.setEnabled(idle and not self.listening and not self.cloud_enabled)
        self.cloud_button.setEnabled(idle and not self.listening)
        for button in (self.translate_button, self.file_button):
            button.setEnabled(self.ready and idle and not self.listening)
        self.file_button.setText("打开歌曲" if self.profile_box.currentIndex() == 1 else "打开音频")
        self.auto_box.setEnabled(not (self.listening and self.source_box.currentIndex() == 1))
        self.replay_button.setEnabled(
            self.ready
            and idle
            and not self.listening
            and any(e.target for e in self.selected_entries())
        )
        self.clear_button.setEnabled(idle and not self.listening and bool(self.model.items))
        self.copy_button.setEnabled(bool(self.model.items))
        self.export_button.setEnabled(bool(self.model.items))
        self._update_state()
        self._update_empty()

    def load(self):
        if self.ready or self.pending or self.closing:
            return
        self.cancel.clear()
        self.pending += 1
        self.jobs.put_nowait((self.epoch, 0, "load"))
        self.status("正在加载并预热离线模型，首次可能需要几十秒…")
        self._buttons()

    def _change_transcript(self, callback, new=False):
        follow = self.view.follow_tail
        serial = self.view.interaction_serial
        callback()
        if new and not follow:
            self.unread += 1

        def settle():
            if follow and serial == self.view.interaction_serial:
                self.view.animate_to(self.view.verticalScrollBar().maximum(), 230)
            self.position_changed()

        QTimer.singleShot(0, settle)

    def submit(self, request):
        if not self.ready or self.closing:
            return False
        if self.listening and self.source_box.currentIndex() == 1:
            if request.kind == "speak":
                return False
            request = replace(request, autoplay=False)
        self.sequence += 1
        key = self.sequence
        try:
            self.jobs.put_nowait((self.epoch, key, request))
        except queue.Full:
            self.stop()
            self.status("待处理语句过多，已停止收音。请暂停来源后重试。", True)
            return False
        self.pending += 1
        if request.kind != "speak":
            self.active_ids.add(key)
            target = "zh" if request.source == "yue" else "yue"
            entry = TranscriptEntry(
                key,
                request.source,
                target,
                source=request.text,
                status="翻译中" if request.kind == "text" else "识别中",
            )
            self._change_transcript(lambda: self.model.append(entry), new=True)
        self._buttons()
        return True

    def translate_input(self):
        if self.pending or self.listening:
            return
        text = self.input.toPlainText().strip()
        if not text or len(text) > 120:
            self.status("请输入 1–120 字的短句；字幕缓存可保留上万条记录。", True)
            self.show_composer(True)
            return
        self.cancel.clear()
        if self.submit(
            Request(
                self.epoch,
                "text",
                source=self.source_language(),
                text=text,
                autoplay=self.auto_box.isChecked(),
                number_mode=self.number_mode,
            )
        ):
            self.input.clear()

    def open_audio(self, path=None):
        if self.pending or self.listening or not self.ready:
            return
        song = self.profile_box.currentIndex() == 1
        if not path or isinstance(path, bool):
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择歌曲（最多 10 分钟）" if song else "选择不超过 15 秒的音频",
                str(ROOT),
                "歌曲音频 (*.mp3 *.wav *.flac *.ogg)" if song else "WAV 音频 (*.wav)",
            )
        if path:
            self.cancel.clear()
            if song:
                try:
                    task = SongFile(
                        path,
                        self.source_language(),
                        vocals=self.song_file_vocals,
                        cloud=self.cloud_config if self.cloud_enabled else None,
                    )
                except (OSError, ValueError, RuntimeError) as exc:
                    self.status(str(exc), True)
                    return
                self.song_keys.clear()
                self.song_final_block = -1
                self.song_session = task
                self.pending += 1
                self.jobs.put_nowait((self.epoch, 0, task))
                self.status("正在准备歌曲文件处理…")
                self._buttons()
                return
            self.submit(
                Request(
                    self.epoch,
                    "file",
                    source=self.source_language(),
                    path=str(path),
                    autoplay=self.auto_box.isChecked(),
                    number_mode=self.number_mode,
                )
            )

    def selected_entries(self):
        if not hasattr(self, "view"):
            return []
        indexes = sorted(self.view.selectionModel().selectedRows(), key=lambda index: index.row())
        if indexes:
            return [self.model.items[i.row()] for i in indexes]
        return self.model.items[-1:]

    def replay(self):
        if self.pending or self.listening or not self.ready:
            return
        entries = self.selected_entries()
        if entries and entries[-1].target:
            item = entries[-1]
            self.cancel.clear()
            self.submit(
                Request(
                    self.epoch,
                    "speak",
                    source=item.target_language,
                    text=item.target,
                    number_mode=self.number_mode,
                )
            )

    def toggle_capture(self):
        if self.listening:
            if self.song_session is not None:
                self.listening = False
                if self.microphone:
                    self.microphone.stop()
                    self.microphone = None
                self.song_session.mailbox.finish()
                self.status("已停止收音，正在确认末尾字幕；可点“停止”取消等待。")
                self._buttons()
            else:
                self.stop()
            return
        if not self.ready or self.pending or self.closing:
            return
        self.cancel.clear()
        self.listening = True
        epoch = self.epoch
        source, auto, mode = self.source_language(), self.auto_box.isChecked(), self.number_mode
        self.player.stop()
        self.song_keys.clear()
        self.live_versions.clear()
        self.song_final_block = -1
        if self.profile_box.currentIndex() == 1:
            self.song_session = SongSession(
                source,
                autoplay=auto and self.source_box.currentIndex() == 0,
                number_mode=mode,
                cloud=self.cloud_config if self.cloud_enabled else None,
            )
        else:
            self.song_session = LiveSession(
                source,
                autoplay=auto and self.source_box.currentIndex() == 0,
                number_mode=mode,
            )
        self.pending += 1
        self.jobs.put_nowait((epoch, 0, self.song_session))
        self.status(
            "正在启动实时字幕…"
            if isinstance(self.song_session, LiveSession)
            else "正在准备段落修订…"
        )
        self._buttons()

    def _start_song_capture(self):
        if not self.listening or self.song_session is None:
            return
        epoch = self.epoch
        session = self.song_session
        factory = make_live_stream if isinstance(session, LiveSession) else None

        def error(message):
            self.events.put((epoch, 0, "capture_error", message))

        if self.source_box.currentIndex() == 1:
            self.microphone = SystemAudio(
                session.mailbox.put,
                error,
                lambda name: self.events.put((epoch, 0, "capture_started", name)),
                paragraph=True,
                segmenter_factory=factory,
            )
        else:
            self.microphone = Microphone(
                session.mailbox.put,
                error,
                paragraph=True,
                segmenter_factory=factory,
            )
        self.microphone.start()
        self.status(
            "实时字幕已开始，原文随说话更新，译文随后显示…"
            if isinstance(session, LiveSession)
            else "段落修订已开始，正在等待第一段人声…"
        )

    def _song_key(self, block):
        if block not in self.song_keys:
            self.sequence += 1
            self.song_keys[block] = self.sequence
            source = self.source_language()
            entry = TranscriptEntry(
                self.sequence, source, "zh" if source == "yue" else "yue", status="暂定字幕"
            )
            self.active_ids.add(self.sequence)
            self._change_transcript(lambda: self.model.append(entry), new=True)
        return self.song_keys[block]

    def stop(self):
        self.cancel.set()
        self.epoch += 1
        self.listening = False
        if self.microphone:
            self.microphone.stop()
            self.microphone = None
        if self.song_session is not None:
            self.song_session.mailbox.finish()
            self.song_session = None
        self.player.stop()
        while True:
            try:
                self.jobs.get_nowait()
                self.jobs.task_done()
                self.pending = max(0, self.pending - 1)
            except queue.Empty:
                break
        for key in tuple(self.active_ids):
            item = self.model.by_key.get(key)
            if item and item.status != "已确认":
                self.model.update_entry(
                    key, status="已取消" if not item.target else "暂定 · 已停止"
                )
        self.active_ids.clear()
        self.status(
            "正在停止处理，已有字幕已保留…"
            if self.pending
            else "已停止 · 字幕记录已保留，可回看或导出。"
        )
        self._buttons()

    def _worker(self):
        while True:
            job = self.jobs.get()
            if job is None:
                self.jobs.task_done()
                return
            epoch, key, payload = job

            def emit(kind, value, epoch=epoch, key=key):
                self.events.put((epoch, key, kind, value))

            try:
                if payload == "load":
                    self.engine.load(self.cancel, lambda message: emit("status", message))
                    emit("ready", True)
                elif isinstance(payload, (SongSession, LiveSession)):
                    payload.run(self.engine, self.player, self.cancel, emit)
                elif self.cloud_enabled and payload.kind == "text":
                    from .enhanced_inference import process_text

                    process_text(
                        payload, self.cloud_config, self.engine, self.player, self.cancel, emit
                    )
                    emit("done", True)
                else:
                    self.engine.process(payload, self.cancel, self.player, emit)
                    emit("done", True)
            except (Cancelled, InferenceCancelled):
                pass
            except (ValueError, RuntimeError, TimeoutError) as exc:
                emit("error", str(exc))
            except Exception:
                emit("error", "本次处理失败，请停止后重试。")
            finally:
                self.events.put((epoch, key, "finished", None))
                self.jobs.task_done()

    def poll(self):
        for _ in range(160):
            try:
                epoch, key, kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "finished":
                self.pending = max(0, self.pending - 1)
                self.active_ids.discard(key)
                continue
            if epoch != self.epoch:
                continue
            if kind == "ready":
                self.ready = True
                self.status(
                    "本地模型已就绪，选择音源后即可开始。"
                    + ("联网增强将在开始处理时请求云端。" if self.cloud_enabled else "")
                )
            elif kind == "network_state":
                mode = value["mode"]
                self.network_mode = mode
                self.source_changed()
                self.network_pill.setText(
                    {
                        "offline": "本地离线",
                        "cloud_pending": "联网待请求",
                        "cloud": "联网增强",
                        "fallback": "本地回退",
                    }[mode]
                )
                note = (
                    f"本次任务 {value['requests']} 次云端请求（含失败）；累计请求音频 {value['audio_seconds']:.1f} 秒（含重复窗口），"
                    f"翻译输入 {value['text_characters']} 字。费用以百炼账单为准。"
                )
                if mode == "fallback":
                    note = value["reason"] + "。本次任务不再联网，再次开始任务才重试。\n" + note
                    self.status("已回退本地：" + value["reason"] + "。详情可查看顶部状态。", True)
                self.network_pill.setToolTip(note)
            elif kind == "source":
                self._change_transcript(
                    lambda: self.model.update_entry(
                        key, source=value, source_confirmed=len(value), status="翻译中"
                    )
                )
            elif kind == "translation":
                self._change_transcript(
                    lambda: self.model.update_entry(
                        key,
                        target=value["text"],
                        target_confirmed=len(value["text"]),
                        status="已翻译",
                    )
                )
                self.status(
                    f"识别 {value['recognition_seconds']:.2f} 秒 · 翻译 {value['translation_seconds']:.2f} 秒"
                )
                self.status_label.setToolTip(
                    "从音频分段完成后计时，不包含等候语音、断句和任务排队。"
                )
            elif kind == "status":
                self.status(value)
            elif kind == "first_audio":
                self.status(f"译音已生成 · 本句用时 {value:.1f} 秒")
            elif kind == "capture_started":
                self.status(f"正在获取设备声音：{value}（仅字幕）")
            elif kind == "song_ready":
                self._start_song_capture()
            elif kind == "live_source":
                row_key = self._song_key(value["block"])
                self.live_versions[value["block"]] = value["version"]
                self._change_transcript(
                    lambda: self.model.update_entry(
                        row_key,
                        source=value["text"],
                        source_confirmed=value.get("frozen_characters", 0),
                        status="原文已固定 · 译文更新中"
                        if value["final"]
                        else "亮色已固定 · 浅色暂定",
                    )
                )
                self.status("原文已确认，正在翻译…" if value["final"] else "原文实时更新中…")
                self.status_label.setToolTip(
                    f"本次识别 {value['recognition_seconds']:.2f} 秒；"
                    f"音频快照末尾至原文返回 {value['lag_seconds']:.2f} 秒，不含攒帧和本次绘制。"
                )
            elif kind == "live_translation":
                block = value["block"]
                current_version = self.live_versions.get(block)
                if current_version is None:
                    continue
                row_key = self.song_keys.get(block)
                item = self.model.by_key.get(row_key)
                if item is None:
                    continue
                frozen_target = value.get("frozen_target", value["text"] if value["final"] else "")
                if current_version != value["version"]:
                    # An old draft may have completed a still-valid fixed prefix.
                    # Adopt that prefix only; its speculative tail stays obsolete.
                    frozen_source = value.get("frozen_source", "")
                    if (
                        not frozen_source
                        or not item.source.startswith(frozen_source)
                        or len(frozen_target) <= item.target_confirmed
                        or not frozen_target.startswith(item.target[: item.target_confirmed])
                    ):
                        continue
                    self._change_transcript(
                        lambda: self.model.update_entry(
                            row_key,
                            target=frozen_target,
                            target_confirmed=len(frozen_target),
                            status="前文已固定 · 末尾更新中",
                        )
                    )
                    continue
                self._change_transcript(
                    lambda: self.model.update_entry(
                        row_key,
                        target=value["text"],
                        target_confirmed=len(frozen_target),
                        status="已确认" if value["final"] else "亮色已固定 · 浅色暂定",
                    )
                )
                if value["final"]:
                    self.active_ids.discard(row_key)
                    self.song_keys.pop(block, None)
                    self.live_versions.pop(block, None)
            elif kind == "live_empty":
                block = value["block"]
                row_key = self.song_keys.pop(block, None)
                self.live_versions.pop(block, None)
                if row_key is not None:
                    self._change_transcript(
                        lambda: self.model.update_entry(row_key, status="暂定 · 未确认")
                    )
                    self.active_ids.discard(row_key)
            elif kind == "song_source":
                if value["block"] <= self.song_final_block:
                    continue
                row_key = self._song_key(value["block"])
                fields = dict(
                    source=value["text"],
                    source_confirmed=value.get("frozen_characters", 0),
                    status="片段固定 · 翻译中" if value["final"] else "亮色已固定 · 浅色暂定",
                )
                self._change_transcript(lambda: self.model.update_entry(row_key, **fields))
            elif kind == "song_translation":
                if value["block"] <= self.song_final_block:
                    continue
                row_key = self._song_key(value["block"])
                self._change_transcript(
                    lambda: self.model.update_entry(
                        row_key,
                        target=value["text"],
                        target_confirmed=len(value.get("frozen_target", "")),
                        status=(
                            "已确认"
                            if value["final"]
                            else "亮色已固定 · 浅色暂定"
                            if value.get("frozen_characters", 0)
                            else "暂定 · 待复核"
                        ),
                    )
                )
                if value["final"]:
                    self.song_final_block = value["block"]
                    self.active_ids.discard(row_key)
                    self.song_keys.pop(value["block"], None)
                self.status(
                    f"{'片段确认' if value['final'] else '暂定字幕'} · "
                    f"识别 {value['recognition_seconds']:.2f} 秒 · "
                    f"翻译 {value['translation_seconds']:.2f} 秒"
                )
                self.status_label.setToolTip(
                    f"输入窗口末尾至译文返回 {value['lag_seconds']:.2f} 秒；"
                    "不代表逐字延迟，尚未计入本次绘制。"
                )
            elif kind == "song_empty":
                self.song_final_block = max(self.song_final_block, value["block"])
                row_key = self.song_keys.get(value["block"])
                if row_key is not None:
                    self.model.update_entry(
                        row_key,
                        source=value.get("source", ""),
                        target=value.get("target", ""),
                        source_confirmed=len(value.get("source", "")),
                        target_confirmed=len(value.get("target", "")),
                        status="前文已固定 · 末尾未确认"
                        if value.get("partial")
                        else "未检测到新内容",
                    )
                    self.active_ids.discard(row_key)
                    self.song_keys.pop(value["block"], None)
            elif kind == "song_drained":
                self.song_session = None
                self.status(
                    "已有字幕已保留，部分末尾没有有效识别结果，尚未确认。"
                    if isinstance(value, dict) and value.get("partial_count")
                    else "本次没有生成有效字幕，已有记录已保留。"
                    if isinstance(value, dict) and not value.get("confirmed_count")
                    else "末尾字幕已确认 · 本次记录已保留，可回看或导出。"
                )
            elif kind in ("capture_error", "audio_error"):
                self.stop()
                self.status(value, True)
            elif kind == "error":
                if self.song_session is not None:
                    self.stop()
                self.model.update_entry(key, status="处理失败")
                self.status(value, True)
        self._buttons()
        if self.closing and not self.worker.is_alive():
            self.timer.stop()
            self.player.close()
            self.close()

    def position_changed(self):
        if self.view.follow_tail:
            self.unread = 0
        self.latest_button.setVisible(not self.view.follow_tail and bool(self.model.items))
        self.latest_button.setText(
            f"{self.unread} 条新字幕 · 回到最新 ↓" if self.unread else "回到最新 ↓"
        )

    def go_latest(self):
        self.unread = 0
        self.view.latest()
        self.position_changed()

    def copy_records(self):
        selected = self.view.selectionModel().selectedRows()
        entries = self.selected_entries() if selected else self.model.items
        QApplication.clipboard().setText(self.model.export_text(entries))
        self.status(f"已复制 {len(entries):,} 条双语字幕。")

    def export_records(self):
        if not self.model.items:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出本次字幕", "粤普随译-字幕.txt", "文本文件 (*.txt)"
        )
        if path:
            try:
                self.write_export(Path(path))
                self.status("字幕已导出到所选文件。")
            except OSError:
                self.status("导出失败，请选择可写入的位置重试。", True)

    def write_export(self, path):
        path.write_text(self.model.export_text(), encoding="utf-8-sig")

    def clear_records(self):
        if self.pending or self.listening:
            return
        if (
            QMessageBox.question(
                self,
                "清空本次字幕",
                "清空后无法恢复。需要保留时请先导出。是否清空？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        ):
            self.model.clear()
            self.delegate.cache.clear()
            self.delegate.heights.clear()
            self.unread = 0
            self.view.follow_tail = True
            self.position_changed()

    def settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("阅读与播报")
        form = QFormLayout(dialog)
        form.setContentsMargins(24, 24, 24, 24)
        font = QSpinBox()
        font.setRange(12, 24)
        font.setValue(self.delegate.font_size)
        form.addRow("字幕字号", font)
        smooth = QCheckBox("平滑滚动与字幕跟随动画")
        smooth.setChecked(self.view.smooth)
        form.addRow(smooth)
        numbers = QComboBox()
        numbers.addItems(["按原文", "金额", "号码逐位"])
        numbers.setCurrentIndex(["original", "amount", "identifier"].index(self.number_mode))
        form.addRow("普通话数字读法", numbers)
        vocals = QCheckBox("人声分离（较慢，仅处理歌曲文件）")
        vocals.setChecked(self.song_file_vocals)
        vocals.setEnabled(not self.pending and not self.listening)
        form.addRow("高质量选项", vocals)
        note = QLabel(
            "字幕仅保存在本次会话内，关闭软件后释放。\n上限 10,000 条 / 原文译文合计 200 万字符。\n数字读音仍需核对；系统收音期间仅显示字幕。"
        )
        note.setObjectName("muted")
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.Accepted:
            self.delegate.font_size = font.value()
            self.delegate.cache.clear()
            self.delegate.heights.clear()
            self.view.smooth = smooth.isChecked()
            if not self.view.smooth:
                self.view.animation.stop()
            self.number_mode = ["original", "amount", "identifier"][numbers.currentIndex()]
            self.song_file_vocals = vocals.isChecked()
            self.view.doItemsLayout()
            self.view.viewport().update()

    def cloud_settings(self):
        if self.pending or self.listening or self.closing:
            return
        dialog = CloudDialog(self.cloud_config, self.cloud_enabled, self.cloud_remember, self)
        if dialog.exec() == QDialog.Accepted:
            self.cloud_config, self.cloud_enabled, self.cloud_remember = (
                dialog.config,
                dialog.enabled,
                dialog.remember,
            )
            self.network_mode = "cloud_pending" if self.cloud_enabled else "offline"
            if self.cloud_enabled:
                self.profile_box.setCurrentIndex(1)
            self.network_pill.setText("联网待请求" if self.cloud_enabled else "本地离线")
            self.network_pill.setToolTip(
                "音频与文字仅在启用后开始处理时发送至所选百炼地域；每次启动默认离线。"
                if self.cloud_enabled
                else "推理仅使用本机模型。"
            )
            self.source_changed()
            self.status(
                "联网增强已开启；开始处理时发送近期音频和待翻译文字，失败后回退本地。仍需准备本地段落修订模型。"
                if self.cloud_enabled
                else "联网增强已关闭，后续处理仅使用本地模型。"
            )

    def closeEvent(self, event):
        if self.closing and not self.worker.is_alive():
            event.accept()
            return
        event.ignore()
        if self.closing:
            return
        self.stop()
        self.closing = True
        self.status("正在停止并释放模型…未导出的本次字幕将在退出后释放。")
        self.jobs.put_nowait(None)
        self._buttons()


def main(*, muted=False):
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window(muted=muted)
    window.show()
    app.exec()
