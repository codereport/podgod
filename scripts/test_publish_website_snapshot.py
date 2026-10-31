import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import publish_website_snapshot as publisher


def snapshot(date="2026-10-31T14:05:00Z"):
    return {"version": 1, "updatedAt": date, "personalities": [{
        "id": "ada", "name": "Ada", "title": "Scientist", "artwork_url": None,
        "episodes": [{"title": "Approved interview", "podcast_title": "Interviews", "pub_date": date,
            "language": "en", "episode_url": "https://podcast.test/episode", "audio_url": "https://podcast.test/audio.mp3", "podcast_artwork_url": None}],
    }]}


class WebsiteSnapshotTest(unittest.TestCase):
    def test_atomic_publication_is_idempotent_and_cannot_roll_back_a_newer_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            self.assertTrue(publisher.save_snapshot(snapshot(), path))
            self.assertFalse(publisher.save_snapshot(snapshot(), path))
            self.assertFalse(publisher.save_snapshot(snapshot("2026-10-30T14:05:00Z"), path))
            self.assertEqual(json.loads(path.read_text()), snapshot())

    def test_private_fields_and_unexpected_episode_cards_are_rejected_before_writing(self):
        for mutate in [lambda data: data.update(reviewState="private"),
                       lambda data: data["personalities"][0].update(reviewNote="private"),
                       lambda data: data["personalities"][0]["episodes"][0].update(classification="private"),
                       lambda data: data["personalities"][0]["episodes"][0].update(language="fr")]:
            data = copy.deepcopy(snapshot())
            mutate(data)
            with self.assertRaises(ValueError):
                publisher.validate_snapshot(data)

    def test_waits_for_the_completed_kv_publication_before_publishing(self):
        with patch.dict("os.environ", {"EXPECTED_PUBLISHED_AT": "2026-10-31T14:05:00Z", "PODGOD_WEBSITE_TOKEN": "job-secret"}), \
             patch.object(publisher.urllib.request, "urlopen", side_effect=[io.BytesIO(json.dumps(snapshot("2026-10-30T14:05:00Z")).encode()), io.BytesIO(json.dumps(snapshot()).encode())]), \
             patch.object(publisher.time, "sleep") as sleep, \
             patch.object(publisher, "save_snapshot") as save:
            publisher.main()
            sleep.assert_called_once_with(10)
            save.assert_called_once_with(snapshot())


if __name__ == "__main__":
    unittest.main()
