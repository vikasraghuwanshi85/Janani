// GENERATED COMPLETE SCRIPT: paste this file alone into Apps Script.
// Sources: entrypoints.gs, fuel_header_fix.gs, bill_folder_fix.gs.

// This bundle needs no separate helper files, despite component comments below.

/**
 * JANANI FLEET V82 - complete web-app entry points.
 * Use the generated Janani.gs as the single-file deployment.
 */
var SHEET_ID = '1ii9MU_bScuYAqtuXGQyKd4QLsgHcwwJJLcfusoo5NWI';
var BILL_IMAGES_FOLDER_ID = '1fGcvEMxynl9MNsADvpqFQEf1elDbrFgH';
var BILL_LOG_SHEET_NAME = 'Bill log';
var JANANI_VERSION = 'V82';
var JANANI_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
var FUEL_HEADERS_OLD = ['Date', 'Location', 'Vehicle', 'Type', 'Present ODO', 'Previous ODO',
  'Total KM', 'Diesel Amount', 'Diesel Liter', 'Rate', 'Average', 'Bill Amount',
  'Work Details', 'Pilot', 'Pump', 'Source', 'Timestamp', 'Image URL'];

function jsonResponseWithCallback(obj, params) {
  obj.v = JANANI_VERSION;
  var callback = params && params.callback ? String(params.callback) : '';
  var mime = ContentService.MimeType.JSON;
  var text;
  if (callback && !/^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$/.test(callback)) {
    text = JSON.stringify({success: false, error: 'Invalid callback name', v: JANANI_VERSION});
  } else {
    text = JSON.stringify(obj);
    if (callback) { text = callback + '(' + text + ')'; mime = ContentService.MimeType.JAVASCRIPT; }
  }
  return ContentService.createTextOutput(text).setMimeType(mime);
}

function parseDate(dateStr) {
  // Calendar validation is strict. Missing/invalid dates never become today's date.
  var valid = billDateV81_(dateStr);
  var parts = valid.folder.split('-');
  return {folder: valid.sheet, folderDashed: valid.folder, folderFull: valid.folder,
    monthName: JANANI_MONTHS[Number(parts[1]) - 1], year: Number(parts[2]),
    date: new Date(Date.UTC(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]))),
    original: String(dateStr || '')};
}

function requestData_(e) {
  var parameters = e && e.parameter ? e.parameter : {};
  if (e && e.postData && e.postData.contents) {
    try {
      var data = JSON.parse(e.postData.contents);
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Expected a JSON object');
      return data;
    } catch (error) {
      // Retain form-encoded clients, but do not acknowledge malformed JSON as a read.
      if (Object.keys(parameters).length) return parameters;
      throw new Error('Invalid JSON request: ' + error.message);
    }
  }
  return parameters;
}

function normalizeFuelOdometer_(value) {
  var text = fuelString_(value);
  if (!text) return '';
  if (!/^(?:\d+|\d{1,3}(?:[,\.]\s*\d{3})+|\d{1,2}(?:,\s*\d{2})+,\s*\d{3})$/.test(text)) {
    throw new Error('Invalid odometer reading; correct the source message.');
  }
  var digits = text.replace(/[,\.\s]/g, '');
  if (digits.length > 7) throw new Error('Odometer exceeds seven digits; no silent truncation allowed.');
  return digits;
}

