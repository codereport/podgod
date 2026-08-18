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
    Per-person `itunes_guest_queries` can also search descriptions for opaque
    titles; those candidates must have an exact RSS podcast:person guest tag.
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
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    # Optional: language-detection fallback for episodes whose source carries no
    # language tag (e.g. iTunes episode search). PodcastIndex `feedLanguage` is
    # used first; this only fills the gaps. Seeded for deterministic output.
    from langdetect import DetectorFactory, LangDetectException
    from langdetect import detect as _langdetect_detect

    DetectorFactory.seed = 0
    _HAS_LANGDETECT = True
except Exception:  # pragma: no cover - langdetect is optional
    _HAS_LANGDETECT = False

    class LangDetectException(Exception):  # type: ignore[no-redef]
        pass

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


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def normalize_lang(code: str | None) -> str | None:
    """Normalize an RSS/ISO language tag to a base lowercase code.

    e.g. 'en-US' -> 'en', 'ZH_hans' -> 'zh', '' -> None. Anything that isn't a
    plausible 2-3 letter alpha code is dropped."""
    if not code:
        return None
    base = re.split(r"[-_]", str(code).strip().lower(), maxsplit=1)[0]
    return base if base.isalpha() and 2 <= len(base) <= 3 else None


def detect_language(ep: dict[str, Any]) -> str | None:
    """Best-effort language for an episode.

    Prefer the feed's declared language; otherwise detect from the episode title
    plus a plain-text snippet of the description (langdetect, when available).
    Returns a normalized base code (e.g. 'en') or None when undeterminable."""
    declared = normalize_lang(ep.get("language"))
    if declared:
        return declared
    if not _HAS_LANGDETECT:
        return None
    title = ep.get("title") or ""
    desc = _HTML_TAG_RE.sub(" ", ep.get("description") or "")
    sample = f"{title}. {desc}".strip()
    if len(sample) < 8:
        return None
    try:
        return normalize_lang(_langdetect_detect(sample))
    except LangDetectException:
        return None


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


def public_hosted_podcasts(person: dict[str, Any]) -> list[dict[str, str]]:
    """Return the public, UI-safe hosted-show metadata for one personality.

    Feed URLs and title aliases remain publisher-side matching details. The
    stable id is what clients persist when a listener includes or excludes an
    individual hosted show.
    """
    hosted: list[dict[str, str]] = []
    seen: set[str] = set()
    configured = person.get("hosted_podcasts", [])
    for show in configured if isinstance(configured, list) else []:
        if not isinstance(show, dict):
            continue
        show_id = str(show.get("id") or "").strip()
        title = str(show.get("title") or "").strip()
        if not show_id or not title or show_id in seen:
            continue
        hosted.append({"id": show_id, "title": title})
        seen.add(show_id)
    return hosted


def hosted_podcast_id(ep: dict[str, Any], person: dict[str, Any]) -> str | None:
    """Identify whether an episode belongs to a show the personality hosts.

    Prefer exact feed-URL matches, with exact source-title matching as a
    fallback for discovery records whose backend omitted or rewrote the URL.
    """
    episode_feed_url = norm(ep.get("feed_url")).rstrip("/")
    episode_title = norm(ep.get("podcast_title"))
    configured = person.get("hosted_podcasts", [])
    for show in configured if isinstance(configured, list) else []:
        if not isinstance(show, dict):
            continue
        show_id = str(show.get("id") or "").strip()
        if not show_id:
            continue
        configured_feed_urls = show.get("feed_urls", [])
        feed_urls = {
            norm(value).rstrip("/")
            for value in (
                configured_feed_urls if isinstance(configured_feed_urls, list) else []
            )
            if isinstance(value, str) and norm(value)
        }
        configured_aliases = show.get("title_aliases", [])
        aliases = configured_aliases if isinstance(configured_aliases, list) else []
        titles = {
            norm(value)
            for value in [show.get("title"), *aliases]
            if isinstance(value, str) and norm(value)
        }
        if (episode_feed_url and episode_feed_url in feed_urls) or (
            episode_title and episode_title in titles
        ):
            return show_id
    return None


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
            "language": normalize_lang(item.get("feedLanguage")),
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
            # iTunes episode search exposes no language; filled by detect_language.
            "language": None,
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


