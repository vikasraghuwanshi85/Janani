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
  bill_category: 'FUEL', ocr_status: 'classified', ocr_reason: 'Matched Aadeshwar Fuels Hindi text', ocr_engine: 'Tesseract', ocr_confidence: '93',
  vehicle: '7412', image_data: 'data:image/png;base64,' + bytes.toString('base64'), image_hash: hash,
  file_name: '7412_081026_' + hash.slice(0, 12) + '.png', mimeType: 'image/png'};
const headers = ['Date', 'File Name', 'Vehicle', 'Drive Link', 'Original Date', 'Uploaded At', 'Image Hash', 'Date Folder'];
const iterator = values => { let index = 0; return {hasNext: () => index < values.length, next: () => values[index++]}; };

function fixture(options = {}) {
  const state = {folders: [], files: [], rows: [headers.slice()], notes: [[]], released: 0, moves: 0, flushes: 0, pending: {}, inserts: 0};
  const resolveFolder = id => state.folders.find(folder => folder.getId() === id) || {getId: () => id, getParents: () => iterator([])};
  function folder(name, id) {
    return {getName: () => name, getId: () => id, getParents: () => iterator([{getId: () => 'configured-parent'}]),
      getFiles: () => iterator(state.files.filter(file => file.folderId === id)),
      createFile(blob) {
        if (options.uploadError) throw Error('Drive upload failed');
        const file = {id: 'file_' + state.files.length, folderId: id, name: blob.name,
          description: '', bytes: blob.bytes, getId() {return this.id;}, getName() {return this.name;},
          getDescription() {return this.description;}, setDescription(text) {this.description = text;},
          setSharing() {}, getUrl() {return 'https://drive.google.com/file/d/' + this.id + '/view';},
          getBlob() {return {getBytes: () => this.bytes};},
          getParents() {return iterator([resolveFolder(this.folderId)]);},
          moveTo(target) {if (options.moveError) throw Error('Move denied'); this.folderId = target.getId(); state.moves++;}
        };
        state.files.push(file); return file;
      }
    };
  }
  const parent = {getId: () => 'configured-parent', getFoldersByName: name => iterator(state.folders.filter(f => f.getName() === name)),
    createFolder(name) {
      if (options.folderError) throw Error('Folder creation denied');
      const f = folder(name, 'folder_' + state.folders.length); state.folders.push(f); return f;
    }};
  parent.getName = () => 'Bills';
  parent.getFiles = () => iterator(state.files.filter(f => f.folderId === 'configured-parent'));
  parent.createFile = blob => {
    if (options.uploadError) throw Error('Drive upload failed');
    const file = {folderId: 'configured-parent', name: blob.name, bytes: blob.bytes, description: '',
      id: 'file_' + state.files.length, getId() {return this.id;}, getName() {return this.name;},
      getUrl() {return 'https://drive.google.com/file/d/' + this.id + '/view';},
      setDescription(v) {this.description = v;}, getDescription() {return this.description;}, setSharing() {},
      getBlob() {return {getBytes: () => this.bytes};}, getParents() {return iterator(this.folderId === parent.getId() ? [parent] : state.folders.filter(f => f.getId() === this.folderId));},
      moveTo(target) {this.folderId = target.getId(); state.moves++;}
    };
    state.files.push(file); return file;
  };
  const sheet = {getLastRow: () => state.rows.length, getMaxColumns: () => options.maxColumns || 26, insertColumnAfter() {state.inserts++;},
    getDataRange: () => ({getValues: () => state.rows, getNotes: () => state.notes}),
    getRange(row, column) {return {
      setNumberFormat() {return this;},
      setValue(value) {state.rows[row - 1] ||= []; state.rows[row - 1][column - 1] = value;},
      setNote(text) {state.notes[row - 1] ||= []; state.notes[row - 1][column - 1] = text;},
      setValues(values) {state.rows[row - 1] = Array.from(values[0]);}
    };},
    appendRow(row) {
      if (options.logError) throw Error('Sheet write failed');
      state.rows.push(Array.from(row)); state.notes.push([]);
    }, setFrozenRows() {}
  };
  let exists = !options.newSheet;
  const ss = {getSheetByName: () => exists ? sheet : null, insertSheet() {exists = true; state.rows = []; state.notes = []; return sheet;}};
  const context = vm.createContext({Date, Number, String, Object, Error,
    BILL_IMAGES_FOLDER_ID: 'configured-parent', BILL_LOG_SHEET_NAME: 'Bill log',
    BILL_FUEL_FOLDER_ID: '', BILL_MAINTENANCE_FOLDER_ID: '',
    jsonResponseWithCallback: result => result,
    Utilities: {DigestAlgorithm: {SHA_256: 'sha256'},
      computeDigest: (_, value) => Array.from(crypto.createHash('sha256').update(Buffer.from(value)).digest()),
      base64Decode(value) {
        if (!/^[A-Za-z0-9+/]*={0,2}$/.test(value)) throw Error('Invalid base64');
        return Array.from(Buffer.from(value, 'base64'));
      }, newBlob: (value, mime, name) => ({bytes: value, mime, name})},
    LockService: {getScriptLock: () => ({waitLock() {}, releaseLock() {state.released++;}})},
    PropertiesService: {getScriptProperties: () => ({getProperty: key => state.pending[key] || null,
      setProperty(key, value) {if (options.journalFileIdError && JSON.parse(value).fileId) throw Error('File ID journal write failed'); state.pending[key] = value;},
      deleteProperty(key) {delete state.pending[key];}})},
    SpreadsheetApp: {flush() {state.flushes++;}},
    DriveApp: {Access: {ANYONE_WITH_LINK: 1}, Permission: {VIEW: 1},
      getFolderById(id) {if (options.accessError) throw Error('Parent folder inaccessible'); return id === 'configured-parent' ? parent : resolveFolder(id);},
      searchFiles(query) {const wanted = query.match(/title contains '([^']+)'/)[1]; return iterator(options.searchIndexLag ? [] : state.files.filter(file => file.name.includes(wanted) || file.description.includes(wanted)));},
      getFileById(id) {const f = state.files.find(f => f.id === id); if (!f) throw Error('File inaccessible'); return f;}
    }
  });
  vm.runInContext(source, context);
  return {state, options, parent, context, write: (data = payload) => context.writeBillReportV81_(data, ss, {})};
}

