#!/usr/bin/env python3
"""Step 3b: push the exported rows into an existing Google Sheet.

Adds (or replaces) two tabs in the spreadsheet: "Luma Organisers" (one row per
event) and "Luma Hosts" (one row per host). Existing tabs are left untouched.

Authentication, one of:
  * a service-account JSON key: --service-account key.json
    (share the spreadsheet with the service account's email as an editor)
  * OAuth client credentials:  --oauth-client client_secret.json
    (opens a browser the first time; token cached in ~/.config/gspread/)

Usage:
    python3 write_to_sheet.py --spreadsheet-id 1Tf9P7iy...jgx8 \
        --rows data/export/rows.json --service-account key.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import gspread

DEFAULT_SPREADSHEET_ID = "1Tf9P7iyCTdUmpbvztLMb6zPBfoHhWApxpSxDyn3jgx8"
TABS = {"events": "Luma Organisers", "hosts": "Luma Hosts"}


def client(args) -> gspread.Client:
    if args.service_account:
        return gspread.service_account(filename=args.service_account)
    if args.oauth_client:
        return gspread.oauth(credentials_filename=args.oauth_client)
    raise SystemExit("pass --service-account key.json or --oauth-client client_secret.json")


def upsert_tab(sh: gspread.Spreadsheet, title: str, columns: list[str], rows: list[list]) -> None:
    n_rows = len(rows) + 1
    n_cols = len(columns)
    try:
        ws = sh.worksheet(title)
        ws.clear()
        ws.resize(rows=max(n_rows, 2), cols=n_cols)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=max(n_rows, 2), cols=n_cols)
    # value_input_option RAW keeps handles/IDs as text instead of letting Sheets guess
    ws.update(range_name="A1", values=[columns] + rows, value_input_option="RAW")
    ws.freeze(rows=1)
    ws.format(f"A1:{gspread.utils.rowcol_to_a1(1, n_cols)}", {"textFormat": {"bold": True}})
    print(f"wrote {len(rows)} rows x {n_cols} cols to tab {title!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spreadsheet-id", default=DEFAULT_SPREADSHEET_ID)
    ap.add_argument("--rows", default="data/export/rows.json")
    ap.add_argument("--service-account", default=None)
    ap.add_argument("--oauth-client", default=None)
    ap.add_argument("--only", choices=list(TABS), default=None, help="write just one of the tabs")
    args = ap.parse_args()

    data = json.loads(Path(args.rows).read_text())
    gc = client(args)
    sh = gc.open_by_key(args.spreadsheet_id)
    print(f"opened {sh.title!r}")
    for key, title in TABS.items():
        if args.only and key != args.only:
            continue
        upsert_tab(sh, title, data[key]["columns"], data[key]["rows"])


if __name__ == "__main__":
    main()
