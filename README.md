# Resume.Home

**The job description changes. Your experience doesn't have to be rewritten from scratch.**

Business school students know the routine: one more application, one more round of copying familiar bullet points between resume files, then another check that the spacing, sections, and margins still look right. Resume.Home gives that work a home. Keep your experience in one local library, choose the points that fit each role, and build a resume you can preview before exporting as a PDF.

It runs on your computer in a browser. Your resume and job descriptions stay in a local SQLite database; there is no account, API key, or external AI service.

## From job posting to finished resume

1. **Save your story once.** Import a resume or add work, education, projects, skills, and other details by hand. Revise an entry without losing its earlier wording.
2. **Bring in the role.** Save a job description and review the app's basic, local suggestions about which entries may be relevant. You make the final call.
3. **Build your version.** Select the exact entries you want, rearrange sections, and keep separate application selections for different roles.
4. **Check the details.** Preview the resume, choose Arial, Calibri, or Times New Roman, adjust margins, and export a PDF without rebuilding the layout in Word.

The aim is simple: spend more time deciding what your experience says, and less time nudging the same bullet points around a page.

## Start in your browser on Windows

Install Python 3.13 and the preview dependency, then double-click **Open Resume.Home in Browser.cmd**:

```powershell
python -m pip install -r requirements.txt
```

The launcher opens Resume.Home in your default browser and stores your library under `%LOCALAPPDATA%\Resume.Home\resume.sqlite3`. Keep the command window open while using the site; close it or press Ctrl+C to stop. The `.exe` build is not needed.

## Start

```sh
python -m pip install -r requirements.txt
python -B app.py
```

Open http://127.0.0.1:8765. Keep the terminal running; Ctrl+C stops the server. Restart with the same command to retain the library. This command stores data in `data/resume.sqlite3`, relative to the app directory; the Windows browser launcher uses `%LOCALAPPDATA%` instead. The bundled PDF export binaries are built for Windows Python 3.13.

To use a separate database/port:

```sh
python -B app.py --db data/separate.sqlite3 --port 8766
```

An explicitly supplied database path is relative to the terminal working directory. The server binds only to 127.0.0.1 and is intended for one local user.

## Resume sections

Technical skills have their own PDF section. Certifications, interests, and custom sections appear under **Additional Information** as one labelled line per section, such as **Interest:** Equity markets, FinTech. In the library, use **Edit additional sections** to rename labels or add another, such as Languages. Choose the new section when creating an entry. Renaming a label updates existing entries without changing their saved wording. Under Education, Relevant Coursework is exported as a bullet beneath the matching degree, even when the entry title includes the course list.

Use **New entry → Resume section**, or filter the library with **Section**.

| Section | Main fields |
| --- | --- |
| Work experience | Employer, job title, optional work location, dates, wording, optional project |
| Education | Degree/qualification, school, optional location and field of study, enrollment dates, details |
| Projects | Project name, details, optional organization and role |
| Technical skills | Skill name/group, details, optional proficiency and context |
| Certifications | Certification name, issuer, credential ID/level, details |
| Interests | Interest name, details, optional organization/context |

All categories support tags, dates as written, optional exact start/issue and end/expiry dates, supporting context, verified metrics, and a tailored-job link. Only work experience requires employer and role. Other categories require a title and wording. Leave genuinely unknown values blank; dates as written avoid inventing days for month/year dates.

Edit with **View history → Revise / tailor**. Changing a section or any wording creates a new version. Older versions and application selections are unchanged. **Restore as new revision** copies an older version and records it as the parent. **Prefer this** changes only the preferred pointer. To recategorize an existing project that was previously saved as work experience, revise it and select Projects; the original version is retained.

## Resume import

1. Open **Import resume**. Upload a PDF/DOCX up to 10 MB, or paste resume text.
2. Extract an editable preview. Nothing is written to the library yet. Common work, education, project, skills, certification, and interest sections become selectable entries. Contacts, summaries, and unclassified content stay separate.
3. Review section classifications, titles, organizations, roles, dates, wording, and tags. Move entries between groups, add groups, or deselect unwanted entries. Standalone projects need a project title, not an invented employer or job title.
4. Resolve duplicates: skip, create a separate entry, or append a new revision to an existing entry. Exact comparisons normalize case and whitespace; likely comparisons use at least 78% character similarity for strings of at least 20 characters, including wording with changed metrics. All existing versions and other preview entries are checked.
5. After edits, **Recheck duplicates**, then **Confirm import**. Required-field and duplicate blockers are shown beside the confirmation button. All selected entries commit atomically, or none do. Retrying a successful confirmation is idempotent.