function validateFuelPayload_(data) {
  var type = fuelString_(data.type || 'FUEL').toUpperCase();
  data.type = type;
  if (type !== 'FUEL') return data;
  var vehicle = fuelString_(data.vehicle || data.vehicle_id || data.vehicle_no).toUpperCase().replace(/[\s-]/g, '');
  if (!/^(?:\d{4}|[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{1,4})$/.test(vehicle)) {
    throw new Error('Missing or invalid vehicle ID; use the WhatsApp source ID.');
  }
  data.vehicle = vehicle;
  ['present_odo', 'previous_odo', 'diesel_amount', 'diesel_liter'].forEach(function(field) {
    if (!fuelString_(data[field])) throw new Error('Missing required fuel field: ' + field);
  });
  data.present_odo = normalizeFuelOdometer_(data.present_odo);
  data.previous_odo = normalizeFuelOdometer_(data.previous_odo);
  if (data.present_odo && data.previous_odo) {
    var distance = Number(data.present_odo) - Number(data.previous_odo);
    if (distance < 0) throw new Error('Present odometer is below previous odometer; report rejected.');
    if (fuelString_(data.total_km) && Number(data.total_km) !== distance) {
      throw new Error('Total KM disagrees with odometers; report rejected.');
    }
    data.total_km = String(distance);
  }
  ['diesel_amount', 'diesel_liter', 'rate', 'average'].forEach(function(field) {
    var value = fuelString_(data[field]);
    if (value && !/^\d+(?:\.\d+)?$/.test(value)) throw new Error('Invalid numeric ' + field + '; report rejected.');
  });
  if (fuelString_(data.diesel_liter) && Number(data.diesel_liter) <= 0) {
    throw new Error('Diesel liters must be greater than zero.');
  }
  if (Number(data.diesel_amount) <= 0) throw new Error('Diesel amount must be greater than zero.');
  if (fuelString_(data.diesel_amount) && fuelString_(data.diesel_liter)) {
    var rate = Number(data.diesel_amount) / Number(data.diesel_liter);
    if (fuelString_(data.rate) && Math.abs(Number(data.rate) - rate) > 0.02) {
      throw new Error('Rate disagrees with amount/liters; report rejected.');
    }
    data.rate = rate.toFixed(2);
  }
  if (fuelString_(data.total_km) && Number(data.diesel_liter) > 0) {
    var average = Number(data.total_km) / Number(data.diesel_liter);
    if (fuelString_(data.average) && Math.abs(Number(data.average) - average) > 0.03) {
      throw new Error('Average disagrees with Total KM/liters; check source readings and volume.');
    }
    if (!fuelString_(data.average)) data.average = average.toFixed(2);
  }
  return data;
}

function doPost(e) {
  var data = {};
  try {
    data = requestData_(e);
    var action = fuelString_(data.action).toLowerCase();
    if (action.indexOf('get_') === 0 || ['search', 'list_folders', 'test_date', 'fix_headers'].indexOf(action) >= 0 || !Object.keys(data).length) {
      return doGet({parameter: data});
    }
    if (action && action !== 'insert' && action !== 'upload_bill') throw new Error('Unsupported write action: ' + action);
    var target = fuelString_(data.target_sheet || data.month);
    var isBill = Boolean(data.image_data || data.filedata) || action === 'upload_bill' ||
      data.has_image === true || String(data.has_image).toLowerCase() === 'true' ||
      target.toLowerCase().replace(/[\s_]/g, '') === BILL_LOG_SHEET_NAME.toLowerCase().replace(/[\s_]/g, '');
    var ss = SpreadsheetApp.openById(SHEET_ID);
    if (isBill) {
      // Accept legacy upload_bill field names as well as the current Python payload.
      data.image_data = data.image_data || data.filedata;
      data.file_name = data.file_name || data.filename;
      return writeBillReportV81_(data, ss, data);
    }
    var parsed = parseDate(data.date || data.original_date);
    if (JANANI_MONTHS.indexOf(target) >= 0 && target !== parsed.monthName) {
      throw new Error('Target month disagrees with report date.');
    }
    validateFuelPayload_(data);
    return writeFuelReportV80_(data, target, parsed.monthName, "'" + parsed.folder, parsed.folder, ss, data);
  } catch (error) {
    return jsonResponseWithCallback({success: false, error: String(error.message || error), v: JANANI_VERSION}, data);
  }
}

function dashboardCell_(value, header) {
  if (value instanceof Date) {
    var normalized = normalizeFuelHeader_(header);
    if (normalized === 'date' || normalized === 'originaldate') {
      return Utilities.formatDate(value, Session.getScriptTimeZone(), 'dd/MM/yy');
    }
    return value.toISOString();
  }
  return typeof value === 'string' ? value.replace(/^'/, '') : value;
}

function readDashboardRows_(sheet, kind) {
  if (!sheet || sheet.getLastRow() <= 1) return [];
  var allRows = sheet.getDataRange().getValues(), headers = allRows[0], result = [];
  var canonical = {date: 'Date', location: 'Location', vehicle: 'Vehicle', type: 'Type',
    present_odo: 'Present ODO', previous_odo: 'Previous ODO', total_km: 'Total KM',
    diesel_amount: 'Diesel Amount', diesel_liter: 'Diesel Liter', rate: 'Rate', average: 'Average',
    bill_amount: 'Bill Amount', work_details: 'Work Details', pilot: 'Pilot', pump: 'Pump',
    source: 'Source', timestamp: 'Timestamp', image_url: 'Image URL'};
  for (var i = 1; i < allRows.length; i++) {
    var row = allRows[i];
    if (!row.some(function(value) {return value !== '' && value !== null;})) continue;
    var obj = {};
    headers.forEach(function(header, column) {
      var value = dashboardCell_(row[column], header);
      obj[header] = value;
      if (kind === 'FUEL') {
        var field = fuelFieldForHeader_(header);
        if (canonical[field]) obj[canonical[field]] = value;
      }
    });
    obj._sheet = sheet.getName(); obj._type = kind;
    result.push(obj);
  }
  return result;
}

function dashboardDateMillis_(record) {
  try {return parseDate(record.Date || record['Original Date']).date.getTime();}
  catch (error) {return 0;}
}

function doGet(e) {
  var params = e && e.parameter ? e.parameter : {};
  try {
    var action = fuelString_(params.action).toLowerCase();
    if (action === 'test_date') {
      var parsed = parseDate(params.date);
      return jsonResponseWithCallback({success: true, v: JANANI_VERSION, folder: parsed.folder,
        folderDashed: parsed.folderFull, folderFull: parsed.folderFull, sheet: BILL_LOG_SHEET_NAME,
        fuelHeaders: FUEL_HEADERS_OLD}, params);
    }
    if (action === 'fix_headers') {
      return jsonResponseWithCallback({success: false, v: JANANI_VERSION,
        error: 'Header-only relabeling is disabled because it can mislabel existing data. Existing header variants are supported.'}, params);
    }
    if (action === 'list_folders') {
      var folders = DriveApp.getFolderById(BILL_IMAGES_FOLDER_ID).getFolders(), list = [];
      while (folders.hasNext()) {var folder = folders.next(); list.push({name: folder.getName(), id: folder.getId(), url: folder.getUrl()});}
      return jsonResponseWithCallback({success: true, v: JANANI_VERSION, data: list, count: list.length}, params);
    }
    var ss = SpreadsheetApp.openById(SHEET_ID);
    var bills = readDashboardRows_(ss.getSheetByName(BILL_LOG_SHEET_NAME), 'BILL_LOG');
    var fuel = [];
    JANANI_MONTHS.forEach(function(month) {fuel = fuel.concat(readDashboardRows_(ss.getSheetByName(month), 'FUEL'));});
    var all = fuel.concat(bills);
    [fuel, bills, all].forEach(function(records) {records.sort(function(a, b) {return dashboardDateMillis_(b) - dashboardDateMillis_(a);});});
    var base = {success: true, v: JANANI_VERSION, fuelCount: fuel.length, billCount: bills.length, totalCount: all.length};
    if (action === 'get_all_data') {
      // Preserve V79's bill-only response for the existing bill dashboard.
      base.data = bills; base.count = bills.length; base.sheet = BILL_LOG_SHEET_NAME;
    } else if (action === 'get_dashboard' || action === 'get_fuel' || action === '') {
      base.data = fuel; base.recent = fuel; base.count = fuel.length;
    } else {
      base.data = all; base.count = all.length;
      if (action === 'get_both' || action === 'get_combined') {base.fuel = fuel; base.bills = bills;}
      if (action === 'search') {
        var query = fuelString_(params.q || params.query).toLowerCase();
        base.data = all.filter(function(record) {return JSON.stringify(record).toLowerCase().indexOf(query) >= 0;});
        base.count = base.data.length;
      }
    }
    return jsonResponseWithCallback(base, params);
  } catch (error) {
    return jsonResponseWithCallback({success: false, error: String(error.message || error), v: JANANI_VERSION}, params);
  }
}

function previewBillLogDuplicates() {
  var sheet = SpreadsheetApp.openById(SHEET_ID).getSheetByName(BILL_LOG_SHEET_NAME);
  if (!sheet || sheet.getLastRow() <= 1) return {success: true, groups: [], extraCopies: 0};
  var rows = sheet.getDataRange().getValues(), notes = sheet.getDataRange().getNotes();
  var columns = billColumnsV81_(rows[0]), groups = {}, total = 0;
  for (var i = 1; i < rows.length; i++) {
    var hash = columns.image_hash !== undefined ? fuelString_(rows[i][columns.image_hash]) : '';
    if (!hash) {var match = String(notes[i] && notes[i][columns.file_name] || '').match(/Hash: ([a-f0-9]{20,64})/i); if (match) hash = match[1];}
    var name = fuelString_(rows[i][columns.file_name]);
    var key = hash ? 'hash:' + hash : (name ? 'name:' + name : '');
    if (!key) continue;
    if (!groups[key]) groups[key] = [];
    groups[key].push(i + 1);
  }
  var duplicates = Object.keys(groups).filter(function(key) {return groups[key].length > 1;}).map(function(key) {
    total += groups[key].length - 1; return {key: key, rows: groups[key]};
  });
  var result = {success: true, groups: duplicates, extraCopies: total, message: 'Preview only; no rows or files deleted.'};
  Logger.log(JSON.stringify(result));
  return result;
}

function cleanupBillLogDuplicates() {
  // Retain the old entry point as a read-only preview; historical cleanup requires review.
  return previewBillLogDuplicates();
}

function fixFuelShiftForExistingData() {
  return 'No existing rows changed. Header variants are handled during writes; review and repair source values separately.';
}


/**
 * Janani V80 fuel-column fix for the supplied V79 Apps Script.
 * Add this file to the existing Apps Script project. Replace only doPost's
 * FUEL LOG else branch with the call documented in apps_script/README.md.
 * Existing bill upload, dashboard and configuration functions are retained.
 */

function normalizeFuelHeader_(header) {
  return String(header || '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

function fuelFieldForHeader_(header) {
  var name = normalizeFuelHeader_(header);
  var aliases = {
    date: 'date', location: 'location',
    vehicle: 'vehicle', vehicleno: 'vehicle', vehiclenofull: 'vehicle',
    vehiclenumber: 'vehicle', vehicleid: 'vehicle', vehiclefull: 'vehicle',
    registrationno: 'vehicle', registrationnumber: 'vehicle',
    type: 'type', presentodo: 'present_odo', previousodo: 'previous_odo',
    prevodo: 'previous_odo', totalkm: 'total_km',
    dieselamount: 'diesel_amount', disealamount: 'diesel_amount',
    dieselliter: 'diesel_liter', diesellitre: 'diesel_liter', disealliter: 'diesel_liter',
    rate: 'rate', ratel: 'rate', rateliter: 'rate', rateperliter: 'rate',
    average: 'average', billamount: 'bill_amount', workdetails: 'work_details',
    pilot: 'pilot', pilotname: 'pilot', pump: 'pump', pumpname: 'pump',
    source: 'source', timestamp: 'timestamp', imageurl: 'image_url'
  };
  return Object.prototype.hasOwnProperty.call(aliases, name) ? aliases[name] : '';
}

function fuelColumnIndexes_(headers) {
  var indexes = {};
  headers.forEach(function(header, index) {
    var field = fuelFieldForHeader_(header);
    if (field && !Object.prototype.hasOwnProperty.call(indexes, field)) indexes[field] = index;
  });
  return indexes;
}

function fuelDateKey_(value) {
  if (value instanceof Date) {
    return Utilities.formatDate(value, Session.getScriptTimeZone(), 'dd/MM/yy');
  }
  var text = String(value || '').replace(/^'/, '').trim();
  var match = text.match(/^(\d{1,2})[\/-](\d{1,2})[\/-](\d{2}|\d{4})$/);
  if (!match) return text;
  return ('0' + Number(match[1])).slice(-2) + '/' + ('0' + Number(match[2])).slice(-2) + '/' + match[3].slice(-2);
}

function fuelString_(value) {
  return value === null || value === undefined ? '' : String(value).trim();
}

function writeFuelReportV80_(data, targetSheet, monthName, dateForSheet, date, ss, params) {
  var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var monthSheetName = months.indexOf(targetSheet) >= 0 ? targetSheet : monthName;
  var vehicle = fuelString_(data.vehicle || data.vehicle_id || data.vehicle_no).toUpperCase();
  if (!vehicle) throw new Error('Missing vehicle ID in webhook payload; no fuel row written.');

  var lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    var sheet = ss.getSheetByName(monthSheetName);
    if (!sheet) {
      sheet = ss.insertSheet(monthSheetName);
      sheet.appendRow(FUEL_HEADERS_OLD);
      sheet.getRange(1, 1, 1, FUEL_HEADERS_OLD.length).setFontWeight('bold').setBackground('#4f46e5').setFontColor('white');
      sheet.setFrozenRows(1);
    }

    var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
    var indexes = fuelColumnIndexes_(headers);
    ['date', 'vehicle', 'type', 'present_odo', 'previous_odo'].forEach(function(field) {
      if (!Object.prototype.hasOwnProperty.call(indexes, field)) {
        throw new Error('Missing recognized ' + field + ' column in ' + monthSheetName + '; no row written.');
      }
    });

    var values = {
      date: dateForSheet, location: fuelString_(data.location), vehicle: vehicle,
      type: fuelString_(data.type || 'FUEL').toUpperCase(),
      present_odo: fuelString_(data.present_odo), previous_odo: fuelString_(data.previous_odo),
      total_km: fuelString_(data.total_km), diesel_amount: fuelString_(data.diesel_amount),
      diesel_liter: fuelString_(data.diesel_liter), rate: fuelString_(data.rate),
      average: fuelString_(data.average), bill_amount: fuelString_(data.bill_amount),
      work_details: fuelString_(data.work_details), pilot: fuelString_(data.pilot),
      pump: fuelString_(data.pump), source: fuelString_(data.source),
      timestamp: new Date(), image_url: fuelString_(data.image_url)
    };

    if (!values.rate && /^\d+(?:\.\d+)?$/.test(values.diesel_amount) && /^\d+(?:\.\d+)?$/.test(values.diesel_liter) && Number(values.diesel_liter) > 0) {
      values.rate = (Number(values.diesel_amount) / Number(values.diesel_liter)).toFixed(2);
    }
    if (!values.total_km && /^\d+$/.test(values.present_odo) && /^\d+$/.test(values.previous_odo)) {
      values.total_km = String(Number(values.present_odo) - Number(values.previous_odo));
    }

    var allRows = sheet.getDataRange().getValues();
    if (values.present_odo) {
      for (var i = 1; i < allRows.length; i++) {
        var row = allRows[i];
        if (fuelDateKey_(row[indexes.date]) === fuelDateKey_(date) &&
            fuelString_(row[indexes.vehicle]).toUpperCase() === vehicle &&
            fuelString_(row[indexes.type]).toUpperCase() === values.type &&
            fuelString_(row[indexes.present_odo]) === values.present_odo &&
            fuelString_(row[indexes.previous_odo]) === values.previous_odo) {
          return jsonResponseWithCallback({success: true, status: 'duplicate', sheet: monthSheetName,
            duplicate: true, vehicle: vehicle, existingRow: i + 1, v: 'V80 vehicle headers'}, params);
        }
      }
    }

    var rowData = headers.map(function(header) {
      var field = fuelFieldForHeader_(header);
      return field ? values[field] : '';
    });
    var nextRow = sheet.getLastRow() + 1;
    // Apply text formatting before writing, including numeric-looking vehicle IDs.
    ['date', 'vehicle', 'present_odo', 'previous_odo'].forEach(function(field) {
      sheet.getRange(nextRow, indexes[field] + 1).setNumberFormat('@');
    });
    sheet.appendRow(rowData);
    SpreadsheetApp.flush();
    return jsonResponseWithCallback({success: true, status: 'inserted', sheet: monthSheetName,
      date: date, vehicle: vehicle, type: values.type, present_odo: values.present_odo,
      total_km: values.total_km, rate: values.rate, headers: headers, rowData: rowData,
      vehicleColumn: indexes.vehicle + 1, v: 'V80 vehicle headers'}, params);
  } finally {
    lock.releaseLock();
  }
}


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
