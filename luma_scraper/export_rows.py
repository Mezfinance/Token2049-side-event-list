#!/usr/bin/env python3
"""Step 3a: flatten organiser records into spreadsheet rows (CSV + JSON).

Two layouts are produced:
  * events view  - one row per event, hosts joined into one cell each
  * hosts view   - one row per (event, host) pair, for filtering by person/org

Usage:
    python3 export_rows.py --in data/organisers.json --out-dir data/export
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

EVENT_COLUMNS = [
    "Date", "Start", "End", "Event", "Venue", "Venue status", "Luma link", "Platform", "Tags",
    "Organising calendar", "Calendar website", "Calendar X", "Calendar LinkedIn",
    "Hosts", "Host bios", "Host websites", "Host X handles", "Host LinkedIn",
    "Host Instagram", "Host count", "Guest count", "City", "Country", "Event ID",
]
HOST_COLUMNS = [
    "Date", "Event", "Venue", "Luma link", "Host name", "Host username", "Host bio",
    "Host website", "Host X", "Host LinkedIn", "Host Instagram", "Host TikTok",
    "Host YouTube", "Verified", "Organising calendar", "Calendar website", "Event ID",
]


def local(ts: str | None, tz: str | None, fmt: str) -> str:
    if not ts:
        return ""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    try:
        dt = dt.astimezone(ZoneInfo(tz or "Asia/Singapore"))
    except Exception:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime(fmt)


def x_url(handle: str | None) -> str:
    return f"https://x.com/{handle.lstrip('@')}" if handle else ""


def li_url(handle: str | None) -> str:
    if not handle:
        return ""
    h = handle.strip()
    if h.startswith("http"):
        return h
    return "https://www.linkedin.com/" + h.lstrip("/")


def ig_url(handle: str | None) -> str:
    return f"https://instagram.com/{handle.lstrip('@')}" if handle else ""


def joined(items, sep="; "):
    return sep.join(i for i in items if i)


VENUE_STATUS = {
    "shown": "Public",
    "obfuscated": "Hidden until registered",
    None: "Not set",
}


def venue(r: dict) -> str:
    """Street address when Luma shows it; blank when hidden or missing."""
    addr = r.get("address") or ""
    # an obfuscated event still reports "Singapore" as its address; treat that as no venue
    if r.get("venue_visibility") != "shown" and addr.strip().lower() in ("", "singapore"):
        return ""
    return addr


def venue_status(r: dict) -> str:
    if r.get("platform") == "external":
        return "External listing"
    return VENUE_STATUS.get(r.get("venue_visibility"), "Not set")


def event_row(r: dict) -> list:
    hosts = r.get("hosts") or []
    cal = r.get("calendar") or {}
    tz = r.get("timezone")
    return [
        local(r.get("start_at"), tz, "%a %d %b %Y"),
        local(r.get("start_at"), tz, "%H:%M"),
        local(r.get("end_at"), tz, "%H:%M"),
        r.get("name") or "",
        venue(r),
        venue_status(r),
        r.get("url") or "",
        r.get("platform") or "luma",
        joined(r.get("tags") or [], ", "),
        "" if cal.get("is_personal") else (cal.get("name") or ""),
        cal.get("website") or "",
        x_url(cal.get("twitter_handle")),
        li_url(cal.get("linkedin_handle")),
        joined(h.get("name") for h in hosts),
        joined((h.get("bio_short") or "").strip() for h in hosts),
        joined(h.get("website") for h in hosts),
        joined(x_url(h.get("twitter_handle")) for h in hosts),
        joined(li_url(h.get("linkedin_handle")) for h in hosts),
        joined(ig_url(h.get("instagram_handle")) for h in hosts),
        len(hosts),
        r.get("guest_count") if r.get("guest_count") is not None else "",
        r.get("city") or "",
        r.get("country") or "",
        r.get("event_api_id") or r.get("calendar_entry_id") or "",
    ]


def host_rows(r: dict) -> list[list]:
    cal = r.get("calendar") or {}
    tz = r.get("timezone")
    rows = []
    for h in r.get("hosts") or []:
        rows.append([
            local(r.get("start_at"), tz, "%a %d %b %Y"),
            r.get("name") or "",
            venue(r),
            r.get("url") or "",
            h.get("name") or "",
            h.get("username") or "",
            (h.get("bio_short") or "").strip(),
            h.get("website") or "",
            x_url(h.get("twitter_handle")),
            li_url(h.get("linkedin_handle")),
            ig_url(h.get("instagram_handle")),
            h.get("tiktok_handle") or "",
            h.get("youtube_handle") or "",
            "yes" if h.get("is_verified") else "",
            "" if cal.get("is_personal") else (cal.get("name") or ""),
            cal.get("website") or "",
            r.get("event_api_id") or r.get("calendar_entry_id") or "",
        ])
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/organisers.json")
    ap.add_argument("--out-dir", default="data/export")
    args = ap.parse_args()

    records = json.loads(Path(args.inp).read_text())
    records.sort(key=lambda r: (r.get("start_at") or "", r.get("name") or ""))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    ev_rows = [event_row(r) for r in records]
    ho_rows = [row for r in records for row in host_rows(r)]

    with (out / "events.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(EVENT_COLUMNS)
        w.writerows(ev_rows)
    with (out / "hosts.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HOST_COLUMNS)
        w.writerows(ho_rows)
    (out / "rows.json").write_text(json.dumps({
        "events": {"columns": EVENT_COLUMNS, "rows": ev_rows},
        "hosts": {"columns": HOST_COLUMNS, "rows": ho_rows},
    }, ensure_ascii=False))
    print(f"{len(ev_rows)} event rows, {len(ho_rows)} host rows -> {out}/")


if __name__ == "__main__":
    main()
