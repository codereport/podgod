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


if __name__ == "__main__":
    unittest.main()
