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
            },
        )

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
