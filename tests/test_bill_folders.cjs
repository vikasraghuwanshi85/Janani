const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../apps_script/bill_folder_fix.gs'), 'utf8');
const bytes = Buffer.from('test bill image bytes');
const hash = crypto.createHash('sha256').update(bytes).digest('hex');
const payload = {date: '08/10/26', original_date: '08/10/26', date_folder: '08-10-2026',
  vehicle: '7412', image_data: 'data:image/png;base64,' + bytes.toString('base64'), image_hash: hash,
  file_name: '7412_081026_' + hash.slice(0, 12) + '.png', mimeType: 'image/png'};
const headers = ['Date', 'File Name', 'Vehicle', 'Drive Link', 'Original Date', 'Uploaded At', 'Image Hash', 'Date Folder'];
const iterator = values => { let index = 0; return {hasNext: () => index < values.length, next: () => values[index++]}; };

function fixture(options = {}) {
  const state = {folders: [], files: [], rows: [headers.slice()], notes: [[]], released: 0, moves: 0, flushes: 0};
  function folder(name, id) {
    return {getName: () => name, getId: () => id,
      getFiles: () => iterator(state.files.filter(file => file.folderId === id)),
      createFile(blob) {
        if (options.uploadError) throw Error('Drive upload failed');
        const file = {id: 'file_' + state.files.length, folderId: id, name: blob.name,
          description: '', bytes: blob.bytes, getId() {return this.id;}, getName() {return this.name;},
          getDescription() {return this.description;}, setDescription(text) {this.description = text;},
          setSharing() {}, getUrl() {return 'https://drive.google.com/file/d/' + this.id + '/view';},
          getBlob() {return {getBytes: () => this.bytes};},
          getParents() {return iterator([{getId: () => this.folderId}]);},
          moveTo(target) {if (options.moveError) throw Error('Move denied'); this.folderId = target.getId(); state.moves++;}
        };
        state.files.push(file); return file;
      }
    };
  }
  const parent = {getFoldersByName: name => iterator(state.folders.filter(f => f.getName() === name)),
    createFolder(name) {
      if (options.folderError) throw Error('Folder creation denied');
      const f = folder(name, 'folder_' + state.folders.length); state.folders.push(f); return f;
    }};
  const sheet = {getLastRow: () => state.rows.length,
    getDataRange: () => ({getValues: () => state.rows, getNotes: () => state.notes}),
    getRange(row, column) {return {
      setNumberFormat() {return this;},
      setNote(text) {state.notes[row - 1] ||= []; state.notes[row - 1][column - 1] = text;},
      setValues(values) {state.rows[row - 1] = Array.from(values[0]);}
    };},
    appendRow(row) {
      if (options.logError) throw Error('Sheet write failed');
      state.rows.push(Array.from(row)); state.notes.push([]);
    }, setFrozenRows() {}
  };
  const ss = {getSheetByName: () => sheet};
  const context = vm.createContext({Date, Number, String, Object, Error,
    BILL_IMAGES_FOLDER_ID: 'configured-parent', BILL_LOG_SHEET_NAME: 'Bill log',
    jsonResponseWithCallback: result => result,
    Utilities: {DigestAlgorithm: {SHA_256: 'sha256'},
      computeDigest: (_, value) => Array.from(crypto.createHash('sha256').update(Buffer.from(value)).digest()),
      base64Decode(value) {
        if (!/^[A-Za-z0-9+/]*={0,2}$/.test(value)) throw Error('Invalid base64');
        return Array.from(Buffer.from(value, 'base64'));
      }, newBlob: (value, mime, name) => ({bytes: value, mime, name})},
    LockService: {getScriptLock: () => ({waitLock() {}, releaseLock() {state.released++;}})},
    SpreadsheetApp: {flush() {state.flushes++;}},
    DriveApp: {Access: {ANYONE_WITH_LINK: 1}, Permission: {VIEW: 1},
      getFolderById(id) {assert.equal(id, 'configured-parent'); if (options.accessError) throw Error('Parent folder inaccessible'); return parent;},
      getFileById(id) {const f = state.files.find(f => f.id === id); if (!f) throw Error('File inaccessible'); return f;}
    }
  });
  vm.runInContext(source, context);
  return {state, options, parent, context, write: (data = payload) => context.writeBillReportV81_(data, ss, {})};
}

