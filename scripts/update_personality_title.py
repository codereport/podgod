#!/usr/bin/env python3
"""Update one personality title in config and its generated public JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CONFIG_PATH = SCRIPT_DIR / "personalities.config.json"
INDEX_PATH = REPO_ROOT / "data" / "v1" / "personalities.json"
PERSONALITY_DIR = REPO_ROOT / "data" / "v1" / "personalities"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


def clean_single_line(value: object, maximum: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:maximum]


def validate_metadata(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("Title metadata must be a JSON object")
    personality_id = clean_single_line(value.get("id"), 80)
    title = clean_single_line(value.get("title"), 100)
    if not ID_RE.fullmatch(personality_id):
        raise ValueError("Personality id must be a lowercase URL slug")
    if len(title) < 2:
        raise ValueError("Personality title must contain at least two characters")
    return {"id": personality_id, "title": title}


def update_title(
    config: dict[str, Any],
    index: dict[str, Any],
    feed: dict[str, Any],
    metadata: dict[str, str],
) -> None:
    personality_id = metadata["id"]
    title = metadata["title"]

    people = config.get("personalities")
    indexed = index.get("personalities")
    if not isinstance(people, list):
        raise ValueError("personalities.config.json has no personalities array")
    if not isinstance(indexed, list):
        raise ValueError("personalities.json has no personalities array")
    if feed.get("id") != personality_id:
        raise ValueError(f"Public feed for '{personality_id}' was not found")

    config_person = next(
        (person for person in people if isinstance(person, dict) and person.get("id") == personality_id),
        None,
    )
    index_person = next(
        (person for person in indexed if isinstance(person, dict) and person.get("id") == personality_id),
        None,
    )
    if config_person is None or index_person is None:
        raise ValueError(f"Personality '{personality_id}' was not found")

    config_person["title"] = title
    index_person["title"] = title
    feed["title"] = title


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    parser.add_argument("--personality-dir", type=Path, default=PERSONALITY_DIR)
    args = parser.parse_args()

    metadata = validate_metadata(json.loads(args.metadata.read_text(encoding="utf-8")))
    feed_path = args.personality_dir / f"{metadata['id']}.json"
    config = json.loads(args.config.read_text(encoding="utf-8"))
    index = json.loads(args.index.read_text(encoding="utf-8"))
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    update_title(config, index, feed, metadata)
    write_json(args.config, config)
    write_json(args.index, index)
    write_json(feed_path, feed)
    print(f"Updated {metadata['id']} title to {metadata['title']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
