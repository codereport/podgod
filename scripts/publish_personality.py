#!/usr/bin/env python3
"""Approve one reviewed personality for inclusion in the public index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from create_personality import ID_RE, clean_single_line


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "personalities.config.json"


def approve_personality(
    config: dict[str, Any], personality_id: str, feed_blocklist: list[str]
) -> dict[str, Any]:
    people = config.get("personalities")
    if not isinstance(people, list):
        raise ValueError("personalities.config.json has no personalities array")
    person = next(
        (
            item
            for item in people
            if isinstance(item, dict) and item.get("id") == personality_id
        ),
        None,
    )
    if person is None:
        raise ValueError(f"Personality id '{personality_id}' does not exist")
    person.pop("review_pending", None)
    existing = [
        clean_single_line(value, 500)
        for value in person.get("feed_blocklist", [])
    ]
    for value in feed_blocklist:
        cleaned = clean_single_line(value, 500)
        if cleaned and cleaned.casefold() not in {
            item.casefold() for item in existing
        }:
            existing.append(cleaned)
    if existing:
        person["feed_blocklist"] = existing
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    personality_id = clean_single_line(metadata.get("id"), 80)
    if not ID_RE.fullmatch(personality_id):
        raise ValueError("Personality id must be a lowercase URL slug")
    raw_blocklist = metadata.get("feedBlocklist", [])
    if not isinstance(raw_blocklist, list):
        raise ValueError("Feed blocklist must be an array")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    approve_personality(config, personality_id, raw_blocklist)
    args.config.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Approved {personality_id} for publication")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
