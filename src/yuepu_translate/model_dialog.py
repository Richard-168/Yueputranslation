"""Qt model manager. The worker process owns all network and disk transfers."""

import json
import os
import sys

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .model_assets import GROUPS, assets, format_size, model_path, partial_path, ready
from .paths import DATA_DIR


class ModelDialog(QDialog):
    def __init__(self, parent, group="base", intro="", before_delete=None):
        super().__init__(parent)
        self.setWindowTitle("模型管理")
        self.setMinimumWidth(500)
        self.before_delete = before_delete
        self.bundled = os.environ.get("YUEPU_BUNDLED_DATA_DIR") == str(DATA_DIR)
        self.cancelled = False
        self.message = ""
        layout = QVBoxLayout(self)
        description = QLabel(
            intro or "基础模型用于本地识别、翻译和播报。pro 复核和人声分离可按需安装。"
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.groups = QComboBox()
        self.groups.setAccessibleName("模型组")
        for key, (title, folders) in GROUPS.items():
            size = sum(asset.size for asset in assets(folders))
            self.groups.addItem(f"{title} · {format_size(size)}", key)
        self.groups.setCurrentIndex(self.groups.findData(group))
        self.groups.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.groups)
        location = QLabel(f"模型目录：{DATA_DIR / 'models'}")
        location.setWordWrap(True)
        location.setTextFormat(Qt.PlainText)
        location.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(location)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.progress = QProgressBar()
        self.progress.setAccessibleName("模型传输进度")
        self.progress.setRange(0, 100)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.download_button = QPushButton("下载或修复")
        self.download_button.clicked.connect(self.download)
        self.import_button = QPushButton("导入离线包…")
        self.import_button.clicked.connect(self.import_zip)
        self.delete_button = QPushButton("删除…")
        self.delete_button.clicked.connect(self.delete)
        self.close_button = QPushButton("关闭")
        self.close_button.clicked.connect(self.reject)
        for button in (self.download_button, self.import_button, self.delete_button):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self.worker = QProcess(self)
        self.worker.readyReadStandardOutput.connect(self.read_progress)
        self.worker.finished.connect(self.worker_finished)
        self.worker.errorOccurred.connect(self.process_error)
        self.refresh()

    def group(self):
        return GROUPS[self.groups.currentData()]

    def refresh(self):
        _, folders = self.group()
        if self.bundled:
            self.summary.setText("随完整安装包提供，由 Windows 安装程序管理。")
        else:
            self.summary.setText("已就绪" if ready(folders) else "未安装或缺少文件")
        self.status.clear()
        self.progress.hide()
        try:
            files = [(model_path(DATA_DIR, asset), asset) for asset in assets(folders)]
            can_delete = any(
                path.exists() or partial_path(path, asset).exists() for path, asset in files
            )
        except (OSError, ValueError):
            can_delete = False
        self.download_button.setEnabled(not self.bundled)
        self.import_button.setEnabled(not self.bundled)
        self.delete_button.setEnabled(not self.bundled and can_delete)
        self.groups.setEnabled(True)
        self.close_button.setText("关闭")

    def download(self):
        title, folders = self.group()
        size = format_size(sum(asset.size for asset in assets(folders)))
        if (
            QMessageBox.question(
                self,
                "下载模型",
                f"从 Hugging Face 或 GitHub 下载「{title}」，总大小 {size}。"
                "\n已校验的文件会复用，中断后可点击「下载或修复」重试。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            == QMessageBox.Yes
        ):
            self.start("download")

    def import_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择离线模型包", "", "模型包 (*.zip)")
        if path:
            self.start("import", path)

    def delete(self):
        if (
            QMessageBox.question(
                self,
                "删除模型",
                f"删除「{self.group()[0]}」及未完成的下载？需要时可以重新安装。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        ):
            if self.before_delete is not None:
                self.before_delete()
            self.start("delete")

    def start(self, action, *args):
        self.cancelled = False
        self.message = ""
        self.progress.setValue(0)
        self.progress.show()
        self.status.setText("正在准备…")
        self.groups.setEnabled(False)
        self.download_button.setEnabled(False)
        self.import_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.close_button.setText("停止" if action != "delete" else "请稍候")
        self.close_button.setEnabled(action != "delete")
        self.worker.start(
            sys.executable,
            ["-B", "-m", "yuepu_translate.model_worker", action, self.groups.currentData(), *args],
        )

    def read_progress(self):
        while self.worker.canReadLine():
            try:
                update = json.loads(bytes(self.worker.readLine()))
            except ValueError:
                continue
            self.message = update["message"]
            self.status.setText(self.message)
            if update["total"]:
                self.progress.setValue(int(100 * update["done"] / update["total"]))

    def worker_finished(self, code, exit_status):
        self.read_progress()
        self.refresh()
        self.close_button.setEnabled(True)
        if self.cancelled:
            self.status.setText("已停止。重试下载时会复用可续传的数据。")
        elif code or exit_status != QProcess.NormalExit:
            self.status.setText(
                self.message if self.message.startswith("操作未完成") else "操作未完成，请重试。"
            )
        else:
            self.status.setText(self.message or "操作已完成。")

    def process_error(self, error):
        if error == QProcess.FailedToStart:
            self.refresh()
            self.close_button.setEnabled(True)
            self.status.setText("无法启动模型工具，请检查程序安装。")

    def reject(self):
        if self.worker.state() != QProcess.NotRunning:
            if self.close_button.isEnabled():
                self.cancelled = True
                self.worker.kill()
            return
        super().reject()
