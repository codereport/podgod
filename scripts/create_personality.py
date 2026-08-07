#!/usr/bin/env python3
"""Add one validated personality entry from an authenticated creation job.

The private backend supplies only public catalog metadata. The source photo is
passed separately to ``make_personality_art.py`` and is never committed.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "personalities.config.json"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


def clean_single_line(value: object, maximum: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:maximum]


def validate_metadata(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("Creation metadata must be a JSON object")
    personality_id = clean_single_line(value.get("id"), 80)
    name = clean_single_line(value.get("name"), 100)
    title = clean_single_line(value.get("title"), 100)
    if not ID_RE.fullmatch(personality_id):
        raise ValueError("Personality id must be a lowercase URL slug")
    if len(name) < 2:
        raise ValueError("Personality name must contain at least two characters")
    if len(title) < 2:
        raise ValueError("Personality subtitle must contain at least two characters")
    return {"id": personality_id, "name": name, "title": title}


def add_personality(
    config: dict[str, Any], metadata: dict[str, str]
) -> dict[str, Any]:
    people = config.get("personalities")
    if not isinstance(people, list):
        raise ValueError("personalities.config.json has no personalities array")

    personality_id = metadata["id"]
    folded_name = metadata["name"].casefold()
    for person in people:
        if not isinstance(person, dict):
            continue
        if person.get("id") == personality_id:
            raise ValueError(f"Personality id '{personality_id}' already exists")
        if clean_single_line(person.get("name"), 100).casefold() == folded_name:
            raise ValueError(f"Personality name '{metadata['name']}' already exists")

    people.append(
        {
            "id": personality_id,
            "name": metadata["name"],
            "aliases": [],
            "title": metadata["title"],
            "queries": [metadata["name"]],
        }
    )
    people.sort(key=lambda person: str(person.get("id", "")))
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()

    metadata = validate_metadata(
        json.loads(args.metadata.read_text(encoding="utf-8"))
    )
    config = json.loads(args.config.read_text(encoding="utf-8"))
    updated = add_personality(config, metadata)
    args.config.write_text(
        json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Added {metadata['name']} ({metadata['id']}) to {args.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
