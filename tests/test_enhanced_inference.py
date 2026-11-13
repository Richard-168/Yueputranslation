"""Fallback/state contracts; fake models are not recognition quality evidence."""

import threading
import unittest

from yuepu_translate.cloud_config import CloudConfig
from yuepu_translate.cloud_protocol import CloudError
from yuepu_translate.enhanced_inference import SessionInference
from yuepu_translate.inference_control import InferenceCancelled


class FakeLocal:
    def __init__(self, role, source, threads):
        self.calls = []

    def start(self, cancel):
        pass

    def transcribe(self, value, cancel):
        self.calls.append("asr")
        return "本地原文"

    def translate(self, value, cancel):
        self.calls.append("translation")
        return "本地译文"

    def punctuate(self, value, cancel):
        return value + "。"

    def stop(self):
        pass

    def close(self):
        pass


class EnhancedInferenceTests(unittest.TestCase):
    def make_stack(self):
        events = []
        stack = SessionInference(
            "yue",
            CloudConfig("synthetic-test-key"),
            lambda kind, value: events.append((kind, value)),
            FakeLocal,
        )
        return stack, events

    def test_provider_failure_latches_offline_and_never_retries_in_this_session(self):
        stack, events = self.make_stack()
        calls = []

        def failure(*args):
            calls.append("uploaded")
            raise CloudError("quota")

        stack.cloud.transcribe = failure
        self.assertEqual(stack.transcribe(None, threading.Event()), "本地原文")
        self.assertEqual(stack.transcribe(None, threading.Event()), "本地原文")
        self.assertEqual(stack.translate("需要翻译", threading.Event()), "本地译文")
        self.assertEqual(calls, ["uploaded"])
        self.assertEqual([v["mode"] for _, v in events], ["fallback"])

    def test_cancel_never_becomes_fallback_or_a_second_billable_request(self):
        stack, events = self.make_stack()

        def canceled(*args):
            raise InferenceCancelled()

        stack.cloud.translate = canceled
        with self.assertRaises(InferenceCancelled):
            stack.translate("测试", threading.Event())
        self.assertFalse(events)
        self.assertFalse(stack.local["translation"].calls)

    def test_unsupported_script_from_cloud_falls_back_before_display_or_translation(self):
        stack, events = self.make_stack()
        stack.cloud.transcribe = lambda *args: "テスト"
        self.assertEqual(stack.transcribe(None, threading.Event()), "本地原文")
        self.assertEqual(events[-1][1]["mode"], "fallback")
