"""Qt desktop client. Real local engine; session-only paired transcript."""

from __future__ import annotations

import os
import queue
import random
import threading
import time
from collections import OrderedDict, deque
from dataclasses import replace
from datetime import datetime
from functools import partial
from html import escape
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QActionGroup,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
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
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from . import APP_NAME
from .audio_profile import VOICE_PROFILES, voice_profile
from .cloud_config import CloudConfig, load_settings
from .cloud_dialog import CloudDialog
from .composer_input import ComposerInput
from .desktop_engine import AudioPlayer, Cancelled, Engine, Microphone, Request, SystemAudio
from .desktop_sidebar import HistorySplitter
from .desktop_theme import STYLE, THEMES, palette, stylesheet
from .inference_control import InferenceCancelled
from .live_session import LiveSession, make_live_stream
from .model_assets import GROUPS, ready
from .model_dialog import ModelDialog
from .paths import DATA_DIR
from .preferences import (
    Preferences,
    export_directory,
    load_preferences,
    save_preferences,
    settings_store,
)
from .session_history import SessionHistory, SessionHistoryConflict, SessionHistoryError
from .settings_dialog import SettingsDialog
from .song_pipeline import SongFile, SongSession, make_song_stream
from .song_stream import RATE, SongOverload
from .transcript_model import TranscriptEntry, TranscriptModel
from .window_chrome import ChromeWindow

ROOT = DATA_DIR
WAITING_FOR_AUDIO = "音源已打开，但尚未收到新的音频包。请检查输入设备或播放来源。"
NAMES = {"zh": "普通话", "yue": "粤语", "en": "英文"}
VOICE_MODELS = {"zh": "tts-zh", "yue": "canto"}
LOGO = Path(__file__).with_name("assets") / "yuepu-logo.png"
WELCOME_LINES = (
    (5, "夜深了，想翻译点什么？", "夜喇，想譯啲咩？"),
    (11, "早上好，今天想翻译点什么？", "早晨，今日想譯啲咩？"),
    (14, "中午好，想从哪一句开始？", "午安，想由邊句開始？"),
    (18, "下午好，今天想翻译点什么？", "下晝好，今日想譯啲咩？"),
    (24, "晚上好，想翻译哪一句？", "夜晚好，想譯邊句？"),
)


