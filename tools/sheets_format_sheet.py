#!/usr/bin/env python3
"""
Rebuild the dashboard and chart_data tabs on the Mistake Log Google Sheet.

Run any time to refresh charts and stats after new data is logged.

What it does:
  - Reads all mistakes from the 'mistakes' tab
  - Splits data into writing vs speaking
  - Writes aggregations to 'chart_data' tab
  - Rebuilds 'dashboard' tab with:
      * Scorecard row (live formulas)
      * WRITING section: monthly column chart, type bar chart, severity donut
      * SPEAKING section: same three charts (empty until speaking data flows in)
      * Live QUERY tables: monthly breakdown + top patterns
  - Formats 'mistakes' tab (bold header, freeze, severity color-coding)
"""

import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _google_auth import get_credentials

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── helpers ───────────────────────────────────────────────────────────────────

def _rgb(r, g, b):
    return {"red": r / 255, "green": g / 255, "blue": b / 255}


def _cell_range(sheet_id, r0, r1, c0, c1):
    return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def _source_range(sheet_id, r0, r1, c0, c1):
    return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def _overlay(sheet_id, row, col, w, h):
    return {"overlayPosition": {
        "anchorCell": {"sheetId": sheet_id, "rowIndex": row, "columnIndex": col},
        "widthPixels": w, "heightPixels": h,
    }}


def get_sheet_ids(service, spreadsheet_id):
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    ids = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    cond_rules = {s["properties"]["sheetId"]: len(s.get("conditionalFormats", []))
                  for s in meta["sheets"]}
    return ids, cond_rules


def ensure_tab(service, spreadsheet_id, title, existing_ids):
    if title in existing_ids:
        return existing_ids[title]
    resp = service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()
    return resp["replies"][0]["addSheet"]["properties"]["sheetId"]


# ── data reading & aggregation ────────────────────────────────────────────────

MISTAKE_COLS = [
    "id", "date", "source", "source_ref", "original", "correction",
    "mistake_type", "tag", "explanation", "severity", "cefr_focus",
    "created_at", "naturalness_score",
]


def read_mistakes(service, spreadsheet_id):
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range="mistakes!A2:M"
    ).execute()
    out = []
    for row in result.get("values", []):
        d = {col: (row[i] if i < len(row) else "") for i, col in enumerate(MISTAKE_COLS)}
        out.append(d)
    return out


def _agg_group(items):
    monthly = defaultdict(int)
    by_type = Counter()
    by_severity = Counter()
    by_tag = Counter()
    for m in items:
        date = m.get("date", "")
        if date and len(date) >= 7:
            monthly[date[:7]] += 1
        t = m.get("mistake_type", "").strip()
        if t:
            by_type[t] += 1
        s = m.get("severity", "").strip()
        if s:
            by_severity[s] += 1
        tag = m.get("tag", "").strip()
        if tag:
            by_tag[tag] += 1
    return sorted(monthly.items()), by_type, by_severity, by_tag


def compute_aggregations(mistakes):
    writing = [m for m in mistakes if m.get("source") == "writing"]
    speaking = [m for m in mistakes if m.get("source") == "speaking"]
    return _agg_group(writing), _agg_group(speaking), len(writing), len(speaking)


# ── chart_data tab ────────────────────────────────────────────────────────────
#
# Column layout (gaps are empty separator columns):
#
#  Writing section                          Speaking section
#  A-B          D-E          G-H   J-K      M-N          P-Q          S-T   V-W
#  Writ.Monthly Writ.Type    Sev   Tags     Spk.Monthly  Spk.Type     Sev   Tags

def _section(header_pair, data_pairs):
    rows = [list(header_pair)]
    for a, b in data_pairs:
        rows.append([a, b])
    return rows


def _monthly_pairs(monthly):
    out = []
    for month_key, count in monthly:
        try:
            label = datetime.strptime(month_key, "%Y-%m").strftime("%b %Y")
        except ValueError:
            label = month_key
        out.append((label, count))
    return out


