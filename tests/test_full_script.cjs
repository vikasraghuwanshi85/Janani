const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const vm = require('node:vm');
const test = require('node:test');
const script = fs.readFileSync(path.join(__dirname, '../apps_script/Janani.gs'), 'utf8');
const fuelHeaders = ['Date', 'Location', 'Vehicle No (Full)', 'Type', 'Present Odo',
  'Previous Odo', 'Total KM', 'Diesel Amount', 'Diesel Liter', 'Rate', 'Average',
  'Bill Amount', 'Work Details', 'Pilot', 'Pump', 'Source', 'Timestamp'];
const sample = {action: 'insert', date: '08/10/26', month: 'Oct', vehicle: '7412', location: 'Khargone Dh',
  type: 'FUEL', present_odo: '366754', previous_odo: '366205', total_km: '549',
  diesel_amount: '3441.45', diesel_liter: '35.05', rate: '98.19', average: '15.66'};
const iter = values => {let index = 0; return {hasNext: () => index < values.length, next: () => values[index++]};};

function fixture(options = {}) {
  const state = {sheets: {}, files: [], folders: [], released: 0};
  function sheet(name, headers) {
    const s = {rows: headers ? [headers] : [], notes: [], getName: () => name,
      getLastColumn() {return this.rows[0]?.length || 0;}, getLastRow() {return this.rows.length;},
      getDataRange() {return {getValues: () => this.rows, getNotes: () => this.notes};},
      getRange(row, column) {return {
        getValues: () => [s.rows[row - 1]], setNumberFormat() {return this;},
        setFontWeight() {return this;}, setBackground() {return this;}, setFontColor() {return this;},
        setValues(values) {s.rows[row - 1] = Array.from(values[0]);},
        setNote(note) {s.notes[row - 1] ||= []; s.notes[row - 1][column - 1] = note;}
      };}, appendRow(row) {this.rows.push(Array.from(row));}, setFrozenRows() {}
    };
    state.sheets[name] = s; return s;
  }
  sheet('Oct', fuelHeaders);
  const ss = {getSheetByName: name => state.sheets[name] || null, insertSheet: name => sheet(name)};
  const parent = {getFolders: () => iter(state.folders),
    getFoldersByName: name => iter(state.folders.filter(f => f.getName() === name)),
    createFolder(name) {
      const id = 'folder_' + state.folders.length;
      const f = {getId: () => id, getName: () => name, getUrl: () => 'https://drive.google.com/drive/folders/' + id,
        getFiles: () => iter(state.files.filter(file => file.folderId === id)),
        createFile(blob) {
          const file = {folderId: id, name: blob.name, bytes: blob.bytes, description: '',
            id: 'file_' + state.files.length, getId() {return this.id;}, getName() {return this.name;},
            getUrl() {return 'https://drive.google.com/file/d/' + this.id + '/view';},
            setDescription(value) {this.description = value;}, getDescription() {return this.description;}, setSharing() {},
            getBlob() {return {getBytes: () => this.bytes};}, getParents() {return iter([{getId: () => this.folderId}]);},
            moveTo(folder) {this.folderId = folder.getId();}
          };
          state.files.push(file); return file;
        }};
      state.folders.push(f); return f;
    }};
  const context = vm.createContext({Date, Number, String, Object, Error, JSON, Array,
    ContentService: {MimeType: {JSON: 'json', JAVASCRIPT: 'javascript'}, createTextOutput(text) {
      return {text, setMimeType(mime) {this.mime = mime; return this;}};
    }},
    SpreadsheetApp: {openById: () => ss, flush() {}},
    LockService: {getScriptLock: () => ({waitLock() {}, releaseLock() {state.released++;}})},
    Session: {getScriptTimeZone: () => 'Asia/Kolkata'}, Logger: {log() {}},
    Utilities: {DigestAlgorithm: {SHA_256: 'sha256'},
      computeDigest: (_, bytes) => Array.from(crypto.createHash('sha256').update(Buffer.from(bytes)).digest()),
      base64Decode: text => Array.from(Buffer.from(text, 'base64')),
      newBlob: (bytes, mime, name) => ({bytes, mime, name}),
      formatDate: date => String(date.getUTCDate()).padStart(2, '0') + '/' + String(date.getUTCMonth() + 1).padStart(2, '0') + '/' + String(date.getUTCFullYear()).slice(-2)},
    DriveApp: {Access: {ANYONE_WITH_LINK: 1}, Permission: {VIEW: 1},
      getFolderById() {if (options.driveDenied) throw Error('Drive access denied'); return parent;},
      getFileById: id => state.files.find(file => file.id === id)}
  });
  vm.runInContext(script, context);
  return {context, state, post: data => JSON.parse(context.doPost({postData: {contents: JSON.stringify(data)}}).text),
    get: params => JSON.parse(context.doGet({parameter: params}).text)};
}

