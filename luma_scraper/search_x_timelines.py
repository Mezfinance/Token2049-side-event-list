#!/usr/bin/env python3
"""Step 4b: look for venues in the hosts' own X timelines.

Unlike /2/tweets/search/recent (7-day window) the user-timeline endpoint
(/2/users/:id/tweets) returns a user's recent posts with start_time/end_time
filters and no 7-day cap, so it works on the Basic tier. For every host (and
organiser calendar) with an X handle on a hidden-venue event, this pulls their
posts in a window around their events and keeps the ones that mention the
event and/or a venue-like word.

Credentials: X_BEARER_TOKEN (X API v2 app bearer token).

Rate limits (per app, per 15 min): Basic tier allows about 10 timeline reads
and 300 username lookups; Pro allows 1500 timeline reads. With 473 handles a
Basic-tier run takes roughly 12 hours; the script sleeps on 429 and caches
every response, so it can be stopped and resumed.

Usage:
    X_BEARER_TOKEN=... python3 search_x_timelines.py \
        --in data/organisers.json --out data/export/x_timeline_candidates.json
    python3 search_x_timelines.py --dry-run     # list handles and windows, call nothing
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

from search_x_locations import VENUE_HINTS, keywords  # same folder; shared helpers

API = "https://api.x.com/2"
TWEET_FIELDS = "created_at,text,entities,public_metrics,referenced_tweets"
POSTCODE = re.compile(r"\bSingapore\s+\d{6}\b|\b\d{6}\b", re.I)


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def api_get(session: requests.Session, path: str, params: dict) -> dict:
    """GET with 429 handling (sleep until the window resets) and basic retries."""
    for attempt in range(8):
        r = session.get(f"{API}{path}", params=params, timeout=30)
        if r.status_code == 429:
            reset = int(r.headers.get("x-rate-limit-reset") or 0)
            wait = max(5, min(960, reset - int(time.time()) + 2)) if reset else 60 * (attempt + 1)
            print(f"  rate limited on {path}; sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        if r.status_code in (401, 403):
            raise SystemExit(f"X API {r.status_code} on {path}: {r.text[:300]}")
        if r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"gave up on {path}")


def collect_targets(events: list[dict]) -> tuple[list[dict], dict[str, list[dict]]]:
    """Hidden-venue events, and handle -> list of those events."""
    hidden = [e for e in events
              if e.get("platform") != "external"
              and (e.get("venue_visibility") != "shown" or not e.get("address"))]
    by_handle: dict[str, list[dict]] = {}
    for e in hidden:
        handles = {h["twitter_handle"].lstrip("@").lower()
                   for h in e.get("hosts") or [] if h.get("twitter_handle")}
        cal = (e.get("calendar") or {}).get("twitter_handle")
        if cal:
            handles.add(cal.lstrip("@").lower())
        for h in handles:
            by_handle.setdefault(h, []).append(e)
    return hidden, by_handle


def resolve_users(session, handles: list[str], cache_file: Path) -> dict[str, dict]:
    users = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    todo = [h for h in handles if h not in users]
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        data = api_get(session, "/users/by", {"usernames": ",".join(batch), "user.fields": "id,username,name"})
        for u in data.get("data") or []:
            users[u["username"].lower()] = {"id": u["id"], "username": u["username"], "name": u.get("name")}
        for err in data.get("errors") or []:
            missing = (err.get("value") or "").lower()
            if missing:
                users[missing] = {"id": None, "error": err.get("detail") or err.get("title")}
        cache_file.write_text(json.dumps(users, indent=1))
        print(f"  resolved {min(i + 100, len(todo))}/{len(todo)} handles", file=sys.stderr)
    return users


def fetch_timeline(session, user_id: str, start: datetime, end: datetime, max_pages: int,
                   cache_file: Path) -> list[dict]:
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    tweets: list[dict] = []
    token = None
    for _ in range(max_pages):
        params = {
            "start_time": fmt_ts(start), "end_time": fmt_ts(end), "max_results": 100,
            "exclude": "retweets", "tweet.fields": TWEET_FIELDS,
        }
        if token:
            params["pagination_token"] = token
        data = api_get(session, f"/users/{user_id}/tweets", params)
        tweets.extend(data.get("data") or [])
        token = (data.get("meta") or {}).get("next_token")
        if not token:
            break
    cache_file.write_text(json.dumps(tweets))
    return tweets


def score(tweet: dict, event: dict, terms: list[str]) -> tuple[int, bool, bool]:
    text = (tweet.get("text") or "").lower()
    overlap = sum(1 for t in terms if t in text)
    hint = bool(VENUE_HINTS.search(text))
    postcode = bool(POSTCODE.search(text))
    return overlap, hint, postcode


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/organisers.json")
    ap.add_argument("--out", default="data/export/x_timeline_candidates.json")
    ap.add_argument("--cache", default="data/cache_x", help="cached user lookups and timelines (git-ignored)")
    ap.add_argument("--days-before", type=int, default=10)
    ap.add_argument("--days-after", type=int, default=2)
    ap.add_argument("--max-pages", type=int, default=2, help="timeline pages of 100 per host")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--limit", type=int, default=0, help="only the first N handles (testing)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("X_BEARER_TOKEN")
    if not token and not args.dry_run:
        # In the Claude cloud environment a "network secret" for api.x.com is added by the
        # proxy, not exposed as a variable, so carry on without our own header; a 401 is
        # reported below if nothing authenticates the call.
        print("X_BEARER_TOKEN not set; relying on a proxy-injected credential for api.x.com",
              file=sys.stderr)

    events = json.loads(Path(args.inp).read_text())
    hidden, by_handle = collect_targets(events)
    # hosts tied to the most events first, so a partial run covers the most ground
    handles = sorted(by_handle, key=lambda h: -len(by_handle[h]))
    if args.limit:
        handles = handles[: args.limit]
    print(f"{len(hidden)} hidden-venue events, {len(by_handle)} handles "
          f"({sum(1 for e in hidden if not any(e in v for v in by_handle.values()))} events have no handle)",
          file=sys.stderr)

    windows = {}
    for h in handles:
        starts = [parse_ts(e["start_at"]) for e in by_handle[h]]
        windows[h] = (min(starts) - timedelta(days=args.days_before),
                      max(starts) + timedelta(days=args.days_after))

    if args.dry_run:
        for h in handles[:15]:
            s, e = windows[h]
            print(f"  @{h}: {len(by_handle[h])} event(s), window {s.date()} -> {e.date()}", file=sys.stderr)
        print(f"  ... {len(handles)} handles in total; Basic tier ~{len(handles) * 1.5 / 60:.1f} h at 10 reads/15 min",
              file=sys.stderr)
        return

    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": "token2049-venue-finder/1.0"})
    if token:
        s.headers["Authorization"] = f"Bearer {token}"

    users = resolve_users(s, handles, cache / "users.json")
    now = datetime.now(timezone.utc) - timedelta(seconds=30)

    per_event: dict[str, dict] = {}
    for e in hidden:
        key = e.get("event_api_id") or e.get("calendar_entry_id")
        per_event[key] = {
            "event_api_id": e.get("event_api_id"), "name": e.get("name"), "url": e.get("url"),
            "start_at": e.get("start_at"), "venue_visibility": e.get("venue_visibility"),
            "handles_checked": [], "posts": [],
        }

    for i, h in enumerate(handles, 1):
        u = users.get(h) or {}
        if not u.get("id"):
            print(f"[{i}/{len(handles)}] @{h}: not found on X", file=sys.stderr)
            continue
        start, end = windows[h]
        tweets = fetch_timeline(s, u["id"], start, min(end, now), args.max_pages, cache / f"tl_{u['id']}.json")
        kept = 0
        for e in by_handle[h]:
            key = e.get("event_api_id") or e.get("calendar_entry_id")
            per_event[key]["handles_checked"].append(h)
            terms = keywords(e.get("name") or "", max_terms=6)
            ev_start = parse_ts(e["start_at"])
            lo, hi = ev_start - timedelta(days=args.days_before), ev_start + timedelta(days=args.days_after)
            for t in tweets:
                created = parse_ts(t["created_at"])
                if not (lo <= created <= hi):
                    continue
                overlap, hint, postcode = score(t, e, terms)
                if overlap == 0 and not postcode:
                    continue  # unrelated post, or venue words with no link to this event
                per_event[key]["posts"].append({
                    "id": t["id"], "url": f"https://x.com/{u['username']}/status/{t['id']}",
                    "author": u["username"], "created_at": t["created_at"],
                    "text": " ".join((t.get("text") or "").split()),
                    "likes": (t.get("public_metrics") or {}).get("like_count"),
                    "keyword_overlap": overlap, "venue_hint": hint, "postcode": postcode,
                })
                kept += 1
        print(f"[{i}/{len(handles)}] @{h}: {len(tweets)} posts in window, {kept} matched", file=sys.stderr)
        time.sleep(args.delay)

    results = list(per_event.values())
    for rec in results:
        rec["posts"].sort(key=lambda p: (-(p["venue_hint"] or p["postcode"]), -p["keyword_overlap"], -(p["likes"] or 0)))
        rec["handles_checked"] = sorted(set(rec["handles_checked"]))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Event", "Luma link", "Event date", "Handles checked", "Post URL", "Author",
                    "Posted at", "Likes", "Venue hint", "Post text"])
        for rec in results:
            top = [p for p in rec["posts"] if p["venue_hint"] or p["postcode"]] or rec["posts"][:3]
            if not top:
                w.writerow([rec["name"], rec["url"], rec["start_at"][:10], ", ".join(rec["handles_checked"]),
                            "", "", "", "", "", "no matching posts" if rec["handles_checked"] else "no X handle"])
            for p in top:
                w.writerow([rec["name"], rec["url"], rec["start_at"][:10], ", ".join(rec["handles_checked"]),
                            p["url"], p["author"], p["created_at"], p["likes"],
                            "yes" if (p["venue_hint"] or p["postcode"]) else "", p["text"]])
    found = sum(1 for r in results if any(p["venue_hint"] or p["postcode"] for p in r["posts"]))
    print(f"wrote {out} and {out.with_suffix('.csv')}: {found}/{len(results)} events have venue-hinting posts",
          file=sys.stderr)


if __name__ == "__main__":
    main()
