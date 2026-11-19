"""Desktop model ownership without opening audio devices or loading native weights."""

import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from yuepu_translate import model_runtime
from yuepu_translate.cloud_config import CloudConfig
from yuepu_translate.cloud_protocol import CloudError
from yuepu_translate.desktop_engine import Cancelled, Engine, Request
from yuepu_translate.enhanced_inference import SessionInference
from yuepu_translate.inference_control import InferenceCancelled
from yuepu_translate.live_session import LiveSession
from yuepu_translate.local_inference import COMPLETION, LocalInference, LoopbackDenied
from yuepu_translate.song_stream import SongWindow


class DirectTranslationTests(unittest.TestCase):
    def test_cancel_reaps_direct_process_and_removes_prompt(self):
        service = LocalInference("translation")
        service.using_completion = True
        token = threading.Event()
        launched = threading.Event()
        children = []
        failures = []
        popen = subprocess.Popen

        def launch(command, **options):
            prompt_file = Path(command[command.index("-f") + 1])
            self.assertIn("测试短句", prompt_file.read_text(encoding="utf-8"))
            self.assertNotIn("测试短句", " ".join(command))
            child = popen([sys.executable, "-c", "import time; time.sleep(40)"], **options)
            children.append(child)
            launched.set()
            return child

        def generate():
            try:
                service.translate("测试短句", token, source="zh")
            except Exception as exc:
                failures.append(exc)

        with (
            tempfile.TemporaryDirectory() as cache,
            patch("yuepu_translate.local_inference.cache_directory", return_value=Path(cache)),
            patch("yuepu_translate.local_inference.subprocess.Popen", side_effect=launch),
        ):
            worker = threading.Thread(target=generate)
            worker.start()
            try:
                self.assertTrue(launched.wait(5))
            finally:
                token.set()
                worker.join(5)
                service.close()
            self.assertFalse(worker.is_alive())
            self.assertIsNotNone(children[0].poll())
            self.assertEqual(list(Path(cache).iterdir()), [])
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], InferenceCancelled)


class ModelLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.cancel = threading.Event()
        self.engine = Engine()
        self.addCleanup(self.engine.close)
        self.children = []
        self.prompts = []
        self.block_request = False
        self.request_started = threading.Event()
        self.enterContext(patch.object(LocalInference, "check_files"))
        self.enterContext(
            patch("yuepu_translate.local_inference.subprocess.Popen", side_effect=self.launch)
        )
        socket = self.enterContext(patch("yuepu_translate.local_inference.socket.socket"))
        socket.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 12345)
        self.engine.translator.opener = Mock()
        self.engine.translator.opener.open.side_effect = self.respond

    def launch(self, command, **kwargs):
        child = Mock()
        child.poll.return_value = None
        child.terminated = threading.Event()

        def terminate():
            child.poll.return_value = 0
            child.terminated.set()

        child.terminate.side_effect = terminate
        self.children.append(child)
        return child

    def respond(self, request, **kwargs):
        if isinstance(request, str):
            response = io.BytesIO()
            response.status = 200
            return response
        payload = json.loads(request.data)
        self.prompts.append(payload["prompt"])
        self.assertFalse(payload["cache_prompt"])
        if self.block_request:
            self.request_started.set()
            if not self.children[-1].terminated.wait(2):
                raise TimeoutError("Canceled requests must release the local server")
            raise ConnectionResetError()
        return io.BytesIO(b'{"content":"translated"}')

    def test_text_then_live_sessions_and_reverse_direction_share_one_server(self):
        self.engine.process(
            Request(0, "text", "yue", text="你好", autoplay=False),
            self.cancel,
            None,
            lambda *args: None,
        )
        for source in ("zh", "yue"):
            session = SessionInference(
                source, None, lambda *args: None, roles=("translation",), engine=self.engine
            )
            session.start(self.cancel)
            self.assertEqual(session.translate("你好", self.cancel), "translated")
            session.close()
        self.assertEqual(len(self.children), 1)
        self.assertIsNone(self.children[0].poll())
        self.assertEqual(len(self.prompts), 3)
        for prompt, target in zip(self.prompts, ("中文", "粤语", "中文"), strict=True):
            self.assertIn(f"为{target}", prompt)
        self.assertIsNone(self.engine.asr)
        self.assertIsNone(self.engine.zh_tts)
        self.assertIsNone(self.engine.yue_tts)
        self.engine.close()
        self.assertTrue(self.children[0].terminated.is_set())

    def test_cancel_during_request_reaps_child_and_next_task_can_restart(self):
        self.block_request = True
        errors = []

        def translate():
            try:
                self.engine.translate("测试", "yue", self.cancel)
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=translate)
        thread.start()
        try:
            self.assertTrue(self.request_started.wait(2))
        finally:
            self.cancel.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], Cancelled)
        self.assertTrue(self.children[0].terminated.is_set())
        self.block_request = False
        self.cancel.clear()
        self.assertEqual(self.engine.translate("再试", "zh", self.cancel), "translated")
        self.assertEqual(len(self.children), 2)

    def test_local_permission_denial_uses_completion_once_per_request_without_retrying_health(self):
        denied = urllib.error.URLError(PermissionError(13, "access denied"))
        translator = self.engine.translator
        translator.opener.open.side_effect = denied
        with (
            patch.object(
                Path,
                "is_file",
                autospec=True,
                side_effect=lambda p: p.name == Path(COMPLETION).name,
            ),
            patch.object(translator, "_complete_without_socket", return_value="译文") as direct,
        ):
            self.assertEqual(translator.translate("你好", self.cancel, source="zh"), "译文")
            self.assertEqual(translator.translate("多謝", self.cancel, source="yue"), "译文")
        self.assertTrue(translator.using_completion)
        self.assertEqual(direct.call_count, 2)
        self.assertEqual(translator.opener.open.call_count, 1)
        self.assertTrue(self.children[0].terminated.is_set())

    def test_denied_review_connection_is_reported_before_the_loading_deadline(self):
        reviewer = LocalInference("asr")
        self.addCleanup(reviewer.close)
        reviewer.opener = Mock()
        reviewer.opener.open.side_effect = urllib.error.URLError(
            PermissionError(13, "access denied")
        )
        with self.assertRaisesRegex(LoopbackDenied, "127.0.0.1"):
            reviewer.start(self.cancel)
        self.assertEqual(reviewer.opener.open.call_count, 1)
        self.assertTrue(self.children[0].terminated.is_set())

    def test_loading_http_status_can_be_followed_by_success(self):
        translator = self.engine.translator
        loading = urllib.error.HTTPError(
            "http://127.0.0.1/health", 503, "loading", {}, io.BytesIO()
        )
        ready = io.BytesIO()
        ready.status = 200
        translator.opener.open.side_effect = [loading, ready]
        translator.start(self.cancel)
        self.assertEqual(translator.opener.open.call_count, 2)
        self.assertFalse(translator.using_completion)

    def test_cloud_preflight_starts_no_models_and_fallback_reuses_local_server(self):
        session = SessionInference(
            "zh",
            CloudConfig("test-only"),
            lambda *args: None,
            roles=("translation",),
            engine=self.engine,
        )
        self.addCleanup(session.close)
        session.start(self.cancel)
        session.cloud.translate = Mock(side_effect=["在线", CloudError("quota")])
        self.assertEqual(session.translate("测试", self.cancel), "在线")
        self.assertFalse(self.children)
        self.assertEqual(session.translate("继续", self.cancel), "translated")
        self.assertEqual(session.translate("再次", self.cancel), "translated")
        self.assertEqual(session.cloud.translate.call_count, 2)
        self.assertEqual(len(self.children), 1)
        self.assertIn("为粤语", self.prompts[-1])

    def test_recognition_and_each_voice_load_only_on_first_use(self):
        with (
            patch.object(model_runtime, "recognizer") as recognizer,
            patch.object(model_runtime, "mandarin_engine") as mandarin,
            patch.object(model_runtime, "canto_engine") as cantonese,
        ):
            self.engine.prepare_recognition(self.cancel)
            self.engine.prepare_recognition(self.cancel)
            recognizer.assert_called_once()
            mandarin.assert_not_called()
            cantonese.assert_not_called()
            self.engine.prepare_voice("yue", self.cancel)
            self.engine.prepare_voice("yue", self.cancel)
            cantonese.assert_called_once()
            mandarin.assert_not_called()
        self.assertFalse(self.children)

    def test_automatic_voice_failure_keeps_short_translation_and_manual_replay_reports_error(self):
        events = []
        self.engine.speak = Mock(side_effect=RuntimeError("voice unavailable"))
        self.engine.process(
            Request(1, "text", text="你好", autoplay=True),
            self.cancel,
            None,
            lambda kind, value: events.append(kind),
        )
        self.assertLess(events.index("translation"), events.index("speech_warning"))
        self.assertFalse(self.cancel.is_set())
        with self.assertRaisesRegex(RuntimeError, "voice unavailable"):
            self.engine.process(
                Request(1, "speak", text="你好"), self.cancel, None, lambda *_: None
            )
        self.engine.speak.side_effect = Cancelled()
        with self.assertRaises(Cancelled):
            self.engine.process(Request(2, "text", text="你好"), self.cancel, None, lambda *_: None)

    def test_failed_live_autoplay_warns_once_and_later_finals_still_complete(self):
        events = []
        self.engine.converters = {"zh": SimpleNamespace(convert=lambda text: text)}
        self.engine.recognize = Mock(return_value="今天天气很好")
        self.engine.prepare_voice = Mock()
        self.engine.speak = Mock(side_effect=RuntimeError("voice unavailable"))
        session = LiveSession("yue", autoplay=True)
        for block in (0, 1):
            now = time.monotonic()
            samples = np.ones(16000, dtype=np.float32)
            session.mailbox.put(SongWindow(block, 0, len(samples), samples, True, now, now))
        session.mailbox.finish()
        session.run(
            self.engine, None, self.cancel, lambda kind, value: events.append((kind, value))
        )
        self.engine.speak.assert_called_once()
        self.assertEqual([k for k, _ in events].count("speech_warning"), 1)
        self.assertEqual(
            [v["block"] for k, v in events if k == "live_translation" and v["final"]], [0, 1]
        )
        self.assertFalse(self.cancel.is_set())
