/** Add to the existing project and replace doPost's isBillLog branch as documented. */
function billDateV81_(value) {
  var match = String(value || '').replace(/^'/, '').trim().match(/^(\d{1,2})[\/-](\d{1,2})[\/-](\d{2}|\d{4})$/);
  if (!match) throw new Error('Bill date missing or invalid; no upload performed.');
  var day = Number(match[1]), month = Number(match[2]), year = Number(match[3]);
  if (year < 100) year += 2000;
  var check = new Date(Date.UTC(year, month - 1, day));
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) {
    throw new Error('Invalid calendar date for bill; no upload performed.');
  }
  var dd = ('0' + day).slice(-2), mm = ('0' + month).slice(-2);
  return {folder: dd + '-' + mm + '-' + year, sheet: dd + '/' + mm + '/' + String(year).slice(-2)};
}

function billColumnsV81_(headers) {
  // Keep mappings explicit: a header rename must never silently shift a column.
  var aliases = {date: 'date', filename: 'file_name', vehicle: 'vehicle',
    vehiclenofull: 'vehicle', drivelink: 'drive_link', imageurl: 'drive_link',
    originaldate: 'original_date', uploadedat: 'uploaded_at', timestamp: 'uploaded_at',
    imagehash: 'image_hash', datefolder: 'date_folder'};
  var columns = {};
  headers.forEach(function(header, index) {
    var field = aliases[String(header || '').toLowerCase().replace(/[^a-z0-9]/g, '')];
    if (field && columns[field] === undefined) columns[field] = index;
  });
  ['date', 'file_name', 'drive_link'].forEach(function(field) {
    if (columns[field] === undefined) throw new Error('Bill log missing ' + field + ' column; no upload performed.');
  });
  return columns;
}

function billHashV81_(bytes) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, bytes).map(function(value) {
    return ('0' + ((value + 256) % 256).toString(16)).slice(-2);
  }).join('');
}

function billFileIdV81_(url) {
  var match = String(url || '').match(/\/d\/([A-Za-z0-9_-]+)/) || String(url || '').match(/[?&]id=([A-Za-z0-9_-]+)/);
  return match ? match[1] : '';
}

function billHasParentV81_(file, folderId) {
  var parents = file.getParents();
  while (parents.hasNext()) if (parents.next().getId() === folderId) return true;
  return false;
}

function billDateFolderV81_(parent, name) {
  var folders = parent.getFoldersByName(name);
  if (!folders.hasNext()) return parent.createFolder(name);
  var folder = folders.next();
  if (folders.hasNext()) throw new Error('Multiple bill folders named ' + name + '; reconcile them before retrying.');
  return folder;
}

