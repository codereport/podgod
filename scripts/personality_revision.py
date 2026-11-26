"""Content revisions for public personality feeds; publication dates are not content."""

import hashlib
import json
from pathlib import Path
from typing import Any


def stamp_feed_revision(feed: dict[str, Any], index: dict[str, Any] | None = None) -> str:
    content = {key: value for key, value in feed.items() if key not in {"updatedAt", "revision"}}
    revision = hashlib.sha256(json.dumps(
        content, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    feed["revision"] = revision
    if index is not None:
        for person in index.get("personalities", []):
            if person.get("id") == feed.get("id"):
                person["revision"] = revision
    return revision


def main() -> None:
    """Refresh revisions after hand-editing public JSON, without rediscovery."""
    root = Path(__file__).resolve().parents[1]
    index_path = root / "data/v1/personalities.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for path in sorted((root / "data/v1/personalities").glob("*.json")):
        feed = json.loads(path.read_text(encoding="utf-8"))
        if feed.get("id") != path.stem or not isinstance(feed.get("episodes"), list):
            raise ValueError(f"Invalid personality feed: {path.name}")
        stamp_feed_revision(feed, index)
        text = json.dumps(feed, indent=2, ensure_ascii=False) + "\n"
        if path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
    text = json.dumps(index, indent=2, ensure_ascii=False) + "\n"
    if index_path.read_text(encoding="utf-8") != text:
        index_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
