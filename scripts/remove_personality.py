#!/usr/bin/env python3
"""Remove a personality from discovery and the public catalog.

Artwork remains available for listeners with cached episodes. Git history keeps
the removed configuration and feed recoverable.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


def remove_personality(root: Path, personality_id: str) -> None:
    if not ID_RE.fullmatch(personality_id):
        raise ValueError("Personality id must be a lowercase URL slug")
    paths = [
        root / "scripts/personalities.config.json",
        root / "data/v1/personalities.json",
        root / "website-data/personalities.json",
    ]
    # Validate every document before modifying any files. Missing entries are
    # allowed so a workflow retry after a successful commit is idempotent.
    documents: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("personalities"), list):
            raise ValueError(f"{path.name} has no personalities array")
        if any(not isinstance(person, dict) or not isinstance(person.get("id"), str)
               for person in document["personalities"]):
            raise ValueError(f"{path.name} has an invalid personality entry")
        documents.append((path, document))

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for path, document in documents:
        people = document["personalities"]
        remaining = [person for person in people if person.get("id") != personality_id]
        if len(remaining) == len(people):
            continue
        document["personalities"] = remaining
        if "updatedAt" in document:
            document["updatedAt"] = now
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (root / "data/v1/personalities" / f"{personality_id}.json").unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True)
    args = parser.parse_args()
    remove_personality(REPO_ROOT, args.id)
    print(f"Removed {args.id} from discovery and the public catalog")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
