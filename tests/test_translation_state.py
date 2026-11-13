"""Fixed-prefix caching and bounded model inputs, independent of model quality."""

import unittest

from yuepu_translate.translation_state import IncrementalTranslation


class TranslationStateTests(unittest.TestCase):
    def test_fixed_prefix_is_translated_once_while_only_the_tail_changes(self):
        state, calls = IncrementalTranslation(), []

        def translate(text):
            calls.append(text)
            return "[" + text + "]"

        first = state.update("前文已经固定，", "末尾暂定", translate)
        fixed = state.target
        second = state.update("前文已经固定，", "末尾已经修改", translate)
        self.assertEqual(calls, ["前文已经固定，", "末尾暂定", "末尾已经修改"])
        self.assertTrue(first.startswith(fixed) and second.startswith(fixed))
        final = state.update("前文已经固定，末尾已经修改", "", translate)
        self.assertEqual(calls, ["前文已经固定，", "末尾暂定", "末尾已经修改"])
        self.assertEqual(final, state.target)
        self.assertEqual(final, "[前文已经固定，][末尾已经修改]")

    def test_coalesced_updates_translate_every_new_fixed_piece_without_resending_history(self):
        state, calls = IncrementalTranslation(), []

        def translate(text):
            calls.append(text)
            return text

        text = ""
        for i in range(80):
            addition = f"这是第{i}个新固定的片段。"
            text += addition
            self.assertEqual(state.update(text, "", translate), text)
        self.assertEqual(len(calls), 80)
        self.assertLess(max(map(len, calls)), 24)

    def test_large_new_delta_is_bounded_and_words_are_not_dropped(self):
        state, calls = IncrementalTranslation(), []

        def translate(text):
            calls.append(text)
            return text

        text = "这是一段超过模型单次输入限制的新内容，" * 40
        self.assertEqual(state.update(text, "", translate), text)
        self.assertTrue(all(0 < len(part) <= 96 for part in calls))
        self.assertEqual("".join(calls), text)

    def test_throttled_preview_keeps_its_previous_text_until_replacement_arrives(self):
        state, calls = IncrementalTranslation(), []

        def translate(text):
            calls.append(text)
            return text

        state.update("已固定的前文", "旧的暂定文字", translate)
        target = state.update("已固定的前文", "新的暂定文字", translate, preview=False)
        self.assertEqual(target, "已固定的前文旧的暂定文字")
        self.assertEqual(calls, ["已固定的前文", "旧的暂定文字"])
        self.assertNotEqual(state.preview_source, "新的暂定文字")

    def test_fixed_prefix_cannot_be_rewritten_by_a_later_job(self):
        state = IncrementalTranslation()
        state.update("原来的固定前文", "", lambda text: text)
        with self.assertRaises(ValueError):
            state.update("改写后的固定前文", "", lambda text: text)
        self.assertEqual(state.target, "原来的固定前文")
