const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'apps_script/fuel_header_fix.gs'), 'utf8');
const octoberHeaders = ['Date', 'Location', 'Vehicle No (Full)', 'Type', 'Present Odo',
  'Previous Odo', 'Total KM', 'Diesel Amount', 'Diesel Liter', 'Rate', 'Average',
  'Bill Amount', 'Work Details', 'Pilot', 'Pump', 'Source', 'Timestamp'];
const oldHeaders = octoberHeaders.map(header => header === 'Vehicle No (Full)' ? 'Vehicle' : header);
const sampleMessage = 'Fuel msg-\n\nDate-8/10/26\nLocation-khargone DH\nVehicle no-7412\n' +
  'Present odo-366754\nPrevious odo-366205\nDiseal amount-3441.45\n' +
  'Diseal liter-35.05\nAverage-15.66\nPilot name-Raja\nPump Name- Aadeswar';
const pythonResult = spawnSync(process.env.JANANI_TEST_PYTHON || 'python', ['-c',
  'import runpy,json,sys; app=runpy.run_path(sys.argv[1]); ' +
  'print(json.dumps(app["parse_message"](sys.argv[2])["payload"]))',
  path.join(root, 'janani-webhook.py'), sampleMessage], { encoding: 'utf8' });
assert.equal(pythonResult.status, 0, pythonResult.stderr || 'Activate the project Python environment first');
const payload = JSON.parse(pythonResult.stdout);

function fixture(headers = octoberHeaders, existingRows = [], options = {}) {
  const state = { rows: [headers.slice(), ...existingRows], formatting: [], waits: [], released: 0, flushes: 0, created: 0 };
  const sheet = {
    getLastColumn: () => state.rows[0].length,
    getLastRow: () => state.rows.length,
    getRange(row, column) {
      return {
        getValues: () => [state.rows[row - 1]],
        setNumberFormat(format) { state.formatting.push({ row, column, format }); return this; },
        setFontWeight() { return this; }, setBackground() { return this; }, setFontColor() { return this; }
      };
    },
    getDataRange: () => ({ getValues: () => state.rows }),
    appendRow(row) {
      if (options.appendError) throw new Error('append failed');
      state.rows.push(Array.from(row));
    },
    setFrozenRows() {}
  };
  let exists = !options.newSheet;
  const ss = {
    getSheetByName: () => exists ? sheet : null,
    insertSheet() { exists = true; state.created++; state.rows = []; return sheet; }
  };
  const context = vm.createContext({ Date, Number, String, Object, Error,
    FUEL_HEADERS_OLD: oldHeaders,
    jsonResponseWithCallback: result => result,
    LockService: { getScriptLock: () => ({
      waitLock(ms) { state.waits.push(ms); if (options.lockError) throw new Error('lock unavailable'); },
      releaseLock() { state.released++; }
    }) },
    SpreadsheetApp: { flush() { state.flushes++; } },
    Session: { getScriptTimeZone: () => 'Asia/Kolkata' },
    Utilities: { formatDate(date) {
      return [String(date.getUTCDate()).padStart(2, '0'), String(date.getUTCMonth() + 1).padStart(2, '0'),
        String(date.getUTCFullYear()).slice(-2)].join('/');
    } }
  });
  vm.runInContext(source, context);
  return { context, state, write(data = payload) {
    return context.writeFuelReportV80_(data, 'Oct', 'Oct', "'08/10/26", '08/10/26', ss, {});
  } };
}

test('actual WhatsApp message reaches the October vehicle column', () => {
  const f = fixture();
  const result = f.write();
  assert.equal(result.success, true);
  assert.equal(result.vehicle, '7412');
  assert.equal(result.vehicleColumn, 3);
  assert.equal(f.state.rows[1][2], '7412');
  assert.equal(f.state.rows[1][4], '366754');
  assert.equal(f.state.rows[1][5], '366205');
  assert.equal(f.state.rows[1][6], '549');
  assert.equal(f.state.rows[1][7], '3441.45');
  assert.equal(f.state.rows[1][8], '35.05');
  assert.ok(f.state.rows[1][16] instanceof Date);
  assert.equal(f.state.released, 1);
  assert.equal(f.state.flushes, 1);
});

