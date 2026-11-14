"""Synthetic provider/credential contracts. No cloud account or uploaded recording."""

import io
import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock

from yuepu_translate.cloud_config import CloudConfig, load_settings, save_settings
from yuepu_translate.cloud_protocol import CloudError, payload, response_text
from yuepu_translate.cloud_worker import perform

KEY = "synthetic-test-key-only"


class CloudProtocolTests(unittest.TestCase):
    def test_only_provider_hosts_can_be_built_and_key_is_not_in_repr(self):
        config = CloudConfig(KEY, workspace="12345")
        self.assertEqual(
            config.endpoint,
            "https://12345.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
        )
        self.assertNotIn(KEY, repr(config))
        for workspace in ["evil.com/x", "a@evil.com", "../x", "a\nheader", "x:443", "a_ignored"]:
            with self.assertRaises(ValueError):
                CloudConfig(KEY, workspace=workspace).validate()
        with self.assertRaises(ValueError):
            CloudConfig("key\nAuthorization: leak").validate()

    def test_translation_uses_selected_dialect_and_preserves_mixed_input(self):
        for source, language, target, text in [
            ("zh", "Chinese", "Cantonese", "test 2038，不是2308，你们不要昧着良心说话。"),
            ("yue", "Cantonese", "Chinese", "test 2038，唔系2308，你哋唔好撑住个心口讲。"),
        ]:
            body = payload("translation", source, text)
            self.assertEqual(body["translation_options"]["source_lang"], language)
            self.assertEqual(body["translation_options"]["target_lang"], target)
            self.assertEqual(body["messages"], [dict(role="user", content=text)])
        for text in ["", "x" * 241]:
            with self.assertRaises(ValueError):
                payload("translation", "yue", text)

    def test_asr_language_is_fixed_and_audio_is_in_memory_data_uri(self):
        import base64

        out = io.BytesIO()
        with wave.open(out, "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes(bytes(320))
        encoded = base64.b64encode(out.getvalue()).decode()
        body = payload("asr", "yue", encoded)
        self.assertEqual(body["asr_options"], dict(language="yue", enable_itn=False))
        self.assertTrue(
            body["messages"][0]["content"][0]["input_audio"]["data"].startswith(
                "data:audio/wav;base64,"
            )
        )
        with self.assertRaises(ValueError):
            payload("asr", "yue", "https://untrusted/audio.wav")

    def test_truncated_and_malformed_results_never_become_confirmed_text(self):
        for value in [
            {},
            {"choices": []},
            {"choices": [{"finish_reason": "length", "message": {"content": "部分"}}]},
        ]:
            with self.assertRaises(CloudError):
                response_text(json.dumps(value).encode(), "translation")
        with self.assertRaises(CloudError):
            response_text(b"x" * 65537, "asr")

    def test_unchecking_remember_removes_saved_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cloud.json"
            path.write_text("old encrypted config")
            save_settings(CloudConfig(), False, path)
            self.assertFalse(path.exists())
            self.assertEqual(load_settings(path), (CloudConfig(), False))

    @unittest.skipUnless(os.name == "nt", "Windows current-user DPAPI")
    def test_remembered_key_is_encrypted_and_never_persists_upload_consent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cloud.json"
            config = CloudConfig(KEY, "singapore", "12345", 6)
            save_settings(config, True, path)
            stored = path.read_text()
            self.assertNotIn(KEY, stored)
            self.assertNotIn("enabled", stored)
            self.assertEqual(load_settings(path), (config, True))

    def test_http_error_never_exposes_provider_body_or_key(self):
        import urllib.error

        raw = json.dumps(
            dict(config=dict(api_key=KEY), operation="translation", source="yue", content="你好")
        ).encode()
        for status, code in [(401, "auth"), (429, "quota"), (503, "server")]:
            opener = Mock()
            opener.open.side_effect = urllib.error.HTTPError(
                "https://example", status, "secret " + KEY, {}, io.BytesIO(KEY.encode())
            )
            with self.assertRaises(CloudError) as raised:
                perform(raw, opener)
            self.assertEqual(raised.exception.code, code)
            self.assertNotIn(KEY, str(raised.exception))

    def test_malformed_response_list_is_safe(self):
        with self.assertRaises(CloudError):
            response_text(b"[]", "translation")

    def test_wrong_choice_type_is_a_sanitized_provider_error(self):
        with self.assertRaises(CloudError):
            response_text(b'{"choices":[123]}', "translation")

    def test_cloud_invalid_json_is_reported_without_exception_body(self):
        raw = json.dumps(
            dict(config=dict(api_key=KEY), operation="translation", source="yue", content="你好")
        ).encode()
        response = io.BytesIO(b"{ invalid-json secret: " + KEY.encode())
        opener = Mock()
        opener.open.return_value = response
        with self.assertRaises(CloudError):
            perform(raw, opener)

    def test_redirect_is_not_followed(self):
        from yuepu_translate.cloud_worker import NoRedirect

        with self.assertRaises(CloudError):
            NoRedirect().redirect_request(None, None, 307, "redirect", {}, "https://elsewhere.test")


if __name__ == "__main__":
    unittest.main()
