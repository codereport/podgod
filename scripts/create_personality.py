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
PUBLIC_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


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


def validate_hosted_podcasts(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("Hosted podcasts must be an array of at most 20 entries")
    hosted: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_feeds: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("Each hosted podcast must be an object")
        show_id = clean_single_line(raw.get("id"), 80)
        title = clean_single_line(raw.get("title"), 160)
        feed_url = clean_single_line(raw.get("feedUrl"), 1000)
        artwork_url = clean_single_line(raw.get("artworkUrl"), 1000)
        if not ID_RE.fullmatch(show_id):
            raise ValueError("Hosted podcast ids must be lowercase URL slugs")
        if len(title) < 2:
            raise ValueError("Hosted podcasts must have a title")
        if not PUBLIC_URL_RE.match(feed_url):
            raise ValueError("Hosted podcasts must have a public RSS URL")
        normalized_feed = feed_url.casefold().rstrip("/")
        if show_id in seen_ids or normalized_feed in seen_feeds:
            raise ValueError("Hosted podcast ids and RSS feeds must be unique")
        show: dict[str, Any] = {
            "id": show_id,
            "title": title,
            "feed_urls": [feed_url],
        }
        if artwork_url and PUBLIC_URL_RE.match(artwork_url):
            show["artwork_url"] = artwork_url
        hosted.append(show)
        seen_ids.add(show_id)
        seen_feeds.add(normalized_feed)
    return hosted


def validate_metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Creation metadata must be a JSON object")
    personality_id = clean_single_line(value.get("id"), 80)
    name = clean_single_line(value.get("name"), 100)
    title = clean_single_line(value.get("title"), 100)
    former_last_name = clean_single_line(value.get("formerLastName"), 80)
    hosted_podcasts = validate_hosted_podcasts(value.get("hostedPodcasts", []))
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
        "hosted_podcasts": hosted_podcasts,
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
    if metadata.get("hosted_podcasts"):
        person["hosted_podcasts"] = metadata["hosted_podcasts"]
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
