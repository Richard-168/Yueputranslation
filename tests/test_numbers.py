import unittest

from yuepu_translate.numbers import spoken_numbers


class NumberTests(unittest.TestCase):
    def test_identifiers_keep_leading_zeroes_and_digit_order(self):
        text = "编号是0076，不是0760。"
        spoken, edits = spoken_numbers(text, "identifier")
        self.assertEqual(spoken, "编号是零零七六，不是零七六零。")
        self.assertEqual([e["recovered"] for e in edits], ["0076", "0760"])
        self.assertEqual(text, "编号是0076，不是0760。")

    def test_amounts_preserve_decimal_value(self):
        spoken, edits = spoken_numbers("一共105.05元，不是150.50元。", "amount")
        self.assertIn("一百零五点零五", spoken)
        self.assertEqual([e["recovered"] for e in edits], ["105.05", "150.50"])

    def test_ambiguous_modes_and_decimal_identifiers_are_rejected(self):
        with self.assertRaises(ValueError):
            spoken_numbers("金额42.5", "automatic")
        with self.assertRaises(ValueError):
            spoken_numbers("编号42.5", "identifier")


if __name__ == "__main__":
    unittest.main()
