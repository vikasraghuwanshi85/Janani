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
    imagehash: 'image_hash', datefolder: 'date_folder',
    billcategory: 'bill_category', category: 'bill_category', billtype: 'bill_category', billfolder: 'bill_folder'};
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

function billManagedFileV84_(file, parentId) {
  var pending = [], parents = file.getParents(), seen = {}, count = 0;
  while (parents.hasNext()) pending.push(parents.next());
  while (pending.length) {
    var folder = pending.pop(), id = folder.getId();
    if (id === parentId) return true;
    if (seen[id]) continue;
    seen[id] = true;
    if (++count > 100) throw new Error('Bill folder ancestry is too complex; verify Drive folders before retrying.');
    parents = folder.getParents();
    while (parents.hasNext()) pending.push(parents.next());
  }
  return false;
}

function billPendingFileV84_(properties, key, hash, parent) {
  var saved = properties.getProperty(key);
  if (!saved) return null;
  var pending;
  try {pending = JSON.parse(saved);} catch (error) {throw new Error('Pending bill journal is invalid; verify it before retrying.');}
  if (!pending || !pending.folderId || !pending.fileName) throw new Error('Pending bill journal is incomplete; verify it before retrying.');
  var file;
  if (pending.fileId) file = DriveApp.getFileById(pending.fileId);
  else {
    var folder = DriveApp.getFolderById(pending.folderId);
    if (folder.getId() !== parent.getId() && !billManagedFileV84_(folder, parent.getId())) throw new Error('Pending bill folder is outside the configured bill root.');
    var files = folder.getFiles(), matches = [];
    while (files.hasNext()) {var candidate = files.next(); if (candidate.getName() === pending.fileName) matches.push(candidate);}
    if (matches.length > 1) throw new Error('Multiple files match an interrupted bill upload; reconcile before retrying.');
    if (!matches.length) throw new Error('Previous bill upload outcome is unconfirmed; inspect its reserved folder and pending script property before retrying. No second file created.');
    file = matches[0];
  }
  if (!billManagedFileV84_(file, parent.getId())) throw new Error('Pending bill file is outside the configured bill root.');
  if (billHashV81_(file.getBlob().getBytes()) !== hash) throw new Error('Pending bill content differs; verify Drive before retrying.');
  return file;
}

function billRecoverFilesV84_(parent, folder, hash, fileName, originalName, referencedFile) {
  var found = {}, total = 0;
  function remember(candidate) {
    var id = candidate.getId();
    if (found[id]) return;
    if (billHashV81_(candidate.getBlob().getBytes()) !== hash) throw new Error('Conflicting bill image in Drive; verify ' + candidate.getName() + ' before retrying.');
    found[id] = candidate;
  }
  if (referencedFile) remember(referencedFile);
  var files = folder.getFiles();
  while (files.hasNext()) {
    var candidate = files.next(), name = candidate.getName();
    if (name === fileName || name === originalName || name.indexOf(hash.slice(0, 12)) >= 0 || String(candidate.getDescription() || '').indexOf('Hash: ' + hash) >= 0) remember(candidate);
  }
  // Recover a partial upload from either category or an old dated folder, bounded
  // to the configured bill root. Never move a matching personal/outside file.
  files = DriveApp.searchFiles("trashed = false and (title contains '" + hash + "' or fullText contains '" + hash + "')");
  while (files.hasNext()) {
    candidate = files.next();
    if (++total > 200) throw new Error('Too many matching bill files; reconcile duplicates before retrying.');
    if (billManagedFileV84_(candidate, parent.getId())) remember(candidate);
  }
  var ids = Object.keys(found);
  if (ids.length > 1) throw new Error('Multiple Drive files match this bill image; reconcile existing copies before retrying.');
  return ids.length ? found[ids[0]] : null;
}

