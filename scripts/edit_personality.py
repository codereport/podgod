#!/usr/bin/env python3
"""Edit one personality while keeping its stable id and feed URLs."""

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
PUBLIC_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def clean_single_line(value: object, maximum: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:maximum]


def clean_unique_strings(value: object, maximum: int, limit: int) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("Expected an array of strings")
    unique: dict[str, str] = {}
    for raw in value:
        cleaned = clean_single_line(raw, maximum)
        if cleaned:
            unique[cleaned.casefold()] = cleaned
    if len(unique) > limit:
        raise ValueError(f"No more than {limit} values are allowed")
    return list(unique.values())


def validate_hosted_podcasts(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("Hosted podcasts must be an array of at most 20 entries")
    hosted: list[dict[str, str]] = []
    seen: set[str] = set()
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
        if feed_url and not PUBLIC_URL_RE.match(feed_url):
            raise ValueError("Hosted podcast RSS URLs must be public HTTP URLs")
        if artwork_url and not PUBLIC_URL_RE.match(artwork_url):
            raise ValueError("Hosted podcast artwork URLs must be public HTTP URLs")
        if show_id in seen:
            raise ValueError("Hosted podcast ids must be unique")
        item = {"id": show_id, "title": title}
        if feed_url:
            item["feed_url"] = feed_url
        if artwork_url:
            item["artwork_url"] = artwork_url
        hosted.append(item)
        seen.add(show_id)
    return hosted


def validate_metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Edit metadata must be a JSON object")
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
    aliases = clean_unique_strings(value.get("aliases", []), 100, 20)
    required_keywords = clean_unique_strings(
        value.get("requiredKeywords", []), 60, 12
    )
    potentially_common_name = value.get("potentiallyCommonName") is True
    if potentially_common_name and not required_keywords:
        raise ValueError("A potentially common name requires identifying keywords")
    return {
        "id": personality_id,
        "name": name,
        "title": title,
        "aliases": aliases,
        "former_last_name": former_last_name,
        "potentially_common_name": potentially_common_name,
        "required_context_keywords": required_keywords,
        "hosted_podcasts": validate_hosted_podcasts(
            value.get("hostedPodcasts", [])
        ),
    }


def resolved_hosted_podcasts(
    requested: list[dict[str, str]], existing: object
) -> list[dict[str, Any]]:
    current = {
        str(item.get("id")): item
        for item in existing if isinstance(item, dict) and item.get("id")
    } if isinstance(existing, list) else {}
    resolved: list[dict[str, Any]] = []
    for item in requested:
        old = current.get(item["id"], {})
        feed_url = item.get("feed_url", "")
        if feed_url:
            result: dict[str, Any] = {
                "id": item["id"],
                "title": item["title"],
                "feed_urls": [feed_url],
            }
        elif isinstance(old, dict) and old.get("feed_urls"):
            result = dict(old)
            result["title"] = item["title"]
        else:
            raise ValueError(
                f"Hosted podcast '{item['title']}' needs an RSS URL before it can be added"
            )
        if item.get("artwork_url"):
            result["artwork_url"] = item["artwork_url"]
        resolved.append(result)
    return resolved


def edit_personality(
    config: dict[str, Any],
    index: dict[str, Any],
    feed: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    people = config.get("personalities")
    indexed = index.get("personalities")
    if not isinstance(people, list):
        raise ValueError("personalities.config.json has no personalities array")
    if not isinstance(indexed, list):
        raise ValueError("personalities.json has no personalities array")
    personality_id = metadata["id"]
    if feed.get("id") != personality_id:
        raise ValueError(f"Public feed for '{personality_id}' was not found")
    person = next(
        (item for item in people if isinstance(item, dict) and item.get("id") == personality_id),
        None,
    )
    if person is None:
        raise ValueError(f"Personality '{personality_id}' was not found")
    duplicate = next(
        (
            item for item in people
            if isinstance(item, dict)
            and item.get("id") != personality_id
            and clean_single_line(item.get("name"), 100).casefold()
            == metadata["name"].casefold()
        ),
        None,
    )
    if duplicate is not None:
        raise ValueError(f"Personality name '{metadata['name']}' already exists")

    hosted = resolved_hosted_podcasts(
        metadata["hosted_podcasts"], person.get("hosted_podcasts", [])
    )
    public_hosted = [
        {"id": item["id"], "title": item["title"]} for item in hosted
    ]
    queries = [metadata["name"]]
    for alias in metadata["aliases"]:
        if " " in alias and alias.casefold() not in {q.casefold() for q in queries}:
            queries.append(alias)

    person["name"] = metadata["name"]
    person["aliases"] = metadata["aliases"]
    person["title"] = metadata["title"]
    person["queries"] = queries
    if metadata["former_last_name"]:
        person["former_last_name"] = metadata["former_last_name"]
    else:
        person.pop("former_last_name", None)
    if hosted:
        person["hosted_podcasts"] = hosted
    else:
        person.pop("hosted_podcasts", None)
    if metadata["potentially_common_name"]:
        person["potentially_common_name"] = True
        person["required_context_keywords"] = metadata["required_context_keywords"]
    else:
        person.pop("potentially_common_name", None)
        person.pop("required_context_keywords", None)

    feed["name"] = metadata["name"]
    feed["title"] = metadata["title"]
    feed["aliases"] = metadata["aliases"]
    if metadata["former_last_name"]:
        feed["former_last_name"] = metadata["former_last_name"]
    else:
        feed.pop("former_last_name", None)
    if public_hosted:
        feed["hosted_podcasts"] = public_hosted
    else:
        feed.pop("hosted_podcasts", None)

    index_person = next(
        (item for item in indexed if isinstance(item, dict) and item.get("id") == personality_id),
        None,
    )
    # Review drafts intentionally do not appear in the public index yet.
    if index_person is not None:
        index_person["name"] = metadata["name"]
        index_person["aliases"] = metadata["aliases"]
        index_person["title"] = metadata["title"]
        if public_hosted:
            index_person["hosted_podcasts"] = public_hosted
        else:
            index_person.pop("hosted_podcasts", None)


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
    edit_personality(config, index, feed, metadata)
    write_json(args.config, config)
    write_json(args.index, index)
    write_json(feed_path, feed)
    print(f"Edited {metadata['name']} ({metadata['id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
