#!/usr/bin/env python3
"""Build a self-contained, local-only review dashboard for the personality feeds.

Reads the index (data/v1/personalities.json) and every per-person feed
(data/v1/personalities/<id>.json), embeds them as inline JSON, and writes a
single HTML file you can open directly in a browser (no server required):

    .venv/bin/python scripts/build_dashboard.py
    # then open personalities-dashboard.html

It is intended for eyeballing episode quality (titles, source, duration, art,
inline audio) before committing/pushing. The output is gitignored.
"""

from __future__ import annotations

import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DATA_DIR = REPO_ROOT / "data" / "v1"
PERSON_DIR = DATA_DIR / "personalities"
INDEX_PATH = DATA_DIR / "personalities.json"
OUT_PATH = REPO_ROOT / "personalities-dashboard.html"


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> int:
    index = load(INDEX_PATH)
    people = index.get("personalities", [])
    payload = []
    for p in people:
        feed = load(PERSON_DIR / f"{p['id']}.json")
        payload.append(
            {
                "id": p["id"],
                "name": p.get("name", p["id"]),
                "title": p.get("title", ""),
                "artwork_url": p.get("artwork_url", ""),
                "episode_count": p.get("episode_count", 0),
                "episodes": feed.get("episodes", []),
            }
        )

    # Resolve local art paths so thumbnails render offline (file://). Falls back
    # to the remote URL when a local PNG is missing.
    for person in payload:
        local_art = PERSON_DIR / "art" / f"{person['id']}.png"
        if local_art.exists():
            person["local_artwork"] = f"data/v1/personalities/art/{person['id']}.png"

    data_json = json.dumps(payload, ensure_ascii=False)
    total = sum(len(p["episodes"]) for p in payload)
    html = HTML_TEMPLATE.replace("__DATA__", data_json).replace("__TOTAL__", str(total)).replace(
        "__PEOPLE__", str(len(payload))
    )
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT_PATH}  ({len(payload)} personalities, {total} episodes)")
    print(f"Open it: file://{OUT_PATH}")
    return 0


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PodGod Personalities — Review Dashboard</title>
<style>
  :root {
    --bg: #0b0e17; --panel: #141a28; --panel2: #1b2233; --line: rgba(255,255,255,.08);
    --text: #e2e8f0; --muted: #8b97ad; --pink: #ff4d8d; --purple: #c850f2; --blue: #6c63ff;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text); display: flex; height: 100vh; overflow: hidden; }
  a { color: var(--blue); }
  .grad { background: linear-gradient(135deg, var(--pink), var(--purple), var(--blue));
    -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }

  /* Sidebar */
  aside { width: 290px; flex: 0 0 290px; background: var(--panel); border-right: 1px solid var(--line);
    display: flex; flex-direction: column; }
  aside header { padding: 16px; border-bottom: 1px solid var(--line); }
  aside header h1 { font-size: 18px; font-weight: 800; letter-spacing: .04em; }
  aside header .sub { color: var(--muted); font-size: 12px; margin-top: 4px; }
  .plist { overflow-y: auto; flex: 1; }
  .pitem { display: flex; align-items: center; gap: 10px; padding: 10px 14px; cursor: pointer;
    border-bottom: 1px solid rgba(255,255,255,.04); }
  .pitem:hover { background: var(--panel2); }
  .pitem.active { background: linear-gradient(90deg, rgba(200,80,242,.18), transparent); }
  .pitem img { width: 42px; height: 42px; border-radius: 8px; object-fit: cover; background: #222; }
  .pitem .nm { font-weight: 600; font-size: 14px; }
  .pitem .ct { color: var(--muted); font-size: 12px; }
  .badge { margin-left: auto; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px;
    background: var(--panel2); color: var(--muted); }

  /* Main */
  main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .topbar { padding: 14px 20px; border-bottom: 1px solid var(--line); display: flex; gap: 14px; align-items: center; }
  .topbar h2 { font-size: 20px; font-weight: 800; }
  .topbar .t { color: var(--muted); font-size: 13px; }
  .topbar input { margin-left: auto; background: var(--panel); border: 1px solid var(--line);
    color: var(--text); padding: 9px 12px; border-radius: 9px; width: 280px; font-size: 13px; }
  .eps { overflow-y: auto; padding: 16px 20px; flex: 1; }

  .ep { display: grid; grid-template-columns: 64px 64px 1fr; gap: 14px; padding: 14px;
    border: 1px solid var(--line); border-radius: 12px; margin-bottom: 12px; background: var(--panel); }
  .ep img { width: 64px; height: 64px; border-radius: 8px; object-fit: cover; background: #222; }
  .ep .art-label { font-size: 9px; color: var(--muted); text-align: center; margin-top: 3px; text-transform: uppercase; letter-spacing: .05em; }
  .ep .body { min-width: 0; }
  .ep .ti { font-weight: 700; font-size: 15px; line-height: 1.3; }
  .ep .meta { color: var(--muted); font-size: 12.5px; margin-top: 4px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .ep .pod { color: var(--text); font-weight: 600; }
  .chip { font-size: 10.5px; font-weight: 700; padding: 2px 7px; border-radius: 6px; text-transform: uppercase; letter-spacing: .04em; }
  .chip.pi { background: rgba(108,99,255,.18); color: #aab2ff; }
  .chip.it { background: rgba(255,77,141,.16); color: #ff9bc0; }
  .chip.dur { background: var(--panel2); color: var(--muted); }
  .chip.warn { background: rgba(255,176,32,.18); color: #ffce7a; }
  .chip.lang { background: rgba(34,197,94,.16); color: #86efac; }
  .chip.lang.nolang { background: rgba(255,176,32,.18); color: #ffce7a; }
  .ep .desc { color: var(--muted); font-size: 12.5px; margin-top: 8px; line-height: 1.45;
    max-height: 3.2em; overflow: hidden; cursor: pointer; }
  .ep .desc.open { max-height: none; }
  .ep audio { margin-top: 10px; width: 100%; height: 32px; }
  .ep .links { margin-top: 8px; font-size: 12px; display: flex; gap: 14px; }
  .empty { color: var(--muted); text-align: center; margin-top: 60px; }
</style>
</head>
<body>
<aside>
  <header>
    <h1 class="grad">POD GOD · REVIEW</h1>
    <div class="sub">__PEOPLE__ personalities · __TOTAL__ episodes · local only</div>
  </header>
  <div class="plist" id="plist"></div>
</aside>
<main>
  <div class="topbar">
    <h2 id="mainName">—</h2>
    <span class="t" id="mainTitle"></span>
    <input id="filter" placeholder="Filter episodes (title, podcast)…">
  </div>
  <div class="eps" id="eps"></div>
</main>

<script>
const DATA = __DATA__;
let current = DATA[0] ? DATA[0].id : null;

function fmtDur(s) {
  if (typeof s !== "number" || !s) return "?";
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
  return h ? `${h}h${String(m).padStart(2,"0")}` : `${m}m`;
}
function fmtDate(iso) { return iso ? String(iso).slice(0,10) : "?"; }
function esc(t){ return (t||"").replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

function renderSidebar() {
  const el = document.getElementById("plist");
  el.innerHTML = DATA.map(p => `
    <div class="pitem ${p.id===current?'active':''}" data-id="${p.id}">
      <img src="${p.local_artwork||p.artwork_url}" loading="lazy">
      <div><div class="nm">${esc(p.name)}</div><div class="ct">${esc(p.title)}</div></div>
      <span class="badge">${p.episodes.length}</span>
    </div>`).join("");
  el.querySelectorAll(".pitem").forEach(n =>
    n.onclick = () => { current = n.dataset.id; renderSidebar(); renderEpisodes(); });
}

function renderEpisodes() {
  const p = DATA.find(x => x.id === current);
  document.getElementById("mainName").textContent = p ? p.name : "—";
  document.getElementById("mainTitle").textContent = p ? `${p.title} · ${p.episodes.length} episodes` : "";
  const q = document.getElementById("filter").value.trim().toLowerCase();
  const eps = (p?.episodes||[]).filter(e =>
    !q || (e.title||"").toLowerCase().includes(q) || (e.podcast_title||"").toLowerCase().includes(q));
  const host = document.getElementById("eps");
  if (!eps.length) { host.innerHTML = `<div class="empty">No episodes${q?" match the filter":""}.</div>`; return; }
  host.innerHTML = eps.map(e => {
    const src = e.podcastindex_id ? '<span class="chip pi">PodcastIndex</span>'
              : e.itunes_id ? '<span class="chip it">iTunes</span>' : '';
    const noDur = (typeof e.duration !== "number" || !e.duration) ? '<span class="chip warn">no duration</span>' : '';
    const noAudio = !e.audio_url ? '<span class="chip warn">no audio</span>' : '';
    const lang = e.language
      ? `<span class="chip lang">${esc(e.language)}</span>`
      : '<span class="chip lang nolang">no lang</span>';
    return `
    <div class="ep">
      <div><img src="${e.artwork_url||''}" loading="lazy"><div class="art-label">episode</div></div>
      <div><img src="${e.podcast_artwork_url||''}" loading="lazy"><div class="art-label">podcast</div></div>
      <div class="body">
        <div class="ti">${esc(e.title)}</div>
        <div class="meta">
          <span class="pod">${esc(e.podcast_title||"?")}</span>
          <span>· ${fmtDate(e.pub_date)}</span>
          <span class="chip dur">${fmtDur(e.duration)}</span>
          ${lang} ${src} ${noDur} ${noAudio}
        </div>
        ${e.description ? `<div class="desc" onclick="this.classList.toggle('open')">${esc(e.description)}</div>` : ''}
        ${e.audio_url ? `<audio controls preload="none" src="${esc(e.audio_url)}"></audio>` : ''}
        <div class="links">
          ${e.episode_url ? `<a href="${esc(e.episode_url)}" target="_blank">episode link ↗</a>` : ''}
          ${e.audio_url ? `<a href="${esc(e.audio_url)}" target="_blank">audio ↗</a>` : ''}
        </div>
      </div>
    </div>`;
  }).join("");
}

document.getElementById("filter").addEventListener("input", renderEpisodes);
renderSidebar();
renderEpisodes();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
