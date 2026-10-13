# Fixed bill folders — V84

Use the complete [Janani.gs](Janani.gs) and [deployment instructions](DEPLOY_COMPLETE.md).

| OCR category | Path |
| --- | --- |
| FUEL | Janani Reporting / Bills / Fuel |
| MAINTENANCE | Janani Reporting / Bills / Maintanence |

`BILL_IMAGES_FOLDER_ID` identifies the existing Bills parent. Only these two category folders are created when missing; there are no date subfolders and no fallback to My Drive. Optional `BILL_FUEL_FOLDER_ID` / `BILL_MAINTENANCE_FOLDER_ID` can identify existing direct children with the exact category names.

Python [image OCR](../BILL_OCR.md) supplies `bill_category`, `ocr_status`, `ocr_reason`, `ocr_engine`, and `ocr_confidence`. Missing, unknown, failed, or review-required classifications are rejected. Bill log stores category and confirmed Drive URL. An existing recognized category column is reused or a new Bill Category column is appended. Dates may be blank when unavailable; supplied dates must agree and validate. Deprecated `date_folder` input never chooses a Drive folder.

SHA-256 identity, a script lock, and an unfinished-upload journal reuse the same file and row on retries. New names contain the full checksum. `janani_bill_v84_pending_<SHA256>` reserves the folder/name before creation and is removed only after the Bill log flush. If the prior creation outcome is unconfirmed, check its reserved folder/name before clearing that specific property; another copy is blocked. Never clear all pending properties or local push history as a repair.

Old acknowledged images and dated folders aren't automatically migrated/deleted. Resending a verified matching image can move the same file into its category folder, preserving its URL. Conflicting files/links require review. Hashes do not prove equality of visually identical re-encoded photos.

Tests use mocked Google services for both categories, no dated-folder creation, blank dates, failed OCR metadata, retries, interrupted uploads, category changes and confirmed URLs. Verify a real authorized upload after deployment.
