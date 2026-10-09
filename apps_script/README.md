Use [the complete single-file script](Janani.gs) with [full replacement instructions](DEPLOY_COMPLETE.md) if you want all fixes together. The modular installation below remains available for an existing project.

# Fix the deployed V79 fuel-column mapping

The supplied V79 script maps only the header `Vehicle`. October uses `Vehicle No (Full)`, so `rowData` receives an empty value for that column despite Python sending `vehicle: "7412"`. The same header map omits `Timestamp`. V79's duplicate check also assumes fixed column positions, even though its row writer allows columns to move.

The helper in [fuel_header_fix.gs](fuel_header_fix.gs) recognizes both vehicle headers and common variants, records a timestamp when that column exists, and uses actual header positions for duplicate checks and text formatting. It serializes fuel writes with a script lock. Missing required headers or a missing vehicle fail rather than acknowledging a blank vehicle row. The helper reads `vehicle`, with fallback to `vehicle_id` or `vehicle_no`.

## Apply to your existing Apps Script project

1. Preserve a copy of your current script and spreadsheet.
2. Add a new script file named `fuel_header_fix` and paste the complete contents of `fuel_header_fix.gs` into it.
3. In the existing `doPost`, replace the contents of the **FUEL LOG - V79 FIXED COLUMN SHIFT** `else` branch with:

```javascript
    } else {
      return writeFuelReportV80_(
        data, targetSheet, monthName, dateForSheet, date, ss, params
      );
    }
```

The snippet shows the existing branch braces for context. Replace that branch once; keep the enclosing `try/catch`, `doPost`, bill branch, `doGet`, configuration IDs, and other functions. Do not leave the old fuel block after the return. The helper relies on the existing `FUEL_HEADERS_OLD` and `jsonResponseWithCallback` definitions.

4. Save, then select **Deploy → Manage deployments → Edit → Version: New version → Deploy** for the web-app deployment used by Python. Editing the same deployment preserves its URL. If you create a different deployment, update `webhook_url` in `sheet_config.json` to its URL.
5. On your next authorized sync, verify that vehicle `7412` appears in October's `Vehicle No (Full)` column and that the response reports `vehicleColumn: 3` for the current October layout.

Do not run a synthetic insert against the production spreadsheet as a test. The repository's mocked test sends the actual sample through Python and this helper without contacting Google or WhatsApp.

## Existing rows and scope

This fix applies to incoming records. Existing blank IDs and duplicate rows are not silently edited or deleted. Records already in Python's push history will not automatically replay; do not use `--force` indiscriminately to fill old rows. Existing rows with blank vehicle IDs cannot match a vehicle-aware duplicate check and may be duplicated if resent. Backfilling those rows needs a separate source-based reconciliation.

The vehicle-column helper changes only fuel writes. For missing bill dates and the V79 Drive folder/acknowledgment bugs, also apply the [bill-folder fix](BILL_FOLDERS.md). Dashboard behavior remains in your existing code. No live deployment or sheet changes are performed by committing these files.

## Local validation

```text
node --test tests/test_apps_script.cjs
```

The tests use mocked Apps Script services and the supplied October/September headers, including the actual WhatsApp report. They do not establish a live deployment or Google access.
