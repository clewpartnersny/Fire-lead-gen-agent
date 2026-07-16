/**
 * Fire Lead-Gen Agent -> Google Sheet bridge.
 *
 * Lets the agent write leads into this spreadsheet WITHOUT a Google Cloud
 * service account (no admin rights needed). Setup, ~3 minutes:
 *
 *  1. Open the target spreadsheet.
 *  2. Extensions -> Apps Script. Delete any placeholder code and paste
 *     this entire file.
 *  3. Change SECRET below to a long random string.
 *  4. Deploy -> New deployment -> type "Web app":
 *       - Execute as: Me
 *       - Who has access: Anyone
 *     Click Deploy, authorize when prompted, and copy the Web app URL
 *     (it looks like https://script.google.com/macros/s/XXXX/exec).
 *  5. In the agent's .env set:
 *       SHEETS_WEBHOOK_URL=<that URL>
 *       SHEETS_WEBHOOK_SECRET=<the same SECRET string>
 *
 * The agent POSTs JSON: {secret, key_column, headers, rows:[{header:value}]}
 * Rows are UPSERTED: if a row with the same key (Company - Domain) exists
 * it is updated in place, otherwise appended. The header row is created
 * automatically on first write.
 */

const SECRET = 'change-me-to-a-long-random-string';
// Fallback tab; each request may name its own tab via body.worksheet,
// which is how multiple sectors share one spreadsheet.
const WORKSHEET = 'Sheet1';

function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return respond({ ok: false, error: 'invalid JSON' });
  }
  if (!body || body.secret !== SECRET) {
    return respond({ ok: false, error: 'bad secret' });
  }

  // housekeeping actions (secret-protected)
  if (body.action === 'delete_sheet') {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const target = ss.getSheetByName(body.worksheet || '');
    if (!target) return respond({ ok: false, error: 'no such tab' });
    if (ss.getSheets().length < 2) return respond({ ok: false, error: 'cannot delete the last tab' });
    ss.deleteSheet(target);
    return respond({ ok: true, deleted: body.worksheet });
  }
  if (body.action === 'dedupe') {
    // Remove rows whose key column repeats, keeping the FIRST occurrence.
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sh = ss.getSheetByName(body.worksheet || WORKSHEET);
    if (!sh || sh.getLastRow() < 2) return respond({ ok: true, removed: 0 });
    const values = sh.getDataRange().getValues();
    const header = values[0].map(String);
    const keyIdx = header.indexOf(body.key_column || 'Company - Domain');
    if (keyIdx < 0) return respond({ ok: false, error: 'key column not found' });
    const seen = {};
    const toDelete = [];
    for (let i = 1; i < values.length; i++) {
      const k = String(values[i][keyIdx]).trim().toLowerCase();
      if (!k) continue;
      if (seen[k]) toDelete.push(i + 1); else seen[k] = true;
    }
    // delete bottom-up so row numbers stay valid
    for (let j = toDelete.length - 1; j >= 0; j--) sh.deleteRow(toDelete[j]);
    return respond({ ok: true, removed: toDelete.length });
  }
  if (body.action === 'list_sheets') {
    const names = SpreadsheetApp.getActiveSpreadsheet().getSheets()
      .map(function (s) { return s.getName(); });
    return respond({ ok: true, sheets: names });
  }

  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const tab = body.worksheet || WORKSHEET;
    const sh = ss.getSheetByName(tab) || ss.insertSheet(tab);

    // header row: use the sheet's existing header if present, else create
    // it; any NEW headers in the payload are appended to the right so
    // column additions in the agent flow through automatically
    let headers;
    if (sh.getLastRow() === 0) {
      headers = body.headers;
      sh.getRange(1, 1, 1, headers.length).setValues([headers]);
    } else {
      headers = sh.getRange(1, 1, 1, sh.getLastColumn())
                  .getValues()[0].map(String).filter(function (h) { return h; });
      const missing = (body.headers || []).filter(function (h) {
        return headers.indexOf(h) < 0;
      });
      if (missing.length) {
        sh.getRange(1, headers.length + 1, 1, missing.length).setValues([missing]);
        headers = headers.concat(missing);
      }
    }

    const keyIdx = headers.indexOf(body.key_column);

    // existing key -> row number map for upserts
    const existing = {};
    const lastRow = sh.getLastRow();
    if (keyIdx >= 0 && lastRow > 1) {
      const keys = sh.getRange(2, keyIdx + 1, lastRow - 1, 1).getValues();
      for (let i = 0; i < keys.length; i++) {
        const k = String(keys[i][0]).trim().toLowerCase();
        if (k) existing[k] = i + 2;
      }
    }

    const appends = [];
    let written = 0;
    (body.rows || []).forEach(function (row) {
      const values = headers.map(function (h) { return row[h] || ''; });
      const key = keyIdx >= 0 ? String(values[keyIdx]).trim().toLowerCase() : '';
      if (key && existing[key]) {
        sh.getRange(existing[key], 1, 1, values.length).setValues([values]);
      } else {
        appends.push(values);
        if (key) existing[key] = lastRow + appends.length;
      }
      written++;
    });
    if (appends.length) {
      sh.getRange(sh.getLastRow() + 1, 1, appends.length, headers.length)
        .setValues(appends);
    }
    return respond({ ok: true, written: written });
  } finally {
    lock.releaseLock();
  }
}

/**
 * Read a tab back (secret-protected). Lets the research agents learn
 * from human edits in the sheet: deleted rows, corrections, notes like
 * "dead" / "PE owned" become training feedback.
 * GET <url>?secret=...&worksheet=Tab%20Name
 */
function doGet(e) {
  if (!e.parameter || e.parameter.secret !== SECRET) {
    return respond({ ok: false, error: 'bad secret' });
  }
  const tab = e.parameter.worksheet || WORKSHEET;
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(tab);
  if (!sh || sh.getLastRow() === 0) return respond({ ok: true, headers: [], rows: [] });
  const values = sh.getDataRange().getValues();
  const headers = (values.shift() || []).map(String);
  const rows = values.map(function (r) {
    const o = {};
    headers.forEach(function (h, i) { if (h) o[h] = String(r[i] ?? ''); });
    return o;
  });
  return respond({ ok: true, headers: headers, rows: rows });
}

function respond(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