def write_chart_data(service, spreadsheet_id, w_agg, s_agg):
    w_monthly, w_type, w_sev, w_tag = w_agg
    s_monthly, s_type, s_sev, s_tag = s_agg

    sev_order = ["high", "medium", "low"]

    w_mon = _section(("Month", "Writing"), _monthly_pairs(w_monthly))
    w_typ = _section(("Type", "Count"), w_type.most_common())
    w_sv  = _section(("Severity", "Count"), [(s, w_sev[s]) for s in sev_order if s in w_sev])
    w_tg  = _section(("Pattern", "Count"), w_tag.most_common(15))

    s_mon = _section(("Month", "Speaking"), _monthly_pairs(s_monthly))
    s_typ = _section(("Type", "Count"), s_type.most_common() or [("no data", 0)])
    s_sv  = _section(("Severity", "Count"), [(s, s_sev[s]) for s in sev_order if s in s_sev] or [("no data", 0)])
    s_tg  = _section(("Pattern", "Count"), s_tag.most_common(15) or [("no data", 0)])

    max_len = max(len(x) for x in [w_mon, w_typ, w_sv, w_tg, s_mon, s_typ, s_sv, s_tg])
    for sec in [w_mon, w_typ, w_sv, w_tg, s_mon, s_typ, s_sv, s_tg]:
        while len(sec) < max_len:
            sec.append(["", ""])

    combined = []
    for i in range(max_len):
        combined.append(
            w_mon[i] + [""] + w_typ[i] + [""] + w_sv[i] + [""] + w_tg[i] +
            [""] +
            s_mon[i] + [""] + s_typ[i] + [""] + s_sv[i] + [""] + s_tg[i]
        )

    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range="chart_data!A1:Z500"
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="chart_data!A1",
        valueInputOption="USER_ENTERED", body={"values": combined},
    ).execute()

    # Column index map (0-based):
    # writing: monthly(0-1), sep(2), type(3-4), sep(5), sev(6-7), sep(8), tag(9-10)
    # gap(11)
    # speaking: monthly(12-13), sep(14), type(15-16), sep(17), sev(18-19), sep(20), tag(21-22)
    return {
        "w_mon_rows": len(w_mon), "w_typ_rows": len(w_typ),
        "w_sv_rows": len(w_sv), "w_tg_rows": len(w_tg),
        "s_mon_rows": len(s_mon), "s_typ_rows": len(s_typ),
        "s_sv_rows": len(s_sv), "s_tg_rows": len(s_tg),
    }


# ── dashboard cells ───────────────────────────────────────────────────────────

def write_dashboard_cells(service, spreadsheet_id, mistakes, n_writing, n_speaking):
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range="dashboard!A1:Z300"
    ).execute()

    dates = {m["date"] for m in mistakes if m.get("date")}
    last_date = max(dates) if dates else "—"

    rows = [
        # Row 1 — title
        ["ENGLISH LEARNING PROGRESS DASHBOARD"],
        # Row 2
        [f"Data through {last_date}   |   Re-run sheets_format_sheet.py to refresh charts"],
        [""],

        # Row 4 — overview scorecards
        ["OVERVIEW"],
        ["Total Mistakes",     f"{len(mistakes):,}",  "",
         "Days Practiced",     f'=COUNTUNIQUE(mistakes!B2:B)'],
        ["Writing Mistakes",   f"{n_writing:,}",       "",
         "Speaking Mistakes",  f"{n_speaking:,}"],
        ["High Severity",      f'=COUNTIF(mistakes!J2:J,"high")', "",
         "Last 7-Day Mistakes",
         '=COUNTIFS(mistakes!B2:B,">="&TEXT(TODAY()-7,"YYYY-MM-DD"),mistakes!B2:B,"<="&TEXT(TODAY(),"YYYY-MM-DD"))'],
        ["Unique Patterns",    f'=COUNTUNIQUE(mistakes!H2:H)', "",
         "Top Pattern",
         f'=IFERROR(INDEX(chart_data!D2:D,MATCH(MAX(chart_data!E2:E),chart_data!E2:E,0)),"—")'],
        [""],

        # Row 10 — WRITING section header (charts float over rows 10-30)
        ["✍️  WRITING ANALYSIS"],
        *[[""] for _ in range(22)],  # rows 11-32 reserved for 3 writing charts

        [""],
        # Row 34 — SPEAKING section header (charts float over rows 34-54)
        ["🎙️  SPEAKING ANALYSIS"],
        *[[""] for _ in range(22)],  # rows 35-56 reserved for 3 speaking charts

        [""],
        # Monthly breakdown
        ["MONTHLY BREAKDOWN  (Writing vs Speaking)"],
        ['=IFERROR(QUERY(mistakes!B2:C,"SELECT YEAR(Col1), MONTH(Col1), Col2, COUNT(Col1)'
         ' WHERE Col1 IS NOT NULL'
         ' GROUP BY YEAR(Col1), MONTH(Col1), Col2'
         ' ORDER BY YEAR(Col1), MONTH(Col1), Col2'
         ' LABEL YEAR(Col1) \'Year\', MONTH(Col1) \'Month\', Col2 \'Source\', COUNT(Col1) \'Mistakes\'",0),"no data")'],
        [""],

        # Top patterns
        ["TOP RECURRING PATTERNS"],
        ['=IFERROR(QUERY(mistakes!H2:J,"SELECT Col1, COUNT(Col1), Col3'
         ' WHERE Col1 <> \'\''
         ' GROUP BY Col1, Col3'
         ' ORDER BY COUNT(Col1) DESC'
         ' LIMIT 20'
         ' LABEL Col1 \'Pattern\', COUNT(Col1) \'Count\', Col3 \'Severity\'",0),"no data")'],
    ]

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="dashboard!A1",
        valueInputOption="USER_ENTERED", body={"values": rows},
    ).execute()


