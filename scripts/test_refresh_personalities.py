import unittest

from scripts.refresh_personalities import context_allowed


class CommonNameContextTests(unittest.TestCase):
    def test_requires_identifying_keyword_for_common_names(self):
        person = {
            "potentially_common_name": True,
            "required_context_keywords": ["Google", "machine learning"],
        }
        self.assertTrue(context_allowed(
            {"title": "Jeff Dean interview", "description": "A conversation about Google AI."},
            person,
        ))
        self.assertFalse(context_allowed(
            {"title": "Jeff Dean joins us", "description": "Portland horror and VHS."},
            person,
        ))

    def test_does_not_filter_unmarked_names(self):
        self.assertTrue(context_allowed(
            {"title": "Any episode", "description": ""},
            {"required_context_keywords": []},
        ))


if __name__ == "__main__":
    unittest.main()
