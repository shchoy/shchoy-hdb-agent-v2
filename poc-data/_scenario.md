# POC Scenario: HEB Properties & Land Group (PLG) "Super-Librarian"

Source: `docs/solution.MD` (selected approach B blend), `docs/REQ.md`.
Generated corpus seed: `42` · size preset: `medium` (80 core artifacts) + 20 submission bundles + database export.

## 1. Business setting

| Item | Value |
|---|---|
| Organisation (fictional) | **Housing & Estates Board (HEB)**, a public housing authority in a Singapore-like city-state |
| Business unit | **Properties & Land Group (PLG)**, Commercial Properties division. Leases and manages ~1,500 commercial units (void-deck shops, neighbourhood centre (NC) shops, eating houses, kiosks) in public housing estates |
| Industry | Public-sector commercial property leasing and estate management |
| Region | Fictional towns: Bayshore Vale (BV), Cendana (CD), Kebun Raya (KR), Rimba Heights (RH), Sungai Tinggi (ST), Pasir Indah (PI) |
| Currency | SGD (S$), GST 9% on rent |
| Corpus date range | 2025-10-01 to 2026-09-30 (some reference documents are older: policies from 2024, a tenancy agreement from 2024, precedents from 2023) |
| Email domains | Staff: `heb.example.org` · tenants: `*.example.com` · vendors: `*.example.com` |
| Source systems (mocked as MCP servers) | SharePoint (policies, SOPs, reports, templates), Lotus Notes (email), i-EMS (defect tickets), PLG Records (tenancies, tasks, submissions) |

## 2. Personas (PLG staff)

| ID | Name | Role | Email | Writing style |
|---|---|---|---|---|
| S01 | Tan Wei Ling | Director, PLG | tan.weiling@heb.example.org | Formal, brief, decisive |
| S02 | Rajesh Pillai | Deputy Director, Leasing Policy & Planning | rajesh.pillai@heb.example.org | Formal, cites policy clauses |
| S03 | Nurul Huda Rahman | Senior Manager, Tenancy Management | nurul.huda@heb.example.org | Chatty, warm, long emails |
| S04 | Marcus Lim | Estate Manager (East: BV, CD, PI) | marcus.lim@heb.example.org | Terse, lowercase, few greetings |
| S05 | Siti Aishah Yusof | Leasing Officer | siti.aishah@heb.example.org | Chatty, occasional typos |
| S06 | Daniel Ong | Property Officer (Inspections) | daniel.ong@heb.example.org | Terse, bullet points |
| S07 | Priya Menon | Manager, Finance & Arrears | priya.menon@heb.example.org | Formal, precise with figures |
| S08 | Kelvin Goh | Data Analyst, Ops Analytics | kelvin.goh@heb.example.org | Terse, technical |
| S09 | Joanne Teo | Legal Counsel | joanne.teo@heb.example.org | Formal, hedged legal language |
| S10 | Ahmad Faizal Ismail | Maintenance Coordinator (i-EMS liaison) | ahmad.faizal@heb.example.org | Terse, ticket-number heavy |
| S11 | Grace Chua | Customer Relations Officer | grace.chua@heb.example.org | Chatty, empathetic |
| S12 | Benjamin Ho | Estate Manager (West: KR, RH, ST) | benjamin.ho@heb.example.org | Semi-formal |

## 3. External parties (all fictional)

- **Tenants**: ~1,450 businesses (minimarts, coffeeshops, clinics, salons, bakeries, tuition centres). Scripted key tenants:
  - Golden Leaf Minimart Pte Ltd (arrears and letter of demand)
  - Sin Hock Eating House (fire incident)
  - Wellcare Family Clinic (late renewal)
  - Mutiara Provision Shop (change of trade to bubble tea)
  - Lucky Star Hair Studio (unauthorised subletting)
  - Prima Dental Care (new tenant, security-deposit query)
  - Heng Ann Confectionery (tenancy agreement whose rent disagrees with the database)
- **Vendors**: Sunrise M&E Services Pte Ltd (M&E term contractor), Kemas Building Works Pte Ltd (civil/structural), PestAway Solutions (pest control), Lumina Valuers & Surveyors (market rent valuation)
- **Regulators**: Environmental Health Authority (EHA, food shop licences), Civil Defence Authority (CDA, fire safety), Urban Planning Authority (UPA)
- **Partners**: Bayshore-Cendana Town Council, Kebun Raya-Rimba Town Council, Sungai Tinggi-Pasir Indah Town Council

## 4. Core entities and ID formats

