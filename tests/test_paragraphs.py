"""Synthetic text contracts, separate from real recognition-quality evidence."""

import unittest

from yuepu_translate.paragraphs import ParagraphRevision, accept_punctuation, overlap_cut


class ParagraphTests(unittest.TestCase):
    def test_punctuation_review_cannot_change_numbers_or_words(self):
        self.assertEqual(
            accept_punctuation("号码2038不是2308", "号码2038，不是2308。"), "号码2038，不是2308。"
        )
        self.assertEqual(accept_punctuation("号码2038", "号码2308。"), "号码2038。")
        self.assertEqual(accept_punctuation("英文ABC", "英文abc。"), "英文ABC。")

    def test_revisions_replace_a_single_record_and_stale_results_are_rejected(self):
        paragraph = ParagraphRevision()
        paragraph.update("今天去公园", 0, 1, 4)
        result = paragraph.update("今天去医院，不是公园。", 0, 2, 6)
        self.assertEqual(result.source, "今天去医院，不是公园。")
        self.assertIsNone(paragraph.update("过时的结果", 0, 1, 7))
        self.assertEqual(paragraph.source, result.source)

    def test_final_text_cannot_be_reopened_or_overwritten(self):
        paragraph = ParagraphRevision()
        final = paragraph.update("句末重新检查。", 0, 1, 8, final=True)
        self.assertEqual(final.frozen_delta, "句末重新检查。")
        self.assertEqual(final.tail, "")
        self.assertIsNone(paragraph.update("错误的迟到修订", 0, 2, 9))

    def test_long_stable_prefix_freezes_while_recent_tail_can_change(self):
        paragraph = ParagraphRevision()
        prefix = "前面的内容已经经过连续两次识别核对，较早的稳定内容可以逐步保留。"
        tail = "后面还有一段较长的内容正在讲话，需要继续检查具体字词和断句。"
        paragraph.update(prefix + tail, 0, 1, 14)
        self.assertEqual(paragraph.frozen, "")
        paragraph.update(prefix + tail, 0, 2, 22)
        frozen = paragraph.frozen
        self.assertTrue(frozen)
        changed = paragraph.update("错" + (prefix + tail)[1:-3] + "修订。", 0, 3, 24)
        self.assertTrue(changed.source.startswith(frozen))
        self.assertTrue(changed.source.endswith("修订。"))

    def test_audio_checkpoint_corrects_adjacent_context_without_new_paragraph(self):
        paragraph = ParagraphRevision()
        paragraph.update("前文，今天天气真的很好", 0, 1, 10)
        changed = paragraph.update("今天天气真的很热，我们出发。", 16000 * 4, 2, 16)
        self.assertEqual(changed.source, "前文，今天天气真的很热，我们出发。")
        later = paragraph.update("今天天气真的很热，我们现在出发。", 16000 * 4, 3, 18)
        self.assertEqual(later.source, "前文，今天天气真的很热，我们现在出发。")

    def test_same_phrase_later_in_the_text_is_not_globally_removed(self):
        before = "测试完成，接下来继续讲话。"
        incoming = "下一段测试完成。"
        self.assertEqual(overlap_cut(before, incoming), len(before))

    def test_exact_overlap_does_not_delete_the_words_before_it(self):
        paragraph = ParagraphRevision()
        paragraph.update("第一部分已经完成。现在开始处理新的请求。", 0, 1, 14)
        result = paragraph.update("现在开始处理新的请求，继续检查。", 16000 * 8, 2, 20)
        self.assertEqual(result.source, "第一部分已经完成。现在开始处理新的请求，继续检查。")


if __name__ == "__main__":
    unittest.main()
