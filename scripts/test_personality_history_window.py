import unittest

from scripts.personality_history_window import creation_history_window


class PersonalityHistoryWindowTests(unittest.TestCase):
    def test_older_jobs_default_to_one_year(self):
        self.assertEqual(creation_history_window({}), "365d")

    def test_converts_requested_years_to_discovery_days(self):
        self.assertEqual(creation_history_window({"yearsBack": 5}), "1825d")
        self.assertEqual(creation_history_window({"yearsBack": 20}), "7300d")

    def test_rejects_invalid_years(self):
        for years in (0, -1, 21, 1.5, True, "5", None, "1; exit 0"):
            with self.subTest(years=years), self.assertRaises(ValueError):
                creation_history_window({"yearsBack": years})


if __name__ == "__main__":
    unittest.main()
