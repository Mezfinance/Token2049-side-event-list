#!/usr/bin/env python3
"""Step 2: visit each event and collect organiser information.

Reads the events JSON produced by fetch_events.py, calls Luma's per-event
endpoint (the same data the event page renders from its __NEXT_DATA__), and
writes one JSON record per event with the full host list plus the calendar
(organisation) that published it. Results are cached per event so the script
can be re-run or interrupted without re-fetching everything.

Usage:
    python3 scrape_organisers.py --events data/events.json --out data/organisers.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

EVENT_API = "https://api.lu.ma/event/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) token2049-organiser-scraper/1.0",
    "Accept": "application/json",
}
HOST_FIELDS = (
    "api_id", "name", "username", "bio_short", "website",
    "twitter_handle", "linkedin_handle", "instagram_handle",
    "tiktok_handle", "youtube_handle", "is_verified", "avatar_url",
)
CAL_FIELDS = (
    "api_id", "name", "slug", "description_short", "website",
    "twitter_handle", "linkedin_handle", "instagram_handle",
    "tiktok_handle", "youtube_handle", "is_personal", "is_verified",
)


def fetch_event(session: requests.Session, event_api_id: str) -> dict | None:
    for attempt in range(5):
        try:
            r = session.get(EVENT_API, params={"event_api_id": event_api_id}, timeout=30)
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                raise requests.HTTPError("429 rate limited", response=r)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            wait = 2 ** attempt
            print(f"  {event_api_id}: {exc}; retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    print(f"  {event_api_id}: giving up", file=sys.stderr)
    return None


def description_text(d: dict) -> str:
    """Flatten Luma's TipTap description_mirror into plain text (best effort)."""
    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text" and node.get("text"):
                out.append(node["text"])
            for child in node.get("content") or []:
                walk(child)
            if node.get("type") in ("paragraph", "heading", "bulletList", "listItem"):
                out.append("\n")
        elif isinstance(node, list):
            for n in node:
                walk(n)

    walk(d.get("description_mirror") or {})
    return " ".join("".join(out).split())


def extract(event_record: dict, api: dict) -> dict:
    hosts = [{k: h.get(k) for k in HOST_FIELDS} for h in api.get("hosts") or []]
    cal = api.get("calendar") or {}
    personal_user = cal.get("personal_user") or {}
    calendar = {k: cal.get(k) for k in CAL_FIELDS}
    if cal.get("is_personal") and personal_user:
        calendar["personal_user_name"] = personal_user.get("name")
    ev = api.get("event") or {}
    geo = ev.get("geo_address_info") or {}
    return {
        **event_record,
        "fetched_from": f"{EVENT_API}?event_api_id={event_record['event_api_id']}",
        "guest_count": api.get("guest_count"),
        "address": geo.get("full_address") or geo.get("address"),
        "city": geo.get("city") or event_record.get("city"),
        "country": geo.get("country") or event_record.get("country"),
        "categories": [c.get("name") for c in api.get("categories") or [] if isinstance(c, dict)],
        "calendar": calendar,
        "hosts": hosts,
        "description": description_text(api)[:2000],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="data/events.json")
    ap.add_argument("--out", default="data/organisers.json")
    ap.add_argument("--cache", default="data/cache", help="directory for per-event raw API responses")
    ap.add_argument("--delay", type=float, default=0.7, help="seconds between requests")
    ap.add_argument("--limit", type=int, default=0, help="only process the first N events (testing)")
    args = ap.parse_args()

    events = json.loads(Path(args.events).read_text())
    if args.limit:
        events = events[: args.limit]
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)

    s = requests.Session()
    s.headers.update(HEADERS)

    results: list[dict] = []
    fetched = 0
    for i, e in enumerate(events, 1):
        if not e.get("event_api_id"):
            # external (non-Luma) listing: nothing to visit, keep what the calendar gave us
            results.append({**e, "hosts": [{"name": h} for h in e.get("list_hosts") or []],
                            "calendar": None, "description": "", "address": None, "categories": []})
            continue
        cpath = cache / f"{e['event_api_id']}.json"
        if cpath.exists():
            api = json.loads(cpath.read_text())
        else:
            api = fetch_event(s, e["event_api_id"])
            if api is None:
                print(f"[{i}/{len(events)}] {e['name']!r}: no data", file=sys.stderr)
                results.append({**e, "hosts": [], "calendar": None, "error": "not found"})
                time.sleep(args.delay)
                continue
            cpath.write_text(json.dumps(api))
            fetched += 1
            time.sleep(args.delay)
        rec = extract(e, api)
        results.append(rec)
        if i % 25 == 0 or i == len(events):
            print(f"[{i}/{len(events)}] done ({fetched} fetched this run)", file=sys.stderr)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    n_hosts = sum(len(r.get("hosts") or []) for r in results)
    print(f"wrote {len(results)} events with {n_hosts} host entries -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