test('uploads directly with URL, no category/OCR/subfolder requirement', () => {
  const f = fixture(); const result = f.write({...payload, bill_category: undefined, ocr_status: 'failed'});
  assert.equal(result.success, true); assert.equal(result.billUploadMode, 'DIRECT');
  assert.equal(result.folderId, 'configured-parent'); assert.equal(f.state.folders.length, 0);
  assert.equal(f.state.rows[1][3], result.driveLink); assert.equal(f.state.rows[1][6], hash);
});
test('same bytes reuse file and row on repeat', () => {
  const f = fixture(); f.write(); assert.equal(f.write().duplicate, true);
  assert.equal(f.state.files.length, 1); assert.equal(f.state.rows.length, 2);
});
test('missing metadata never fabricates date', () => {
  const f = fixture(); const result = f.write({...payload, date: '', original_date: '', date_folder: 'ignored'});
  assert.equal(result.date, ''); assert.equal(f.state.rows[1][0], ''); assert.equal(f.state.folders.length, 0);
});
test('access and upload failures are not acknowledged', () => {
  for (const options of [{accessError: true}, {uploadError: true}]) {
    const f = fixture(options); assert.throws(() => f.write(), /inaccessible|failed/); assert.equal(f.state.rows.length, 1);
  }
});
test('log failure recovers existing file instead of copying', () => {
  const f = fixture({logError: true}); assert.throws(() => f.write(), /Sheet write failed/);
  f.options.logError = false; assert.equal(f.write().duplicate, true);
  assert.equal(f.state.files.length, 1); assert.equal(f.state.rows.length, 2);
});
test('unknown creation outcome blocks a second file', () => {
  const f = fixture({uploadError: true}); assert.throws(() => f.write(), /failed/);
  f.options.uploadError = false; assert.throws(() => f.write(), /unconfirmed/); assert.equal(f.state.files.length, 0);
});
test('failed file-ID journal recovers from root reservation', () => {
  const f = fixture({journalFileIdError: true}); assert.throws(() => f.write(), /journal/);
  f.options.journalFileIdError = false; assert.equal(f.write().duplicate, true); assert.equal(f.state.files.length, 1);
});
test('invalid date and checksum fail before upload', () => {
  for (const data of [{...payload, date: '31/02/26'}, {...payload, image_hash: '0'.repeat(64)}]) {
    const f = fixture(); assert.throws(() => f.write(data)); assert.equal(f.state.files.length, 0);
  }
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

test('different date metadata for same bytes reuses the file without dated folders', () => {
  const f = fixture(); f.write();
  const result = f.write({...payload, date: '06/10/26', original_date: '06/10/26', date_folder: '06-10-2026'});
  assert.equal(result.dateFolder, ''); assert.equal(result.moved, false); assert.equal(result.billFolder, 'Bills');
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

test('historical dated-folder orphan is recovered but outside matching files are untouched', () => {
  const f = fixture(); f.write(); const legacy = f.parent.createFolder('08-10-2026'); f.state.files[0].folderId = legacy.getId();
  f.state.rows.splice(1); f.state.notes.splice(1); const result = f.write();
  assert.equal(result.moved, true); assert.equal(result.duplicate, true); assert.equal(f.state.files.length, 1);
  const g = fixture(); g.write(); const outside = g.state.files[0]; outside.folderId = 'personal-folder';
  g.state.rows.splice(1); g.state.notes.splice(1); g.write(); assert.equal(g.state.files.length, 2); assert.equal(outside.folderId, 'personal-folder');
});

test('conflicting managed copies block success without another copy', () => {
  const f = fixture(); f.write(); f.state.files.push({...f.state.files[0], id: 'historical-copy'});
  assert.throws(() => f.write(), /Multiple Drive files/); assert.equal(f.state.files.length, 2);
});
