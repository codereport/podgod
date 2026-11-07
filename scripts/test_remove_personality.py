import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.remove_personality import remove_personality


class RemovePersonalityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.paths = [
            "scripts/personalities.config.json",
            "data/v1/personalities.json",
            "website-data/personalities.json",
        ]
        self.other = {"id": "grace-hopper", "name": "Grace Hopper", "episodes": [{"guid": "other"}]}
        for relative in self.paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "version": 1, "updatedAt": "old", "defaults": {"keep": True},
                "personalities": [{"id": "ada-lovelace", "name": "Ada Lovelace"}, copy.deepcopy(self.other)],
            }))
        self.feed = self.root / "data/v1/personalities/ada-lovelace.json"
        self.feed.parent.mkdir(parents=True)
        self.feed.write_text('{"id":"ada-lovelace","episodes":[{"guid":"saved"}]}')
        self.art = self.root / "data/v1/personalities/art/ada-lovelace.png"
        self.art.parent.mkdir()
        self.art.write_bytes(b"existing artwork")

    def test_removes_discovery_feed_and_both_listings_but_keeps_other_people_and_artwork(self):
        remove_personality(self.root, "ada-lovelace")
        for relative in self.paths:
            document = json.loads((self.root / relative).read_text())
            self.assertEqual(document["personalities"], [self.other])
            self.assertEqual(document["defaults"], {"keep": True})
            self.assertNotEqual(document["updatedAt"], "old")
        self.assertFalse(self.feed.exists())
        self.assertEqual(self.art.read_bytes(), b"existing artwork")

    def test_retry_produces_no_further_changes(self):
        remove_personality(self.root, "ada-lovelace")
        before = [(self.root / relative).read_bytes() for relative in self.paths]
        remove_personality(self.root, "ada-lovelace")
        self.assertEqual(before, [(self.root / relative).read_bytes() for relative in self.paths])

    def test_rejects_unsafe_ids_without_modifying_files(self):
        before = self.feed.read_bytes()
        for invalid in ["../index", "Ada", "", "/tmp/file", "ada/lovelace"]:
            with self.assertRaisesRegex(ValueError, "lowercase URL slug"):
                remove_personality(self.root, invalid)
        self.assertEqual(self.feed.read_bytes(), before)

    def test_invalid_later_document_does_not_partially_remove_anything(self):
        before = (self.root / self.paths[0]).read_bytes()
        (self.root / self.paths[-1]).write_text('{"personalities": [null]}')
        with self.assertRaisesRegex(ValueError, "invalid personality entry"):
            remove_personality(self.root, "ada-lovelace")
        self.assertEqual((self.root / self.paths[0]).read_bytes(), before)
        self.assertTrue(self.feed.exists())


if __name__ == "__main__":
    unittest.main()
