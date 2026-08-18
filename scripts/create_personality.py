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


def former_full_name(name: str, former_last_name: str) -> str:
    """Replace the current surname while preserving the displayed given names."""
    if not former_last_name:
        return ""
    parts = name.rsplit(" ", 1)
    current_last_name = parts[-1]
    if current_last_name.casefold() == former_last_name.casefold():
        return ""
    given_names = parts[0] if len(parts) > 1 else name
    return f"{given_names} {former_last_name}"


def validate_metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Creation metadata must be a JSON object")
    personality_id = clean_single_line(value.get("id"), 80)
    name = clean_single_line(value.get("name"), 100)
    title = clean_single_line(value.get("title"), 100)
    former_last_name = clean_single_line(value.get("formerLastName"), 80)
    if not ID_RE.fullmatch(personality_id):
        raise ValueError("Personality id must be a lowercase URL slug")
    if len(name) < 2:
        raise ValueError("Personality name must contain at least two characters")
    if len(title) < 2:
        raise ValueError("Personality subtitle must contain at least two characters")
    potentially_common_name = value.get("potentiallyCommonName") is True
    raw_keywords = value.get("requiredKeywords", [])
    if not isinstance(raw_keywords, list):
        raise ValueError("Required keywords must be an array")
    required_keywords: list[str] = []
    for raw_keyword in raw_keywords:
        keyword = clean_single_line(raw_keyword, 60)
        if keyword and keyword.casefold() not in {
            existing.casefold() for existing in required_keywords
        }:
            required_keywords.append(keyword)
    if len(required_keywords) > 12:
        raise ValueError("No more than 12 required keywords are allowed")
    if potentially_common_name and not required_keywords:
        raise ValueError("A potentially common name requires at least one keyword")
    metadata = {
        "id": personality_id,
        "name": name,
        "title": title,
        "potentially_common_name": potentially_common_name,
        "required_context_keywords": required_keywords,
    }
    former_name = former_full_name(name, former_last_name)
    if former_name:
        metadata["former_last_name"] = former_last_name
        metadata["former_name"] = former_name
    return metadata


def add_personality(
    config: dict[str, Any], metadata: dict[str, Any]
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

    former_name = metadata.get("former_name", "")
    former_last_name = metadata.get("former_last_name", "")
    aliases = [value for value in (former_name, former_last_name) if value]
    queries = [metadata["name"], *([former_name] if former_name else [])]
    person = {
        "id": personality_id,
        "name": metadata["name"],
        "aliases": aliases,
        "title": metadata["title"],
        "queries": queries,
        # New personalities stay out of the public index until an
        # administrator reviews and explicitly approves their candidates.
        "review_pending": True,
    }
    if former_last_name:
        person["former_last_name"] = former_last_name
    if metadata.get("potentially_common_name"):
        person["potentially_common_name"] = True
        person["required_context_keywords"] = metadata.get(
            "required_context_keywords", []
        )
    people.append(person)
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
