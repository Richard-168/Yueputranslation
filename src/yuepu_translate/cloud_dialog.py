"""Cloud consent, encrypted credential storage and explicit asynchronous probe."""

import os
import queue
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
)

from .cloud_client import CloudClient
from .cloud_config import CloudConfig, save_settings
from .cloud_protocol import CloudError
from .inference_control import InferenceCancelled


class CloudDialog(QDialog):
    def __init__(self, config, enabled=False, remember=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("联网增强 · 阿里云百炼")
        self.setMinimumWidth(570)
        self.config = config
        self.enabled = enabled
        self.remember = remember
        self.cancel = threading.Event()
        self.worker = None
        self.results = queue.Queue(maxsize=1)
        form = QFormLayout(self)
        form.setContentsMargins(26, 24, 26, 24)
        form.setSpacing(14)
        intro = QLabel("云端识别：Qwen3-ASR-Flash\n云端翻译：Qwen-MT-Flash · 译音仍使用本地模型")
        intro.setWordWrap(True)
        form.addRow(intro)
        self.enable_box = QCheckBox("启用联网增强（仅本次运行）")
        self.enable_box.setChecked(enabled)
        form.addRow(self.enable_box)
        self.region_box = QComboBox()
        self.region_box.addItems(["中国内地 · 北京", "国际 · 新加坡"])
        self.region_box.setCurrentIndex(0 if config.region == "beijing" else 1)
        form.addRow("服务地域", self.region_box)
        self.workspace_edit = QLineEdit(config.workspace)
        self.workspace_edit.setMaxLength(64)
        self.workspace_edit.setPlaceholderText("可选；留空使用对应地域的公共域名")
        form.addRow("业务空间 ID", self.workspace_edit)
        self.key_edit = QLineEdit(config.api_key)
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setMaxLength(512)
        self.key_edit.setPlaceholderText("填写对应地域的 API Key；不要发到聊天或 Issue")
        form.addRow("API Key", self.key_edit)
        self.remember_box = QCheckBox("使用当前 Windows 账户加密记住密钥")
        self.remember_box.setChecked(remember)
        self.remember_box.setEnabled(os.name == "nt")
        form.addRow(self.remember_box)
        self.timeout_box = QSpinBox()
        self.timeout_box.setRange(3, 30)
        self.timeout_box.setSuffix(" 秒")
        self.timeout_box.setValue(config.timeout)
        form.addRow("单次请求超时", self.timeout_box)
        notice = QLabel(
            "开启后，仅在你开始收音、打开音频或翻译文字时发送内容。\n"
            "识别会发送最近最多 30 秒音频（可能含停顿及背景声音）；翻译发送待翻译文字。\n"
            "暂定字幕更新会重复提交部分音频和文字，费用由你的百炼账户承担，\n"
            "以服务商实际账单为准；不是每秒音频只计费一次。\n"
            "首次请求失败后，本次任务仅使用本地模型；再次开始任务才尝试联网。\n"
            "关闭软件后恢复离线。取消请求不能撤回已经发送的内容或费用。"
        )
        notice.setWordWrap(True)
        notice.setObjectName("muted")
        form.addRow(notice)
        self.probe_button = QPushButton("测试识别与翻译连接")
        self.probe_button.clicked.connect(self.probe)
        form.addRow(self.probe_button)
        probe_note = QLabel(
            "测试仅发送 0.25 秒程序生成的静音和“你好”，也可能产生少量费用；不会收音。"
        )
        probe_note.setWordWrap(True)
        probe_note.setObjectName("muted")
        form.addRow(probe_note)
        self.feedback = QLabel("密钥默认仅用于本次运行；取消设置不会保存改动。")
        self.feedback.setWordWrap(True)
        form.addRow(self.feedback)
        self.clear_button = QPushButton("清除密钥并关闭联网（保存后生效）")
        self.clear_button.clicked.connect(self.clear_key)
        form.addRow(self.clear_button)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(50)

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
                    "可取消勾选“使用当前 Windows 账户加密记住密钥”，再点 Save，"
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
