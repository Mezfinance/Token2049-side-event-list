#!/usr/bin/env python3
"""Step 1: fetch every event listed on the Luma TOKEN2049 calendar.

The public page https://luma.com/token2049?period=past is a Next.js app that
loads its list from Luma's JSON API, so we call that API directly instead of
rendering the page in a browser. Output is a JSON file with one record per
event (api_id, name, url, start/end, hosts as shown in the list view, etc.).

Usage:
    python3 fetch_events.py --out data/events.json [--year 2026] [--period past]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

CALENDAR_PAGE = "https://luma.com/token2049"
CALENDAR_API_ID = "cal-WfTOVDTJaAVqK3S"  # discovered from __NEXT_DATA__ on the page
API = "https://api.lu.ma/calendar/get-items"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) token2049-organiser-scraper/1.0",
    "Accept": "application/json",
}


def discover_calendar_id(session: requests.Session) -> str:
    """Read the calendar api_id from the public page so the script survives a change."""
    import re

    r = session.get(CALENDAR_PAGE, params={"period": "past"}, timeout=30)
    r.raise_for_status()
    m = re.search(r'"api_id":"(cal-[A-Za-z0-9]+)"', r.text)
    return m.group(1) if m else CALENDAR_API_ID


def fetch_all(session: requests.Session, calendar_id: str, period: str, delay: float) -> list[dict]:
    entries: list[dict] = []
    cursor: str | None = None
    page = 0
    while True:
        params = {
            "calendar_api_id": calendar_id,
            "period": period,
            "pagination_limit": 50,
        }
        if cursor:
            params["pagination_cursor"] = cursor
        for attempt in range(5):
            try:
                r = session.get(API, params=params, timeout=30)
                if r.status_code == 429:
                    raise requests.HTTPError("429 rate limited", response=r)
                r.raise_for_status()
                break
            except requests.RequestException as exc:  # retry with backoff
                wait = 2 ** attempt
                print(f"  page {page}: {exc}; retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
        else:
            raise SystemExit("gave up fetching calendar items")

        data = r.json()
        batch = data.get("entries", [])
        entries.extend(batch)
        page += 1
        print(f"  page {page}: +{len(batch)} (total {len(entries)})", file=sys.stderr)
        if not data.get("has_more") or not data.get("next_cursor") or not batch:
            break
        cursor = data["next_cursor"]
        time.sleep(delay)
    return entries


def simplify(entry: dict) -> dict:
    ev = entry["event"]
    cal = entry.get("calendar") or {}
    geo = ev.get("geo_address_info") or {}
    platform = entry.get("platform") or "luma"
    if platform == "external":
        # Submitted to the calendar but hosted off Luma: no event api_id, url is absolute.
        host = ev.get("host")
        return {
            "event_api_id": None,
            "calendar_entry_id": entry.get("api_id"),
            "platform": "external",
            "name": ev.get("name"),
            "url": ev.get("url"),
            "slug": None,
            "start_at": ev.get("start_at"),
            "end_at": None,
            "timezone": ev.get("timezone"),
            "city": geo.get("city") or geo.get("city_state"),
            "country": geo.get("country"),
            "location_type": "offline",
            "guest_count": None,
            "tags": [t.get("name") for t in entry.get("tags") or []],
            "calendar_name": None,
            "calendar_slug": None,
            "calendar_website": None,
            "calendar_is_personal": None,
            "list_hosts": [host] if isinstance(host, str) and host else
                          [host.get("name")] if isinstance(host, dict) else [],
        }
    return {
        "event_api_id": ev["api_id"],
        "calendar_entry_id": entry.get("api_id"),
        "platform": "luma",
        "name": ev.get("name"),
        "url": f"https://luma.com/{ev.get('url')}",
        "slug": ev.get("url"),
        "start_at": ev.get("start_at"),
        "end_at": ev.get("end_at"),
        "timezone": ev.get("timezone"),
        "city": geo.get("city"),
        "country": geo.get("country"),
        "location_type": ev.get("location_type"),
        "guest_count": entry.get("guest_count"),
        "tags": [t.get("name") for t in entry.get("tags") or []],
        "calendar_name": cal.get("name"),
        "calendar_slug": cal.get("slug"),
        "calendar_website": cal.get("website"),
        "calendar_is_personal": cal.get("is_personal"),
        "list_hosts": [h.get("name") for h in entry.get("hosts") or []],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/events.json")
    ap.add_argument("--year", type=int, default=2026, help="keep only events starting in this year")
    ap.add_argument("--period", default="past", choices=["past", "future"])
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between API pages")
    ap.add_argument("--raw", default=None, help="optional path to dump the raw API entries too")
    ap.add_argument("--from-raw", default=None, help="skip the network and rebuild from a raw dump")
    args = ap.parse_args()

    if args.from_raw:
        raw = json.loads(Path(args.from_raw).read_text())
        print(f"loaded {len(raw)} raw entries from {args.from_raw}", file=sys.stderr)
    else:
        s = requests.Session()
        s.headers.update(HEADERS)
        cal_id = discover_calendar_id(s)
        print(f"calendar {cal_id}, period={args.period}", file=sys.stderr)
        raw = fetch_all(s, cal_id, args.period, args.delay)
        if args.raw:
            Path(args.raw).parent.mkdir(parents=True, exist_ok=True)
            Path(args.raw).write_text(json.dumps(raw, indent=1))

    events = [simplify(e) for e in raw]
    if args.year:
        events = [e for e in events if (e["start_at"] or "").startswith(str(args.year))]
    # de-duplicate on event id (or calendar entry id for external events), keep chronological order
    seen: set[str] = set()
    uniq = []
    for e in sorted(events, key=lambda x: x["start_at"] or ""):
        key = e["event_api_id"] or e["calendar_entry_id"]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(uniq, indent=1, ensure_ascii=False))
    years = sorted({(e["start_at"] or "")[:4] for e in events})
    print(f"wrote {len(uniq)} events ({args.year or 'all years'}; raw had {len(raw)}, years seen {years}) -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
