import copy
import unittest

from scripts.edit_personality import edit_personality, validate_metadata


class EditPersonalityTests(unittest.TestCase):
    def test_edits_a_published_profile_and_preserves_existing_feed_details(self):
        config = {"personalities": [{
            "id": "conor-shakory",
            "name": "Conor Shakory",
            "aliases": ["Conor Hoekstra", "Hoekstra"],
            "title": "Podcaster",
            "queries": ["Conor Shakory", "Conor Hoekstra"],
            "former_last_name": "Hoekstra",
            "hosted_podcasts": [{
                "id": "podcastindex-1",
                "title": "ADSP",
                "feed_urls": ["https://example.com/adsp.xml"],
            }],
        }]}
        index = {"personalities": [{
            "id": "conor-shakory", "name": "Conor Shakory",
            "aliases": [], "title": "Podcaster",
        }]}
        feed = {
            "id": "conor-shakory", "name": "Conor Shakory",
            "title": "Podcaster", "episodes": [{"guid": "1"}],
        }
        metadata = validate_metadata({
            "id": "conor-shakory",
            "name": "Conor Shakory",
            "title": "NVIDIA researcher and podcaster",
            "aliases": ["Conor Hoekstra", "Hoekstra"],
            "formerLastName": "Hoekstra",
            "hostedPodcasts": [{"id": "podcastindex-1", "title": "ADSP"}],
            "potentiallyCommonName": False,
            "requiredKeywords": [],
        })

        edit_personality(config, index, feed, metadata)

        person = config["personalities"][0]
        self.assertEqual(person["title"], "NVIDIA researcher and podcaster")
        self.assertEqual(
            person["hosted_podcasts"][0]["feed_urls"],
            ["https://example.com/adsp.xml"],
        )
        self.assertEqual(index["personalities"][0]["aliases"], ["Conor Hoekstra", "Hoekstra"])
        self.assertEqual(feed["former_last_name"], "Hoekstra")
        self.assertEqual(feed["episodes"], [{"guid": "1"}])

    def test_edits_a_review_draft_that_is_absent_from_the_public_index(self):
        config = {"personalities": [{
            "id": "draft-person", "name": "Old Name", "aliases": [],
            "title": "Old title", "queries": ["Old Name"],
            "review_pending": True,
        }]}
        index = {"personalities": []}
        feed = {"id": "draft-person", "name": "Old Name", "title": "Old title", "episodes": []}

        edit_personality(config, index, feed, validate_metadata({
            "id": "draft-person", "name": "New Name", "title": "New title",
            "aliases": ["Old Name"], "formerLastName": "",
            "hostedPodcasts": [], "potentiallyCommonName": False,
            "requiredKeywords": [],
        }))

        self.assertEqual(config["personalities"][0]["name"], "New Name")
        self.assertEqual(feed["name"], "New Name")
        self.assertEqual(index["personalities"], [])

    def test_missing_personality_does_not_partially_update(self):
        config = {"personalities": [{"id": "someone-else", "name": "Else"}]}
        index = {"personalities": []}
        feed = {"id": "missing", "name": "Missing", "title": "Old", "episodes": []}
        before = copy.deepcopy((config, index, feed))
        with self.assertRaisesRegex(ValueError, "was not found"):
            edit_personality(config, index, feed, validate_metadata({
                "id": "missing", "name": "Missing", "title": "New",
                "aliases": [], "formerLastName": "", "hostedPodcasts": [],
                "potentiallyCommonName": False, "requiredKeywords": [],
            }))
        self.assertEqual((config, index, feed), before)


if __name__ == "__main__":
    unittest.main()