function writeBillReportV81_(data, ss, params) {
  var dates = [data.original_date, data.date, data.date_folder].filter(function(value) {
    return value !== undefined && value !== null && String(value).trim() !== '';
  }).map(billDateV81_);
  if (!dates.length) throw new Error('Bill date missing; no upload performed.');
  var date = dates[0];
  if (dates.some(function(item) { return item.folder !== date.folder; })) {
    throw new Error('Bill date and date_folder disagree; no upload performed.');
  }
  var imageData = String(data.image_data || '');
  if (!imageData) throw new Error('Bill image missing; success cannot be acknowledged.');
  var prefix = imageData.match(/^data:(image\/(?:jpeg|png|webp|gif));base64,/i);
  if (imageData.indexOf('data:') === 0 && !prefix) throw new Error('Unsupported bill image format.');
  var mime = prefix ? prefix[1].toLowerCase() : String(data.mimeType || 'image/jpeg').toLowerCase();
  if (['image/jpeg', 'image/png', 'image/webp', 'image/gif'].indexOf(mime) < 0) throw new Error('Unsupported bill image format.');
  var encoded = prefix ? imageData.slice(prefix[0].length) : imageData;
  var bytes = Utilities.base64Decode(encoded.replace(/\s+/g, ''));
  if (!bytes.length) throw new Error('Empty bill image; no upload performed.');
  var hash = billHashV81_(bytes);
  if (data.image_hash && String(data.image_hash).length === 64 && String(data.image_hash).toLowerCase() !== hash) {
    throw new Error('Bill image checksum does not match payload; no upload performed.');
  }
  var vehicle = String(data.vehicle || data.vehicle_id || data.vehicle_no || 'BILL').trim().toUpperCase().replace(/[^A-Z0-9_]/g, '');
  var extension = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/gif': 'gif'}[mime];
  var fileName = String(data.file_name || '').trim() || vehicle + '_' + date.folder.replace(/-/g, '') + '_' + hash.slice(0, 12) + '.' + extension;

  var lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    // Access errors propagate. Never upload to the Drive root or parent as a fallback.
    var parent = DriveApp.getFolderById(BILL_IMAGES_FOLDER_ID);
    var sheet = ss.getSheetByName(BILL_LOG_SHEET_NAME);
    if (!sheet) {
      sheet = ss.insertSheet(BILL_LOG_SHEET_NAME);
      sheet.appendRow(['Date', 'File Name', 'Vehicle', 'Drive Link', 'Original Date', 'Uploaded At', 'Image Hash', 'Date Folder']);
      sheet.setFrozenRows(1);
    }
    var rows = sheet.getDataRange().getValues();
    var headers = rows[0], columns = billColumnsV81_(headers);
    var notes = sheet.getDataRange().getNotes();
    var matchingRows = [], file = null;
    for (var i = 1; i < rows.length; i++) {
      var existingName = String(rows[i][columns.file_name] || '').trim();
      var storedHash = columns.image_hash !== undefined ? String(rows[i][columns.image_hash] || '') : '';
      var note = notes[i] ? String(notes[i][columns.file_name] || '') : '';
      if (existingName === fileName || storedHash === hash || note.indexOf('Hash: ' + hash) >= 0 || existingName.indexOf(hash.slice(0, 12)) >= 0) {
        matchingRows.push(i);
        var link = String(rows[i][columns.drive_link] || '');
        if (link && !file) {
          var id = billFileIdV81_(link);
          if (!id) throw new Error('Existing bill link is invalid; verify Bill log row ' + (i + 1) + ' before retrying.');
          file = DriveApp.getFileById(id);
          if (billHashV81_(file.getBlob().getBytes()) !== hash) {
            throw new Error('Existing bill content differs; verify Bill log row ' + (i + 1) + ' before retrying.');
          }
        }
      }
    }

    var folder = billDateFolderV81_(parent, date.folder);
    var reused = Boolean(file), moved = false;
    if (!file) {
      // Recover files created before an interrupted Bill log write.
      var files = folder.getFiles();
      while (files.hasNext()) {
        var candidate = files.next();
        if (candidate.getName() === fileName || String(candidate.getDescription() || '').indexOf('Hash: ' + hash) >= 0) {
          if (billHashV81_(candidate.getBlob().getBytes()) !== hash) throw new Error('Conflicting bill file in ' + date.folder + '; no duplicate created.');
          file = candidate;
          reused = true;
          break;
        }
      }
    }
    if (file) {
      if (!billHasParentV81_(file, folder.getId())) {
        file.moveTo(folder);
        moved = true;
      }
    } else {
      file = folder.createFile(Utilities.newBlob(bytes, mime, fileName));
      file.setDescription('Hash: ' + hash + ' | Date Folder: ' + date.folder);
      // Retain V79's link-sharing behavior; organization restrictions may disallow it.
      try { file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW); } catch (sharingError) {}
    }
    if (!billHasParentV81_(file, folder.getId())) throw new Error('Drive file is not in the requested date folder.');
    var url = file.getUrl();
    if (!url) throw new Error('Drive upload has no URL; no success acknowledged.');
    var values = {date: "'" + date.sheet, file_name: file.getName(), vehicle: vehicle,
      drive_link: url, original_date: date.sheet, uploaded_at: new Date(), image_hash: hash, date_folder: date.folder};
    var rowNumber = matchingRows.length ? matchingRows[0] + 1 : sheet.getLastRow() + 1;
    var rowData = headers.map(function(header, index) {
      var field;
      Object.keys(columns).some(function(key) { if (columns[key] === index) { field = key; return true; } return false; });
      if (field === 'uploaded_at' && matchingRows.length && rows[matchingRows[0]][index]) return rows[matchingRows[0]][index];
      return field ? values[field] : (matchingRows.length ? rows[matchingRows[0]][index] : '');
    });
    sheet.getRange(rowNumber, columns.date + 1).setNumberFormat('@');
    if (columns.original_date !== undefined) sheet.getRange(rowNumber, columns.original_date + 1).setNumberFormat('@');
    if (matchingRows.length) sheet.getRange(rowNumber, 1, 1, headers.length).setValues([rowData]);
    else sheet.appendRow(rowData);
    sheet.getRange(rowNumber, columns.file_name + 1).setNote('Hash: ' + hash);
    SpreadsheetApp.flush();
    return jsonResponseWithCallback({success: true, status: reused ? 'duplicate' : 'inserted',
      duplicate: reused, sheet: BILL_LOG_SHEET_NAME, vehicle: vehicle, fileName: file.getName(),
      driveLink: url, existingUrl: reused ? url : '', date: date.sheet, dateFolder: date.folder,
      folderId: folder.getId(), fileId: file.getId(), moved: moved, existingRow: rowNumber,
      v: 'V81 bill date folders'}, params);
  } finally {
    lock.releaseLock();
  }
}
