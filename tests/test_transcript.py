"""Characterize retention and pairing independently of any speech model."""

import unittest

from PySide6.QtCore import Qt

from yuepu_translate.transcript_model import TranscriptEntry, TranscriptModel


class TranscriptTests(unittest.TestCase):
    def test_confirmed_spans_are_validated_atomically_and_are_accessible(self):
        model = TranscriptModel()
        model.append(
            TranscriptEntry(1, "yue", "zh", source="固定前文暂定末尾", target="固定译文草稿")
        )
        model.update_entry(1, source_confirmed=4, target_confirmed=4)
        self.assertIn(
            "已固定原文 4 字、译文 4 字", model.data(model.index(0), Qt.AccessibleTextRole)
        )
        before = model.characters
        for fields in (
            dict(source_confirmed=100),
            dict(target_confirmed=-1),
            dict(target="小", target_confirmed=4),
        ):
            with self.assertRaises(ValueError):
                model.update_entry(1, **fields)
        self.assertEqual(model.characters, before)
        self.assertEqual(model.items[0].target, "固定译文草稿")

    def test_row_notifications_stay_correct_after_pruning_and_clear(self):
        model, changed = TranscriptModel(max_rows=2), []
        model.dataChanged.connect(lambda first, last: changed.append(first.row()))
        for key in range(4):
            model.append(TranscriptEntry(key, "yue", "zh", source="原文"))
        model.update_entry(2, target="倒数第二条")
        model.update_entry(3, target="最后一条")
        self.assertEqual(changed, [0, 1])
        model.clear()
        model.append(TranscriptEntry(10, "zh", "yue"))
        model.update_entry(10, source="新的内容")
        self.assertEqual(changed[-1], 0)

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
            TranscriptEntry(
                1, "yue", "zh", source="測試", target="测试", status="已翻译", timestamp="12:34:56"
            )
        )
        model.append(TranscriptEntry(2, "zh", "yue", source="停止", status="已取消"))
        exported = model.export_text()
        self.assertIn("[12:34:56] 粤语 → 普通话", exported)
        self.assertIn("原文：測試\n译文：测试", exported)
        self.assertIn("[已取消]", exported)
        model.clear()
        self.assertEqual(model.export_text(), "")

    def test_old_unversioned_partial_keeps_only_confirmed_prefix_in_paired_translation(self):
        model = TranscriptModel()
        model.append(
            TranscriptEntry(
                1,
                "yue",
                "zh",
                source="新原文",
                target="前文旧尾",
                target_confirmed=2,
                status="末尾更新中",
            )
        )
        text = model.export_text()
        self.assertIn("译文：前文 [仅已固定前文]", text)
        self.assertIn("此前的译文草稿（与本版原文未核对）：前文旧尾", text)
        self.assertIn("状态：末尾更新中", text)


if __name__ == "__main__":
    unittest.main()
