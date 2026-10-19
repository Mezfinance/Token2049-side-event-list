#!/usr/bin/env python3
"""Step 4: look for venues of location-less events in X (Twitter) posts.

For every event whose Luma venue is hidden or missing, search X for posts in
a window around the event date that mention the event (name keywords, host
X handles, organiser handle) and keep any post that looks like it names a
venue. Output is a JSON + CSV of candidate posts per event for a human to
confirm; nothing is written back to the organiser data automatically.

Credentials: set X_BEARER_TOKEN (an X API v2 app bearer token).

Endpoint note: /2/tweets/search/recent only covers the last 7 days. The
TOKEN2049 events ran 3-11 Oct 2026, so after 18 Oct you need the
full-archive endpoint (/2/tweets/search/all), which X only enables on the
Pro tier or above. Pass --archive to use it; without it the script uses the
recent endpoint and will find nothing for dates older than a week.

Usage:
    X_BEARER_TOKEN=... python3 search_x_locations.py --archive \
        --in data/organisers.json --out data/export/x_location_candidates.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

RECENT = "https://api.x.com/2/tweets/search/recent"
ARCHIVE = "https://api.x.com/2/tweets/search/all"

# words in a post that suggest it names a place
VENUE_HINTS = re.compile(
    r"\b(venue|location|address|located|at the|hotel|rooftop|bar|lounge|club|"
    r"restaurant|hall|theatre|theater|tower|marina|sentosa|orchard|raffles|"
    r"boulevard|blvd|street|st\.|road|rd\.|level \d|#\d{2}-\d{2}|singapore \d{6})\b",
    re.I,
)
STOPWORDS = {
    "the", "and", "of", "at", "in", "x", "a", "an", "to", "by", "with", "for", "on",
    "token2049", "token", "2049", "singapore", "sg", "event", "party", "night", "day",
    "private", "official", "side", "edition", "presents", "happy", "hour", "dinner",
    "brunch", "breakfast", "lunch", "mixer", "meetup", "networking", "2026", "week",
    "pre", "post", "after", "afters", "live", "meet", "up", "session", "summit",
    "drinks", "social", "hours", "exclusive", "vip", "invite", "only", "house",
}


def keywords(name: str, max_terms: int = 4) -> list[str]:
    """Pick the distinctive words of an event name for the X query."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'.&-]+", name)
    picked = []
    for w in words:
        lw = w.lower().strip(".'&-")
        if len(lw) < 3 or lw in STOPWORDS or lw in picked:
            continue
        picked.append(lw)
        if len(picked) == max_terms:
            break
    return picked


def build_query(ev: dict) -> str | None:
    handles = []
    for h in ev.get("hosts") or []:
        if h.get("twitter_handle"):
            handles.append("@" + h["twitter_handle"].lstrip("@"))
    cal = ev.get("calendar") or {}
    if cal.get("twitter_handle"):
        handles.append("@" + cal["twitter_handle"].lstrip("@"))
    handles = list(dict.fromkeys(handles))[:5]

    terms = keywords(ev.get("name") or "")
    parts = []
    if terms:
        # exact-ish phrase on the two most distinctive words, plus the rest loosely
        parts.append('"' + " ".join(terms[:2]) + '"' if len(terms) >= 2 else terms[0])
    if handles:
        parts.append("(" + " OR ".join(f"from:{h[1:]}" for h in handles) + ")")
    if not parts:
        return None
    q = " OR ".join(parts) if len(parts) > 1 else parts[0]
    q = f"({q}) (token2049 OR singapore OR venue OR location) -is:retweet"
    return q[:512]  # v2 query length cap on most tiers


