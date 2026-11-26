"""Content revisions for public personality feeds; publication dates are not content."""

import hashlib
import json
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
