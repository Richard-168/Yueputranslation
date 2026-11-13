"""Characterize retention and pairing independently of any speech model."""

import unittest

from yuepu_translate.transcript_model import TranscriptEntry, TranscriptModel


class TranscriptTests(unittest.TestCase):
    def test_late_result_does_not_overwrite_another_row(self):
        model = TranscriptModel(max_rows=2)
        for key in range(3):
            model.append(TranscriptEntry(key, "yue", "zh", source=f"句子{key}"))
        self.assertFalse(model.update_entry(0, target="迟到的结果"))
        self.assertTrue(model.update_entry(1, target="对应译文"))
        self.assertEqual([e.key for e in model.items], [1, 2])
        self.assertEqual(model.items[0].target, "对应译文")
        self.assertEqual(model.items[1].target, "")

    def test_character_cap_counts_source_and_translation(self):
        model = TranscriptModel(max_rows=10, max_chars=8)
        model.append(TranscriptEntry(1, "yue", "zh", source="1234"))
        model.append(TranscriptEntry(2, "zh", "yue", source="56"))
        model.update_entry(2, target="7890")
        self.assertEqual([e.key for e in model.items], [2])
        self.assertEqual(model.characters, 6)
        with self.assertRaises(ValueError):
            model.update_entry(2, target="x" * 20)
        self.assertEqual(model.items[0].target, "7890")
        self.assertEqual(model.characters, 6)

    def test_default_limits_keep_long_session(self):
        model = TranscriptModel()
        for key in range(10001):
            model.append(TranscriptEntry(key, "yue", "zh", source="甲", target="乙"))
        self.assertEqual(len(model.items), 10000)
        self.assertEqual(model.items[0].key, 1)
        self.assertEqual(model.evicted, 1)
        model.clear()
        model.append(TranscriptEntry(1, "yue", "zh", source="甲" * 1999999))
        model.append(TranscriptEntry(2, "zh", "yue", source="丙"))
        model.update_entry(2, target="丁")
        self.assertEqual([e.key for e in model.items], [2])

    def test_export_retains_direction_and_incomplete_status(self):
        model = TranscriptModel()
        model.append(
            TranscriptEntry(1, "yue", "zh", source="測試", target="测试", timestamp="12:34:56")
        )
        model.append(TranscriptEntry(2, "zh", "yue", source="停止", status="已取消"))
        exported = model.export_text()
        self.assertIn("[12:34:56] 粤语 → 普通话", exported)
        self.assertIn("原文：測試\n译文：测试", exported)
        self.assertIn("[已取消]", exported)
        model.clear()
        self.assertEqual(model.export_text(), "")


if __name__ == "__main__":
    unittest.main()