test('September Vehicle header remains compatible', () => {
  const f = fixture(oldHeaders);
  f.write();
  assert.equal(f.state.rows[1][2], '7412');
});

test('reordered headers write and deduplicate using their actual positions', () => {
  const reordered = ['Timestamp', 'Previous Odo', 'Vehicle No (Full)', 'Location', 'Date',
    'Diesel Liter', 'Type', 'Present Odo', 'Total KM', 'Diesel Amount', 'Rate'];
  const f = fixture(reordered);
  f.write();
  assert.equal(f.state.rows[1][4], "'08/10/26");
  assert.equal(f.state.rows[1][1], '366205');
  assert.equal(f.state.rows[1][7], '366754');
  assert.equal(f.state.rows[1][5], '35.05');
  const result = f.write();
  assert.equal(result.duplicate, true);
  assert.equal(result.existingRow, 2);
  assert.equal(f.state.rows.length, 2);
});

test('fuel duplicate recognition survives numeric sheet values and full-year dates', () => {
  const f = fixture();
  f.write();
  f.state.rows[1][0] = '8-10-2026';
  f.state.rows[1][2] = 7412;
  f.state.rows[1][4] = 366754;
  f.state.rows[1][5] = 366205;
  assert.equal(f.write().duplicate, true);
  assert.equal(f.state.rows.length, 2);
});

test('different vehicles with the same odometer are not collapsed', () => {
  const f = fixture();
  f.write();
  const result = f.write({ ...payload, vehicle: '6047' });
  assert.equal(result.status, 'inserted');
  assert.equal(f.state.rows.length, 3);
});

test('four-digit IDs including leading zeros remain text', () => {
  const f = fixture();
  f.write({ ...payload, vehicle: '0047' });
  assert.equal(f.state.rows[1][2], '0047');
  assert.ok(f.state.formatting.some(item => item.column === 3 && item.format === '@'));
});

test('header aliases and alternate Python payload keys are accepted', () => {
  for (const header of [' Vehicle No (Full) ', 'VEHICLE NUMBER', 'Vehicle ID', 'Registration No']) {
    const headers = octoberHeaders.slice(); headers[2] = header;
    const f = fixture(headers);
    f.write({ ...payload, vehicle: '', vehicle_id: '7412' });
    assert.equal(f.state.rows[1][2], '7412');
  }
});

test('missing vehicle or unrecognized vehicle column fails without appending', () => {
  const f = fixture();
  assert.throws(() => f.write({ ...payload, vehicle: '', vehicle_id: '', vehicle_no: '' }), /Missing vehicle/);
  assert.equal(f.state.rows.length, 1);
  const headers = octoberHeaders.slice(); headers[2] = 'Unrecognized column';
  const g = fixture(headers);
  assert.throws(() => g.write(), /Missing recognized vehicle column/);
  assert.equal(g.state.rows.length, 1);
  assert.equal(g.state.released, 1);
});

test('script lock is released on failure and lock contention prevents writes', () => {
  const f = fixture(octoberHeaders, [], { appendError: true });
  assert.throws(() => f.write(), /append failed/);
  assert.equal(f.state.released, 1);
  const g = fixture(octoberHeaders, [], { lockError: true });
  assert.throws(() => g.write(), /lock unavailable/);
  assert.equal(g.state.rows.length, 1);
  assert.equal(g.state.released, 0);
});

test('new month sheets use the existing compatible header definition', () => {
  const f = fixture(octoberHeaders, [], { newSheet: true });
  f.write();
  assert.deepEqual(f.state.rows[0], oldHeaders);
  assert.equal(f.state.rows[1][2], '7412');
  assert.equal(f.state.created, 1);
});

test('legacy blank vehicle rows are not silently modified', () => {
  const f = fixture();
  f.write();
  f.state.rows[1][2] = '';
  assert.equal(f.write().status, 'inserted');
  assert.equal(f.state.rows[1][2], '');
  assert.equal(f.state.rows.length, 3);
});