test('bill goes to full-year date folder with confirmed URL', () => {
  const f = fixture(); const result = f.write();
  assert.equal(result.dateFolder, '08-10-2026');
  assert.equal(result.success, true);
  assert.equal(f.state.files.length, 1);
  assert.equal(f.state.folders[0].getName(), '08-10-2026');
  assert.equal(f.state.rows[1][3], result.driveLink);
  assert.equal(f.state.rows[1][6], hash);
  assert.equal(f.state.released, 1);
});

test('retry reuses the same file and log row', () => {
  const f = fixture(); f.write(); const result = f.write();
  assert.equal(result.duplicate, true);
  assert.equal(f.state.files.length, 1);
  assert.equal(f.state.rows.length, 2);
});

test('missing/invalid/conflicting dates do not upload', () => {
  for (const data of [{...payload, date: '', original_date: '', date_folder: ''},
    {...payload, date: '31/02/26', original_date: '31/02/26', date_folder: '31-02-2026'},
    {...payload, date_folder: '07-10-2026'}]) {
    const f = fixture(); assert.throws(() => f.write(data), /date/i);
    assert.equal(f.state.files.length, 0);
  }
});

test('Drive access and date-folder creation failures never fall back', () => {
  for (const options of [{accessError: true}, {folderError: true}]) {
    const f = fixture(options); assert.throws(() => f.write(), /inaccessible|denied/);
    assert.equal(f.state.files.length, 0); assert.equal(f.state.rows.length, 1);
    assert.equal(f.state.released, 1);
  }
});

test('upload failure leaves no successful Bill log row', () => {
  const f = fixture({uploadError: true}); assert.throws(() => f.write(), /upload failed/);
  assert.equal(f.state.rows.length, 1); assert.equal(f.state.files.length, 0);
});

test('retry after upload succeeded but log failed does not create another file', () => {
  const options = {logError: true}; const f = fixture(options);
  assert.throws(() => f.write(), /Sheet write failed/); assert.equal(f.state.files.length, 1);
  options.logError = false; assert.equal(f.write().duplicate, true);
  assert.equal(f.state.files.length, 1); assert.equal(f.state.rows.length, 2);
});

test('old log entry without a Drive link is uploaded instead of skipped', () => {
  const f = fixture(); f.state.rows.push(["'08/10/26", payload.file_name, '7412', '', '08/10/26', '', '', '']);
  f.state.notes.push([]); f.write();
  assert.equal(f.state.rows.length, 2); assert.ok(f.state.rows[1][3]); assert.equal(f.state.files.length, 1);
});

test('existing referenced bill in wrong folder is moved and link reused', () => {
  const f = fixture(); const first = f.write();
  f.state.files[0].folderId = 'old-root-or-wrong-date';
  const result = f.write();
  assert.equal(result.moved, true); assert.equal(result.driveLink, first.driveLink);
  assert.equal(f.state.files.length, 1); assert.equal(f.state.moves, 1);
});

test('different date for the same bytes reuses and relocates the file', () => {
  const f = fixture(); f.write();
  const result = f.write({...payload, date: '06/10/26', original_date: '06/10/26', date_folder: '06-10-2026'});
  assert.equal(result.dateFolder, '06-10-2026'); assert.equal(result.moved, true);
  assert.equal(f.state.files.length, 1); assert.equal(f.state.rows.length, 2);
});

test('bad checksum and missing image are not acknowledged', () => {
  for (const data of [{...payload, image_hash: '0'.repeat(64)}, {...payload, image_data: ''}]) {
    const f = fixture(); assert.throws(() => f.write(data), /checksum|image missing/);
    assert.equal(f.state.rows.length, 1); assert.equal(f.state.files.length, 0);
  }
});

test('conflicting content behind an existing link is not silently replaced', () => {
  const f = fixture(); f.write(); f.state.files[0].bytes = Buffer.from('different image');
  assert.throws(() => f.write(), /content differs/);
  assert.equal(f.state.files.length, 1);
});