def feed_allowed(ep: dict[str, Any], person: dict[str, Any], defaults: dict[str, Any]) -> bool:
    """Reject an episode whose source feed or episode title looks like a
    news/digest/recap show (global blocklists) or matches the person's own
    feed_blocklist; honor an optional per-person feed_allowlist."""
    feed_title = norm(ep.get("podcast_title"))
    feed_url = norm(ep.get("feed_url"))
    ep_title = norm(ep.get("title"))
    allowlist = [norm(x) for x in person.get("feed_allowlist", [])]
    feed_blocklist = [
        norm(x) for x in (*person.get("feed_blocklist", []), *defaults.get("global_feed_blocklist", []))
    ]
    title_blocklist = [norm(x) for x in defaults.get("global_title_blocklist", [])]
    if feed_blocklist and any(b and (b in feed_title or b in feed_url) for b in feed_blocklist):
        return False
    if title_blocklist and any(b and b in ep_title for b in title_blocklist):
        return False
    if allowlist:
        return any(a and (a in feed_title or a in feed_url) for a in allowlist)
    return True


def context_allowed(ep: dict[str, Any], person: dict[str, Any]) -> bool:
    """Require identifying context for an explicitly marked common name."""
    if not person.get("potentially_common_name"):
        return True
    keywords = [norm(value) for value in person.get("required_context_keywords", [])]
    keywords = [value for value in keywords if value]
    if not keywords:
        return False
    context = " ".join((norm(ep.get("title")), norm(ep.get("description"))))
    return any(keyword in context for keyword in keywords)


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


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _is_podcast_namespace(namespace: str) -> bool:
    """Accept both Podcast Namespace URIs found in live feeds.

    Older Transistor feeds use the original GitHub documentation URL while
    newer feeds generally use podcastindex.org/namespace/1.0.
    """
    namespace = norm(namespace)
    return (
        "podcastindex.org/namespace" in namespace
        or "podcastindex-org/podcast-namespace" in namespace
    )


def _rss_item_matches_episode(item: ET.Element, ep: dict[str, Any]) -> bool:
    """Match an Apple result back to its RSS item using stable identifiers."""
    rss_guid = ""
    rss_title = ""
    rss_audio = ""
    for child in item:
        local_name = _xml_local_name(child.tag)
        if local_name == "guid":
            rss_guid = norm(child.text)
        elif local_name == "title":
            rss_title = norm(child.text)
        elif local_name == "enclosure":
            rss_audio = norm(child.get("url"))

    return any(
        (
            norm(ep.get("guid")) and rss_guid and norm(ep.get("guid")) == rss_guid,
            norm(ep.get("audio_url")) and rss_audio and norm(ep.get("audio_url")) == rss_audio,
            norm(ep.get("title")) and rss_title and norm(ep.get("title")) == rss_title,
        )
    )


def rss_confirms_guest(root: ET.Element, ep: dict[str, Any], person: dict[str, Any]) -> bool:
    """Confirm that an episode's RSS item names the person as an exact guest.

    Apple description search is useful for finding opaque episode titles, but it
    also returns episodes that merely mention a person. The Podcast Namespace
    ``podcast:person`` tag gives us a precise way to distinguish appearances.
    """
    names = {norm(person["name"]), *(norm(alias) for alias in person.get("aliases", []))}
    names.discard("")
    for item in root.iter():
        if _xml_local_name(item.tag) != "item" or not _rss_item_matches_episode(item, ep):
            continue
        for child in item.iter():
            namespace = _xml_namespace(child.tag)
            if (
                _xml_local_name(child.tag) == "person"
                and _is_podcast_namespace(namespace)
                and norm(child.get("role")) == "guest"
                and norm(child.text) in names
            ):
                return True
    return False