# ── chart management ──────────────────────────────────────────────────────────

def delete_all_charts(service, spreadsheet_id, sheet_id):
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    chart_ids = []
    for sheet in meta["sheets"]:
        if sheet["properties"]["sheetId"] == sheet_id:
            for chart in sheet.get("charts", []):
                chart_ids.append(chart["chartId"])
    if chart_ids:
        requests = [{"deleteEmbeddedObject": {"objectId": cid}} for cid in chart_ids]
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()
        print(f"  Deleted {len(chart_ids)} old chart(s).", file=sys.stderr)


def _column_chart(title, chart_data_id, dashboard_id, col_domain, col_series,
                  n_rows, anchor_row, anchor_col, color, w=500, h=260):
    return {"addChart": {"chart": {
        "spec": {
            "title": title,
            "titleTextFormat": {"bold": True, "fontSize": 11},
            "basicChart": {
                "chartType": "COLUMN",
                "legendPosition": "NO_LEGEND",
                "axis": [
                    {"position": "BOTTOM_AXIS", "title": "Month"},
                    {"position": "LEFT_AXIS",   "title": "Mistakes"},
                ],
                "domains": [{"domain": {"sourceRange": {"sources": [
                    _source_range(chart_data_id, 0, n_rows, col_domain, col_domain + 1)
                ]}}}],
                "series": [{"series": {"sourceRange": {"sources": [
                    _source_range(chart_data_id, 0, n_rows, col_series, col_series + 1)
                ]}}, "targetAxis": "LEFT_AXIS", "color": _rgb(*color)}],
                "headerCount": 1,
            },
        },
        "position": _overlay(dashboard_id, anchor_row, anchor_col, w, h),
    }}}


def _bar_chart(title, chart_data_id, dashboard_id, col_domain, col_series,
               n_rows, anchor_row, anchor_col, color, w=340, h=260):
    return {"addChart": {"chart": {
        "spec": {
            "title": title,
            "titleTextFormat": {"bold": True, "fontSize": 11},
            "basicChart": {
                "chartType": "BAR",
                "legendPosition": "NO_LEGEND",
                "axis": [
                    {"position": "BOTTOM_AXIS", "title": "Count"},
                    {"position": "LEFT_AXIS",   "title": "Type"},
                ],
                "domains": [{"domain": {"sourceRange": {"sources": [
                    _source_range(chart_data_id, 0, n_rows, col_domain, col_domain + 1)
                ]}}}],
                "series": [{"series": {"sourceRange": {"sources": [
                    _source_range(chart_data_id, 0, n_rows, col_series, col_series + 1)
                ]}}, "targetAxis": "BOTTOM_AXIS", "color": _rgb(*color)}],
                "headerCount": 1,
            },
        },
        "position": _overlay(dashboard_id, anchor_row, anchor_col, w, h),
    }}}


