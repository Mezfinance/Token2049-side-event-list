# TOKEN2049 side-event organiser scraper

Collects every side event listed on the Luma TOKEN2049 calendar
(https://luma.com/token2049?period=past), visits each event and records who
organised it (hosts and the publishing calendar, with websites and socials),
then pushes the result into an existing Google Sheet as two new tabs.

## Pipeline

| Step | Script | Input | Output |
|---|---|---|---|
| 1. List events | `luma_scraper/fetch_events.py` | Luma calendar API | `data/events.json` |
| 2. Organisers | `luma_scraper/scrape_organisers.py` | `data/events.json` | `data/organisers.json` (+ `data/cache/` raw API responses) |
| 3a. Flatten | `luma_scraper/export_rows.py` | `data/organisers.json` | `data/export/events.csv`, `hosts.csv`, `rows.json` |
| 3b. Sheet | `luma_scraper/write_to_sheet.py` | `data/export/rows.json` | tabs "Luma Organisers" and "Luma Hosts" in the Google Sheet |

```bash
cd luma_scraper
pip install -r requirements.txt
python3 fetch_events.py --year 2026 --out data/events.json
python3 scrape_organisers.py --events data/events.json --out data/organisers.json
python3 export_rows.py --in data/organisers.json --out-dir data/export
python3 write_to_sheet.py --spreadsheet-id <sheet id> --service-account key.json
```

Steps 1 to 3a need no credentials. Step 2 caches every raw event response in
`data/cache/`, so re-running it is instant and an interrupted run resumes.

## How the data is fetched

The Luma calendar page is a Next.js app that loads its list from Luma's public
JSON API, so the scripts call that API directly instead of driving a browser:

- `GET https://api.lu.ma/calendar/get-items?calendar_api_id=cal-WfTOVDTJaAVqK3S&period=past&pagination_limit=50`
  (paginated with `pagination_cursor`). The calendar id is re-read from the
  page's `__NEXT_DATA__` on every run in case it changes.
- `GET https://api.lu.ma/event/get?event_api_id=evt-...` for each event. This
  is the same payload the event page renders, including the full host list
  with bio, website, X, LinkedIn and Instagram handles.

Entries with `platform: external` were submitted to the calendar but are hosted
off Luma (for example the main conference). They are kept in the list with
their own URL and no host detail.

## Google Sheet

`write_to_sheet.py` authenticates with either a Google service account key
(share the sheet with the service account's email as an editor) or an OAuth
client secret. Credentials are git-ignored. The script only adds or replaces its
own two tabs and never touches the sheet's existing tabs.

## Data snapshot

`luma_scraper/data/` holds the JSON and CSV output of the last run so the
results can be inspected without re-scraping. See `CLAUDE.md` for run details.
