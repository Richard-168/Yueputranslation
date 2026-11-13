"""Score meanings and edit directions without models or private lyrics."""

import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "experiments/offline-poc/song_metrics.py"
spec = importlib.util.spec_from_file_location("song_metrics", path)
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)


class SongMetricsTests(unittest.TestCase):
    def test_substitutions_deletions_and_insertions_have_correct_direction(self):
        for hypothesis, field in [
            ("甲错丙", "substitutions"),
            ("甲丙", "deletions"),
            ("甲乙多丙", "insertions"),
        ]:
            with self.subTest(field=field):
                result = metrics.character_errors("甲乙丙", hypothesis)
                self.assertEqual(result[field], 1)
                self.assertEqual(result["distance"], 1)
                self.assertAlmostEqual(result["cer"], 1 / 3)

    def test_repeating_a_phrase_is_not_silently_removed(self):
        result = metrics.character_errors("甲乙", "甲乙甲乙")
        self.assertEqual(result["insertions"], 2)
        self.assertEqual(result["cer"], 1)

    def test_punctuation_and_spaces_are_optional_but_words_are_not_rewritten(self):
        self.assertEqual(metrics.normalize("甲，乙。\n 丙！"), "甲乙丙")
        self.assertEqual(
            metrics.character_errors("甲乙丙", metrics.normalize("甲，乙。丙！"))["cer"], 0
        )
        self.assertEqual(metrics.character_errors("忧", "幽")["substitutions"], 1)

    def test_empty_hypothesis_counts_as_deletions(self):
        result = metrics.character_errors("甲乙丙", "")
        self.assertEqual(result["deletions"], 3)
        self.assertEqual(result["cer"], 1)

    def test_empty_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            metrics.character_errors("", "甲")


if __name__ == "__main__":
    unittest.main()
