import copy
import unittest

from scripts.update_personality_title import update_title, validate_metadata


class UpdatePersonalityTitleTests(unittest.TestCase):
    def test_updates_config_index_and_feed(self):
        config = {"personalities": [{"id": "mark-zuckerberg", "title": "Old"}]}
        index = {"personalities": [{"id": "mark-zuckerberg", "title": "Old"}]}
        feed = {"id": "mark-zuckerberg", "title": "Old", "episodes": [{"guid": "1"}]}

        update_title(
            config,
            index,
            feed,
            {"id": "mark-zuckerberg", "title": "CEO of Meta"},
        )

        self.assertEqual(config["personalities"][0]["title"], "CEO of Meta")
        self.assertEqual(index["personalities"][0]["title"], "CEO of Meta")
        self.assertEqual(feed["title"], "CEO of Meta")
        self.assertEqual(feed["episodes"], [{"guid": "1"}])

    def test_missing_personality_does_not_partially_update(self):
        config = {"personalities": [{"id": "someone-else", "title": "Original"}]}
        index = {"personalities": [{"id": "mark-zuckerberg", "title": "Original"}]}
        feed = {"id": "mark-zuckerberg", "title": "Original", "episodes": []}
        before = copy.deepcopy((config, index, feed))

        with self.assertRaisesRegex(ValueError, "was not found"):
            update_title(
                config,
                index,
                feed,
                {"id": "mark-zuckerberg", "title": "CEO of Meta"},
            )

        self.assertEqual((config, index, feed), before)

    def test_validates_and_normalizes_metadata(self):
        self.assertEqual(
            validate_metadata({"id": "mark-zuckerberg", "title": "  CEO   of Meta "}),
            {"id": "mark-zuckerberg", "title": "CEO of Meta"},
        )
        with self.assertRaisesRegex(ValueError, "lowercase URL slug"):
            validate_metadata({"id": "Mark Zuckerberg", "title": "CEO of Meta"})


if __name__ == "__main__":
    unittest.main()
