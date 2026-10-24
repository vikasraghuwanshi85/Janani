# Direct bill image storage — V86

Use [Janani.gs](Janani.gs) and [deployment instructions](DEPLOY_COMPLETE.md). `BILL_IMAGES_FOLDER_ID` points to the existing Bills folder. All newly uploaded images go into its Fuel child, which is reused or created once. No date subfolders or image classifications are used. No image OCR/classification is performed and no OCR metadata is required.

Bill log records the original metadata date when available, file name, optional source vehicle, confirmed Drive URL, upload time and SHA-256. Images with no date can upload with a blank date. The hash, lock, and pending upload journal reuse an existing file/log row on retry. An uncertain creation outcome requires checking its reserved folder before clearing its specific pending script property. No complete history/property reset is needed.

Prior folders/files are retained. Already acknowledged images do not automatically replay. A repeated verified request can reuse or relocate the same matched file without copying it. Conflicting file contents/links require review.

Maintenance text is separate: Mntc MSG messages populate the month's sheet as MAINTENANCE, including Bill Amount and Work Details. See the root README. An attachment and its maintenance caption can both be recorded independently.

For existing uploads, run previewLoggedBillsMoveToFuel in the Apps Script editor to review the linked images, then moveLoggedBillsToFuel to relocate only those inside the configured Bills root. No copies are created and URLs remain unchanged. This moves files, not their resolution; previously saved blurry previews require replacement with original photos.
