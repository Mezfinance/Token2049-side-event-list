# CLAUDE.md

Context for anyone (human or Claude session) opening this repo cold. Read this
first, then `README.md`.

## What this repo is

A small Python pipeline that scrapes the Luma TOKEN2049 calendar
(https://luma.com/token2049?period=past), collects organiser details for every
side event, and writes them into Jerome's Google Sheet
"Copy of TOKEN2049 Week Singapore: Official Side Events Sheet"
(spreadsheet id `1Tf9P7iyCTdUmpbvztLMb6zPBfoHhWApxpSxDyn3jgx8`).

Owner: jerome@mezfi.com (MezFi). Purpose: a contact list of who runs
TOKEN2049 side events, for outreach.

## Layout

```
luma_scraper/
  fetch_events.py        step 1: paginate the calendar API -> data/events.json
  scrape_organisers.py   step 2: per-event API -> data/organisers.json (cached in data/cache/)
  export_rows.py         step 3a: flatten to CSV/JSON rows -> data/export/
  write_to_sheet.py      step 3b: gspread upload into two tabs of the sheet
  build_xlsx.py          step 3c: styled XLSX files with the TOKEN2049 Week banner
  search_x_locations.py  step 4a: X keyword search for venues of hidden-location events (needs X_BEARER_TOKEN + Pro tier)
  search_x_timelines.py  step 4b: same goal via each host's own timeline (Basic tier works; slow)
  assets/                token2049_week_banner.png (2048x228, extracted from the official sheet)
  requirements.txt
  data/                  committed snapshot of the last run (cache/ is git-ignored)
```

Styling used by `build_xlsx.py`, copied from the official sheet: header fill
`#073763` with white bold Calibri 12, date column fill `#6FA8DC`, pale blue
`#CFE2F3` for sub-headers. Banner sits in rows 1-3, title row 4, source note
row 5, header row 6, data from row 7, header frozen, autofilter on.

## Key facts discovered while building it

- Luma's web app is Next.js; the calendar page embeds `__NEXT_DATA__` with the
  calendar id `cal-WfTOVDTJaAVqK3S`. The list itself comes from
  `api.lu.ma/calendar/get-items` (50 per page, cursor pagination). No browser
  automation is needed.
- `api.lu.ma/event/get?event_api_id=...` returns the full event including all
  hosts (the list view truncates hosts). Host fields: name, username,
  bio_short, website, twitter/linkedin/instagram/tiktok/youtube handles.
- The `calendar` object on an event is the organisation that published it;
  `is_personal: true` means it is just a person's default calendar, so the
  export leaves the organisation blank in that case.
- `platform: "external"` entries have no Luma event id and an absolute `url`.
- `event.geo_address_info.mode` is `"shown"` (full_address public) or
  `"obfuscated"` (only city; address says "Singapore"). 2026 run: 133 shown,
  226 obfuscated, 3 external. Exported as the "Venue" / "Venue status" columns.
- X API v2: `search/recent` covers 7 days only; `search/all` (full archive)
  needs the Pro tier. The 2026 events (3-11 Oct) fell out of the recent window
  on 18 Oct, so the venue search needs `--archive` and a Pro-tier token.
- The past list covers several editions: 2023 (362 entries), 2024 (555),
  2025 (547), 2026 (362). Everything is filtered to `--year 2026` by default.
- The target sheet's existing tab "TOKEN2049 Week" is the official side-events
  list from the TOKEN2049 site (columns: Event ID, Date, Start, End, Event,
  Category, Price, Registration). It is left untouched; the scraper adds its
  own tabs "Luma Organisers" and "Luma Hosts".

## Session history

- 2026-10-18: first build. Scraped 362 events for the October 2026 Singapore
  edition (3 to 11 Oct; 359 on Luma, 3 external), zero fetch errors. Result:
  1,120 host entries, 864 unique host names; 862 hosts have an X handle, 823
  a LinkedIn URL, 486 a website; 214 events were published by a named
  organisation calendar (the rest by personal calendars). Output is in
  `luma_scraper/data/organisers.json` and `luma_scraper/data/export/`.
  The Claude session had Google Drive access but no Google Sheets connector,
  so the sheet write was left for `write_to_sheet.py` to run with the user's
  own credentials, or for a later session with the Sheets connector enabled.
  Next step when that is available: run step 3b (or write the two tabs via
  the connector from `data/export/rows.json`).
- 2026-10-18 (later): added `build_xlsx.py` and the banner asset on request,
  producing the two styled XLSX files in `luma_scraper/data/export/`.
  Verified by rendering page 1 of each through LibreOffice. No formulas in
  these workbooks, so no recalculation step is needed.
- 2026-10-19: added "Venue" and "Venue status" columns to every export and
  the XLSX files (addresses were already in the cache; no re-scrape). Wrote
  `search_x_locations.py` for the 226 hidden-venue events. Not run: the
  session had no X bearer token (api.x.com is reachable, returns 401 without
  one). To run it, the user adds `X_BEARER_TOKEN` to the cloud environment's
  secrets, then a new session runs step 4 with `--archive`.
- 2026-10-19 (later): user chose the host-timeline route. Added
  `search_x_timelines.py` (step 4b). Sizing: 226 hidden-venue events map to
  473 unique X handles; 13 events have no handle at all. Still no token in
  the environment, so it was dry-run only. Cache dir `data/cache_x/` is
  git-ignored. When a token exists: run step 4b, then review
  `data/export/x_timeline_candidates.csv` and copy confirmed venues into the
  export by hand (the script does not write venues back).
- 2026-10-19 (token attempt): user added the bearer token as a cloud
  environment network secret scoped to `x.com`. It did not reach the running
  session: no env var, and api.x.com still answered 401. Two things to know:
  the API host is `api.x.com` (not `x.com`), and environment secrets only
  load into a NEW session. Both X scripts now run without X_BEARER_TOKEN and
  rely on the proxy-injected credential when the variable is absent.
  After the user re-scoped the secret to `api.x.com` the proxy did inject it
  live (no new session needed): api.x.com answered 403 `client-not-enrolled`,
  meaning the X developer App is not attached to a Project. Fix is on the X
  developer portal (create a Project, add the App to it, regenerate the
  bearer token, update the secret). Then run step 4b.

## Conventions

- Keep scripts runnable with plain `python3 script.py` from `luma_scraper/`.
- Never commit credentials (`.gitignore` already covers the usual names).
- Update this file at the end of every session that changes the repo.
