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

## Conventions

- Keep scripts runnable with plain `python3 script.py` from `luma_scraper/`.
- Never commit credentials (`.gitignore` already covers the usual names).
- Update this file at the end of every session that changes the repo.
