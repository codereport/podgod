import unittest

from scripts.create_personality import add_personality, validate_metadata


class CreatePersonalityTests(unittest.TestCase):
    def test_adds_a_minimal_sorted_entry(self):
        config = {
            "defaults": {"max_episodes": 100},
            "personalities": [
                {"id": "z-person", "name": "Z Person"},
            ],
        }
        metadata = validate_metadata(
            {"id": "ada-lovelace", "name": "Ada Lovelace", "title": "Computing pioneer"}
        )

        result = add_personality(config, metadata)

        self.assertEqual(
            [person["id"] for person in result["personalities"]],
            ["ada-lovelace", "z-person"],
        )
        self.assertEqual(
            result["personalities"][0],
            {
                "id": "ada-lovelace",
                "name": "Ada Lovelace",
                "aliases": [],
                "title": "Computing pioneer",
                "queries": ["Ada Lovelace"],
                "review_pending": True,
            },
        )

    def test_common_name_metadata_adds_required_context(self):
        config = {"personalities": []}
        metadata = validate_metadata({
            "id": "jeff-dean",
            "name": "Jeff Dean",
            "title": "AI researcher",
            "potentiallyCommonName": True,
            "requiredKeywords": ["Google", "AI", "google"],
        })
        person = add_personality(config, metadata)["personalities"][0]
        self.assertTrue(person["potentially_common_name"])
        self.assertEqual(person["required_context_keywords"], ["Google", "AI"])
        self.assertTrue(person["review_pending"])

    def test_former_last_name_adds_search_aliases_and_discovery_query(self):
        config = {"personalities": []}
        metadata = validate_metadata({
            "id": "conor-shakory",
            "name": "Conor Shakory",
            "formerLastName": "Hoekstra",
            "title": "Programming-language enthusiast",
        })

        person = add_personality(config, metadata)["personalities"][0]

        self.assertEqual(person["name"], "Conor Shakory")
        self.assertEqual(person["former_last_name"], "Hoekstra")
        self.assertEqual(person["aliases"], ["Conor Hoekstra", "Hoekstra"])
        self.assertEqual(person["queries"], ["Conor Shakory", "Conor Hoekstra"])

    def test_ignores_a_former_last_name_that_matches_the_current_name(self):
        metadata = validate_metadata({
            "id": "ada-lovelace",
            "name": "Ada Lovelace",
            "formerLastName": "lovelace",
            "title": "Computing pioneer",
        })

        self.assertNotIn("former_last_name", metadata)
        self.assertNotIn("former_name", metadata)

    def test_adds_confirmed_hosted_podcast_metadata(self):
        config = {"personalities": []}
        metadata = validate_metadata({
            "id": "conor-shakory",
            "name": "Conor Shakory",
            "title": "NVIDIA researcher & podcast host",
            "hostedPodcasts": [
                {
                    "id": "itunes-1541407369",
                    "title": "ADSP: Algorithms + Data Structures = Programs",
                    "feedUrl": "https://rss.buzzsprout.com/1501960.rss",
                    "artworkUrl": "https://example.com/adsp.jpg",
                }
            ],
        })

        person = add_personality(config, metadata)["personalities"][0]

        self.assertEqual(person["hosted_podcasts"], [
            {
                "id": "itunes-1541407369",
                "title": "ADSP: Algorithms + Data Structures = Programs",
                "feed_urls": ["https://rss.buzzsprout.com/1501960.rss"],
                "artwork_url": "https://example.com/adsp.jpg",
            }
        ])

    def test_rejects_duplicate_name_or_slug(self):
        base = {"personalities": [{"id": "ada", "name": "Ada Lovelace"}]}
        with self.assertRaisesRegex(ValueError, "already exists"):
            add_personality(
                base,
                {"id": "ada", "name": "Different Name", "title": "Researcher"},
            )
        with self.assertRaisesRegex(ValueError, "already exists"):
            add_personality(
                {"personalities": [{"id": "ada", "name": "Ada Lovelace"}]},
                {"id": "ada-2", "name": "ada lovelace", "title": "Researcher"},
            )

    def test_rejects_an_unsafe_slug(self):
        with self.assertRaisesRegex(ValueError, "URL slug"):
            validate_metadata(
                {"id": "../ada", "name": "Ada Lovelace", "title": "Researcher"}
            )


if __name__ == "__main__":
    unittest.main()
