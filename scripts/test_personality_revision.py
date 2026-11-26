import copy
import unittest

from scripts.personality_revision import stamp_feed_revision


class PersonalityRevisionTests(unittest.TestCase):
    def setUp(self):
        self.feed = {"version": 1, "id": "ada", "name": "Ada", "updatedAt": "2026-11-25",
                     "episodes": [{"guid": "one", "title": "Interview", "description": "A conversation"}]}

    def test_timestamps_existing_revision_and_json_key_order_do_not_change_revision(self):
        revision = stamp_feed_revision(self.feed)
        reordered = dict(reversed(list(self.feed.items())))
        reordered["updatedAt"] = "2026-11-26"
        reordered["revision"] = "previous-value"
        self.assertEqual(stamp_feed_revision(reordered), revision)

    def test_corrections_removals_and_metadata_changes_change_revision(self):
        original = stamp_feed_revision(self.feed)
        for field in ("title", "description"):
            changed = copy.deepcopy(self.feed)
            changed["episodes"][0][field] = "Corrected"
            self.assertNotEqual(stamp_feed_revision(changed), original)
        for key, value in (("episodes", []), ("name", "Ada Lovelace"), ("artwork_url", "https://example.com/new.png")):
            changed = {**self.feed, key: value}
            self.assertNotEqual(stamp_feed_revision(changed), original)

    def test_index_and_feed_match_without_listing_drafts(self):
        index = {"personalities": [{"id": "ada"}, {"id": "grace", "revision": "untouched"}]}
        revision = stamp_feed_revision(self.feed, index)
        self.assertEqual(index["personalities"][0]["revision"], revision)
        stamp_feed_revision({"id": "draft", "episodes": []}, index)
        self.assertEqual(len(index["personalities"]), 2)
        self.assertEqual(index["personalities"][1]["revision"], "untouched")