def welcome_greeting(hour):
    return next(random.choice((zh, yue)) for end_hour, zh, yue in WELCOME_LINES if hour < end_hour)


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
        columns = (
            [(entry.source, len(entry.source))]
            if entry.is_capture_notice
            else [(source, entry.source_confirmed), (target, entry.target_confirmed)]
        )
        for text, confirmed in columns:
            doc = QTextDocument()
            doc.setDocumentMargin(0)
            doc.setDefaultFont(QFont("Microsoft YaHei UI", self.font_size, QFont.Weight.Medium))
            option = QTextOption()
            option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
            doc.setDefaultTextOption(option)
            cursor = QTextCursor(doc)
            fixed, draft = QTextCharFormat(), QTextCharFormat()
            fixed.setForeground(QColor(self.colors["text"]))
            draft.setForeground(QColor(self.colors["draft"]))
            cursor.insertText(text[:confirmed], fixed)
            cursor.insertText(text[confirmed:], draft)
            doc.setTextWidth(max(80, width // len(columns) - 36))
            docs.append(doc)
        height = max(72, int(max(d.size().height() for d in docs)) + 43)
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
            return QSize(100, 72)
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
        if not selected and not entry.is_capture_notice:
            painter.fillRect(
                middle, rect.top(), rect.width() // 2, rect.height(), QColor(self.colors["target"])
            )
        elif selected:
            painter.fillRect(rect.left(), rect.top(), 3, rect.height(), QColor(self.colors["text"]))
        painter.setPen(QColor(self.colors["border"]))
        if not entry.is_capture_notice:
            painter.drawLine(middle, rect.top(), middle, rect.bottom())
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        metadata_font = QFont("Microsoft YaHei UI")
        metadata_font.setPixelSize(15)
        painter.setFont(metadata_font)
        painter.setPen(QColor(self.colors["muted"]))
        source_label = (
            "收音中断"
            if entry.is_capture_notice
            else NAMES.get(entry.source_language, entry.source_language)
        )
        painter.drawText(
            rect.left() + 16,
            rect.top() + 20,
            f"{entry.timestamp}   ·   {source_label}",
        )
        painter.setPen(QColor(self.colors["muted"]))
        if not entry.is_capture_notice:
            painter.drawText(
                middle + 16,
                rect.top() + 20,
                f"{NAMES.get(entry.target_language, entry.target_language)}   ·   {entry.status}",
            )
        for index, doc in enumerate(docs):
            is_target = index == 1
            x = (middle if is_target else rect.left()) + 16
            painter.save()
            painter.translate(x, rect.top() + 28)
            context = doc.documentLayout().PaintContext()
            context.palette.setColor(
                context.palette.ColorRole.Text,
                QColor(self.colors["text"] if is_target and entry.target else self.colors["draft"]),
            )
            doc.documentLayout().draw(painter, context)
            painter.restore()
        painter.restore()


class HistoryDelegate(QStyledItemDelegate):
    def __init__(self, parent):
        super().__init__(parent)
        self.colors = THEMES["dark"]

    def sizeHint(self, option, index):
        return QSize(0, option.fontMetrics.height() + 37)

    def paint(self, painter, option, index):
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        title, _, timestamp = index.data(Qt.DisplayRole).partition("\n")
        styled.text = ""
        styled.widget.style().drawControl(QStyle.CE_ItemViewItem, styled, painter, styled.widget)

        rect = styled.rect.adjusted(12, 8, -12, -8)
        enabled = styled.state & QStyle.State_Enabled
        painter.save()
        painter.setClipRect(rect)
        title_font = QFont(styled.font)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(self.colors["text" if enabled else "disabled"]))
        metrics = QFontMetrics(title_font)
        painter.drawText(
            rect.left(),
            rect.top() + metrics.ascent(),
            metrics.elidedText(title, Qt.ElideRight, rect.width()),
        )
        metadata = QFont(styled.font)
        metadata.setPixelSize(15)
        painter.setFont(metadata)
        painter.setPen(QColor(self.colors["muted" if enabled else "disabled"]))
        painter.drawText(
            rect.left(),
            rect.top() + metrics.height() + QFontMetrics(metadata).ascent() + 2,
            timestamp,
        )
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


class AudioOptionsMenu(QMenu):
    def __init__(self, controls, parent):
        super().__init__(parent)
        self.controls = controls
        for control in controls:
            control.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            visible = [control for control in self.controls if control.isVisible()]
            if watched in visible:
                backward = event.key() == Qt.Key_Backtab or event.modifiers() & Qt.ShiftModifier
                step = -1 if backward else 1
                reason = Qt.BacktabFocusReason if backward else Qt.TabFocusReason
                visible[(visible.index(watched) + step) % len(visible)].setFocus(reason)
                return True
        return super().eventFilter(watched, event)


class Window(ChromeWindow):
    def __init__(self, muted=False, *, history=None):
        super().__init__()
        self.preferences = settings_store()
        preference_warning = ""
        try:
            self.defaults = load_preferences(self.preferences)
        except (ValueError, TypeError):
            self.defaults = Preferences()
            preference_warning = "已保存的首选项无法读取，已使用默认设置；请在设置中重新保存。"
        self.theme = "dark"
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(LOGO.with_suffix(".ico"))))
        self.resize(1180, 790)
        self.setMinimumSize(800, 520)
        self.events = queue.Queue()
        self.jobs = queue.Queue(maxsize=2)
        self.cancel = threading.Event()
        self.engine = Engine()
        self.playback_token = None
        self.player = AudioPlayer(
            lambda message: self.events.put((self.epoch, 0, "audio_error", (None, message))),
            muted=muted,
        )
        self.microphone = None
        self.song_session = None
        self.song_keys = {}
        self.live_versions = {}
        self.live_preview_versions = {}
        self.song_final_block = -1
        self.song_file_vocals = self.defaults.vocals
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
        self.listening = self.closing = False
        self.capture_started = False
        self.capture_waiting = False
        self.capture_notice = ""
        self.model = TranscriptModel()
        self.active_ids = set()
        self.unread = 0
        self.history = history if history is not None else SessionHistory()
        self.session_id = uuid4().hex
        self.session_heading = ""
        self.history_dirty = self.restoring_history = False
        self.drafts = {}
        self.history_timer = QTimer(self)
        self.history_timer.setSingleShot(True)
        self.history_timer.setInterval(900)
        self.history_timer.timeout.connect(self.save_history)
        self._build()
        self.apply_preferences()
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
        elif preference_warning:
            self.status(preference_warning, True)
        self.refresh_history()

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

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        sidebar = QVBoxLayout(self.sidebar)
        sidebar.setContentsMargins(24, 17, 18, 20)
        sidebar.setSpacing(10)
        self.new_button = self.button("＋  新会话", self.new_session, "historyNew")
        sidebar.addWidget(self.new_button)
        sidebar.addSpacing(10)
        history_label = self.label("会话历史", "section")
        history_label.setContentsMargins(12, 0, 0, 0)
        sidebar.addWidget(history_label)
        self.history_list = QListWidget()
        self.history_list.setObjectName("historyList")
        self.history_list.setAccessibleName("会话历史")
        self.history_list.setMouseTracking(True)
        self.history_delegate = HistoryDelegate(self.history_list)
        self.history_list.setItemDelegate(self.history_delegate)
        self.history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history_list.itemClicked.connect(self.open_session)
        self.history_list.itemActivated.connect(self.open_session)
        sidebar.addWidget(self.history_list, 1)
        self.history_empty = self.label("暂无会话", "muted")
        self.history_empty.setContentsMargins(12, 2, 0, 0)
        self.history_empty.setAlignment(Qt.AlignTop)
        sidebar.addWidget(self.history_empty, 1)
        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        self.history_splitter = HistorySplitter(self.sidebar, workspace, self.preferences)

        header = QFrame()
        header.setObjectName("header")
        header.setMinimumHeight(52)
        top = QHBoxLayout(header)
        self.header_layout = top
        self.update_header_margins()
        top.setSpacing(10)
        self.sidebar_toggle = QToolButton(header)
        self.sidebar_toggle.setObjectName("sidebarToggle")
        self.sidebar_toggle.setFixedSize(36, 36)
        self.sidebar_toggle.setIconSize(QSize(19, 19))
        self.sidebar_toggle.setCursor(Qt.PointingHandCursor)
        self.sidebar_toggle.setCheckable(True)
        self.sidebar_toggle.clicked.connect(self.history_splitter.set_sidebar_expanded)
        self.history_splitter.sidebar_toggled.connect(self.update_sidebar_toggle)
        top.addWidget(self.sidebar_toggle)
        top.addWidget(self.label(APP_NAME, "brand"))
        top.addStretch(1)
        self.network_pill = self.label("本地离线", "pill")
        self.network_pill.setToolTip("推理仅使用本机模型。")
        top.addWidget(self.network_pill)
        self.settings_button = QToolButton()
        self.settings_button.setObjectName("tool")
        self.settings_button.setText("设置")
        self.settings_button.setPopupMode(QToolButton.InstantPopup)
        settings_menu = QMenu(self.settings_button)
        settings_menu.setObjectName("settingsMenu")
        self.preferences_action = settings_menu.addAction("首选项…", self.settings)
        self.models_action = settings_menu.addAction("模型管理…", self.model_manager)
        self.cloud_action = settings_menu.addAction("联网设置…", self.cloud_settings)
        settings_menu.addSeparator()
        appearance = settings_menu.addMenu("外观")
        appearance.setObjectName("settingsMenu")
        appearance_group = QActionGroup(appearance)
        self.theme_actions = {}
        for theme, title in (("dark", "深色主题"), ("light", "浅色主题")):
            action = appearance.addAction(title, partial(self.apply_theme, theme))
            action.setCheckable(True)
            appearance_group.addAction(action)
            self.theme_actions[theme] = action
        self.settings_button.setMenu(settings_menu)
        top.addWidget(self.settings_button)
        top.addWidget(self.caption_controls(header))
        self.set_caption_area(header)
        root.addWidget(header)
        root.addWidget(self.history_splitter, 1)

        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(30, 10, 30, 22)
        self.body_layout.setSpacing(12)
        workspace_layout.addWidget(body, 1)
        self.body_layout.addStretch(1)

        self.workarea = QFrame()
        self.workarea.setObjectName("workarea")
        area = QVBoxLayout(self.workarea)
        area.setContentsMargins(0, 0, 0, 0)
        area.setSpacing(0)
        self.session_title = self.label("", "title")
        self.session_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        area.addWidget(self.session_title)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(10, 0, 0, 6)
        toolbar.setSpacing(4)
        self.count_label = self.label("", "count")
        toolbar.addWidget(self.count_label)
        toolbar.addStretch()
        self.latest_button = self.button("回到最新", self.go_latest, "quiet")
        self.latest_button.hide()
        toolbar.addWidget(self.latest_button)
        self.replay_button = self.button("播报", self.replay, "quiet")
        self.replay_button.setToolTip(
            "播报选中的译文，未选中时播报最后一句。译稿与当前原文未核对时，仅播报已固定前文。"
        )
        toolbar.addWidget(self.replay_button)
        self.copy_button = self.button("复制", self.copy_records, "quiet")
        self.copy_button.setToolTip("复制选中的字幕；未选中时复制全部")
        toolbar.addWidget(self.copy_button)
        self.export_button = self.button("导出", self.export_records, "quiet")
        self.export_button.setToolTip("导出此会话的全部字幕")
        toolbar.addWidget(self.export_button)
        self.clear_button = self.button("清空", self.clear_records, "quiet")
        self.clear_button.setToolTip("清空字幕并从会话历史中移除")
        toolbar.addWidget(self.clear_button)
        area.addLayout(toolbar)

        language_bar = QFrame()
        language_bar.setObjectName("languages")
        languages = QHBoxLayout(language_bar)
        languages.setContentsMargins(16, 9, 16, 9)
        languages.setSpacing(0)
        languages.addWidget(self.label("原文", "panelTitle"), 1)
        target_header = self.label("译文", "panelTitle")
        target_header.setContentsMargins(16, 0, 0, 0)
        languages.addWidget(target_header, 1)
        area.addWidget(language_bar)
        self.view = SmoothTranscriptView()
        self.view.setModel(self.model)
        self.delegate = PairDelegate(self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.setAccessibleName("字幕，原文在左，译文在右")
        self.view.position_changed.connect(self.position_changed)
        self.view.selectionModel().selectionChanged.connect(self._buttons)
        area.addWidget(self.view, 1)
        self.body_layout.addWidget(self.workarea, 1)

        composer_wrap = QWidget()
        composer_wrap.setMaximumWidth(900)
        wrap = QVBoxLayout(composer_wrap)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(4)
        self.empty_brand = QWidget()
        brand_layout = QHBoxLayout(self.empty_brand)
        brand_layout.setContentsMargins(0, 0, 0, 22)
        brand_layout.setSpacing(14)
        brand_image = QLabel()
        brand_image.setPixmap(QIcon(str(LOGO)).pixmap(QSize(46, 46), self.devicePixelRatioF()))
        brand_layout.addWidget(brand_image, 0, Qt.AlignVCenter)
        self.welcome_title = self.label(welcome_greeting(datetime.now().hour), "welcomeTitle")
        brand_layout.addWidget(self.welcome_title)
        wrap.addWidget(self.empty_brand, 0, Qt.AlignHCenter)
        self.composer = QFrame()
        self.composer.setObjectName("composer")
        compose = QVBoxLayout(self.composer)
        compose.setContentsMargins(12, 10, 12, 10)
        compose.setSpacing(4)
        self.input = ComposerInput()
        self.input.setObjectName("composerInput")
        self.input.setPlaceholderText("输入要翻译的文字，或开始收音")
        self.input.setAccessibleName("要翻译的文字")
        self.input.setTabChangesFocus(True)
        self.input.setFixedHeight(76)
        self.input.textChanged.connect(self._buttons)
        compose.addWidget(self.input)

        bar = QWidget()
        bar.setObjectName("composerBar")
        self.composer_bar = QGridLayout(bar)
        self.composer_bar.setContentsMargins(0, 0, 0, 0)
        self.composer_bar.setSpacing(8)
        self.composer_bar.setColumnStretch(1, 1)

        tools = QWidget()
        controls = QHBoxLayout(tools)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        self.direction_box = QComboBox()
        self.direction_box.setObjectName("directionSelect")
        self.direction_box.addItems(["粤语 → 普通话", "普通话 → 粤语"])
        self.direction_box.setAccessibleName("翻译方向")
        controls.addWidget(self.direction_box)
        self.file_button = self.button("打开音频", self.open_audio, "quiet")
        controls.addWidget(self.file_button)
        self.composer_bar.addWidget(tools, 0, 0, Qt.AlignLeft)
        self.composer_tools = tools

        self.composer_actions = QWidget()
        actions = QHBoxLayout(self.composer_actions)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self.audio_button = QToolButton()
        self.audio_button.setObjectName("audioMenu")
        self.audio_button.setText("收音选项")
        self.audio_button.setPopupMode(QToolButton.InstantPopup)
        self._build_audio_menu()
        actions.addWidget(self.audio_button)
        self.record_button = self.button("开始收音", self.toggle_capture, "primary")
        actions.addWidget(self.record_button)
        self.translate_button = self.button("翻译", self.translate_input, "primary")
        self.translate_button.setToolTip("翻译文字 (Ctrl + Enter)")
        actions.addWidget(self.translate_button)
        self.compact_layout = None
        self.reflow_workspace()
        compose.addWidget(bar)
        wrap.addWidget(self.composer)

        feedback = QHBoxLayout()
        feedback.setContentsMargins(8, 0, 8, 0)
        feedback.setSpacing(6)
        self.status_label = self.label("", "statusLabel")
        self.status_label.setWordWrap(True)
        feedback.addWidget(self.status_label, 1)
        self.stop_button = self.button("取消任务", self.stop, "quiet")
        self.stop_button.setToolTip("取消仍在处理的内容 (Esc)")
        feedback.addWidget(self.stop_button)
        wrap.addLayout(feedback)

        composer_line = QHBoxLayout()
        composer_line.addStretch(1)
        composer_line.addWidget(composer_wrap, 100)
        composer_line.addStretch(1)
        self.body_layout.addLayout(composer_line)
        self.body_layout.addStretch(1)
        self.history_splitter.sidebar_resized.connect(self.reflow_workspace)

        self.number_mode = "original"
        for signal in (self.model.rowsInserted, self.model.rowsRemoved, self.model.modelReset):
            signal.connect(self._model_changed)
            signal.connect(self.schedule_history_save)
        self.model.dataChanged.connect(self.schedule_history_save)
        self._model_changed()

    def _build_audio_menu(self):
        options = QWidget()
        options.setMinimumWidth(296)
        form = QFormLayout(options)
        form.setContentsMargins(14, 12, 14, 12)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        self.source_box = QComboBox()
        self.source_box.addItems(["麦克风", "设备播放声音"])
        self.source_box.setAccessibleName("声音来源")
        self.source_box.currentIndexChanged.connect(self.source_changed)
        form.addRow("音源", self.source_box)

        self.profile_box = QComboBox()
        self.profile_box.addItem("快速  (flash)", "flash")
        self.profile_box.addItem("精细  (pro)", "pro")
        self.profile_box.setAccessibleName("识别模式")
        self.profile_box.setToolTip("快速优先显示字幕；精细模式会在句末复核和修正。")
        self.profile_box.currentIndexChanged.connect(self.source_changed)
        form.addRow("识别模式", self.profile_box)

        self.sensitivity_box = QComboBox()
        for key, profile in VOICE_PROFILES.items():
            self.sensitivity_box.addItem(profile.label, key)
        self.sensitivity_box.setAccessibleName("收音灵敏度")
        self.sensitivity_box.currentIndexChanged.connect(self.sensitivity_changed)
        form.addRow("灵敏度", self.sensitivity_box)
        self.auto_box = QCheckBox("自动播报译音")
        self.auto_box.setChecked(True)
        form.addRow(self.auto_box)
        self.caption_only_hint = self.label("设备收音期间仅显示字幕", "muted")
        form.addRow(self.caption_only_hint)
        menu = AudioOptionsMenu(
            (self.source_box, self.profile_box, self.sensitivity_box, self.auto_box),
            self.audio_button,
        )
        menu.setObjectName("audioOptions")
        settings_action = QWidgetAction(menu)
        settings_action.setDefaultWidget(options)
        menu.addAction(settings_action)
        options.setFocusPolicy(Qt.StrongFocus)
        options.setFocusProxy(self.source_box)
        menu.aboutToShow.connect(self.source_changed)
        menu.aboutToShow.connect(lambda: QTimer.singleShot(0, self.source_box.setFocus))
        self.audio_button.setMenu(menu)

    @staticmethod
    def label(text, kind):
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setObjectName(kind)
        return label

    def apply_theme(self, theme, *, persist=True):
        self.theme = theme if isinstance(theme, str) and theme in THEMES else "dark"
        app = QApplication.instance()
        app.setPalette(palette(self.theme))
        app.setStyleSheet(stylesheet(self.theme))
        for name, action in self.theme_actions.items():
            action.setChecked(name == self.theme)
        self.delegate.colors = THEMES[self.theme]
        self.history_delegate.colors = THEMES[self.theme]
        self.delegate.cache.clear()
        self.view.viewport().update()
        self.history_list.viewport().update()
        self.reflow_workspace()
        self.update_sidebar_toggle(self.history_splitter.sidebar_expanded)
        if persist:
            self.preferences.setValue("appearance", self.theme)

    def update_sidebar_toggle(self, expanded):
        self.sidebar_toggle.setChecked(expanded)
        label = "收起会话侧栏" if expanded else "展开会话侧栏"
        self.sidebar_toggle.setAccessibleName(label)
        self.sidebar_toggle.setToolTip(label)
        ratio = self.sidebar_toggle.devicePixelRatioF()
        pixmap = QPixmap(round(19 * ratio), round(19 * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.transparent)
        with QPainter(pixmap) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            color = QColor(THEMES[self.theme]["text"])
            painter.setPen(QPen(color, 1.35))
            painter.drawRoundedRect(QRectF(2, 3.5, 15, 12), 2, 2)
            painter.drawLine(7, 4, 7, 15)
            if expanded:
                color.setAlpha(90)
                painter.fillRect(QRectF(3.5, 5, 3, 9), color)
        self.sidebar_toggle.setIcon(QIcon(pixmap))

    def _model_changed(self, *args):
        if self.restoring_history:
            return
        count = self.model.rowCount()
        self.workarea.setVisible(bool(count))
        self.empty_brand.setVisible(not count)
        self.body_layout.setStretch(0, 4 if count == 0 else 0)
        self.body_layout.setStretch(3, 6 if count == 0 else 0)
        self.count_label.setText(f"{count:,} 条字幕")
        self.count_label.setToolTip(
            f"已达单个会话容量上限，最早 {self.model.evicted:,} 条已移出。"
            if self.model.evicted
            else ""
        )
        self._buttons()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "composer_actions"):
            self.reflow_workspace()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and hasattr(self, "header_layout"):
            self.update_header_margins()

    def update_header_margins(self):
        inset = 0 if self._integrated_caption and self.isMaximized() else 8
        self.header_layout.setContentsMargins(25, inset, inset, inset)

    def reflow_workspace(self, *args):
        controls_width = (
            self.composer_tools.sizeHint().width() + self.composer_actions.sizeHint().width()
        )
        compact = self.workspace_width() < max(640, controls_width + 100)
        if compact != self.compact_layout:
            self.compact_layout = compact
            self.welcome_title.setProperty("compact", compact)
            self.welcome_title.style().unpolish(self.welcome_title)
            self.welcome_title.style().polish(self.welcome_title)
            self.welcome_title.updateGeometry()
            self.body_layout.setContentsMargins(
                20 if compact else 30, 10, 20 if compact else 30, 22
            )
            self.composer_bar.removeWidget(self.composer_actions)
            if compact:
                self.composer_bar.addWidget(self.composer_actions, 1, 0, 1, 2, Qt.AlignRight)
            else:
                self.composer_bar.addWidget(self.composer_actions, 0, 1, Qt.AlignRight)
        self.update_session_heading()

    def workspace_width(self):
        sidebar = self.history_splitter.sidebar_width
        return self.width() - sidebar - (self.history_splitter.handleWidth() if sidebar else 0)

    def update_session_heading(self):
        title = self.session_title.fontMetrics().elidedText(
            self.session_heading, Qt.ElideRight, max(0, self.workspace_width() - 80)
        )
        self.session_title.setText(title)
        self.session_title.setVisible(bool(title))

    def schedule_history_save(self, *args):
        if not self.restoring_history and self.model.items:
            self.history_dirty = True
            if not self.history_timer.isActive():
                self.history_timer.start()

    def save_history(self):
        self.history_timer.stop()
        if not self.history_dirty:
            return True
        try:
            try:
                self.history.save(self.session_id, self.model.items)
            except SessionHistoryConflict:
                session_id = uuid4().hex
                self.history.save(session_id, self.model.items)
                self.session_id = session_id
                self.status("该会话已在另一个窗口变更，这里的字幕已另存为新会话。")
        except SessionHistoryError as exc:
            self.status(str(exc) + " 可先导出字幕。", True)
            return False
        self.history_dirty = False
        self.refresh_history()
        return True

    def refresh_history(self):
        try:
            summaries = self.history.list_sessions()
        except SessionHistoryError as exc:
            self.status(str(exc), True)
            return
        scrollbar = self.history_list.verticalScrollBar()
        position = scrollbar.value()
        self.history_list.clear()
        title = ""
        for summary in summaries:
            timestamp = summary.updated_at.strftime("%m/%d %H:%M")
            item = QListWidgetItem(f"{summary.title}\n{timestamp}")
            item.setData(Qt.UserRole, summary.id)
            item.setToolTip(
                f"<p>{escape(summary.title)}<br>{summary.updated_at:%Y-%m-%d %H:%M}</p>"
            )
            self.history_list.addItem(item)
            if summary.id == self.session_id:
                title = summary.title
                self.history_list.setCurrentItem(item)
        scrollbar.setValue(position)
        self.history_empty.setVisible(not summaries)
        self.history_list.setVisible(bool(summaries))
        self.session_heading = title
        self.update_session_heading()
        self.session_title.setToolTip(f"<p>{escape(title)}</p>" if title else "")

    def new_session(self):
        if not self.pending and not self.listening and not self.closing and self.save_history():
            self.welcome_title.setText(welcome_greeting(datetime.now().hour))
            self.switch_session(uuid4().hex, [])

    def open_session(self, item):
        session_id = item.data(Qt.UserRole)
        if self.pending or self.listening or self.closing or session_id == self.session_id:
            return
        if not self.save_history():
            self.refresh_history()
            return
        try:
            entries = self.history.load(session_id)
            if entries:
                self.switch_session(session_id, entries)
                return
        except (SessionHistoryError, ValueError):
            self.status("无法打开这次会话，请检查本地历史文件。", True)
            self.refresh_history()
            return
        self.refresh_history()

    def switch_session(self, session_id, entries):
        self.playback_token = None
        self.player.stop()
        self.delegate.cache.clear()
        self.delegate.heights.clear()
        self.view.animation.stop()
        self.restoring_history = True
        try:
            self.model.replace_entries(entries)
        finally:
            self.restoring_history = False
        draft = self.input.toPlainText()
        if draft:
            self.drafts[self.session_id] = draft
        else:
            self.drafts.pop(self.session_id, None)
        self.session_id = session_id
        self.sequence = max((entry.key for entry in self.model.items), default=0)
        self.input.setPlainText(self.drafts.pop(session_id, ""))
        self.unread = 0
        self._model_changed()
        self.go_latest()
        self.refresh_history()
        self.status("")
        self.input.setFocus()

    def source_language(self):
        return "yue" if self.direction_box.currentIndex() == 0 else "zh"

    def sensitivity_changed(self):
        selected = self.sensitivity_box.currentData()
        if selected == self.defaults.sensitivity:
            return
        candidate = replace(self.defaults, sensitivity=selected)
        try:
            save_preferences(candidate, self.preferences)
        except (ValueError, OSError):
            self.sensitivity_box.blockSignals(True)
            self.sensitivity_box.setCurrentIndex(
                self.sensitivity_box.findData(self.defaults.sensitivity)
            )
            self.sensitivity_box.blockSignals(False)
            self.preferences.setValue("defaults/sensitivity", self.defaults.sensitivity)
            self.status("无法保存收音灵敏度，请检查设置目录权限。", True)
            return
        self.defaults = candidate
        self.sensitivity_box.setToolTip(voice_profile(selected).description)

    def source_changed(self):
        microphone = self.source_box.currentIndex() == 0
        self.auto_box.setVisible(microphone)
        self.caption_only_hint.setVisible(not microphone)
        self.audio_button.setToolTip(
            f"{self.source_box.currentText()} · {self.profile_box.currentText()}"
        )
        self._buttons()
        self.reflow_workspace()

    def status(self, text, error=False):
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))
        self.status_label.setToolTip("")
        self.status_label.setProperty("severity", "error" if error else "normal")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _buttons(self, *args):
        if not hasattr(self, "stop_button"):
            return
        idle = not self.pending and not self.listening and not self.closing
        can_submit = self.can_start_task()
        has_text = not self.input.document().isEmpty()
        can_record = not self.closing and (self.listening or can_submit)
        self.record_button.setEnabled(can_record)
        self.record_button.setText(
            "结束收音"
            if self.capture_started
            else "停止准备"
            if self.listening
            else "翻译设备声音"
            if self.source_box.currentIndex() == 1
            else "开始收音"
        )
        for button, primary in (
            (self.record_button, self.listening or not has_text),
            (self.translate_button, not self.listening and has_text),
        ):
            kind = "primary" if primary else "tool"
            if button.objectName() != kind:
                button.setObjectName(kind)
                button.style().unpolish(button)
                button.style().polish(button)
        self.stop_button.setVisible(
            not self.closing and bool(self.pending or self.listening or self.player.busy)
        )
        for control in (self.direction_box, self.audio_button, self.file_button):
            control.setEnabled(can_submit)
        for control in (self.new_button, self.history_list):
            control.setEnabled(idle)
        self.settings_button.setEnabled(not self.closing)
        self.preferences_action.setEnabled(idle)
        self.models_action.setEnabled(idle)
        self.cloud_action.setEnabled(idle)
        self.input.setReadOnly(self.closing)
        self.translate_button.setEnabled(can_submit and has_text)
        self.replay_button.setEnabled(
            can_submit
            and bool(entries := self.selected_entries())
            and bool(entries[-1].replay_text)
        )
        self.clear_button.setEnabled(idle and bool(self.model.items))
        self.copy_button.setEnabled(bool(self.model.items))
        self.export_button.setEnabled(bool(self.model.items))

    def can_start_task(self):
        return not self.listening and not self.closing and not self.pending

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

    def _queue_task(self, key, request):
        token = object()
        self.jobs.put_nowait((self.epoch, key, request, token))
        self.playback_token = token
        self.pending += 1

    def submit(self, request):
        if self.closing:
            return False
        if self.listening and self.source_box.currentIndex() == 1:
            if request.kind == "speak":
                return False
            request = replace(request, autoplay=False)
        folders = [] if request.kind == "speak" else ["hymt2"]
        if request.kind == "file":
            folders.append("asr-wenet")
        if request.kind == "speak" or request.autoplay:
            voice = (
                request.source
                if request.kind == "speak"
                else ("zh" if request.source == "yue" else "yue")
            )
            folders.append(VOICE_MODELS[voice])
        if not self.require_model_groups(folders):
            return False
        self.sequence += 1
        key = self.sequence
        try:
            self._queue_task(key, request)
        except queue.Full:
            self.stop()
            self.status("待处理语句过多，已停止收音。请暂停来源后重试。", True)
            return False
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
        if not self.can_start_task():
            return
        text = self.input.toPlainText().strip()
        if not text or len(text) > 120:
            self.status("请输入 1–120 字。", True)
            self.input.setFocus()
            return
        self.cancel.clear()
        self.status("正在翻译…")
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
        if not self.can_start_task():
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
                folders = ["hymt2", "vad", "song-asr-large"]
                if task.vocals:
                    folders.append("song-separator")
                if not self.require_model_groups(folders):
                    return
                self.song_keys.clear()
                self.song_final_block = -1
                self.song_session = task
                self._queue_task(0, task)
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
        if not self.can_start_task():
            return
        entries = self.selected_entries()
        if not entries or not entries[-1].replay_text:
            return
        item = entries[-1]

        self.cancel.clear()
        self.submit(
            Request(
                self.epoch,
                "speak",
                source=item.target_language,
                text=item.replay_text,
                number_mode=self.number_mode,
            )
        )

    def toggle_capture(self):
        if self.listening:
            if not self.capture_started:
                self.stop()
                return
            if self.song_session is not None:
                self.listening = False
                self.capture_started = False
                if self.microphone:
                    self.microphone.request_stop()
                else:
                    self.song_session.mailbox.finish()
                self.status("正在确认末尾字幕…")
                self._buttons()
            else:
                self.stop()
            return
        if not self.can_start_task():
            return
        source, auto, mode = self.source_language(), self.auto_box.isChecked(), self.number_mode
        folders = ["hymt2", "asr-wenet", "vad"]
        if self.profile_box.currentIndex() == 1:
            folders.append("song-asr-large")
        if auto and self.source_box.currentIndex() == 0:
            folders.append(VOICE_MODELS["zh" if source == "yue" else "yue"])
        if not self.require_model_groups(folders):
            return
        self.cancel.clear()
        self.listening = True
        self.capture_started = False
        self.capture_waiting = False
        self.capture_notice = ""
        self.player.stop()
        self.song_keys.clear()
        self.live_versions.clear()
        self.live_preview_versions.clear()
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
                cloud=self.cloud_config if self.cloud_enabled else None,
            )
        self._queue_task(0, self.song_session)
        self.status(
            "正在准备精细收音…"
            if isinstance(self.song_session, SongSession)
            else "正在启动 flash 实时字幕…"
        )
        self._buttons()

    def _start_song_capture(self):
        if not self.listening or self.song_session is None:
            return
        epoch = self.epoch
        session = self.song_session
        stream_factory = make_live_stream if isinstance(session, LiveSession) else make_song_stream
        factory = partial(stream_factory, sensitivity=self.sensitivity_box.currentData())

        def error(message):
            self.events.put((epoch, 0, "capture_error", message))

        def started(name):
            self.events.put((epoch, 0, "capture_started", name))

        saturated = False

        def segment(window):
            nonlocal saturated
            if saturated:
                return
            try:
                session.mailbox.put(window)
            except SongOverload:
                # The last window is already in the queue. Its end is the last
                # input position available to the consumer.
                saturated = True
                message = f"待确认的字幕已满，接收到收音后 {window.end / RATE:.2f} 秒。此后的声音未纳入本次字幕。"
                self.events.put((epoch, 0, "capture_interrupted", (session, message)))
                capture.request_stop()

        if self.source_box.currentIndex() == 1:
            capture = SystemAudio(
                segment,
                error,
                started,
                paragraph=True,
                segmenter_factory=factory,
            )
        else:
            capture = Microphone(
                segment,
                error,
                paragraph=True,
                segmenter_factory=factory,
                started=started,
            )
            if session.autoplay and self.defaults.mute_mic_during_playback:
                capture.playback_intervals = self.player.playback_intervals

        def finished():
            self.events.put((epoch, 0, "capture_finished", capture))
            session.mailbox.finish()

        capture.on_interrupted = lambda report: self.events.put(
            (epoch, 0, "capture_interrupted", (session, report.message))
        )
        capture.on_finished = finished
        capture.on_waiting = lambda waiting: self.events.put(
            (epoch, 0, "capture_waiting", (session, waiting))
        )
        self.microphone = capture
        capture.start()
        self.status("正在打开音源…")

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

    def _save_capture_notice(self):
        if self.capture_notice:
            self.sequence += 1
            entry = TranscriptEntry(
                self.sequence, "", "", source=self.capture_notice, status="收音中断"
            )
            self._change_transcript(lambda: self.model.append(entry), new=True)
            self.capture_notice = ""

    def stop(self):
        self.cancel.set()
        self.playback_token = None
        self.capture_waiting = False
        self.listening = False
        self.capture_started = False
        if self.microphone:
            self.microphone.stop()
            self.microphone = None
        # Commit results published before this cutoff, including any interruption
        # reported as the capture owner exits. Do not start another device or job.
        self._consume_events(self.events.qsize(), stopping=True)
        self.epoch += 1
        self._save_capture_notice()
        if self.song_session is not None:
            if isinstance(self.song_session, (SongSession, LiveSession)):
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
            if item and item.status not in {"已确认", "已翻译"}:
                self.model.update_entry(
                    key, status="已取消" if not item.target else "暂定 · 已停止"
                )
        self.active_ids.clear()
        self.live_preview_versions.clear()
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
                try:
                    self.engine.close()
                finally:
                    self.jobs.task_done()
                return
            epoch, key, payload, token = job

            def emit(kind, value, epoch=epoch, key=key):
                self.events.put((epoch, key, kind, value))

            try:
                output = self.player.for_task(
                    lambda message, token=token, emit=emit: emit("audio_error", (token, message))
                )
                if isinstance(payload, (SongSession, LiveSession)):
                    if not isinstance(payload, SongFile):
                        emit("status", "正在准备语音识别…")
                        self.engine.prepare_recognition(self.cancel)
                    payload.run(self.engine, output, self.cancel, emit)
                elif self.cloud_enabled and payload.kind in {"text", "file"}:
                    from .enhanced_inference import process_short_request

                    process_short_request(
                        payload, self.cloud_config, self.engine, output, self.cancel, emit
                    )
                    emit("done", True)
                else:
                    self.engine.process(payload, self.cancel, output, emit)
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

    def _consume_events(self, limit, *, stopping=False):
        for _ in range(limit):
            try:
                epoch, key, kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "finished":
                self.pending = max(0, self.pending - 1)
                if not stopping and epoch == self.epoch:
                    self.active_ids.discard(key)
                continue
            if epoch != self.epoch:
                continue
            if stopping and kind not in {
                "source",
                "translation",
                "live_source",
                "live_translation",
                "live_empty",
                "song_source",
                "song_translation",
                "song_empty",
                "capture_interrupted",
            }:
                continue
            if (
                kind in {"translation", "song_translation", "live_translation"}
                and self.engine.translator.using_completion
                and self.network_mode in {"offline", "fallback"}
            ):
                detail = (
                    "系统限制了本机服务连接。Hy-MT2 正通过离线程序逐次翻译，每句需要重新加载模型。"
                )
                self.network_pill.setText(
                    "本地回退 · 逐句翻译" if self.network_mode == "fallback" else "本地逐句翻译"
                )
                note = self.network_pill.toolTip()
                if detail not in note:
                    self.network_pill.setToolTip(
                        note + "\n" + detail if self.network_mode == "fallback" else detail
                    )
            if kind == "network_state":
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
                        target_current=True,
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
            elif kind == "capture_started" and self.listening:
                self.capture_started = True
                self.status(
                    f"正在收音 · {value}"
                    if self.source_box.currentIndex() == 0
                    else f"正在翻译设备声音 · {value}（仅字幕）"
                )
            elif kind == "capture_waiting" and value[0] is self.song_session and self.listening:
                self.capture_waiting = value[1]
                if self.capture_waiting:
                    self.status(WAITING_FOR_AUDIO)
                elif self.status_label.text() == WAITING_FOR_AUDIO:
                    self.status("已恢复接收音频。")
            elif kind == "song_ready":
                self._start_song_capture()
            elif kind == "live_source":
                if value["version"] <= self.live_versions.get(value["block"], -1):
                    continue
                row_key = self._song_key(value["block"])
                self.live_versions[value["block"]] = value["version"]
                self._change_transcript(
                    lambda: self.model.update_entry(
                        row_key,
                        source=value["text"],
                        source_confirmed=value.get("frozen_characters", 0),
                        status="原文已固定 · 译文更新中"
                        if value["final"]
                        else "暂定 · 待复核"
                        if value.get("reviewing")
                        else "末尾更新中",
                    )
                )
                self.status("原文已确认，正在翻译…" if value["final"] else "原文实时更新中…")
                self.status_label.setToolTip(
                    f"本次识别 {value['recognition_seconds']:.2f} 秒。"
                    f"从窗口最后一包的采集回调到原文返回约 {value['lag_seconds']:.2f} 秒，"
                    "含采集队列等待，不含设备内部延迟和界面绘制。"
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
                if value.get("preview") and not value["final"]:
                    # Translation can trail the still-changing source. Keep the
                    # latest available rough result, but never revise fixed text.
                    if (
                        item.source_confirmed == len(item.source)
                        or item.target_confirmed
                        or value["version"] > current_version
                        or value["version"] <= self.live_preview_versions.get(block, -1)
                    ):
                        continue
                    self.live_preview_versions[block] = value["version"]
                    self._change_transcript(
                        lambda: self.model.update_entry(
                            row_key,
                            target=value["text"],
                            target_confirmed=0,
                            target_current=(
                                value["version"] == current_version
                                and value.get("source", item.source) == item.source
                                and value.get("tail_current", True)
                            ),
                            status="粗略译文 · 待复核",
                        )
                    )
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
                            target_current=False,
                            status="前文已固定 · 末尾更新中",
                        )
                    )
                    continue
                self._change_transcript(
                    lambda: self.model.update_entry(
                        row_key,
                        target=value["text"],
                        target_confirmed=len(frozen_target),
                        target_current=value["final"] or value.get("tail_current", True),
                        status="已确认" if value["final"] else "末尾更新中",
                    )
                )
                if value["final"]:
                    self.active_ids.discard(row_key)
                    self.song_keys.pop(block, None)
                    self.live_versions.pop(block, None)
                    self.live_preview_versions.pop(block, None)
            elif kind == "live_empty":
                block = value["block"]
                row_key = self.song_keys.pop(block, None)
                self.live_versions.pop(block, None)
                self.live_preview_versions.pop(block, None)
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
                    status="片段固定 · 翻译中" if value["final"] else "末尾更新中",
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
                        target_current=True,
                        status=(
                            "已确认"
                            if value["final"]
                            else "末尾更新中"
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
                        target_current=True,
                        status="前文已固定 · 末尾未确认"
                        if value.get("partial")
                        else "未检测到新内容",
                    )
                    self.active_ids.discard(row_key)
                    self.song_keys.pop(value["block"], None)
            elif kind == "song_drained":
                self.song_session = None
                if self.capture_notice:
                    for row_key in self.song_keys.values():
                        if row_key in self.active_ids and self.model.by_key.get(row_key):
                            self.model.update_entry(row_key, status="末尾未确认 · 收音已停止")
                        self.active_ids.discard(row_key)
                    self.song_keys.clear()
                    self.status("已处理排队音频，字幕和收音中断位置已记入会话。")
                    self._save_capture_notice()
                else:
                    self.status(
                        "已有字幕已保留，部分末尾没有有效识别结果，尚未确认。"
                        if isinstance(value, dict) and value.get("partial_count")
                        else "本次没有生成有效字幕，已有记录已保留。"
                        if isinstance(value, dict) and not value.get("confirmed_count")
                        else "末尾字幕已确认 · 本次记录已保留，可回看或导出。"
                    )
            elif kind == "capture_interrupted" and value[0] is self.song_session:
                self.capture_notice = self.capture_notice or value[1]
                self.listening = False
                self.capture_started = False
            elif kind == "capture_finished" and value is self.microphone:
                self.microphone = None
                self.listening = self.capture_started = False
                self.capture_waiting = False
                report = getattr(value, "report", None)
                if report is not None:
                    muted = (
                        f"播报期间跳过拾音 {report.muted_frames / report.rate:.3f} 秒。"
                        if report.muted_frames
                        else ""
                    )
                    self.record_button.setToolTip(
                        f"上次收音收到 {report.frames / report.rate:.2f} 秒音频。"
                        f"采集缓冲峰值 {report.peak_buffer_frames / report.rate:.3f} 秒，"
                        f"接收队列峰值 {report.peak_receiver_packets} 包。"
                        f"从采集回调到处理的最长等待为 {report.max_delivery_lag_seconds:.3f} 秒。"
                        + muted
                    )
            elif kind in ("speech_warning", "audio_error"):
                if kind == "audio_error":
                    token, value = value
                    if token is not self.playback_token:
                        continue
                if self.song_session is not None:
                    self.song_session.autoplay = False
                self.status(value, True)
            elif kind == "capture_error":
                self.stop()
                self.status(value, True)
            elif kind == "error":
                if self.song_session is not None:
                    self.stop()
                self.model.update_entry(key, status="处理失败")
                self.status(value, True)

    def poll(self):
        self._consume_events(160)
        if (
            self.capture_waiting
            and self.listening
            and self.status_label.text() != WAITING_FOR_AUDIO
        ):
            self.status(WAITING_FOR_AUDIO)
        if self.capture_notice and self.status_label.toolTip() != self.capture_notice:
            self.status("收音已停止，正在补完已接收的字幕…")
            self.status_label.setToolTip(self.capture_notice)
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
            self,
            "导出本次字幕",
            str(export_directory(self.defaults) / f"{APP_NAME}-字幕.txt"),
            "文本文件 (*.txt)",
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
        if self.pending or self.listening or self.closing:
            return
        if (
            QMessageBox.question(
                self,
                "清空本次字幕",
                "这次会话的字幕将从本地历史中移除。需要保留时请先导出。确定清空？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        ):
            try:
                self.history.delete(self.session_id)
            except SessionHistoryError as exc:
                self.status(str(exc), True)
                return
            self.history_timer.stop()
            self.history_dirty = False
            self.switch_session(self.session_id, [])

    def apply_preferences(self, previous=None):
        self.sensitivity_box.blockSignals(True)
        self.sensitivity_box.setCurrentIndex(
            self.sensitivity_box.findData(self.defaults.sensitivity)
        )
        self.sensitivity_box.blockSignals(False)
        self.sensitivity_box.setToolTip(voice_profile(self.defaults.sensitivity).description)
        if previous is None or self.defaults.mode != previous.mode:
            self.profile_box.setCurrentIndex(1 if self.defaults.mode == "pro" else 0)
        if previous is None or self.defaults.direction != previous.direction:
            self.direction_box.setCurrentIndex(0 if self.defaults.direction == "yue" else 1)
        if previous is None or self.defaults.audio_source != previous.audio_source:
            self.source_box.setCurrentIndex(0 if self.defaults.audio_source == "microphone" else 1)
        if previous is None or self.defaults.autoplay != previous.autoplay:
            self.auto_box.setChecked(self.defaults.autoplay)
        self.delegate.font_size = self.defaults.font_size
        self.delegate.cache.clear()
        self.delegate.heights.clear()
        self.view.smooth = self.defaults.smooth
        if not self.view.smooth:
            self.view.animation.stop()
        self.number_mode = self.defaults.number_mode
        self.song_file_vocals = self.defaults.vocals
        self.view.doItemsLayout()
        self.view.viewport().update()
        self.source_changed()

    def model_manager(self, checked=False, *, group="base", intro=""):
        if not self.can_start_task():
            return
        dialog = ModelDialog(self, group, intro, before_delete=self.engine.close)
        dialog.exec()
        dialog.deleteLater()

    def require_model_groups(self, folders):
        for group, (title, members) in GROUPS.items():
            required = [folder for folder in folders if folder in members]
            if ready(required):
                continue
            self.model_manager(group=group, intro=f"使用此功能需要准备「{title}」。")
            if not ready(required):
                self.status(f"「{title}」尚未就绪，可从设置打开模型管理。", True)
                return False
        return True

    def guide_first_model_download(self):
        if (
            os.environ.get("YUEPU_LIGHT_INSTALL") == "1"
            and not self.preferences.value("models/guide_seen", False, type=bool)
            and not ready(GROUPS["base"][1])
        ):
            self.preferences.setValue("models/guide_seen", True)
            self.model_manager(
                intro="欢迎使用粤普同传。先下载或导入基础模型，准备好后即可离线使用。"
            )
            try:
                defaults = load_preferences(self.preferences)
            except (TypeError, ValueError):
                return
            previous, self.defaults = self.defaults, defaults
            self.apply_preferences(previous)

    def settings(self):
        if self.pending or self.listening or self.closing:
            return
        dialog = SettingsDialog(self.defaults, self.preferences, self)
        if dialog.exec() == QDialog.Accepted:
            previous = self.defaults
            self.defaults = dialog.preferences
            self.apply_preferences(previous)
            self.status("首选项已保存。")

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
            self.network_pill.setText("联网待请求" if self.cloud_enabled else "本地离线")
            self.network_pill.setToolTip(
                "音频与文字仅在启用后开始处理时发送至所选百炼地域；每次启动默认离线。"
                if self.cloud_enabled
                else "推理仅使用本机模型。"
            )
            self.source_changed()
            self.status(
                "联网增强已开启；pro 上传复核音频与待翻译文字（含粗译），flash 上传待翻译文字。失败后本次任务回退本地。"
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
        if not self.save_history() and (
            QMessageBox.question(
                self,
                "会话未保存",
                "最近的字幕未能写入历史。选择「否」返回窗口导出。仍要退出吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        self.closing = True
        self.status("正在退出…")
        self.jobs.put_nowait(None)
        self._buttons()


def main(*, muted=False):
    app = QApplication([])
    app.setApplicationDisplayName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window(muted=muted)
    window.show()
    QTimer.singleShot(0, window.guide_first_model_download)
    app.exec()