Imported entries start as version 1 unless you explicitly choose to append a revision. Provenance retains original extracted wording, filename, import timestamp, page/paragraph/line location, and dates as written. Inspect it in **History → Resume source**. Imported claims are not automatically declared verified metrics. **Cancel preview** makes no library changes.

### Extraction limits and privacy

Extraction is local and deterministic; no content goes to external AI, and resume text is never executed as instructions. File bytes remain in memory and are discarded after the isolated parser exits. Review state is held in process/browser memory, expires after 30 minutes or a server restart, and is lost on page reload. At most ten server previews are retained.

Wrapped lines are joined with spaces, preserving wording and numeric claims. Common bullet markers, including the PDF-copy U+007F marker, are recognized. Skill suggestions use literal names present in text. Section text may be grouped into a single entry when individual qualifications cannot be reliably separated; review titles/classification and use manual entries for finer organization.

Complex columns, tables, headers, text boxes, nested lists, non-English headings, and hyphenated line breaks can need correction. DOCX locations are paragraphs, not inferred page numbers. OCR is not included: scanned PDFs receive a clear no-text explanation and paste-text guidance. Mixed PDFs warn about pages without text. Password-protected PDFs and macro-enabled DOCX files are rejected. Limits include 50 PDF pages, 250,000 characters, 300 entries, a 20-second extraction timeout, and 30 MB expanded DOCX archives.

## Job matching and applications

Save a job description, then review locally extracted requirements, required/preferred status, and exact supporting passages. Edit/add/remove requirements manually. Editing a requirement clears its stale manual corrections.

Matching offers literal keywords and limited local synonym/concept normalization (for example led → leadership). This is not an embedding model and does not reliably understand negation or arbitrary paraphrases. Strong means at least 80% meaningful term coverage; partial means some overlap or tags alone. Numeric/credential requirements require manual review. Required requirements get double weight. Scores are text relevance, not hiring probabilities.

Technical-skill listings are capped at partial evidence automatically because listing a skill does not demonstrate proficiency. Interests never count as automatic evidence of professional qualifications. Manual evidence corrections remain available. One best version per entry is recommended by default; enable all versions to choose another.

Build applications by selecting exact versions from any section. In the builder, use the arrows beside each major header to rearrange resume sections and the entry arrows to arrange items within a section. Later revisions never change saved selections. Duplicate versions of one entry are blocked unless explicitly allowed. In Education, degrees are subheaders; a Relevant Coursework entry appears as a bullet beneath the matching degree when a school is supplied. Plain-text and Markdown exports include section headings when non-work entries are selected, preserving selection order.

## Backup and compatibility

**Data & backup** exports/imports full JSON, including every version, category, parent relationship, preferred pointer, job, requirement, match correction, application selection, and import provenance. Exports use schema 4; schema 1, 2, and 3 backups remain importable.

Imports are additive and atomic: identical records are skipped and conflicting records reject the whole import. Restore an older conflicting snapshot into a new `--db` database. Database upgrades add category/title/date/location fields with safe defaults; existing version content and IDs are not rewritten. SQLite files and JSON backups are not encrypted. Use JSON export for live backups; stop the server before manually copying database files without their WAL state. Personal databases, backups, and build output are ignored by Git and are not part of this prototype.

## Tests

```sh
python3 -B -m unittest discover -s tests -v
```

The test suite covers immutable revisions, restore/branching, matching, frozen selections, persistence, backup round trips, legacy schema migration, all six categories, PDF/DOCX extraction, PDF preview, and provenance. HTTP tests need permission to bind a localhost port in restricted environments. Tests use separate temporary databases.

## Files

- `app.py`: SQLite store, migrations, validation, matching, backup and HTTP routes.
- `resume_parser.py`: isolated extraction, section parsing and duplicates.
- `static/`: browser interface and styles.
- `tests/`: workflow and migration tests.
- `vendor/`: bundled PDF reader and Windows PDF export dependencies with licenses.
- `demo.py`: optional fictional examples in `data/demo.sqlite3`, never the real library.

No authentication, shared hosting, automatic backups, or OCR is provided. Unsaved browser drafts do not persist across reloads.

## Delete an entry

Use **Delete** on a library card and confirm to permanently remove the entry and all its revisions. If it is used in a saved application, remove it from that application and save the changes first. Export a JSON backup beforehand if you need a recoverable copy.
