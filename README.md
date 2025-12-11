## Instagram Likers Scraper (Visible Browser) → Google Sheets

This tool opens a real browser window, logs into Instagram, searches for a target account, opens the 5 most recent posts, collects all usernames who liked those posts (with optional limits), and appends them to a Google Sheet each run.

### Important Notes
- Use responsibly and comply with Instagram’s Terms of Use and local laws.
- Instagram’s UI changes often; selectors may need updates over time.
- Heavy accounts can have thousands of likes per post; scraping all can take a long time.

---

## Prerequisites (Windows)
1. Install Python 3.10+ from the Microsoft Store or `python.org`.
2. Open PowerShell in this folder.
3. Create and activate a virtual environment:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
4. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   playwright install
   ```
   - The `playwright install` step downloads the necessary browsers.

---

## Google Sheets Setup (via Google Apps Script Web App)
1. Open your target Google Sheet.
2. From the menu, open: Extensions → Apps Script.
3. In the editor, replace the contents with the “Apps Script (Web App)” code below and save.
4. Click Deploy → New deployment → “Web app”:
   - Execute as: Me
   - Who has access: Anyone
   - Deploy and copy the Web App URL.
5. Paste the Web App URL into `config.py` as `GAS_WEBAPP_URL`.

---

## Configure Settings
Edit values directly in `config.py` (no `.env` required). Set:
- `INSTAGRAM_USERNAME`, `INSTAGRAM_PASSWORD`
- `TARGET_ACCOUNT_HANDLE`, `TARGET_ACCOUNT_QUERY`
- `NUM_POSTS`, `MAX_LIKES_PER_POST`
- `GAS_WEBAPP_URL`, `WORKSHEET_NAME`

Notes:
- The script saves an Instagram login session to `auth.json`. On subsequent runs, it reuses this session so you may not need to log in every time.
- If your account has 2FA enabled, complete it in the visible browser when prompted.

---

## Run the Scraper
With the virtual environment activated:
```powershell
python instagram_scraper.py
```
You will see a browser window. The script will:
- Log in (or reuse session)
- Search for the target account in the UI (and fall back to direct navigation if needed)
- Open the first 5 posts
- Open the likers list for each post and scroll to collect usernames (up to the configured limit)
- Append rows to your Google Sheet: timestamp, account, post URL, username

---

## How It Works (High Level)
- Playwright launches Chromium in headed mode (`headless=False`) so you can watch every step.
- Login is automated using your credentials; session cookies are saved to `auth.json` for reuse.
- The script tries to use the Instagram search UI for visibility; if it fails, it navigates directly to the profile URL.
- For each post, it opens the likers list dialog or a `liked_by` view and scrolls until no more new likers appear or a maximum is reached.
- The scraper sends rows to your Apps Script Web App endpoint, which appends them to the chosen worksheet.

---

## Common Issues
- Selectors break: UI changes can require updating selectors in `instagram_scraper.py`.
- 2FA / suspicious login: complete checks in the visible browser. If blocked, try again later.
- Not all likers loaded: increase `MAX_LIKES_PER_POST` in `config.py`, but expect longer runs.
- If appending fails, verify `GAS_WEBAPP_URL` is correct and deployed with access “Anyone”.

---

## Uninstall / Cleanup
- Deactivate venv: `deactivate`
- Remove the `.venv` folder if you wish.
- Delete `auth.json` to force a fresh login next run.

---

## Apps Script (Web App)
Paste this into the Apps Script editor for your Sheet and deploy as a Web App.

```javascript
function doPost(e) {
  try {
    const payload = JSON.parse(e.postData && e.postData.contents ? e.postData.contents : "{}");
    const worksheetName = (payload.worksheetName || "Likers");
    const rows = payload.rows || [];

    if (!Array.isArray(rows) || rows.length === 0) {
      return _json({ ok: true, appended: 0 });
    }

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let sheet = ss.getSheetByName(worksheetName);
    if (!sheet) {
      sheet = ss.insertSheet(worksheetName);
    }

    // Create header if sheet is empty
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(["run_timestamp_iso", "account_handle", "post_url", "username"]);
    }

    const startRow = sheet.getLastRow() + 1;
    const startCol = 1;
    sheet.getRange(startRow, startCol, rows.length, rows[0].length).setValues(rows);

    return _json({ ok: true, appended: rows.length });
  } catch (err) {
    return _json({ ok: false, error: String(err) }, 500);
  }
}

function _json(obj, status) {
  const output = ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
  if (status && output.setStatusCode) {
    output.setStatusCode(status);
  }
  return output;
}
```

