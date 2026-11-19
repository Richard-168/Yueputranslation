"""Validated user preferences; saving never records audio or upload consent."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .audio_profile import VOICE_PROFILES
from .paths import DATA_DIR
from .preferences import Preferences, default_cache_directory, export_directory, save_preferences


class SettingsDialog(QDialog):
    def __init__(self, preferences, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setWindowTitle("首选项")
        self.setMinimumSize(550, 400)
        self.resize(660, 560)
        self.settings_store = settings
        self.preferences = preferences
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QVBoxLayout()
        header.setContentsMargins(26, 20, 26, 14)
        header.setSpacing(4)
        header.addWidget(self._label("首选项", "dialogTitle"))
        header.addWidget(self._label("为后续会话设置默认值。", "dialogDescription"))
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("dialogNavigation")
        self.tabs.setAccessibleName("首选项分类")
        body = QVBoxLayout()
        body.setContentsMargins(26, 0, 26, 12)
        body.addWidget(self.tabs)
        layout.addLayout(body, 1)

        def page(title):
            scroll = QScrollArea()
            scroll.setObjectName("dialogScroll")
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidgetResizable(True)
            widget = QWidget()
            scroll.setWidget(widget)
            form = QFormLayout(widget)
            form.setContentsMargins(0, 16, 10, 4)
            form.setLabelAlignment(Qt.AlignLeft)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setHorizontalSpacing(20)
            form.setVerticalSpacing(9)
            self.tabs.addTab(scroll, title)
            return form

        def combo(form, label, name, options, value):
            field = QComboBox()
            field.setObjectName(name)
            field.setAccessibleName(label)
            for text, data in options:
                field.addItem(text, data)
            field.setCurrentIndex(field.findData(value))
            form.addRow(label, field)
            return field

        general = page("常规")
        general.addRow(self._label("翻译", "dialogSection"))
        self.mode = combo(
            general,
            "默认模式",
            "default_mode",
            [
                ("pro · 句末复核", "pro"),
                ("flash · 轻量实时字幕", "flash"),
            ],
            preferences.mode,
        )
        self.direction = combo(
            general,
            "默认翻译方向",
            "default_direction",
            [
                ("粤语 → 普通话", "yue"),
                ("普通话 → 粤语", "zh"),
            ],
            preferences.direction,
        )
        general.addRow(self._label("收音与播报", "dialogSection"))
        self.audio_source = combo(
            general,
            "默认音源",
            "default_audio_source",
            [
                ("麦克风", "microphone"),
                ("设备声音", "system"),
            ],
            preferences.audio_source,
        )
        self.sensitivity = combo(
            general,
            "默认收音灵敏度",
            "default_sensitivity",
            [(profile.label, key) for key, profile in VOICE_PROFILES.items()],
            preferences.sensitivity,
        )
        sensitivity_hint = self._label("", "dialogHint")

        def describe_sensitivity():
            profile = VOICE_PROFILES[self.sensitivity.currentData()]
            sensitivity_hint.setText(
                profile.description + " 仅影响实时收音，不能只锁定指定说话人。"
            )

        self.sensitivity.currentIndexChanged.connect(describe_sensitivity)
        describe_sensitivity()
        general.addRow(sensitivity_hint)
        self.autoplay = QCheckBox("确认后自动播报译音")
        self.autoplay.setChecked(preferences.autoplay)
        playback = QHBoxLayout()
        playback.setContentsMargins(0, 0, 0, 0)
        playback.setSpacing(12)
        playback.addWidget(self.autoplay)
        playback.addWidget(self._label("设备收音期间只显示字幕。", "dialogHint"), 1)
        general.addRow(playback)
        self.mute_mic_during_playback = QCheckBox("使用扬声器时，播报译音期间暂停拾音")
        self.mute_mic_during_playback.setChecked(preferences.mute_mic_during_playback)
        general.addRow(self.mute_mic_during_playback)
        general.addRow(
            self._label("仅对麦克风自动播报生效。播报期间对方同时说的话也会跳过。", "dialogHint")
        )
        self.mode.setToolTip("pro 先显示原文和粗译，句末复核时使用 song-asr-large 模型。")

        reading = page("阅读与播报")
        reading.addRow(self._label("字幕", "dialogSection"))
        self.font_size = QSpinBox()
        self.font_size.setRange(12, 24)
        self.font_size.setValue(preferences.font_size)
        self.font_size.setAccessibleName("字幕字号")
        reading.addRow("字幕字号", self.font_size)
        self.smooth = QCheckBox("平滑滚动与字幕跟随动画")
        self.smooth.setChecked(preferences.smooth)
        reading.addRow(self.smooth)
        reading.addRow(self._label("译音", "dialogSection"))
        self.numbers = combo(
            reading,
            "普通话数字读法",
            "number_mode",
            [
                ("按原文", "original"),
                ("金额", "amount"),
                ("号码逐位", "identifier"),
            ],
            preferences.number_mode,
        )
        reading.addRow(self._label("音频文件", "dialogSection"))
        self.vocals = QCheckBox("启用人声分离")
        self.vocals.setChecked(preferences.vocals)
        reading.addRow(self.vocals)
        reading.addRow(self._label("适用于 pro 模式的音频文件，会增加处理时间。", "dialogHint"))

        storage = page("文件位置")
        storage.addRow(self._label("存储目录", "dialogSection"))

        def folder(label, name, value, placeholder):
            host = QWidget()
            row = QHBoxLayout(host)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            field = QLineEdit(value)
            field.setObjectName(name)
            field.setAccessibleName(label)
            field.setPlaceholderText(placeholder)
            field.setToolTip(value or placeholder)
            field.textChanged.connect(lambda path: field.setToolTip(path or placeholder))
            row.addWidget(field, 1)
            browse = QPushButton("浏览…")
            browse.setAutoDefault(False)
            browse.setAccessibleName("选择" + label)

            def choose():
                chosen = QFileDialog.getExistingDirectory(
                    self, "选择" + label, field.text() or placeholder
                )
                if chosen:
                    field.setText(chosen)

            browse.clicked.connect(choose)
            row.addWidget(browse)
            storage.addRow(label, host)
            return field

        self.cache = folder(
            "临时缓存目录",
            "cache_directory",
            preferences.cache_directory,
            str(default_cache_directory()),
        )
        self.exports = folder(
            "字幕默认保存目录",
            "export_directory",
            preferences.export_directory,
            str(export_directory(Preferences())),
        )
        storage.addRow(
            self._label(
                "留空使用默认位置。会话文字和字幕仍会自动保存在本机。",
                "dialogHint",
            )
        )
        storage.addRow(self._label("模型目录", "dialogSection"))
        model_path = QLineEdit(str(DATA_DIR))
        model_path.setAccessibleName("当前模型目录")
        model_path.setReadOnly(True)
        model_path.setToolTip(str(DATA_DIR))
        storage.addRow(model_path)

        footer = QWidget()
        footer.setObjectName("dialogFooter")
        actions = QVBoxLayout(footer)
        actions.setContentsMargins(26, 12, 26, 14)
        actions.setSpacing(8)
        self.feedback = self._label("", "dialogError")
        self.feedback.setProperty("severity", "error")
        self.feedback.setAccessibleName("设置保存结果")
        self.feedback.hide()
        actions.addWidget(self.feedback)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save = self.buttons.button(QDialogButtonBox.Save)
        save.setText("保存")
        save.setObjectName("primary")
        save.setDefault(True)
        cancel = self.buttons.button(QDialogButtonBox.Cancel)
        cancel.setText("取消")
        cancel.setObjectName("quiet")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        actions.addWidget(self.buttons)
        layout.addWidget(footer)

    @staticmethod
    def _label(text, name):
        label = QLabel(text)
        label.setObjectName(name)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        return label

    def accept(self):
        candidate = Preferences(
            mode=self.mode.currentData(),
            direction=self.direction.currentData(),
            audio_source=self.audio_source.currentData(),
            sensitivity=self.sensitivity.currentData(),
            autoplay=self.autoplay.isChecked(),
            mute_mic_during_playback=self.mute_mic_during_playback.isChecked(),
            font_size=self.font_size.value(),
            smooth=self.smooth.isChecked(),
            number_mode=self.numbers.currentData(),
            vocals=self.vocals.isChecked(),
            cache_directory=self.cache.text().strip(),
            export_directory=self.exports.text().strip(),
        )
        try:
            save_preferences(candidate, self.settings_store)
        except (ValueError, OSError) as exc:
            self.feedback.setText(
                str(exc)
                if isinstance(exc, ValueError)
                else "无法写入所选目录或保存设置，请检查权限后重试。"
            )
            self.feedback.show()
            return
        self.preferences = candidate
        super().accept()
