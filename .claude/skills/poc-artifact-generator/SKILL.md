---
name: "poc-artifact-generator"
description: "Read a selected solution MD file and generate a realistic, varied corpus of POC artifacts (emails, PDFs, Excel, Word, CSV, database, etc.) that mimic a real-world business."
---
 
# POC artifact generator
 
Turn a chosen solution design (a Markdown file) into a synthetic but realistic document corpus that a POC can ingest, search, and demo against (for example a RAG pipeline).
 
## Input
- Path to the selected solution MD file (ask once if not given; default to `docs/solution.md`).
- Optional: target output folder (default `poc-data/`), corpus size (default `medium`), random seed (default `42`).

## Step 1: Read and extract the scenario

Read the solution file fully and write `poc-data/_scenario.md` capturing:
- Business domain, fictional company name, industry, region, currency, date range (default: last 12 months).
- Personas: 6 to 12 named people with role, department, email, and writing style (terse, formal, chatty).
- External parties: customers, vendors, regulators, partners.
- Core entities and IDs (orders, policies, tickets, contracts, SKUs, projects) with ID formats.
- Business processes and events the solution must handle, and the questions users will ask the POC.
- Edge cases the solution calls out (exceptions, disputes, escalations, policy changes).
- Source system artifacts that matches the scenario.

If the solution file leaves something out, choose a plausible default and record it under `Assumptions`.

Ask me if there unsure about some source system acronyms or abbreviations

## Step 2: Plan the corpus

Determine the corpus type that best tests the solution, and write `poc-data/_manifest.csv` with one row per artifact.
Clarify with me the corpus type you are planning to generate and for which scenarios.

Write `poc-data/_manifest.csv` before generating anything, one row per artifact:
`id, path, type, title, author, recipients, date, entities_referenced, purpose, test_questions`
 
Size presets:
| size | total files | emails | docx | pdf | xlsx | csv/json | other (pptx, txt, md, eml threads) |
|---|---|---|---|---|---|---|---|
| small | 30 | 12 | 5 | 5 | 3 | 3 | 2 |
| medium | 80 | 30 | 12 | 14 | 8 | 8 | 8 |
| large | 200 | 80 | 30 | 35 | 20 | 20 | 15 |
 
Variation rules:
- Mix document kinds: policies, SOPs, contracts, invoices, quotes, meeting minutes, incident reports, specs, proposals, monthly reports, FAQs, onboarding guides, audit findings.
- Mix lengths: about 20% short (under 1 page), 60% medium (1 to 5 pages), 20% long (6 to 20 pages, with headings, tables, appendices).
- Spread dates across the range, with realistic clustering around events (quarter end, incidents, launches).
- Include versioned docs (v1, v2 with changes), superseded policies, and at least 3 near-duplicates.
- Include some messiness: typos in emails, inconsistent naming, a scanned-style PDF, a spreadsheet with merged headers or notes rows.
- Include deliberate conflicts (two docs disagree on a figure or rule) and record them in the manifest so the POC can be tested on them.

## Step 3: Generate the artifacts
Write a Python generator at `poc-data/_generator/generate.py` driven by the manifest, so the corpus is reproducible with the seed. Use well-known libraries: `python-docx`, `openpyxl`, `reportlab` (or `fpdf2`), `python-pptx`, `faker`, and the standard `email` module.
 
Per type:
- Email: `.eml` files with real headers (From, To, Cc, Date, Subject, Message-ID, In-Reply-To). Build threads of 2 to 8 messages with quoted replies, signatures, forwards, and some attachments that reference other corpus files.
- Word: headings, numbered sections, tables, headers/footers, document control table (version, owner, date).
- PDF: letterhead, page numbers, tables, at least a few multi-page reports; one or two image-only pages to simulate scans.
- Excel: multiple sheets, formulas (totals, lookups), dates and currency formats, 100 to 5000 rows for data sheets, a summary sheet.
- CSV/JSON: system exports (CRM, ticketing, ERP) with consistent IDs that join to other files.
- PowerPoint: 8 to 15 slide decks (QBRs, project kickoffs) with speaker notes.
Consistency: every ID, person, amount, and date must agree across files unless it is a planned conflict. Generate shared master data first (`_master/*.json`), then derive every artifact from it.
- Database: generate a CSV or JSON export of the database tables, with consistent IDs that join to other files. Include at least one table with 1000+ rows. Assume large size relational database with multiple tables, foreign keys, and indexes. Include a few rows with nulls, duplicates, and outliers to test edge cases.

## Step 4: Verify
- Open every file with its library to confirm it is valid; count pages, rows, and messages.
- Check every manifest row has a file and every file has a manifest row.
- Spot-check 5 random files for realism and cross-reference accuracy.
- Write `poc-data/_report.md`: counts by type, total size, date range, planned conflicts, assumptions, artifacts matching the scenario source system, and 15 to 30 sample test questions with the file(s) that answer each.
## Rules
- All data is fictional. Use reserved domains (`example.com`, `example.org`), no real people, companies, or personal data.
- Never overwrite an existing `poc-data/` without asking; write to a new timestamped folder instead.
- Keep content domain-accurate to the solution file; no lorem ipsum.
- Install only the libraries named above with `python3 -m pip install`.
## Output
```
poc-data/
  _scenario.md
  _manifest.csv
  _report.md
  _master/
  _generator/generate.py
  emails/  docs/  pdfs/  sheets/  exports/  decks/ database/
```
Finish by summarising the corpus in 5 lines and pointing to `_report.md`.