def feed_confirms_guest(
    session: requests.Session,
    ep: dict[str, Any],
    person: dict[str, Any],
    cache: dict[str, ET.Element | None],
) -> bool:
    """Fetch an episode's RSS feed once and verify its exact guest tag."""
    feed_url = str(ep.get("feed_url") or "").strip()
    if not feed_url:
        return False
    if feed_url not in cache:
        try:
            response = session.get(feed_url, headers={"User-Agent": USER_AGENT}, timeout=30)
            response.raise_for_status()
            cache[feed_url] = ET.fromstring(response.content)
        except (requests.RequestException, ET.ParseError) as exc:
            print(f"  ! RSS guest verification failed for {feed_url}: {exc}", file=sys.stderr)
            cache[feed_url] = None
    root = cache[feed_url]
    return bool(root is not None and rss_confirms_guest(root, ep, person))


def discovery_queries(
    label: str, person: dict[str, Any], match_scope: str
) -> list[tuple[str, str, bool]]:
    """Return (query, match scope, require exact RSS guest tag) tuples."""
    queries = [
        (query, match_scope, False)
        for query in person.get("queries", [person["name"]])
    ]
    if label == "itunes":
        queries.extend(
            (query, "all", True)
            for query in person.get("itunes_guest_queries", [])
        )
    return queries


