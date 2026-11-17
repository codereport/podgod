#!/usr/bin/env python3
"""Print the discovery window requested by personality creation metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def creation_history_window(metadata: dict[str, object]) -> str:
    # Older creation jobs predate the configurable window and searched one year.
    years = metadata.get("yearsBack", 1)
    if type(years) is not int or not 1 <= years <= 20:
        raise ValueError("yearsBack must be a whole number from 1 to 20")
    return f"{years * 365}d"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metadata", type=Path)
    args = parser.parse_args()
    print(creation_history_window(json.loads(args.metadata.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    main()
