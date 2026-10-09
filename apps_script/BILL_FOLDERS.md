# Bill date folders and missing dates

The supplied logs show Python skipping image bills before any upload because it cannot determine their dates. The Python collector now reads message metadata and timestamp tooltips, then the closest preceding WhatsApp date separator outside message bodies. Numeric day/month/year separators, English named months, Today, Yesterday, and English weekday labels are supported. Relative labels use the browser's local calendar; weekday labels follow WhatsApp's convention of naming days within the previous week. Dates inside another message and separators after the bill are never borrowed. Image extraction is retried if an earlier attempt was empty, and missing date metadata can be filled when a later scroll reveals it.

A date in a bill caption takes precedence. Where neither the caption nor the visible message context supplies a reliable date, the bill remains skipped. Older messages without a visible separator or localized date labels not recognized by the collector may need a caption such as `Date-08/10/2026`. It does not assign today's date to undated bills.

## Install the Drive-side fix

The supplied V79 bill uploader ignores Python's `date_folder`, passes a two-digit-year folder name to Drive, falls back to the root or parent when folder operations fail, and can return success with an empty Drive link. Its early duplicate return can also block retrying a log row whose image never uploaded.

1. Keep a copy of the current Apps Script and spreadsheet.
2. Add a new Apps Script file named `bill_folder_fix` and paste [bill_folder_fix.gs](bill_folder_fix.gs) into it.
3. In the existing `doPost`, replace the contents of its `if(isBillLog)` branch with this call. Retain the existing fuel branch or the previously installed vehicle helper:

```javascript
    if (isBillLog) {
      return writeBillReportV81_(data, ss, params);
    } else {
      return writeFuelReportV80_(
        data, targetSheet, monthName, dateForSheet, date, ss, params
      );
    }
```

The snippet shows both branches for context. The fuel call requires the previously supplied `fuel_header_fix.gs`. If that helper is not installed, keep your existing fuel `else` branch instead. Leave the surrounding `try/catch` and the original configuration and dashboard functions intact. The new helper relies on `BILL_IMAGES_FOLDER_ID`, `BILL_LOG_SHEET_NAME`, and `jsonResponseWithCallback` from your existing script.

4. Confirm that `BILL_IMAGES_FOLDER_ID` identifies the intended parent folder and that the web-app execution account can create folders/files inside it.
5. Save and update the existing web-app deployment using **Deploy → Manage deployments → Edit → New version → Deploy**. Keep the same deployment URL; if it changes, update Python's `sheet_config.json`.
6. Pull the updated Python file onto Windows, then run the normal batch file. Previously skipped bills were not recorded as successful in local history, so they can be retried normally. Do not clear history or use `--force`.

A successful response must contain a Drive link, a file ID, a folder ID, and `dateFolder: "08-10-2026"` for an 8 October 2026 bill. The path is **configured parent folder → DD-MM-YYYY → bill image**. Drive permission, folder, checksum, and upload failures propagate to the existing `doPost` catch and return `success:false`, rather than recording a successful bill without an image.

## Retries and existing files

The helper verifies image bytes with SHA-256, preserves the image MIME type, and serializes bill writes with a script lock. A repeated upload reuses its existing file and log row. If the file was created but the sheet write failed, a retry recovers the file in the target folder. A matching old log entry with no link is repaired on a retry instead of being skipped.

For an existing referenced file whose bytes match the incoming image, a retry moves that same file into the requested date folder if necessary and retains its Drive URL. The response reports `moved:true`. Moving can change inherited folder access; the helper never deletes a file. It does not scan or reorganize every existing Drive file automatically. Invalid links, inaccessible files, conflicting image bytes, and duplicate date-folder names require reconciliation instead of silently making another copy. Different image encodings are not treated as identical merely because they look similar.

Already acknowledged bills in Python history are not automatically resent, even with `--force`. For historical bills that V79 acknowledged without an upload, or already misplaced files that are not being retried, use a separate reviewed reconciliation of Bill log and the original images/dates. Do not erase the entire history to attempt recovery.

V79's old `cleanupBillLogDuplicates` function deletes rows; it is not a folder repair and has not been invoked. Existing duplicate log rows are not deleted by this patch. Dashboard functions and other unrelated actions are retained.

## Tests

```text
node --test tests/test_bill_folders.cjs
```

The Apps Script tests use mocked Drive/Sheets services to verify folder names, calendar validation, access/upload failure handling, reuse, interrupted uploads, and relocation. Browser date tests can be run with the project Python after setting `JANANI_TEST_BROWSER` and `JANANI_TEST_DRIVER` to a compatible browser binary and driver:

```text
python -m unittest discover -s tests -v
```

Without those two variables, the browser-specific tests are skipped. A passing fixture does not establish live WhatsApp DOM compatibility, Drive permissions, or deployment; verify a real authorized bill after deployment.