def discover(
    backends: list[tuple[str, Any, str]],
    person: dict[str, Any],
    defaults: dict[str, Any],
    cutoff_ts: int,
    now_iso: str,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Fetch + filter fresh episodes for one person across one or more backends.

    `backends` is a list of (label, fetcher, match_scope). Each `fetcher(query)`
    returns list[(normalized_ep, texts)]. Backends are tried in order and unioned
    by episode key; the first backend to produce a given episode wins, so list the
    higher-quality source (PodcastIndex) first to prefer its richer metadata.
    iTunes also runs any configured guest queries across descriptions, accepting
    those broader matches only after exact RSS guest-tag verification."""
    min_duration = person.get("min_duration_sec", defaults.get("min_duration_sec", 600))
    seen: dict[str, dict[str, Any]] = {}
    guest_feed_cache: dict[str, ET.Element | None] = {}
    for label, fetcher, match_scope in backends:
        for query, query_scope, require_rss_guest in discovery_queries(label, person, match_scope):
            try:
                candidates = fetcher(query)
            except requests.RequestException as exc:
                print(f"  ! [{label}] query '{query}' failed: {exc}", file=sys.stderr)
                continue
            for ep, texts in candidates:
                if not name_matches(texts, person, query_scope):
                    continue
                if require_rss_guest and (
                    session is None or not feed_confirms_guest(session, ep, person, guest_feed_cache)
                ):
                    continue
                if not feed_allowed(ep, person, defaults):
                    continue
                if not context_allowed(ep, person):
                    continue
                duration = ep.get("duration")
                if isinstance(duration, int) and duration < min_duration:
                    continue
                if not within_window(ep, cutoff_ts):
                    continue
                ep["added_at"] = now_iso
                seen.setdefault(episode_key(ep), ep)
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
    # auto: when PodcastIndex keys exist, use BOTH backends and union the results.
    # PodcastIndex `byperson` is guest-accurate (well-tagged names), while iTunes
    # title-search provides coverage for common-name / weakly-tagged people that
    # byperson returns only noise for. Neither alone is a superset of the other.
    return "both" if has_pi else "itunes"


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
        help="Discovery backend. 'auto' uses both when PodcastIndex secrets are set, else iTunes.",
    )
    args = parser.parse_args()

    # argparse runs the `type` converter, so default "24h" is already seconds.
    cutoff_seconds = args.since if isinstance(args.since, int) else parse_since(args.since)
    cutoff_ts = int(time.time()) - cutoff_seconds if cutoff_seconds > 0 else 0

    source = resolve_source(args.source)
    session = requests.Session()
    # Build the ordered backend list. PodcastIndex first so its richer metadata
    # wins on dedup; iTunes second for coverage. Scopes: byperson is already
    # person-accurate (match leniently across all text); iTunes term search is
    # broad, so normally require the name in the episode title. Explicit iTunes
    # guest queries can search descriptions but require an exact RSS guest tag.
    backends: list[tuple[str, Any, str]] = []
    if source in ("podcastindex", "both"):
        pi_key = os.environ["PODCASTINDEX_KEY"]
        pi_secret = os.environ["PODCASTINDEX_SECRET"]
        backends.append(
            ("podcastindex", lambda q: fetch_podcastindex(session, pi_key, pi_secret, q), "all")
        )
    if source in ("itunes", "both"):
        backends.append(("itunes", lambda q: fetch_itunes(session, q), "title"))

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
        # Re-apply current blocklists to already-stored episodes so tightened
        # rules retroactively purge news/digest noise (merge otherwise preserves
        # existing episodes verbatim, and capping would keep junk over interviews).
        existing_eps = [
            e for e in existing_eps
            if feed_allowed(e, person, defaults) and context_allowed(e, person)
        ]

        fresh = discover(backends, person, defaults, cutoff_ts, now_iso, session=session)
        max_episodes = person.get("max_episodes", defaults.get("max_episodes", 50))
        merged = merge_episodes(existing_eps, fresh, max_episodes)

        # Resolve each episode's source-podcast (collection) art so the player can
        # offer "podcast art" vs "episode art" without ever using the personality
        # cover. Only iTunes-sourced episodes carry a collection_id; PodcastIndex
        # episodes already include feedImage as podcast_artwork_url.
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
            # Tag language (declared feed language, else detected) so the player
            # can offer a per-language filter. Backfills onto pre-existing episodes
            # that were stored before language tagging existed.
            if not e.get("language"):
                e["language"] = detect_language(e)
            # Hosted shows are curated per personality. Tag each matching
            # episode with a stable id so clients can filter individual shows
            # without confusing them with guest appearances elsewhere.
            hosted_id = hosted_podcast_id(e, person)
            if hosted_id:
                e["hosted_podcast_id"] = hosted_id
            else:
                e.pop("hosted_podcast_id", None)

        artwork_url = artwork_url_for(pid)
        hosted_podcasts = public_hosted_podcasts(person)
        feed_payload = {
            "version": FEED_VERSION,
            "id": pid,
            "name": person["name"],
            "title": person.get("title", ""),
            "artwork_url": artwork_url,
            "updatedAt": today,
            "episodes": merged,
        }
        if hosted_podcasts:
            feed_payload["hosted_podcasts"] = hosted_podcasts
        wrote = write_json(feed_path, feed_payload)
        added = len(merged) - len(existing_eps)
        print(f"  {pid}: {len(fresh)} fresh, {len(merged)} total (+{added}){' [written]' if wrote else ''}")
        changed = changed or wrote

        if person.get("review_pending"):
            index_by_id.pop(pid, None)
        else:
            index_entry = {
                "id": pid,
                "name": person["name"],
                "aliases": person.get("aliases", []),
                "title": person.get("title", ""),
                "artwork_url": artwork_url,
                "feed_url": f"{SITE_BASE}/{pid}.json",
                "episode_count": len(merged),
                "handle_entity_id": person.get("handle_entity_id"),
            }
            if hosted_podcasts:
                index_entry["hosted_podcasts"] = hosted_podcasts
            index_by_id[pid] = index_entry

    # Rebuild the index in config order so it stays stable/diff-friendly.
    config_order = [p["id"] for p in config.get("personalities", [])]
    ordered_index = [index_by_id[i] for i in config_order if i in index_by_id]

    # Global set of languages present across ALL per-person feeds (scan every
    # file on disk, not just the ones refreshed this run, so a --only run keeps
    # the union complete). Drives the player's language picker; a language only
    # appears once at least one episode uses it.
    languages: set[str] = set()
    published_ids = set(index_by_id)
    for feed_file in PERSON_DIR.glob("*.json"):
        if feed_file.stem not in published_ids:
            continue
        feed_doc = load_json(feed_file)
        for e in feed_doc.get("episodes", []) if isinstance(feed_doc, dict) else []:
            lang = normalize_lang(e.get("language"))
            if lang:
                languages.add(lang)

    index_payload = {
        "version": FEED_VERSION,
        "updatedAt": today,
        "languages": sorted(languages),
        "personalities": ordered_index,
    }
    if write_json(INDEX_PATH, index_payload):
        changed = True

    print("Done." + ("" if changed else " No changes."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