| Entity | ID format | Example |
|---|---|---|
| Town | 2-letter code | `BV` |
| Commercial unit | `U-<town><blk>-<floor>-<unit>` | `U-BV214-01-32` (Blk 214 Bayshore Vale St 21 #01-32) |
| Tenant | `T-<5 digits>` | `T-10231` |
| Tenancy agreement | `TA-<start year>-<5 digits>` | `TA-2023-00412` |
| Rent invoice | `INV-<yymm>-<6 digits>` | `INV-2609-000123` |
| Payment | `PAY-<8 digits>` | `PAY-00012345` |
| Application | `APP-<year>-<4 digits>` | `APP-2026-0198` |
| Inspection | `INSP-<year>-<4 digits>` | `INSP-2026-1873` |
| Public feedback case (CRM) | `FB-<year>-<5 digits>` | `FB-2026-04417` |
| i-EMS ticket | `IEMS-<yymm>-<4 digits>` | `IEMS-2608-0153` |
| Officer task | `TSK-<year>-<4 digits>` | `TSK-2026-0345` |
| Letter | `LTR-<year>-<5 digits>` | `LTR-2026-00871` |
| Policy / SOP | `PLG-POL-<3>` / `PLG-SOP-<3>` | `PLG-POL-003` |
| Circular | `PLG Circular NN/YYYY` | `PLG Circular 03/2026` |
| Precedent case | `PC-<year>-<3>` | `PC-2024-009` |
| Letter template | `TPL-<code>-<2>` | `TPL-REM-01` |

## 5. Business processes and events the POC must handle

1. **Rental arrears recovery**: monthly rent invoice (due on the 1st) → reminder at 14 days → second reminder at 30 days → letter of demand (LOD) at **60 days** (policy v2.0, from 1 Apr 2026) → termination considered when arrears exceed **3 months' rent**.
2. **Tenancy renewal**: 3-year terms; renewal at market rent (valuation); applications due **6 months** before expiry; security deposit = **3 months'** rent.
3. **Change of trade / trade mix**: no more than 2 units with the same trade per NC cluster unless justified; approvals reference precedents.
4. **A&A works**: tenant alterations need approval; structural works need professional engineer (PE) endorsement.
5. **Usage compliance inspections**: unauthorised trade, display-area encroachment (limit 0.6 m in Policy POL-001 v3.0, raised to **1.0 m** by Circular 07/2026 from 1 Aug 2026), unauthorised subletting, hygiene.
6. **Public feedback → defect classification → i-EMS ticket** routed to the Civil, M&E, Estate Compliance, Pest Control or Town Council liaison team.
7. **Application document completeness**: checklists per application type (new tenancy, renewal, assignment, change of trade, A&A); missing-documents notice to the tenant.
8. **Officer task prioritisation**: renewals due, arrears follow-ups, inspection follow-ups, defects, application reviews.
9. **Vacancy and tender**: monthly vacancy report; vacant units go to tender.

### Questions users will ask the POC (examples)
- "What is PLG's current stance on display areas outside shop fronts?"
- "When do we issue a letter of demand for arrears?"
- "Show me precedents for change of trade to bubble tea within an NC."
- "How many vacant units were there in Bayshore Vale at end-August, and how is vacancy defined?"
- "Which tenants have more than 3 months of arrears? Show me the SQL."
- "Draft a missing-documents notice for APP-2026-0198."
- "Classify this feedback and raise an i-EMS ticket."
- "What are my top 5 tasks this week, and why?"
- "Summarise all documents in the arrears category."
- "Which documents conflict with each other?"

## 6. Edge cases the corpus deliberately includes

- Superseded policy versions (POL-003 v1.0 → v2.0; display-area clause overridden by a circular)
- An SOP left unchanged after its parent policy was revised (still says 45 days)
- A late renewal application (outside the 6-month window)
- Unauthorised subletting found in an inspection; a fire incident with an insurance claim
- Ambiguous or low-confidence feedback texts (multi-category, vague, non-defect complaints)
- Submission bundles with missing, expired, wrong-unit and illegible (scanned) documents
- A prompt-injection attempt inside a tenant email
- Database nulls, duplicate tenant records, outlier rents and impossible dates

## Assumptions

- PLG = Properties & Land Group; i-EMS = integrated Estate Management System (defect/maintenance ticketing). Both confirmed by the user.
- HEB is a fictional stand-in for the real housing authority, and all towns, people, tenants and vendors are invented. The user chose this.
- The solution leaves PLG artefacts unspecified (defect taxonomy, checklists, priority rules, glossary, templates; §7.2), so this corpus invents plausible versions of each.
- Rent is invoiced monthly in advance, due on the 1st. Late-payment interest is 8% p.a. on overdue amounts.
- Vacancy definition (Glossary, April 2026 minutes): **vacant = no active tenancy AND not under tender AND lettable**. The older QBR definition counted units under tender.
- Unit status in the database is a snapshot as at 2026-09-30. The August vacancy report figures were taken at 2026-08-31, and the tender in September did not change those counts.
- NRIC-like identifiers are fictional and masked (`SXXXX123A`).

## Generated IDs

The IDs in sections 4 and 5 are format examples. The generated IDs of the scripted entities (Golden Leaf `TA-2024-00542`, Mutiara change of trade `APP-2026-0256`,
Wellcare renewal `APP-2026-0293`, Prima Dental `APP-2026-0228`, and others) are listed in `_report.md` §4 and `_master/key_entities.json`.
