"""Regression for the input method when the composer moves with its parent."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QInputMethodEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from yuepu_translate.composer_input import ComposerInput  # noqa: E402
from yuepu_translate.window_chrome import ChromeWindow  # noqa: E402


class ComposerInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_maximize_and_restore_keep_preedit_at_the_caret(self):
        window = ChromeWindow()
        self.addCleanup(window.close)
        window.resize(400, 320)
        host = QWidget()
        layout = QVBoxLayout(host)
        controls = window.caption_controls(host)
        layout.addWidget(controls)
        layout.addStretch(1)
        composer = QWidget()
        layout.addWidget(composer, 0, Qt.AlignHCenter)
        layout.addStretch(1)
        editor = ComposerInput(composer)
        editor.setFixedSize(260, 80)
        composer.setFixedSize(260, 80)
        window.setCentralWidget(host)
        window.show()
        window.activateWindow()
        editor.setFocus()
        QTest.qWait(60)
        self.assertIs(self.app.focusObject(), editor)
        self.app.sendEvent(editor, QInputMethodEvent("nihao", []))

        normal_position = editor.mapTo(window, QPoint())
        editor_geometry = editor.geometry()
        for maximized, change_state in ((True, window.showMaximized), (False, window.showNormal)):
            if window._maximize_button is None:
                change_state()
            else:
                QTest.mouseClick(window._maximize_button, Qt.LeftButton)
            QTest.qWait(60)
            self.assertEqual(window.isMaximized(), maximized)
            self.assertIs(self.app.focusObject(), editor)
            self.assertEqual(editor.geometry(), editor_geometry)
            position = editor.mapTo(window, QPoint())
            self.assertEqual(position != normal_position, maximized)
            cursor = QRectF(editor.inputMethodQuery(Qt.ImCursorRectangle))
            self.assertEqual(self.app.inputMethod().cursorRectangle(), cursor.translated(position))
            self.assertEqual(editor.document().begin().layout().preeditAreaText(), "nihao")

        commit = QInputMethodEvent()
        commit.setCommitString("你好")
        self.app.sendEvent(editor, commit)
        self.assertEqual(editor.toPlainText(), "你好")
