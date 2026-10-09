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
