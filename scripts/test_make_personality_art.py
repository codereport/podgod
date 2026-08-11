import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from scripts import make_personality_art


class UploadedPersonalityArtTests(unittest.TestCase):
    def test_uploaded_photo_builds_art_without_copying_the_source(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            upload = root / "source.jpg"
            art_directory = root / "art"
            cache_directory = root / "cache"
            Image.new("RGB", (800, 1000), (80, 120, 180)).save(upload)

            with (
                patch.object(make_personality_art, "REPO_ROOT", root),
                patch.object(make_personality_art, "ART_DIR", art_directory),
                patch.object(make_personality_art, "CACHE_DIR", cache_directory),
            ):
                result = make_personality_art.process_person(
                    {"id": "example-person", "name": "Example Person"},
                    remove_bg=False,
                    model="u2net_human_seg",
                    edge_erode=1,
                    grayscale=True,
                    uploaded_photo=upload,
                )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["credit"]["source"], "admin_upload")
            self.assertTrue((art_directory / "example-person.png").is_file())
            self.assertFalse((cache_directory / "example-person.src").exists())
            self.assertTrue(upload.is_file())

    def test_replacement_cache_busts_existing_public_json(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            personality_directory = root / "personalities"
            personality_directory.mkdir()
            art = personality_directory / "art.png"
            art.write_bytes(b"new artwork")
            feed_path = personality_directory / "example-person.json"
            index_path = root / "personalities.json"
            feed_path.write_text(
                json.dumps({"id": "example-person", "artwork_url": "old"}),
                encoding="utf-8",
            )
            index_path.write_text(
                json.dumps({
                    "personalities": [
                        {"id": "example-person", "artwork_url": "old"},
                        {"id": "someone-else", "artwork_url": "unchanged"},
                    ]
                }),
                encoding="utf-8",
            )

            with (
                patch.object(make_personality_art, "PERSONALITY_DIR", personality_directory),
                patch.object(make_personality_art, "PERSONALITY_INDEX_PATH", index_path),
            ):
                changed = make_personality_art.update_artwork_references(
                    "example-person",
                    art,
                )

            feed = json.loads(feed_path.read_text(encoding="utf-8"))
            index = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(set(changed), {feed_path, index_path})
            self.assertRegex(feed["artwork_url"], r"example-person\.png\?v=[0-9a-f]{8}$")
            self.assertEqual(index["personalities"][0]["artwork_url"], feed["artwork_url"])
            self.assertEqual(index["personalities"][1]["artwork_url"], "unchanged")


if __name__ == "__main__":
    unittest.main()
