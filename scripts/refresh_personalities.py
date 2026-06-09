#!/usr/bin/env python3
"""Refresh the personalities meta-podcast feeds.

A personality is a "meta-podcast": a collection of interview/episode appearances
of one person scattered across many real podcasts. This script discovers those
appearances and writes:

  data/v1/personalities/<id>.json   per-person episode feed
  data/v1/personalities.json        index (metadata + episode counts)

Discovery backend (auto-selected):
  - PodcastIndex `search/byperson` when PODCASTINDEX_KEY + PODCASTINDEX_SECRET
    are set (best match quality; free key, but signup blocks free-email
    providers). Override with --source podcastindex.
  - iTunes Search API (episode search) otherwise - no key/signup required. The
    same backend the player app uses. Guest names are almost always in the
    episode title, and the name/duration/feed filters below keep it clean.
    Override with --source itunes.

Two run modes, differing only in the time window:

  Daily (GitHub Action):   refresh_personalities.py --since 24h
      Only consider episodes published in the last 24h, then merge them in.
      Already-published episodes are preserved (their original `added_at` is
      kept), so the daily run only ever appends genuinely new interviews.

  One-time backfill:       refresh_personalities.py --since 365d [--only <id>]
      Seed ~1 year of history when a personality is first added. Use --only to
      backfill a single newly-added person without re-scanning everyone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CONFIG_PATH = SCRIPT_DIR / "personalities.config.json"
DATA_DIR = REPO_ROOT / "data" / "v1"
PERSON_DIR = DATA_DIR / "personalities"
ART_DIR = PERSON_DIR / "art"
INDEX_PATH = DATA_DIR / "personalities.json"

SITE_BASE = "https://podgod.ca/data/v1/personalities"
PI_API_BASE = "https://api.podcastindex.org/api/1.0"
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
USER_AGENT = "PodGod-Personalities/1.0 (+https://podgod.ca)"
FEED_VERSION = 1

# PodcastIndex caps page size at 1000; iTunes caps at 200.
PI_MAX_RESULTS = 1000
ITUNES_MAX_RESULTS = 200


def parse_since(value: str) -> int:
    """Parse a window like '24h', '365d', '90m' into seconds. 'full'/'all' -> 0."""
    value = value.strip().lower()
    if value in ("full", "all", "0"):
        return 0
    m = re.fullmatch(r"(\d+)([smhdw])", value)
    if not m:
        raise argparse.ArgumentTypeError(
            f"Invalid --since value '{value}'. Use e.g. 24h, 365d, 90m, or 'full'."
        )
    n = int(m.group(1))
    unit = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[m.group(2)]
    return n * unit


def norm(s: str | None) -> str:
    return (s or "").strip().lower()


def to_iso(unix_ts: Any) -> str | None:
    try:
        ts = int(unix_ts)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


# Several Substack-hosted shows (e.g. Lenny's Podcast) are also mirrored on
# Spreaker. iTunes sometimes returns the Spreaker mirror's enclosure, which 404s
# once that mirror is taken down - leaving an unplayable episode. When the guid
# tells us the canonical home is Substack (`substack:post:<id>`) and the audio is
# such a Spreaker download URL, the shared file hash lets us rebuild the stable
# Substack URL.
SPREAKER_DOWNLOAD_RE = re.compile(
    r"^https?://api\.spreaker\.com/download/episode/\d+/([A-Za-z0-9]+\.mp3)", re.I
)
SUBSTACK_GUID_RE = re.compile(r"substack:post:(\d+)")


def canonicalize_audio_url(ep: dict[str, Any]) -> str | None:
    audio = ep.get("audio_url")
    if not audio:
        return audio
    guid_match = SUBSTACK_GUID_RE.match(str(ep.get("guid") or ""))
    spreaker_match = SPREAKER_DOWNLOAD_RE.match(str(audio))
    if guid_match and spreaker_match:
        return f"https://api.substack.com/feed/podcast/{guid_match.group(1)}/{spreaker_match.group(1)}"
    return audio


def episode_key(ep: dict[str, Any]) -> str:
    """Stable dedup key: prefer guid, fall back to audio/episode URL."""
    return (
        norm(ep.get("guid"))
        or norm(ep.get("audio_url"))
        or norm(ep.get("episode_url"))
        or norm(ep.get("title"))
    )


# --------------------------------------------------------------------------- #
# Discovery backends -> each returns list[(normalized_ep, texts)] where `texts`
# is {"title": <ep title>, "all": <title + description + feed title>}, both
# lowercased. The caller decides which scope to match the person's name against.
# --------------------------------------------------------------------------- #
def pi_auth_headers(key: str, secret: str) -> dict[str, str]:
    epoch = str(int(time.time()))
    digest = hashlib.sha1(f"{key}{secret}{epoch}".encode("utf-8")).hexdigest()
    return {
        "User-Agent": USER_AGENT,
        "X-Auth-Key": key,
        "X-Auth-Date": epoch,
        "Authorization": digest,
    }


def fetch_podcastindex(
    session: requests.Session, key: str, secret: str, query: str
) -> list[tuple[dict[str, Any], dict[str, str]]]:
    url = f"{PI_API_BASE}/search/byperson"
    params = {"q": query, "max": PI_MAX_RESULTS, "fulltext": "true"}
    resp = session.get(url, params=params, headers=pi_auth_headers(key, secret), timeout=30)
    resp.raise_for_status()
    items = resp.json().get("items") or []
    out: list[tuple[dict[str, Any], dict[str, str]]] = []
    for item in items:
        audio_url = item.get("enclosureUrl")
        if not audio_url:
            continue
        ep = {
            "guid": item.get("guid") or item.get("id"),
            "title": (item.get("title") or "").strip(),
            "podcast_title": (item.get("feedTitle") or "").strip(),
            "description": (item.get("description") or "").strip() or None,
            "feed_url": item.get("feedUrl"),
            "audio_url": audio_url,
            "artwork_url": item.get("image") or item.get("feedImage"),
            "podcast_artwork_url": item.get("feedImage") or item.get("image"),
            "duration": item.get("duration"),
            "pub_date": to_iso(item.get("datePublished")),
            "episode_url": item.get("link"),
            "podcastindex_id": item.get("id"),
        }
        title = norm(item.get("title"))
        all_text = " ".join(norm(item.get(k)) for k in ("title", "description", "feedTitle"))
        out.append((ep, {"title": title, "all": all_text}))
    return out


def fetch_itunes_collection_art(session: requests.Session, collection_ids: set[Any]) -> dict[str, str]:
    """Resolve each source podcast's (collection) artwork via the iTunes lookup
    endpoint, so the app can show the show's art distinctly from episode art."""
    ids = [str(c) for c in collection_ids if c]
    art: dict[str, str] = {}
    for i in range(0, len(ids), 100):  # lookup accepts a comma-separated batch
        batch = ids[i:i + 100]
        try:
            resp = session.get(
                "https://itunes.apple.com/lookup",
                params={"id": ",".join(batch), "entity": "podcast"},
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            resp.raise_for_status()
            for r in resp.json().get("results") or []:
                cid = r.get("collectionId")
                img = r.get("artworkUrl600") or r.get("artworkUrl160") or r.get("artworkUrl100")
                if cid and img:
                    art[str(cid)] = img
        except requests.RequestException as exc:
            print(f"  ! collection art lookup failed: {exc}", file=sys.stderr)
    return art


def fetch_itunes(session: requests.Session, query: str) -> list[tuple[dict[str, Any], dict[str, str]]]:
    params = {
        "term": query,
        "media": "podcast",
        "entity": "podcastEpisode",
        "limit": ITUNES_MAX_RESULTS,
    }
    resp = session.get(ITUNES_SEARCH_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("results") or []
    out: list[tuple[dict[str, Any], dict[str, str]]] = []
    for r in results:
        audio_url = r.get("episodeUrl")
        if not audio_url:
            continue
        millis = r.get("trackTimeMillis")
        duration = round(millis / 1000) if isinstance(millis, (int, float)) else None
        artwork = r.get("artworkUrl600") or r.get("artworkUrl160") or r.get("artworkUrl100")
        ep = {
            "guid": r.get("episodeGuid") or (str(r["trackId"]) if r.get("trackId") else None) or audio_url,
            "title": (r.get("trackName") or "").strip(),
            "podcast_title": (r.get("collectionName") or "").strip(),
            "description": (r.get("description") or r.get("shortDescription") or "").strip() or None,
            "feed_url": r.get("feedUrl"),
            "audio_url": audio_url,
            "artwork_url": artwork,
            # Source-podcast (collection) art is resolved in a later batch lookup;
            # default to the episode art so there is always something.
            "podcast_artwork_url": artwork,
            "collection_id": r.get("collectionId"),
            "duration": duration,
            "pub_date": r.get("releaseDate"),
            "episode_url": r.get("trackViewUrl"),
            "itunes_id": r.get("trackId"),
        }
        title = norm(r.get("trackName"))
        all_text = " ".join(
            norm(r.get(k)) for k in ("trackName", "description", "shortDescription", "collectionName")
        )
        out.append((ep, {"title": title, "all": all_text}))
    return out


# --------------------------------------------------------------------------- #
# Filtering
# --------------------------------------------------------------------------- #
def name_matches(texts: dict[str, str], person: dict[str, Any], scope: str) -> bool:
    """Require the person's name (or an alias) to appear in the chosen scope.
    `scope='title'` (iTunes term search, which is broad) keeps only episodes
    whose title names the person - a strong proxy for an actual appearance and a
    guard against surname collisions / aggregator feeds named after someone.
    `scope='all'` trusts a person-accurate backend (PodcastIndex byperson)."""
    hay = texts.get(scope) or texts.get("all", "")
    needles = [norm(person["name"]), *(norm(a) for a in person.get("aliases", []))]
    return any(n and n in hay for n in needles)


def feed_allowed(ep: dict[str, Any], person: dict[str, Any]) -> bool:
    feed_title = norm(ep.get("podcast_title"))
    feed_url = norm(ep.get("feed_url"))
    allowlist = [norm(x) for x in person.get("feed_allowlist", [])]
    blocklist = [norm(x) for x in person.get("feed_blocklist", [])]
    if blocklist and any(b and (b in feed_title or b in feed_url) for b in blocklist):
        return False
    if allowlist:
        return any(a and (a in feed_title or a in feed_url) for a in allowlist)
    return True


def within_window(ep: dict[str, Any], cutoff_ts: int) -> bool:
    if cutoff_ts <= 0:
        return True
    iso = ep.get("pub_date")
    if not iso:
        return False
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    return dt.timestamp() >= cutoff_ts


def discover(
    fetcher,
    person: dict[str, Any],
    defaults: dict[str, Any],
    cutoff_ts: int,
    now_iso: str,
    match_scope: str,
) -> list[dict[str, Any]]:
    """Fetch + filter fresh episodes for one person (already normalized).
    `fetcher(query)` returns list[(normalized_ep, texts)]."""
    min_duration = person.get("min_duration_sec", defaults.get("min_duration_sec", 600))
    seen: dict[str, dict[str, Any]] = {}
    for query in person.get("queries", [person["name"]]):
        try:
            candidates = fetcher(query)
        except requests.RequestException as exc:
            print(f"  ! query '{query}' failed: {exc}", file=sys.stderr)
            continue
        for ep, texts in candidates:
            if not name_matches(texts, person, match_scope):
                continue
            if not feed_allowed(ep, person):
                continue
            duration = ep.get("duration")
            if isinstance(duration, int) and duration < min_duration:
                continue
            if not within_window(ep, cutoff_ts):
                continue
            ep["added_at"] = now_iso
            seen[episode_key(ep)] = ep
    return list(seen.values())


def merge_episodes(
    existing: list[dict[str, Any]],
    fresh: list[dict[str, Any]],
    max_episodes: int,
) -> list[dict[str, Any]]:
    """Union by key; preserve the original `added_at` for already-known episodes
    while refreshing their metadata. Newest (by pub_date) first, capped."""
    by_key: dict[str, dict[str, Any]] = {}
    for ep in existing:
        by_key[episode_key(ep)] = ep
    for ep in fresh:
        key = episode_key(ep)
        if key in by_key:
            prior_added = by_key[key].get("added_at")
            merged = {**by_key[key], **ep}
            if prior_added:
                merged["added_at"] = prior_added
            by_key[key] = merged
        else:
            by_key[key] = ep

    def sort_key(ep: dict[str, Any]) -> str:
        return ep.get("pub_date") or ep.get("added_at") or ""

    ordered = sorted(by_key.values(), key=sort_key, reverse=True)
    return ordered[:max_episodes]


def artwork_url_for(pid: str) -> str:
    """Public art URL with a content-hash cache-buster (`?v=<hash>`).

    Clients (and expo-image) cache by exact URL, so reusing the same URL after
    regenerating a PNG would keep serving the stale image. Hashing the committed
    art file makes the URL change only when the art actually changes."""
    base = f"{SITE_BASE}/art/{pid}.png"
    art_path = ART_DIR / f"{pid}.png"
    try:
        digest = hashlib.md5(art_path.read_bytes()).hexdigest()[:8]
        return f"{base}?v={digest}"
    except OSError:
        return base


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> bool:
    """Write only if the content changed. Returns True when written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new_text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == new_text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def resolve_source(requested: str) -> str:
    key = os.environ.get("PODCASTINDEX_KEY")
    secret = os.environ.get("PODCASTINDEX_SECRET")
    has_pi = bool(key and secret)
    if requested == "podcastindex":
        if not has_pi:
            print("ERROR: --source podcastindex requires PODCASTINDEX_KEY and PODCASTINDEX_SECRET.", file=sys.stderr)
            sys.exit(2)
        return "podcastindex"
    if requested == "itunes":
        return "itunes"
    # auto
    return "podcastindex" if has_pi else "itunes"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        type=parse_since,
        default="24h",
        help="Only consider episodes published within this window (e.g. 24h, 365d, full). Default: 24h.",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        metavar="ID",
        help="Limit to one or more personality ids (repeatable). Useful for backfilling a newly added person.",
    )
    parser.add_argument(
        "--source",
        choices=["auto", "itunes", "podcastindex"],
        default="auto",
        help="Discovery backend. 'auto' uses PodcastIndex when its secrets are set, else iTunes.",
    )
    args = parser.parse_args()

    # argparse runs the `type` converter, so default "24h" is already seconds.
    cutoff_seconds = args.since if isinstance(args.since, int) else parse_since(args.since)
    cutoff_ts = int(time.time()) - cutoff_seconds if cutoff_seconds > 0 else 0

    source = resolve_source(args.source)
    session = requests.Session()
    if source == "podcastindex":
        pi_key = os.environ["PODCASTINDEX_KEY"]
        pi_secret = os.environ["PODCASTINDEX_SECRET"]
        fetcher = lambda q: fetch_podcastindex(session, pi_key, pi_secret, q)
        # byperson is already person-accurate, so match the name leniently.
        match_scope = "all"
    else:
        fetcher = lambda q: fetch_itunes(session, q)
        # iTunes term search is broad; require the name in the episode title.
        match_scope = "title"

    config = load_json(CONFIG_PATH)
    defaults = config.get("defaults", {})
    people = config.get("personalities", [])
    if args.only:
        wanted = set(args.only)
        people = [p for p in people if p["id"] in wanted]
        if not people:
            print(f"ERROR: no personalities matched --only {args.only}", file=sys.stderr)
            return 2

    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    today = now_iso[:10]
    window_desc = "full history" if cutoff_ts == 0 else f"last {cutoff_seconds // 3600}h"
    print(f"Refreshing {len(people)} personality feed(s) via {source} [{window_desc}]...")

    index = load_json(INDEX_PATH)
    index_by_id = {p["id"]: p for p in index.get("personalities", [])}
    changed = False

    for person in people:
        pid = person["id"]
        feed_path = PERSON_DIR / f"{pid}.json"
        feed = load_json(feed_path)
        existing_eps = feed.get("episodes", []) if isinstance(feed, dict) else []

        fresh = discover(fetcher, person, defaults, cutoff_ts, now_iso, match_scope)
        max_episodes = person.get("max_episodes", defaults.get("max_episodes", 50))
        merged = merge_episodes(existing_eps, fresh, max_episodes)

        # Resolve each episode's source-podcast (collection) art so the player can
        # offer "podcast art" vs "episode art" without ever using the personality cover.
        if source == "itunes":
            cids = {e.get("collection_id") for e in merged if e.get("collection_id")}
            if cids:
                art_map = fetch_itunes_collection_art(session, cids)
                for e in merged:
                    cid = e.get("collection_id")
                    if cid and art_map.get(str(cid)):
                        e["podcast_artwork_url"] = art_map[str(cid)]
        for e in merged:
            if not e.get("podcast_artwork_url"):
                e["podcast_artwork_url"] = e.get("artwork_url")
            # Repair dead mirror enclosures so episodes stay playable, including
            # ones already stored from a previous (pre-fix) run.
            fixed_audio = canonicalize_audio_url(e)
            if fixed_audio and fixed_audio != e.get("audio_url"):
                e["audio_url"] = fixed_audio

        artwork_url = artwork_url_for(pid)
        feed_payload = {
            "version": FEED_VERSION,
            "id": pid,
            "name": person["name"],
            "title": person.get("title", ""),
            "artwork_url": artwork_url,
            "updatedAt": today,
            "episodes": merged,
        }
        wrote = write_json(feed_path, feed_payload)
        added = len(merged) - len(existing_eps)
        print(f"  {pid}: {len(fresh)} fresh, {len(merged)} total (+{added}){' [written]' if wrote else ''}")
        changed = changed or wrote

        index_by_id[pid] = {
            "id": pid,
            "name": person["name"],
            "aliases": person.get("aliases", []),
            "title": person.get("title", ""),
            "artwork_url": artwork_url,
            "feed_url": f"{SITE_BASE}/{pid}.json",
            "episode_count": len(merged),
            "handle_entity_id": person.get("handle_entity_id"),
        }

    # Rebuild the index in config order so it stays stable/diff-friendly.
    config_order = [p["id"] for p in config.get("personalities", [])]
    ordered_index = [index_by_id[i] for i in config_order if i in index_by_id]
    index_payload = {
        "version": FEED_VERSION,
        "updatedAt": today,
        "personalities": ordered_index,
    }
    if write_json(INDEX_PATH, index_payload):
        changed = True

    print("Done." + ("" if changed else " No changes."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
