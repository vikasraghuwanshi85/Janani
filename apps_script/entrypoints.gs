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