def _pie_chart(title, chart_data_id, dashboard_id, col_domain, col_series,
               n_rows, anchor_row, anchor_col, w=290, h=260):
    return {"addChart": {"chart": {
        "spec": {
            "title": title,
            "titleTextFormat": {"bold": True, "fontSize": 11},
            "pieChart": {
                "legendPosition": "RIGHT_LEGEND",
                "pieHole": 0.4,
                "domain": {"sourceRange": {"sources": [
                    _source_range(chart_data_id, 0, n_rows, col_domain, col_domain + 1)
                ]}},
                "series": {"sourceRange": {"sources": [
                    _source_range(chart_data_id, 0, n_rows, col_series, col_series + 1)
                ]}},
            },
        },
        "position": _overlay(dashboard_id, anchor_row, anchor_col, w, h),
    }}}


def add_charts(service, spreadsheet_id, dashboard_id, chart_data_id, rows):
    """
    Writing section anchored at dashboard row 10 (index 9).
    Speaking section anchored at dashboard row 34 (index 33).

    chart_data column map:
      Writing:  monthly(0,1)  type(3,4)  sev(6,7)  tags(9,10)
      Speaking: monthly(12,13) type(15,16) sev(18,19) tags(21,22)
    """
    W_ROW = 9   # writing charts anchor row
    S_ROW = 33  # speaking charts anchor row

    requests = [
        # ── Writing ──────────────────────────────────────────────────────────
        _column_chart("Writing: Mistakes Per Month",
                      chart_data_id, dashboard_id,
                      col_domain=0, col_series=1,
                      n_rows=rows["w_mon_rows"],
                      anchor_row=W_ROW, anchor_col=0,
                      color=(37, 99, 235)),

        _bar_chart("Writing: Mistakes by Type",
                   chart_data_id, dashboard_id,
                   col_domain=3, col_series=4,
                   n_rows=rows["w_typ_rows"],
                   anchor_row=W_ROW, anchor_col=7,
                   color=(16, 185, 129)),

        _pie_chart("Writing: Severity",
                   chart_data_id, dashboard_id,
                   col_domain=6, col_series=7,
                   n_rows=rows["w_sv_rows"],
                   anchor_row=W_ROW, anchor_col=12),

        # ── Speaking ─────────────────────────────────────────────────────────
        _column_chart("Speaking: Mistakes Per Month",
                      chart_data_id, dashboard_id,
                      col_domain=12, col_series=13,
                      n_rows=rows["s_mon_rows"],
                      anchor_row=S_ROW, anchor_col=0,
                      color=(124, 58, 237)),

        _bar_chart("Speaking: Mistakes by Type",
                   chart_data_id, dashboard_id,
                   col_domain=15, col_series=16,
                   n_rows=rows["s_typ_rows"],
                   anchor_row=S_ROW, anchor_col=7,
                   color=(245, 158, 11)),

        _pie_chart("Speaking: Severity",
                   chart_data_id, dashboard_id,
                   col_domain=18, col_series=19,
                   n_rows=rows["s_sv_rows"],
                   anchor_row=S_ROW, anchor_col=12),
    ]

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()
    print("  6 charts added (3 writing + 3 speaking).", file=sys.stderr)


# ── formatting ────────────────────────────────────────────────────────────────

def format_dashboard(service, spreadsheet_id, dashboard_id):
    requests = []

    def dark_header(row, font_size=14):
        requests.append({"repeatCell": {
            "range": _cell_range(dashboard_id, row, row + 1, 0, 12),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _rgb(15, 23, 42),
                "textFormat": {"bold": True, "fontSize": font_size,
                               "foregroundColor": _rgb(248, 250, 252)},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }})

    def section_header(row, color=(51, 65, 85)):
        requests.append({"repeatCell": {
            "range": _cell_range(dashboard_id, row, row + 1, 0, 12),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _rgb(*color),
                "textFormat": {"bold": True, "fontSize": 11,
                               "foregroundColor": _rgb(226, 232, 240)},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }})

    dark_header(0)       # title
    section_header(3)    # OVERVIEW
    section_header(9,  color=(29, 78, 216))   # WRITING  (blue)
    section_header(33, color=(109, 40, 217))  # SPEAKING (purple)
    section_header(57, color=(51, 65, 85))    # MONTHLY BREAKDOWN
    section_header(61, color=(51, 65, 85))    # TOP PATTERNS

    # Scorecard labels (col A, C)
    for col in [0, 3]:
        requests.append({"repeatCell": {
            "range": _cell_range(dashboard_id, 4, 8, col, col + 1),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _rgb(241, 245, 249),
                "textFormat": {"bold": True, "fontSize": 10},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }})

    # Scorecard values (col B, D)
    for col in [1, 4]:
        requests.append({"repeatCell": {
            "range": _cell_range(dashboard_id, 4, 8, col, col + 1),
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True, "fontSize": 13,
                               "foregroundColor": _rgb(37, 99, 235)},
            }},
            "fields": "userEnteredFormat(textFormat)",
        }})

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()