def search(session: requests.Session, url: str, query: str, start: datetime, end: datetime,
           max_results: int) -> list[dict]:
    params = {
        "query": query,
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_results": max(10, min(max_results, 100)),
        "tweet.fields": "created_at,author_id,text,entities,public_metrics",
        "expansions": "author_id",
        "user.fields": "username,name",
    }
    for attempt in range(5):
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 429:
            reset = int(r.headers.get("x-rate-limit-reset", "0")) or 0
            wait = max(5, min(900, reset - int(time.time()))) if reset else 60 * (attempt + 1)
            print(f"  rate limited, sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        if r.status_code in (401, 403):
            raise SystemExit(f"X API {r.status_code}: {r.text[:300]}")
        r.raise_for_status()
        data = r.json()
        users = {u["id"]: u for u in (data.get("includes") or {}).get("users") or []}
        out = []
        for t in data.get("data") or []:
            u = users.get(t.get("author_id"), {})
            out.append({
                "id": t["id"],
                "url": f"https://x.com/{u.get('username', 'i')}/status/{t['id']}",
                "author": u.get("username"),
                "author_name": u.get("name"),
                "created_at": t.get("created_at"),
                "text": t.get("text"),
                "likes": (t.get("public_metrics") or {}).get("like_count"),
                "venue_hint": bool(VENUE_HINTS.search(t.get("text") or "")),
            })
        return out
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/organisers.json")
    ap.add_argument("--out", default="data/export/x_location_candidates.json")
    ap.add_argument("--archive", action="store_true", help="use /search/all (Pro tier) instead of /search/recent")
    ap.add_argument("--days-before", type=int, default=10)
    ap.add_argument("--days-after", type=int, default=2)
    ap.add_argument("--max-results", type=int, default=50)
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests")
    ap.add_argument("--limit", type=int, default=0, help="only the first N events (testing)")
    ap.add_argument("--dry-run", action="store_true", help="print the queries, call nothing")
    args = ap.parse_args()

    token = os.environ.get("X_BEARER_TOKEN")
    if not token and not args.dry_run:
        print("X_BEARER_TOKEN not set; relying on a proxy-injected credential for api.x.com",
              file=sys.stderr)

    events = json.loads(Path(args.inp).read_text())
    targets = [e for e in events
               if e.get("platform") != "external"
               and (e.get("venue_visibility") != "shown" or not e.get("address"))]
    if args.limit:
        targets = targets[: args.limit]
    print(f"{len(targets)} events without a public venue", file=sys.stderr)

    url = ARCHIVE if args.archive else RECENT
    now = datetime.now(timezone.utc)
    s = requests.Session()
    s.headers.update({"User-Agent": "token2049-venue-finder/1.0"})
    if token:
        s.headers["Authorization"] = f"Bearer {token}"

    results = []
    for i, ev in enumerate(targets, 1):
        q = build_query(ev)
        start_at = datetime.fromisoformat(ev["start_at"].replace("Z", "+00:00"))
        start = start_at - timedelta(days=args.days_before)
        end = min(start_at + timedelta(days=args.days_after), now - timedelta(seconds=30))
        rec = {
            "event_api_id": ev.get("event_api_id"),
            "name": ev.get("name"),
            "url": ev.get("url"),
            "start_at": ev.get("start_at"),
            "venue_visibility": ev.get("venue_visibility"),
            "query": q,
            "window": [start.isoformat(), end.isoformat()],
            "posts": [],
        }
        if args.dry_run or not q:
            results.append(rec)
            continue
        if not args.archive and start < now - timedelta(days=7):
            rec["note"] = "window older than 7 days; recent endpoint cannot see it (use --archive)"
        try:
            posts = search(s, url, q, start, end, args.max_results)
        except requests.RequestException as exc:
            rec["error"] = str(exc)
            posts = []
        posts.sort(key=lambda p: (not p["venue_hint"], -(p["likes"] or 0)))
        rec["posts"] = posts
        results.append(rec)
        print(f"[{i}/{len(targets)}] {ev['name'][:50]!r}: {len(posts)} posts, "
              f"{sum(p['venue_hint'] for p in posts)} with venue hints", file=sys.stderr)
        time.sleep(args.delay)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False))

    # flat CSV: one row per candidate post with a venue hint (plus a row per event with none)
    with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Event", "Luma link", "Event date", "Post URL", "Author", "Posted at", "Likes", "Post text"])
        for rec in results:
            hinted = [p for p in rec["posts"] if p["venue_hint"]] or rec["posts"][:3]
            if not hinted:
                w.writerow([rec["name"], rec["url"], rec["start_at"][:10], "", "", "", "", rec.get("note") or rec.get("error") or "no posts found"])
            for p in hinted:
                w.writerow([rec["name"], rec["url"], rec["start_at"][:10], p["url"], p["author"],
                            p["created_at"], p["likes"], " ".join((p["text"] or "").split())])
    found = sum(1 for r in results if any(p["venue_hint"] for p in r["posts"]))
    print(f"wrote {out} and {out.with_suffix('.csv')}: {found}/{len(results)} events have venue-hinting posts",
          file=sys.stderr)


if __name__ == "__main__":
    main()
