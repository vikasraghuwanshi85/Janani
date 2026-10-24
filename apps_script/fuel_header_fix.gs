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

function fuelComparableV83_(value, field) {
  var text = fuelString_(value);
  if (['present_odo', 'previous_odo', 'total_km', 'diesel_amount', 'diesel_liter', 'rate', 'average', 'bill_amount'].indexOf(field) >= 0 && /^\d+(?:\.\d+)?$/.test(text)) {
    return String(Number(text));
  }
  return text;
}

function fuelRowConflictV83_(row, indexes, values) {
  var fields = ['location', 'total_km', 'diesel_amount', 'diesel_liter', 'rate', 'average', 'pilot', 'pump'];
  return fields.some(function(field) {
    if (indexes[field] === undefined) return false;
    return fuelComparableV83_(row[indexes[field]], field) !== fuelComparableV83_(values[field], field);
  });
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
    (fuelString_(data.type || 'FUEL').toUpperCase() === 'FUEL' ? ['date', 'vehicle', 'type', 'present_odo', 'previous_odo'] : ['date', 'vehicle', 'type', 'bill_amount', 'work_details']).forEach(function(field) {
      if (!Object.prototype.hasOwnProperty.call(indexes, field)) {
        throw new Error('Missing recognized ' + field + ' column in ' + monthSheetName + '; no row written.');
      }
    });
    var reportType = fuelString_(data.type || 'FUEL').toUpperCase();
    var businessColumns = reportType === 'FUEL' ? ['diesel_amount', 'diesel_liter', 'total_km'] : [];
    businessColumns.forEach(function(field) {
      if (indexes[field] === undefined) throw new Error('Missing recognized ' + field + ' column in ' + monthSheetName + '; no row written.');
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
    var notes = sheet.getDataRange().getNotes();
    var messageId = fuelString_(data.message_id);
    if (messageId.length > 1024 || /[\r\n\x00-\x1f]/.test(messageId)) throw new Error('Invalid WhatsApp message ID; no row written.');
    for (var i = 1; i < allRows.length; i++) {
      var row = allRows[i];
      var sameReport = fuelDateKey_(row[indexes.date]) === fuelDateKey_(date) &&
        fuelString_(row[indexes.vehicle]).toUpperCase() === vehicle &&
        fuelString_(row[indexes.type]).toUpperCase() === values.type;
      if (values.type !== 'FUEL') {
        var fields = ['bill_amount', 'work_details', 'present_odo', 'location', 'pilot', 'pump'];
        var sameDetails = fields.every(function(field) {return indexes[field] === undefined || fuelComparableV83_(row[indexes[field]], field) === fuelComparableV83_(values[field], field);});
        var maintenanceNote = notes[i] ? String(notes[i][indexes.date] || '') : '';
        var sameMaintenanceMessage = messageId && maintenanceNote.split('\n').indexOf('Janani Message ID: ' + messageId) >= 0;
        if (sameMaintenanceMessage && (!sameReport || !sameDetails)) throw new Error('Maintenance message differs from its existing sheet row; review before retrying.');
        if (sameMaintenanceMessage || (sameReport && sameDetails)) {
          return jsonResponseWithCallback({success: true, status: 'duplicate', sheet: monthSheetName,
            duplicate: true, vehicle: vehicle, existingRow: i + 1}, params);
        }
        continue;
      }
      var sameOdometers = fuelComparableV83_(row[indexes.present_odo], 'present_odo') === fuelComparableV83_(values.present_odo, 'present_odo') &&
        fuelComparableV83_(row[indexes.previous_odo], 'previous_odo') === fuelComparableV83_(values.previous_odo, 'previous_odo');
      var note = notes[i] ? String(notes[i][indexes.date] || '') : '';
      var sameMessage = messageId && note.split('\n').indexOf('Janani Message ID: ' + messageId) >= 0;
      var conflict = fuelRowConflictV83_(row, indexes, values);
      if (sameMessage && (!sameReport || !sameOdometers || conflict)) {
        throw new Error('WhatsApp message differs from its existing sheet row ' + (i + 1) + '; review the source correction before retrying.');
      }
      var fuelIdentity = values.present_odo && sameReport && sameOdometers;
      if (fuelIdentity && conflict) {
        throw new Error('Fuel values differ from existing row ' + (i + 1) + ' for the same vehicle/date/odometers; review before retrying.');
      }
      if (sameMessage || fuelIdentity) {
        return jsonResponseWithCallback({success: true, status: 'duplicate', sheet: monthSheetName,
          duplicate: true, vehicle: vehicle, existingRow: i + 1, v: 'V83 unique reports'}, params);
      }
    }

    var rowData = headers.map(function(header) {
      var field = fuelFieldForHeader_(header);
      return field ? values[field] : '';
    });
    var nextRow = sheet.getLastRow() + 1;
    // Apply text formatting before writing, including numeric-looking vehicle IDs.
    ['date', 'vehicle', 'present_odo', 'previous_odo'].filter(function(field) {return indexes[field] !== undefined;}).forEach(function(field) {
      sheet.getRange(nextRow, indexes[field] + 1).setNumberFormat('@');
    });
    sheet.appendRow(rowData);
    if (messageId) sheet.getRange(nextRow, indexes.date + 1).setNote('Janani Message ID: ' + messageId);
    SpreadsheetApp.flush();
    return jsonResponseWithCallback({success: true, status: 'inserted', sheet: monthSheetName,
      date: date, vehicle: vehicle, type: values.type, present_odo: values.present_odo,
      total_km: values.total_km, rate: values.rate, headers: headers, rowData: rowData,
      vehicleColumn: indexes.vehicle + 1, v: 'V80 vehicle headers'}, params);
  } finally {
    lock.releaseLock();
  }
}