def format_mistakes_tab(service, spreadsheet_id, mistakes_id, existing_cond_count):
    requests = []

    if existing_cond_count > 0:
        for i in range(existing_cond_count - 1, -1, -1):
            requests.append({
                "deleteConditionalFormatRule": {"sheetId": mistakes_id, "index": i}
            })

    requests.append({"repeatCell": {
        "range": _cell_range(mistakes_id, 0, 1, 0, 13),
        "cell": {"userEnteredFormat": {
            "backgroundColor": _rgb(197, 224, 245),
            "textFormat": {"bold": True},
        }},
        "fields": "userEnteredFormat(backgroundColor,textFormat)",
    }})

    requests.append({"updateSheetProperties": {
        "properties": {"sheetId": mistakes_id,
                        "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount",
    }})

    for idx, (val, r, g, b) in enumerate([
        ("high",   255, 204, 204),
        ("medium", 255, 229, 153),
        ("low",    183, 225, 205),
    ]):
        requests.append({"addConditionalFormatRule": {
            "rule": {
                "ranges": [_cell_range(mistakes_id, 1, 999999, 9, 10)],
                "booleanRule": {
                    "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": val}]},
                    "format": {"backgroundColor": _rgb(r, g, b)},
                },
            },
            "index": idx,
        }})

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    load_dotenv(REPO_ROOT / ".env", override=True)
    sheet_id = os.getenv("GSHEET_MISTAKE_LOG_ID")
    if not sheet_id:
        print("GSHEET_MISTAKE_LOG_ID missing from .env", file=sys.stderr)
        sys.exit(1)

    try:
        creds = get_credentials()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    service = build("sheets", "v4", credentials=creds)

    print("Fetching sheet metadata...", file=sys.stderr)
    existing_ids, cond_rules = get_sheet_ids(service, sheet_id)

    mistakes_id = existing_ids.get("mistakes")
    if mistakes_id is None:
        print("ERROR: 'mistakes' tab not found.", file=sys.stderr)
        sys.exit(1)

    print("Reading mistakes data...", file=sys.stderr)
    mistakes = read_mistakes(service, sheet_id)
    print(f"  {len(mistakes)} rows loaded.", file=sys.stderr)

    print("Computing writing vs speaking aggregations...", file=sys.stderr)
    w_agg, s_agg, n_writing, n_speaking = compute_aggregations(mistakes)
    print(f"  Writing: {n_writing}  Speaking: {n_speaking}", file=sys.stderr)

    print("Ensuring tabs...", file=sys.stderr)
    dashboard_id = ensure_tab(service, sheet_id, "dashboard", existing_ids)
    existing_ids, _ = get_sheet_ids(service, sheet_id)
    chart_data_id = ensure_tab(service, sheet_id, "chart_data", existing_ids)

    print("Writing chart_data tab...", file=sys.stderr)
    rows = write_chart_data(service, sheet_id, w_agg, s_agg)

    print("Writing dashboard cells...", file=sys.stderr)
    write_dashboard_cells(service, sheet_id, mistakes, n_writing, n_speaking)

    print("Removing old charts...", file=sys.stderr)
    delete_all_charts(service, sheet_id, dashboard_id)

    print("Adding 6 new charts (writing + speaking)...", file=sys.stderr)
    add_charts(service, sheet_id, dashboard_id, chart_data_id, rows)

    print("Formatting dashboard...", file=sys.stderr)
    format_dashboard(service, sheet_id, dashboard_id)

    print("Formatting mistakes tab...", file=sys.stderr)
    format_mistakes_tab(service, sheet_id, mistakes_id, cond_rules.get(mistakes_id, 0))

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    print(f"\nDone! Open: {url}", file=sys.stderr)
    print(url)


if __name__ == "__main__":
    main()
