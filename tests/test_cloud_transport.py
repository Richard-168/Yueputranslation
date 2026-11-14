"""Actual child/HTTP integration against a loopback provider emulator, never cloud."""

import json
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import numpy as np

from yuepu_translate.cloud_client import CloudClient
from yuepu_translate.cloud_config import CloudConfig
from yuepu_translate.cloud_protocol import CloudError
from yuepu_translate.inference_control import InferenceCancelled

# Only the lowest HTTP transport is remapped in the test child. Production CLI,
# pipe input, validation, payload, response parsing and process lifetime all run.
EMULATED_CHILD = r"""
import sys, urllib.request
from yuepu_translate import cloud_worker as worker
original = worker.perform
class Loopback:
    def open(self, request, timeout):
        assert request.full_url.startswith("https://dashscope.aliyuncs.com/")
        mapped = urllib.request.Request("http://127.0.0.1:" + sys.argv[1], data=request.data, headers=dict(request.header_items()), method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), worker.NoRedirect())
        return opener.open(mapped, timeout=timeout)
worker.perform = lambda raw: original(raw, Loopback())
worker.main()
"""


class CloudTransportTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.status = 200
        self.invalid = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.calls.append(body)
                text = "测试原文" if body["model"] == "qwen3-asr-flash" else "测试译文"
                response = (
                    b"invalid-json"
                    if owner.invalid
                    else json.dumps(
                        dict(choices=[dict(finish_reason="stop", message=dict(content=text))])
                    ).encode()
                )
                self.send_response(owner.status)
                if owner.status == 307:
                    self.send_header("Location", "https://untrusted.test/key")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        original_popen = subprocess.Popen

        def start(command, **kwargs):
            if command[1:3] != ["-m", "yuepu_translate.cloud_worker"]:
                return original_popen(command, **kwargs)
            self.assertNotIn("synthetic-test-key", str(command))
            return original_popen(
                [sys.executable, "-c", EMULATED_CHILD, str(self.server.server_port)], **kwargs
            )

        self.transport = patch("yuepu_translate.cloud_client.subprocess.Popen", start)
        self.transport.start()
        self.client = CloudClient(CloudConfig("synthetic-test-key", timeout=3), "yue")

    def tearDown(self):
        self.client.close()
        self.transport.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def test_real_pipe_and_http_round_trip_for_audio_and_text(self):
        cancel = threading.Event()
        self.assertEqual(self.client.transcribe(np.zeros(8000, np.float32), cancel), "测试原文")
        self.assertEqual(self.client.translate("待翻译文字2038", cancel), "测试译文")
        self.assertEqual(self.calls[0]["asr_options"]["language"], "yue")
        self.assertEqual(self.calls[1]["translation_options"]["source_lang"], "Cantonese")
        self.assertEqual(self.calls[1]["translation_options"]["target_lang"], "Chinese")
        self.assertEqual(self.client.requests, 2)
        self.assertIsNotNone(self.client.child.poll())

    def test_reverse_direction_reaches_http_with_explicit_source_language(self):
        self.client.source = "zh"
        text = "你们不要昧着良心说话，test 2038。"
        self.assertEqual(self.client.translate(text, threading.Event()), "测试译文")
        options = self.calls[0]["translation_options"]
        self.assertEqual(options["source_lang"], "Chinese")
        self.assertEqual(options["target_lang"], "Cantonese")
        self.assertEqual(self.calls[0]["messages"], [dict(role="user", content=text)])

    def test_actual_http_401_429_and_bad_json_are_not_retried(self):
        for status, invalid, code in [
            (401, False, "auth"),
            (429, False, "quota"),
            (200, True, "response"),
            (307, False, "redirect"),
        ]:
            self.status, self.invalid = status, invalid
            before = len(self.calls)
            with self.assertRaises(CloudError) as raised:
                self.client.translate("测试", threading.Event())
            self.assertEqual(raised.exception.code, code)
            self.assertEqual(len(self.calls), before + 1)
            self.assertIsNotNone(self.client.child.poll())
        self.assertEqual(self.client.text_characters, 8)

    def test_bad_audio_never_starts_request(self):
        with self.assertRaises(ValueError):
            self.client.transcribe(np.array([np.nan], np.float32), threading.Event())
        self.assertEqual(self.calls, [])
        self.assertEqual(self.client.requests, 0)


class CloudCancellationTests(unittest.TestCase):
    def test_cancel_still_works_when_helper_never_reads_large_input(self):
        original = subprocess.Popen

        def blocked(command, **kwargs):
            return original([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)

        cancel = threading.Event()
        client = CloudClient(CloudConfig("synthetic-test-key"), "zh")
        failures = []

        def run():
            try:
                client.transcribe(np.full(20000, 0.1, np.float32), cancel)
            except Exception as exc:
                failures.append(exc)

        with patch("yuepu_translate.cloud_client.subprocess.Popen", blocked):
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            time.sleep(0.2)
            cancel.set()
            thread.join(1.5)
            try:
                self.assertFalse(thread.is_alive(), "A full input pipe must not block cancellation")
                self.assertIsInstance(failures[0], InferenceCancelled)
            finally:
                client.close()
                thread.join(2)

    def test_cancel_kills_and_reaps_owned_helper(self):
        original = subprocess.Popen

        def blocked(command, **kwargs):
            return original(
                [sys.executable, "-c", "import sys,time; sys.stdin.buffer.read(); time.sleep(60)"],
                **kwargs,
            )

        cancel = threading.Event()
        timer = threading.Timer(0.2, cancel.set)
        timer.start()
        client = CloudClient(CloudConfig("synthetic-test-key"), "zh")
        started = time.monotonic()
        try:
            with patch("yuepu_translate.cloud_client.subprocess.Popen", blocked):
                with self.assertRaises(InferenceCancelled):
                    client.translate("取消测试", cancel)
            self.assertLess(time.monotonic() - started, 2)
            self.assertIsNotNone(client.child.poll())
        finally:
            timer.cancel()
            client.close()

    def test_timeout_reaps_helper_without_automatic_retry(self):
        original = subprocess.Popen
        calls = []

        def blocked(command, **kwargs):
            calls.append(command)
            return original(
                [sys.executable, "-c", "import sys,time; sys.stdin.buffer.read(); time.sleep(60)"],
                **kwargs,
            )

        client = CloudClient(CloudConfig("synthetic-test-key", timeout=3), "zh")
        with patch("yuepu_translate.cloud_client.subprocess.Popen", blocked):
            with self.assertRaises(CloudError) as raised:
                client.translate("超时测试", threading.Event())
        self.assertEqual(raised.exception.code, "timeout")
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(client.child.poll())
