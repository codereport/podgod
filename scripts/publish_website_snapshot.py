#!/usr/bin/env python3
"""Publish the completed public homepage snapshot without fetching individual feeds."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

OUTPUT = Path(__file__).resolve().parents[1] / "website-data/personalities.json"
PERSON_FIELDS = {"id", "name", "title", "artwork_url", "episodes"}
EPISODE_FIELDS = {"title", "podcast_title", "episode_url", "audio_url", "pub_date", "language", "podcast_artwork_url"}


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Publication timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != {"version", "updatedAt", "personalities"} or snapshot["version"] != 1:
        raise ValueError("Unsupported website snapshot")
    timestamp(snapshot["updatedAt"])
    if not isinstance(snapshot["personalities"], list):
        raise ValueError("Invalid personality list")
    for person in snapshot["personalities"]:
        if set(person) != PERSON_FIELDS or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", person["id"]):
            raise ValueError("Unexpected personality card fields")
        if not isinstance(person["episodes"], list) or len(person["episodes"]) > 2:
            raise ValueError("Invalid episode cards")
        for episode in person["episodes"]:
            if set(episode) != EPISODE_FIELDS or not re.match(r"^en(?:[-_]|$)", episode["language"] or "", re.I):
                raise ValueError("Unexpected public episode fields or language")


def save_snapshot(snapshot, path=OUTPUT):
    validate_snapshot(snapshot)
    if path.exists() and timestamp(json.loads(path.read_text())["updatedAt"]) > timestamp(snapshot["updatedAt"]):
        return False
    text = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text() == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text)
    temporary.replace(path)
    return True


def main():
    expected = timestamp(os.environ["EXPECTED_PUBLISHED_AT"])
    token = os.environ["PODGOD_WEBSITE_TOKEN"]
    if not token:
        raise ValueError("The website publication credential is not configured")
    for attempt in range(8):
        try:
            request = urllib.request.Request("https://api.podgod.ca/internal/website-snapshot", headers={
                "Authorization": "Bearer " + token, "Accept": "application/json", "User-Agent": "PodGod-Website-Publisher/1.0"})
            with urllib.request.urlopen(request, timeout=20) as response:
                snapshot = json.load(response)
            validate_snapshot(snapshot)
            if timestamp(snapshot["updatedAt"]) >= expected:
                changed = save_snapshot(snapshot)
                print("Website snapshot updated." if changed else "Website snapshot is already current.")
                return
        except urllib.error.HTTPError as error:
            if error.code not in (404, 429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError):
            pass
        if attempt < 7:
            time.sleep(10)
    raise RuntimeError("The completed website snapshot did not become available")


if __name__ == "__main__":
    main()