test('complete file contains its modules exactly once', () => {
  const names = [...script.matchAll(/^function\s+(\w+)\s*\(/gm)].map(m => m[1]);
  assert.equal(names.length, new Set(names).size);
  for (const name of ['doPost', 'doGet', 'writeFuelReportV80_', 'writeBillReportV81_']) assert.ok(names.includes(name));
});

test('doPost writes October ID and rejects duplicate without another row', () => {
  const f = fixture(); const result = f.post(sample);
  assert.equal(result.success, true); assert.equal(result.vehicleColumn, 3);
  assert.equal(f.state.sheets.Oct.rows[1][2], '7412');
  assert.equal(f.post(sample).duplicate, true); assert.equal(f.state.sheets.Oct.rows.length, 2);
});

test('doPost rejects invalid dates, wrong months and corrupted numeric fields', () => {
  for (const change of [{date: '31/02/26'}, {date: ''}, {month: 'Sep'}, {diesel_amount: '4567.0845.'},
    {previous_odo: '3662059'}, {total_km: '-1'}, {average: '50.68'}, {vehicle: ''}, {diesel_liter: '0'}]) {
    const f = fixture(); assert.equal(f.post({...sample, ...change}).success, false, JSON.stringify(change));
    assert.equal(f.state.sheets.Oct.rows.length, 1);
  }
});

test('grouped readings are normalized and absent calculations are computed', () => {
  const f = fixture(); const result = f.post({...sample, present_odo: '366,754', previous_odo: '3,66,205', total_km: '', rate: '', average: ''});
  assert.equal(result.success, true); assert.equal(result.total_km, '549'); assert.equal(result.rate, '98.19');
  assert.equal(f.state.sheets.Oct.rows[1][10], '15.66');
});

test('doPost routes image bill to its correct folder and reuses it on retry', () => {
  const f = fixture(); const image = Buffer.from('image bytes');
  const data = {action: 'insert', date: '08/10/26', original_date: '08/10/26', date_folder: '08-10-2026',
    vehicle: '7412', image_data: 'data:image/png;base64,' + image.toString('base64')};
  const result = f.post(data); assert.equal(result.success, true); assert.equal(result.dateFolder, '08-10-2026');
  assert.ok(result.driveLink); assert.equal(f.state.files.length, 1);
  assert.equal(f.post(data).duplicate, true); assert.equal(f.state.files.length, 1);
  assert.equal(f.state.sheets['Bill log'].rows.length, 2);
});

test('Drive failure reaches doPost as success:false', () => {
  const f = fixture({driveDenied: true});
  const result = f.post({date: '08/10/26', image_data: Buffer.from('image').toString('base64')});
  assert.equal(result.success, false); assert.match(result.error, /Drive access denied/);
  assert.equal(f.state.files.length, 0);
});

test('malformed JSON and absent event are handled without throwing out of doPost', () => {
  const f = fixture();
  assert.equal(JSON.parse(f.context.doPost({postData: {contents: '{bad'}}).text).success, false);
  assert.equal(JSON.parse(f.context.doPost().text).success, true);
});

test('dashboard exposes October vehicle under canonical and original keys', () => {
  const f = fixture(); f.post(sample); const result = f.get({action: 'get_dashboard'});
  assert.equal(result.data[0].Vehicle, '7412'); assert.equal(result.data[0]['Vehicle No (Full)'], '7412');
  assert.match(result.data[0].Timestamp, /^\d{4}-/);
  assert.equal(f.get({action: 'get_all_data'}).count, 0); // V79 bill-only contract retained.
  assert.equal(f.get({action: 'get_combined'}).fuelCount, 1);
});

test('date test and JSON POST read actions retain the full year', () => {
  const f = fixture();
  assert.equal(f.get({action: 'test_date', date: '8/10/26'}).folderFull, '08-10-2026');
  assert.equal(f.post({action: 'test_date', date: '8/10/26'}).folderFull, '08-10-2026');
  assert.equal(f.get({action: 'test_date', date: '31/02/26'}).success, false);
});

test('JSONP is supported with validated callback names', () => {
  const f = fixture();
  const output = f.context.doGet({parameter: {callback: 'dashboard.receive', action: 'get_dashboard'}});
  assert.match(output.text, /^dashboard\.receive\(/); assert.equal(output.mime, 'javascript');
  assert.equal(JSON.parse(f.context.doGet({parameter: {callback: 'alert(1)'}}).text).success, false);
});

test('legacy cleanup functions preview without deleting or relabeling rows', () => {
  const f = fixture(); f.post(sample);
  assert.equal(f.get({action: 'fix_headers'}).success, false);
  assert.equal(f.context.cleanupBillLogDuplicates().extraCopies, 0);
  assert.match(f.context.fixFuelShiftForExistingData(), /No existing rows changed/);
  assert.equal(f.state.sheets.Oct.rows.length, 2);
});