function writeBillReportV81_(data, ss, params) {
  var dates = [data.original_date, data.date].filter(function(value) {return value !== undefined && value !== null && String(value).trim() !== '';}).map(billDateV81_);
  if (dates.length && dates.some(function(item) {return item.folder !== dates[0].folder;})) throw new Error('Bill dates disagree; no upload performed.');
  var date = dates.length ? dates[0].sheet : '';
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
  if (data.image_hash && String(data.image_hash).length === 64 && String(data.image_hash).toLowerCase() !== hash) throw new Error('Bill image checksum does not match payload; no upload performed.');
  var vehicle = String(data.vehicle || data.vehicle_id || data.vehicle_no || 'BILL').trim().toUpperCase().replace(/[^A-Z0-9_]/g, '');
  var extension = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/gif': 'gif'}[mime];
  var originalName = String(data.file_name || '').trim() || vehicle + '_' + hash.slice(0, 12) + '.' + extension;
  var fileName = originalName.indexOf(hash + '_') === 0 ? originalName : hash + '_' + originalName;
  var metadata = 'Direct image upload; no image parsing';
  var lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    var parent = DriveApp.getFolderById(BILL_IMAGES_FOLDER_ID);
    var folder = parent;
    var folderName = parent.getName();
    var sheet = ss.getSheetByName(BILL_LOG_SHEET_NAME);
    if (!sheet) {
      sheet = ss.insertSheet(BILL_LOG_SHEET_NAME);
      sheet.appendRow(['Date', 'File Name', 'Vehicle', 'Drive Link', 'Original Date', 'Uploaded At', 'Image Hash']);
      sheet.setFrozenRows(1);
    }
    var rows = sheet.getDataRange().getValues(), headers = rows[0].slice(), columns = billColumnsV81_(headers);
    var notes = sheet.getDataRange().getNotes(), matchingRows = [], file = null;
    for (var i = 1; i < rows.length; i++) {
      var existingName = String(rows[i][columns.file_name] || '').trim();
      var storedHash = columns.image_hash !== undefined ? String(rows[i][columns.image_hash] || '') : '';
      var note = notes[i] ? String(notes[i][columns.file_name] || '') : '';
      if (existingName === fileName || existingName === originalName || storedHash === hash || note.indexOf('Hash: ' + hash) >= 0 || existingName.indexOf(hash.slice(0, 12)) >= 0) {
        matchingRows.push(i);
        var link = String(rows[i][columns.drive_link] || '');
        if (link) {
          var id = billFileIdV81_(link);
          if (!id) throw new Error('Existing bill link is invalid; verify Bill log row ' + (i + 1) + ' before retrying.');
          var referenced = DriveApp.getFileById(id);
          if (billHashV81_(referenced.getBlob().getBytes()) !== hash) throw new Error('Existing bill content differs; verify Bill log row ' + (i + 1) + ' before retrying.');
          if (file && file.getId() !== id) throw new Error('Multiple Drive links match this bill image; reconcile Bill log rows before retrying.');
          file = referenced;
        }
      }
    }
    var pendingKey = 'janani_bill_v84_pending_' + hash, properties = PropertiesService.getScriptProperties();
    var pendingFile = billPendingFileV84_(properties, pendingKey, hash, parent);
    if (pendingFile) {
      if (file && file.getId() !== pendingFile.getId()) throw new Error('Pending bill and Bill log refer to different files; reconcile before retrying.');
      file = pendingFile;
    }
    file = billRecoverFilesV84_(parent, folder, hash, fileName, originalName, file);
    var reused = Boolean(file), moved = false;
    if (file) {
      if (!billHasParentV81_(file, folder.getId())) {file.moveTo(folder); moved = true;}
    } else {
      properties.setProperty(pendingKey, JSON.stringify({folderId: folder.getId(), fileName: fileName}));
      file = folder.createFile(Utilities.newBlob(bytes, mime, fileName));
      properties.setProperty(pendingKey, JSON.stringify({folderId: folder.getId(), fileName: fileName, fileId: file.getId()}));
      try {file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);} catch (sharingError) {}
    }
    file.setDescription('Hash: ' + hash + ' | Folder: ' + folderName + ' | ' + metadata);
    if (!billHasParentV81_(file, folder.getId())) throw new Error('Drive file is not in the requested configured Bills folder.');
    var url = file.getUrl();
    if (!url) throw new Error('Drive upload has no URL; no success acknowledged.');
    var values = {date: date ? "'" + date : '', file_name: file.getName(), vehicle: vehicle, drive_link: url,
      original_date: date, uploaded_at: new Date(), image_hash: hash, date_folder: '', bill_category: '', bill_folder: folderName};
    var rowNumber = matchingRows.length ? matchingRows[0] + 1 : sheet.getLastRow() + 1;
    var rowData = headers.map(function(header, index) {
      var field;
      Object.keys(columns).some(function(key) {if (columns[key] === index) {field = key; return true;} return false;});
      if (matchingRows.length && (field === 'bill_category' || field === 'uploaded_at' || (!date && (field === 'date' || field === 'original_date')))) return rows[matchingRows[0]][index] || '';
      return field ? values[field] : (matchingRows.length ? rows[matchingRows[0]][index] : '');
    });
    ['date', 'original_date', 'vehicle', 'image_hash'].forEach(function(field) {if (columns[field] !== undefined) sheet.getRange(rowNumber, columns[field] + 1).setNumberFormat('@');});
    if (matchingRows.length) sheet.getRange(rowNumber, 1, 1, headers.length).setValues([rowData]);
    else sheet.appendRow(rowData);
    sheet.getRange(rowNumber, columns.file_name + 1).setNote('Hash: ' + hash + '\n' + metadata);
    SpreadsheetApp.flush();
    properties.deleteProperty(pendingKey);
    return jsonResponseWithCallback({success: true, status: reused ? 'duplicate' : 'inserted', duplicate: reused,
      sheet: BILL_LOG_SHEET_NAME, vehicle: vehicle, fileName: file.getName(), driveLink: url, existingUrl: reused ? url : '',
      date: date, dateFolder: '', billUploadMode: 'DIRECT', billFolder: folderName, folderId: folder.getId(), fileId: file.getId(),
      moved: moved, existingRow: rowNumber, v: 'V84 fixed configured Bills folders'}, params);
  } finally {lock.releaseLock();}
}
