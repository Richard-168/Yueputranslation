"""Cloud consent, encrypted credential storage and explicit asynchronous probe."""

import os
import queue
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .cloud_client import CloudClient
from .cloud_config import CloudConfig, save_settings
from .cloud_protocol import CloudError
from .inference_control import InferenceCancelled


class CloudDialog(QDialog):
    def __init__(self, config, enabled=False, remember=False, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setWindowTitle("联网设置")
        self.setMinimumSize(560, 420)
        self.resize(680, 690)
        self.config = config
        self.enabled = enabled
        self.remember = remember
        self.cancel = threading.Event()
        self.worker = None
        self.results = queue.Queue(maxsize=1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)
        header = QVBoxLayout()
        header.setSpacing(5)
        header.addWidget(self.label("联网增强", "dialogTitle"))
        header.addWidget(
            self.label(
                "使用阿里云百炼的 Qwen3-ASR-Flash 识别与 Qwen-MT-Flash 翻译。"
                "译音仍由本地模型生成。",
                "dialogDescription",
            )
        )
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setObjectName("dialogScroll")
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(scroll, 1)
        content = QWidget()
        fields = QVBoxLayout(content)
        fields.setContentsMargins(0, 1, 12, 1)
        fields.setSpacing(12)
        scroll.setWidget(content)

        consent = QFrame()
        consent.setObjectName("dialogCard")
        consent_layout = QVBoxLayout(consent)
        consent_layout.setContentsMargins(14, 12, 14, 12)
        consent_layout.setSpacing(6)
        consent_layout.addWidget(self.label("数据与费用", "dialogSection"))
        consent_layout.addWidget(
            self.label(
                "开始收音、打开音频或翻译文字后，才会发起翻译请求。"
                "每次识别最多发送最近 30 秒的音频，可能含停顿及背景声音；"
                "翻译会发送待翻译文字。",
                "dialogHint",
            )
        )
        consent_layout.addWidget(
            self.label(
                "暂定字幕更新可能重复提交音频和文字，费用以你的百炼账户账单为准。"
                "取消请求无法撤回已发送的内容或已产生的费用。",
                "dialogHint",
            )
        )
        consent_layout.addWidget(
            self.label(
                "本次任务首次请求失败后会切回本地模型，新任务才重试联网。关闭软件后恢复离线。",
                "dialogHint",
            )
        )
        self.enable_box = QCheckBox("启用联网增强（仅本次运行）")
        self.enable_box.setChecked(enabled)
        consent_layout.addWidget(self.enable_box)
        fields.addWidget(consent)

        fields.addWidget(self.label("服务与密钥", "dialogSection"))
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.region_box = QComboBox()
        self.region_box.setAccessibleName("服务地域")
        self.region_box.addItems(["中国内地 · 北京", "国际 · 新加坡"])
        self.region_box.setCurrentIndex(0 if config.region == "beijing" else 1)
        form.addRow("服务地域", self.region_box)
        self.key_edit = QLineEdit(config.api_key)
        self.key_edit.setAccessibleName("API Key")
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setMaxLength(512)
        self.key_edit.setPlaceholderText("填写所选地域的 API Key")
        form.addRow("API Key", self.key_edit)
        fields.addLayout(form)
        self.remember_box = QCheckBox("使用当前 Windows 账户加密记住密钥")
        self.remember_box.setChecked(remember)
        self.remember_box.setEnabled(os.name == "nt")
        fields.addWidget(self.remember_box)
        fields.addWidget(
            self.label("密钥默认仅用于本次运行。请勿将密钥发到聊天或 Issue。", "dialogHint")
        )

        advanced_button = QToolButton()
        advanced_button.setText("高级选项")
        advanced_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        advanced_button.setObjectName("quiet")
        advanced_button.setCheckable(True)
        fields.addWidget(advanced_button, 0, Qt.AlignLeft)
        advanced = QWidget()
        advanced_form = QFormLayout(advanced)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        advanced_form.setHorizontalSpacing(16)
        advanced_form.setVerticalSpacing(10)
        advanced_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.workspace_edit = QLineEdit(config.workspace)
        self.workspace_edit.setAccessibleName("业务空间 ID")
        self.workspace_edit.setMaxLength(64)
        self.workspace_edit.setPlaceholderText("可选；留空使用对应地域的公共域名")
        advanced_form.addRow("业务空间 ID", self.workspace_edit)
        self.timeout_box = QSpinBox()
        self.timeout_box.setAccessibleName("单次请求超时")
        self.timeout_box.setRange(3, 30)
        self.timeout_box.setSuffix(" 秒")
        self.timeout_box.setValue(config.timeout)
        advanced_form.addRow("单次请求超时", self.timeout_box)
        fields.addWidget(advanced)

        def show_advanced(expanded):
            advanced.setVisible(expanded)
            advanced_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
            if expanded and advanced_button.hasFocus():
                QTimer.singleShot(0, lambda: scroll.ensureWidgetVisible(advanced))

        advanced_button.toggled.connect(show_advanced)
        advanced_button.setChecked(
            bool(config.workspace) or config.timeout != CloudConfig().timeout
        )
        show_advanced(advanced_button.isChecked())

        fields.addWidget(self.label("连接测试", "dialogSection"))
        fields.addWidget(
            self.label(
                "测试只发送 0.25 秒程序生成的静音和“你好”，可能产生少量费用。测试过程不会收音。",
                "dialogHint",
            )
        )
        self.probe_button = QPushButton("测试识别与翻译连接")
        self.probe_button.clicked.connect(self.probe)
        fields.addWidget(self.probe_button, 0, Qt.AlignLeft)
        fields.addStretch()

        self.feedback = self.label("保存后应用改动，取消则保留原设置。", "dialogFeedback")
        layout.addWidget(self.feedback)
        footer = QFrame()
        footer.setObjectName("dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 10, 0, 0)
        self.clear_button = QPushButton("清除密钥")
        self.clear_button.setObjectName("quiet")
        self.clear_button.setToolTip("保存后删除已记住的密钥并关闭联网。")
        self.clear_button.clicked.connect(self.clear_key)
        footer_layout.addWidget(self.clear_button)
        footer_layout.addStretch()
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save = self.buttons.button(QDialogButtonBox.Save)
        save.setText("保存")
        save.setObjectName("primary")
        cancel = self.buttons.button(QDialogButtonBox.Cancel)
        cancel.setText("取消")
        cancel.setObjectName("quiet")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        footer_layout.addWidget(self.buttons)
        layout.addWidget(footer)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(50)

    @staticmethod
    def label(text, name):
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setObjectName(name)
        return label

    def candidate(self):
        config = CloudConfig(
            self.key_edit.text(),
            "beijing" if self.region_box.currentIndex() == 0 else "singapore",
            self.workspace_edit.text().strip(),
            self.timeout_box.value(),
        )
        if self.enable_box.isChecked() or self.remember_box.isChecked() or config.api_key:
            config.validate()
        return config

    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def set_busy(self, busy):
        for widget in (
            self.enable_box,
            self.region_box,
            self.workspace_edit,
            self.key_edit,
            self.timeout_box,
            self.probe_button,
            self.clear_button,
        ):
            widget.setEnabled(not busy)
        self.remember_box.setEnabled(not busy and os.name == "nt")
        self.buttons.button(QDialogButtonBox.Save).setEnabled(not busy)

    def clear_key(self):
        self.key_edit.clear()
        self.remember_box.setChecked(False)
        self.enable_box.setChecked(False)
        self.feedback.setText("保存后删除已记住的密钥；取消则保留原设置。")

    def probe(self):
        if self.busy():
            return
        try:
            config = self.candidate().validate()
        except ValueError as exc:
            self.feedback.setText(str(exc))
            return
        self.cancel.clear()
        self.set_busy(True)
        self.feedback.setText("正在测试识别与翻译权限…可点取消中止等待。")

        def work():
            import numpy as np

            client = CloudClient(config, "yue")
            try:
                client.transcribe(np.zeros(4000, dtype=np.float32), self.cancel)
                client.translate("你好", self.cancel)
                message = "识别与翻译均已响应；这只验证连接与权限，不代表准确性测试通过。"
            except InferenceCancelled:
                message = "测试已取消。"
            except (CloudError, ValueError) as exc:
                message = str(exc)
            except Exception:
                message = "测试未完成，请检查网络与服务配置。"
            finally:
                client.close()
            self.results.put_nowait(message)

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def poll(self):
        if self.busy():
            return
        try:
            self.feedback.setText(self.results.get_nowait())
            self.set_busy(False)
        except queue.Empty:
            pass

    def accept(self):
        if self.busy():
            return
        try:
            config = self.candidate()
            save_settings(config, self.remember_box.isChecked())
        except OSError:
            if self.remember_box.isChecked():
                self.feedback.setText(
                    "无法在本机记住密钥，请检查配置目录权限或文件是否被占用。\n"
                    "可取消勾选“使用当前 Windows 账户加密记住密钥”，再点保存，"
                    "仅在本次运行中使用；不会自动改成明文保存。"
                )
            else:
                self.feedback.setText(
                    "无法清除本机已记住的密钥，请检查配置目录权限或文件是否被占用。"
                    "旧配置仍可能保留，本次设置尚未保存。"
                )
            return
        except (ValueError, RuntimeError) as exc:
            self.feedback.setText(str(exc))
            return
        self.config = config
        self.enabled = self.enable_box.isChecked()
        self.remember = self.remember_box.isChecked()
        self.timer.stop()
        super().accept()

    def reject(self):
        self.cancel.set()
        if self.worker:
            self.worker.join(timeout=2)
        self.timer.stop()
        super().reject()

    def closeEvent(self, event):
        self.reject()
        event.accept()
