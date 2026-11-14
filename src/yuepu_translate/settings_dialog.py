"""Validated user preferences; saving never records audio or upload consent."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .paths import DATA_DIR
from .preferences import Preferences, default_cache_directory, export_directory, save_preferences


class SettingsDialog(QDialog):
    def __init__(self, preferences, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置与首选项")
        self.setMinimumWidth(620)
        self.settings_store = settings
        self.preferences = preferences
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        def page(title):
            widget = QWidget()
            form = QFormLayout(widget)
            form.setContentsMargins(18, 20, 18, 20)
            form.setSpacing(14)
            self.tabs.addTab(widget, title)
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
        self.mode = combo(
            general,
            "默认模式",
            "default_mode",
            [
                ("pro · 段落断句，实时草稿与句末复核", "pro"),
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
        self.autoplay = QCheckBox("确认后自动播报译音（设备收音期间始终关闭）")
        self.autoplay.setChecked(preferences.autoplay)
        general.addRow(self.autoplay)
        note = QLabel(
            "pro 保留原段落检测与断句，原文和粗译先显示，句末由较大模型复核并修正；需要 song-asr-large。\n"
            "flash 保留轻量实时处理。联网增强由“联网设置”独立开启，重启后默认关闭。"
        )
        note.setWordWrap(True)
        general.addRow(note)

        reading = page("阅读与播报")
        self.font_size = QSpinBox()
        self.font_size.setRange(12, 24)
        self.font_size.setValue(preferences.font_size)
        self.font_size.setAccessibleName("字幕字号")
        reading.addRow("字幕字号", self.font_size)
        self.smooth = QCheckBox("平滑滚动与字幕跟随动画")
        self.smooth.setChecked(preferences.smooth)
        reading.addRow(self.smooth)
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
        self.vocals = QCheckBox("人声分离（较慢，仅用于 pro 音频文件）")
        self.vocals.setChecked(preferences.vocals)
        reading.addRow(self.vocals)

        storage = page("文件位置")

        def folder(label, name, value, placeholder):
            host = QWidget()
            row = QHBoxLayout(host)
            row.setContentsMargins(0, 0, 0, 0)
            field = QLineEdit(value)
            field.setObjectName(name)
            field.setAccessibleName(label)
            field.setPlaceholderText(placeholder)
            field.setToolTip(value or placeholder)
            field.textChanged.connect(field.setToolTip)
            row.addWidget(field, 1)
            browse = QPushButton("浏览…")
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
        locations = QLabel(
            "留空使用默认位置。缓存仅放本地推理临时文件，正常结束时清理。\n"
            "字幕仅在手动导出时保存，不自动保存录音或会话。\n"
            "更换目录不会搬动、删除旧文件，也不会移动已下载模型。\n"
            f"当前模型目录：{DATA_DIR}"
        )
        locations.setWordWrap(True)
        storage.addRow(locations)
        self.feedback = QLabel("保存后应用首选项；取消不会保存修改。")
        self.feedback.setWordWrap(True)
        self.feedback.setAccessibleName("设置保存结果")
        layout.addWidget(self.feedback)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("保存")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def accept(self):
        candidate = Preferences(
            mode=self.mode.currentData(),
            direction=self.direction.currentData(),
            audio_source=self.audio_source.currentData(),
            autoplay=self.autoplay.isChecked(),
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
            return
        self.preferences = candidate
        super().accept()
