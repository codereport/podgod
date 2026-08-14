import unittest

from scripts.publish_personality import approve_personality


class PublishPersonalityTests(unittest.TestCase):
    def test_approves_draft_and_persists_review_blocklist(self):
        config = {
            "personalities": [{
                "id": "jeff-dean",
                "name": "Jeff Dean",
                "review_pending": True,
                "feed_blocklist": ["old.example/feed"],
            }]
        }
        result = approve_personality(
            config,
            "jeff-dean",
            ["https://horror.example/rss", "old.example/feed"],
        )
        person = result["personalities"][0]
        self.assertNotIn("review_pending", person)
        self.assertEqual(
            person["feed_blocklist"],
            ["old.example/feed", "https://horror.example/rss"],
        )


if __name__ == "__main__":
    unittest.main()
