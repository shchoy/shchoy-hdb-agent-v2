"""PDF documents."""
import datetime as dt
import random
from collections import Counter

from common import (D, addr, arrears_asof, fd, fdl, late_interest, money, register, scripted, sname, tenancy, tenant, town_name, unit,
                    vacancy_asof)
from master import APP_TYPE_LABEL, GST, TAX_BY_CODE, TOWNS
from render import pdf_render, pdf_scanned


def circular_03():
    return [
        ("title", "PLG CIRCULAR 03/2026"),
        ("kv", [("Date", "16 March 2026"), ("To", "All PLG officers"), ("From", f"{sname('S01')}, Director, PLG"),
                ("Subject", "Revised Rental Arrears Management Policy (PLG-POL-003 v2.0)"), ("Effective", "1 April 2026")]),
        ("p", "1. The Director, PLG has approved the revised Rental Arrears Management Policy (PLG-POL-003 v2.0), effective 1 April 2026. It supersedes v1.0 dated 1 March 2024."),
        ("p", "2. The key changes are:"),
        ("bullets", ["A mandatory hardship assessment call (form FA-07) between 31 and 45 days overdue.",
                     "The Letter of Demand is now issued at 60 days overdue (previously 45 days).",
                     "Termination is considered when arrears exceed 3 months' rent including GST (previously 2 months).",
                     "Instalment plans of up to 12 months (previously 6). The Director approves plans above S$30,000 (previously S$20,000)."]),
        ("p", "3. Cases already referred to Legal before 1 April 2026 will continue under the previous policy."),
        ("p", "4. Finance & Arrears will update PLG-SOP-014 accordingly. Queries may be directed to Ms Priya Menon, Manager, Finance & Arrears."),
        ("sig", [sname("S01"), "Director, Properties & Land Group"]),
    ]


def circular_07():
    return [
        ("title", "PLG CIRCULAR 07/2026"),
        ("kv", [("Date", "20 July 2026"), ("To", "All PLG officers; Estate Managers"), ("From", f"{sname('S01')}, Director, PLG"),
                ("Subject", "Display Area Beyond Shopfront at Neighbourhood Centres (Pilot)"), ("Effective", "1 August 2026 to 31 July 2027")]),
        ("p", "1. Following the PLG Management Meeting of 15 April 2026, tenants of units in designated Neighbourhood Centres (NCs) may display goods "
              "up to 1.0 m beyond the shopfront line, subject to the conditions below. This replaces the 0.6 m limit in clause 7.3 of PLG-POL-001 "
              "Trade Mix & Usage Policy v3.0 for NC units for the duration of the pilot."),
        ("p", "2. Conditions:"),
        ("numbered", ["A clear walkway of at least 1.2 m must be maintained at all times.",
                      "The display may not take up more than 50% of the unit's frontage.",
                      "Goods must be removed outside operating hours.",
                      "Fire exits, hose reels and other fire safety equipment must not be obstructed."]),
        ("p", "3. The 0.6 m limit in clause 7.3 continues to apply to void-deck shops outside NCs."),
        ("p", "4. Estate Managers shall stop enforcement action against NC tenants for displays between 0.6 m and 1.0 m that meet the above conditions. "
              "Open cases will be reviewed and closed if compliant."),
        ("p", "5. PLG will review the pilot in June 2027, taking into account feedback cases and inspection findings."),
        ("sig", [sname("S01"), "Director, Properties & Land Group"]),
    ]


def precedents(M):
    rng = random.Random(M["seed"] + 7)
    mut_t, mut_ta, mut_u = scripted(M, "Mutiara Provision Shop")
    cases = [
        ("PC-2023-018", D(2023, 11, 6), "Late renewal", "Kebun Raya", "Hair salon applied to renew one month before expiry; had two late payments.",
         "Rejected. Unit put to tender.", "Application received < 3 months before expiry (POL-002 cl. 4.4); payment record not good. Tenant allowed to bid at tender."),
        ("PC-2024-009", D(2024, 5, 14), "Change of trade", "Pasir Indah", "Provision shop at Pasir Indah Central NC applied to change trade to bubble tea. The NC already had 2 bubble tea outlets.",
         "Rejected.", "Would exceed the concentration limit of 2 per NC (POL-001 cl. 5.1). No evidence of unmet demand. NC also needs grocery outlets after a minimart closed."),
        ("PC-2024-012", D(2024, 7, 2), "Arrears / hardship", "Cendana", "Eating house operator with S$41,200 arrears after a stall-holder dispute asked for a 9-month instalment plan.",
         "Approved by Director as an exception (9 months).", "Exceeded the 6-month limit under POL-003 v1.0, but the business was viable and the deposit covered 3 months. Repaid in full by Apr 2025."),
        ("PC-2024-021", D(2024, 10, 22), "Unauthorised subletting", "Rimba Heights", "Inspection found the rear part of a hair salon partitioned and operated as a nail salon by a third party.",
         "Composition fee S$500; ordered to regularise within 14 days.", "First occurrence (POL-001 cl. 8). Tenant removed the partition and nail salon within 10 days. A second occurrence would lead to termination being considered."),
        ("PC-2025-006", D(2025, 3, 3), "Late renewal", "Sungai Tinggi", "GP clinic applied to renew 4 months before expiry. Good payment record, no breaches.",
         "Accepted as late application.", "Within the 3-6 month discretion window of POL-002 cl. 4.4; essential trade; continuity of healthcare for residents."),
        ("PC-2025-014", D(2025, 6, 18), "Change of trade", "Bayshore Vale", "Mobile phone shop at Vale Point NC applied to change to bubble tea. The NC had 1 bubble tea outlet.",
         "Approved.", "Within the concentration limit (2nd outlet). Rent revised to market rent for F&B; deposit topped up."),
        ("PC-2025-019", D(2025, 9, 9), "Fire incident / rent rebate", "Kebun Raya", "Fire at an eating house kitchen; premises closed 23 days for repairs and CDA clearance.",
         "50% rent rebate for one month approved.", "The fire did not result from tenant negligence (an electrical fault in HEB's riser). The rebate follows the closure-days guideline: more than 21 days of closure qualifies for 50% for one month."),
        ("PC-2025-023", D(2025, 11, 25), "Display encroachment", "Cendana", "Minimart repeatedly displayed goods 1.5 m beyond the shopfront; third occurrence within 12 months.",
         "Composition fee S$500 and tenancy review.", "Followed POL-001 cl. 8. Tenancy not terminated because the tenant installed a retractable display rack."),
    ]
    templates = [
        ("Assignment", "{trade} at {town} applied to assign tenancy to a new operator after the owner retired.", "Approved.", "Assignee met eligibility; assignment fee paid; rent revised to market."),
        ("Assignment", "{trade} at {town} sought assignment 8 months into the tenancy.", "Rejected.", "Tenancy less than 12 months old; looked like profiteering from a tender-won unit."),
        ("A&A works", "{trade} at {town} installed a mezzanine without approval.", "Reinstatement ordered within 30 days; composition fee S$500.", "Structural works need PE endorsement; safety risk."),
        ("A&A works", "{trade} at {town} applied to hack a non-structural partition wall.", "Approved with conditions.", "Non-structural; contractor registered; works outside peak hours."),
        ("Change of trade", "{trade} at {town} applied to add a tuition trade in the afternoon.", "Rejected.", "Mixed use of a clinic not permitted; licensing conditions."),
        ("Change of trade", "{trade} at {town} applied to change to a pharmacy.", "Approved.", "Essential trade gap in the NC; within limits."),
        ("Arrears / hardship", "{trade} at {town} with arrears of 2.5 months asked for a 6-month instalment plan after a medical emergency.", "Approved (6 months).", "Hardship verified; within the delegated limit."),
        ("Arrears / termination", "{trade} at {town} with arrears of 4.2 months, did not respond to the LOD.", "Tenancy terminated; deposit set off.", "Exceeded the termination threshold; no engagement after the LOD."),
        ("Late renewal", "{trade} at {town} applied 5 months before expiry.", "Accepted.", "Within discretion window; good record."),
        ("Unauthorised trade", "{trade} at {town} found selling e-vaporiser accessories.", "Warning; items removed; police informed.", "Prohibited item (POL-001 cl. 5.3)."),
        ("Noise nuisance", "{trade} at {town} operating karaoke after 11 pm.", "Warning, then composition fee S$200.", "POL-001 cl. 7.4 operating hours."),
        ("Subletting", "{trade} at {town} allowed a relative's company to operate from the unit.", "Regularised via assignment application.", "Family business restructuring; assignment criteria met."),
        ("Rent review appeal", "{trade} at {town} appealed a 28% renewal rent increase.", "Appeal partly allowed; increase phased over 2 years.", "POL-002 cl. 5 phasing rule applied."),
        ("Deposit refund dispute", "{trade} at {town} disputed reinstatement deductions from its deposit.", "Deduction reduced from S$6,800 to S$3,200.", "Independent quote obtained; fair wear and tear excluded."),
        ("Change of trade", "{trade} at {town} applied to change to a second laundry in the NC.", "Approved.", "Within limit of 2; residents' feedback indicated demand."),
        ("Fire safety", "{trade} at {town} found with blocked rear exit twice.", "Composition fee S$500; CDA notified.", "Major breach; repeat occurrence."),
    ]
    trades = ["Minimart", "Hair Salon", "Coffeeshop", "GP Clinic", "Bakery", "Tuition Centre", "Laundry", "Florist", "Restaurant", "TCM Clinic", "Hardware shop"]
    for i, (cat, facts, dec, rat) in enumerate(templates):
        y = rng.choice([2023, 2024, 2025, 2026])
        d = D(y, rng.randint(1, 12 if y < 2026 else 8), rng.randint(1, 28))
        cases.append((f"PC-{y}-{30 + i:03d}", d, cat, town_name(rng.choice(TOWNS)["code"]),
                      facts.format(trade=rng.choice(trades), town=town_name(rng.choice(TOWNS)["code"])), dec, rat))
    cases.sort(key=lambda c: c[1])
    b = [("title", "PLG PRECEDENT CASE COMPENDIUM 2023 - 2026"),
         ("p", "Compiled by Tenancy Management for reference by PLG officers. Each case summarises the facts, the decision and the reasoning, so that "
               f"similar cases are treated consistently. Last updated: {fdl(D(2026, 8, 28))}. Cases are anonymised; tenant names are withheld."),
         ("note", "How to use: search by category or policy clause. Precedents guide decisions but do not bind them. Always apply the policy version in "
                  "force on the date of decision."),
         ("h2", "Index"),
         ("table", ["Case", "Date", "Category", "Town", "Decision"], [(c[0], fd(c[1]), c[2], c[3], c[5]) for c in cases], [2.4, 2.2, 3.4, 2.8, 6.2]),
         ("pagebreak",)]
    for c in cases:
        b += [("h2", f"{c[0]} - {c[2]} ({c[3]})"),
              ("kv", [("Date of decision", fdl(c[1])), ("Category", c[2]), ("Town", c[3])]),
              ("h3", "Facts"), ("p", c[4] + " " + rng.choice([
                  "The officer reviewed the tenancy file, the inspection history and the payment record before making a recommendation.",
                  "Residents' feedback received through CityFix and the hotline over the previous 12 months was also considered.",
                  "The tenant was given an opportunity to make written representations before the decision.",
                  "The case was discussed at the monthly Tenancy Management case review."])),
              ("h3", "Decision"), ("p", c[5]), ("h3", "Reasoning and policy basis"), ("p", c[6]),
              ("h3", "Outcome / lessons"), ("p", rng.choice([
                  "No further breaches recorded in the following 12 months.", "Officers should document the trade-mix count used at the date of decision.",
                  "Applied in subsequent similar cases.", "Highlights the importance of early engagement with the tenant.",
                  "Policy clause later clarified in the next policy revision."]))]
    return b, [c[0] for c in cases]


def aa_guidelines():
    b = [("title", "GUIDELINES ON ALTERATION & ADDITION (A&A) WORKS FOR COMMERCIAL TENANTS"),
         ("p", "Edition 2025 (issued 3 February 2025). These guidelines explain what approvals tenants of HEB commercial premises need before carrying out "
               "renovation or alteration and addition (A&A) works, and the conditions that apply."),
         ("h1", "1. Why Approval is Required"),
         ("p", "HEB commercial premises are mostly at the ground floor of residential blocks. Works that affect structural elements, building services, "
               "fire safety provisions or the external facade can affect residents' safety and the building's integrity. All A&A works therefore "
               "need HEB's written approval before they start, except for the minor works listed in section 3.")]
    b += [("h1", "2. Categories of Works"),
          ("table", ["Category", "Examples", "Approval", "Processing time"], [
              ("Exempt (minor)", "Painting, loose furniture, shelving not fixed to walls, replacing light fittings", "Not required; notify Estate Manager", "-"),
              ("Category A (non-structural)", "Partition walls (drywall), false ceilings, signage, shopfront glazing, electrical rewiring within unit", "Required", "10 working days"),
              ("Category B (services)", "Plumbing, grease traps, exhaust ducting, air-conditioning condensers, gas piping", "Required; licensed contractors", "14 working days"),
              ("Category C (structural)", "Hacking of walls, new openings, mezzanine floors, floor screed > 50 mm, roof works", "Required; PE endorsement", "21 working days"),
          ], [3.3, 7, 3.7, 3])]
    b += [("h1", "3. Exempt Works"),
          ("p", "Exempt works must not damage the structure, obstruct fire safety equipment or change the external appearance. Tenants must still tell the "
                "Estate Manager at least 3 working days beforehand, so that complaints from residents can be handled.")]
    b += [("h1", "4. Documents Required"),
          ("table", ["Code", "Document", "Category A", "Category B", "Category C"], [
              ("AA", "Application for A&A works (form PLG-AA-01)", "Yes", "Yes", "Yes"), ("DWG", "Layout and elevation drawings (scale 1:50 or 1:100)", "Yes", "Yes", "Yes"),
              ("CON", "Contractor's registration certificate", "Yes", "Yes", "Yes"), ("PE", "Professional Engineer endorsement", "-", "If structural support", "Yes"),
              ("MS", "Method statement and work schedule", "Yes", "Yes", "Yes"), ("INS", "Contractor's all-risk insurance certificate", "Yes", "Yes", "Yes")], [1.5, 7, 2.5, 3, 3])]
    b += [("h1", "5. Conditions of Approval"),
          ("numbered", ["Works may only be done between 9.00 am and 6.00 pm on Mondays to Saturdays. Noisy works (hacking, drilling) are limited to 10.00 am - 5.00 pm.",
                        "No works on Sundays or public holidays.", "Debris must be bagged and removed daily, not left in common areas.",
                        "Hoarding must be put up for works lasting more than 3 days.", "Fire safety provisions must stay operational at all times.",
                        "The tenant must reinstate the premises at the end of the tenancy unless HEB agrees in writing otherwise.",
                        "Any damage to common property will be repaired at the tenant's cost."])]
    b += [("h1", "6. Fees"),
          ("table", ["Item", "Fee (before GST)"], [("Category A processing fee", "S$150"), ("Category B processing fee", "S$250"), ("Category C processing fee", "S$500"),
                                                   ("Re-submission after rejection", "50% of processing fee"), ("Inspection of completed works (Category C)", "S$200")], [10, 6])]
    b += [("h1", "7. Prohibited Works"),
          ("bullets", ["Removal or weakening of columns, beams or load-bearing walls.", "Installation of cooking facilities in units not approved for F&B.",
                       "Enclosure of common corridors or five-foot ways.", "Installation of gas cylinders above 2 x 50 kg in eating houses without CDA approval.",
                       "Changes to the external facade colour scheme of the block."])]
    b += [("h1", "8. Unapproved Works"),
          ("p", "If works are carried out without approval, HEB may order them to stop, require the premises to be reinstated within 30 days, and impose "
                "composition fees under PLG-POL-001 clause 8. Repeated breaches may lead to termination being considered."),
          ("h1", "9. Completion"),
          ("p", "The tenant must submit completion photos within 7 days of completing Category A and B works. Category C works need a completion "
                "inspection and a PE certificate of supervision."),
          ("pagebreak",),
          ("h1", "Annex 1 - Drawing Requirements"),
          ("table", ["Item", "Requirement"], [("Title block", "Unit address, unit ID, tenant name, drawing number, revision, date, scale"),
                                             ("Layout plan", "Existing and proposed layouts shown separately; new works hatched"),
                                             ("Elevations", "Shopfront elevation with signage dimensions; display area line at 0.6 m (void deck) or 1.0 m (NC, pilot)"),
                                             ("Services", "Electrical single-line diagram for rewiring; plumbing layout for wet works"),
                                             ("Fire safety", "Exits, extinguishers, hose reels marked; travel distances")], [4, 12]),
          ("pagebreak",),
          ("h1", "Annex 2 - Sample Method Statement Headings"),
          ("numbered", ["Scope of works", "Sequence and schedule", "Manpower and supervision", "Plant and equipment", "Noise and dust control",
                        "Debris management", "Safety measures and permits", "Emergency contacts"]),
          ("h1", "Annex 3 - Frequently Asked Questions"),
          ("table", ["Question", "Answer"], [
              ("Do I need approval to change my signboard?", "Yes, Category A. Signboard must not exceed the shopfront width or 600 mm in height."),
              ("Can I install an air-con condenser on the external wall?", "Only at designated condenser ledges (Category B)."),
              ("Can I knock down the wall between two units I rent?", "Category C with PE endorsement; both tenancies must be in the same name."),
              ("How long is the approval valid?", "Works must start within 3 months of approval and complete within 6 months.")], [7, 9]),
          ("pagebreak",),
          ("h1", "Annex 4 - Trade-specific Requirements"),
          ("table", ["Trade", "Additional requirements", "Typical category"], [
              ("Coffeeshop / eating house", "Grease interceptor sized per EHA guidelines; exhaust duct with access panels every 3 m; quarterly duct cleaning record; "
                                            "gas installation by licensed gas worker; CDA fire safety certificate for ORA enclosures", "B / C"),
              ("Bakery & confectionery", "Oven exhaust and heat shielding; floor trap with grease basket; ovens above 20 kW need electrical load approval", "B"),
              ("Clinics (GP, dental, TCM)", "Radiation shielding plan for X-ray rooms (dental); clinical waste store; wash-hand basins in each consultation room", "A / B"),
              ("Childcare / tuition", "Child-safe glazing; additional exit if occupant load exceeds 50; no mezzanine", "A / C"),
              ("Minimart / provision", "Chiller condensers only at designated ledges; floor loading check for racking above 2.4 m", "A / B"),
              ("Hair salon", "Additional water points and floor traps; hair traps on all basins", "B"),
              ("Bubble tea / snack kiosk", "Sink with hot and cold water; no cooking with open flame in kiosks", "A / B"),
          ], [4, 9.5, 3.5]),
          ("pagebreak",),
          ("h1", "Annex 5 - Worked Examples"),
          ("h3", "Example 1: Shopfront and signage replacement (Category A)"),
          ("p", "A florist wants to replace its aluminium shopfront with frameless glass and install a new lightbox sign. Documents: AA, DWG (elevation "
                "showing sign dimensions), CON, MS, INS. No PE endorsement is needed. Processing time: 10 working days. Fee: S$150."),
          ("h3", "Example 2: Grease trap and exhaust ducting for a new restaurant (Category B)"),
          ("p", "A unit approved for change of trade to restaurant needs a grease interceptor and an exhaust duct to the roof. Documents: AA, DWG (plumbing "
                "layout and duct route), CON (licensed plumber and M&E contractor), MS, INS. The duct route through common areas needs Town Council "
                "consent. Processing time: 14 working days. Fee: S$250."),
          ("h3", "Example 3: Combining two adjoining units (Category C)"),
          ("p", "A tuition centre renting #02-05 and #02-06 wants to open the party wall. Documents: all of the above plus PE endorsement with structural "
                "calculations and a lintel detail. Both tenancies must be in the same name and expire on the same date. Processing time: 21 working days. "
                "Fees: S$500 processing plus S$200 completion inspection. On termination, the wall must be reinstated unless HEB agrees otherwise."),
          ("h3", "Example 4: Works started without approval"),
          ("p", "During a routine inspection, a minimart is found to have installed a mezzanine for storage. It is a Category C structural work done "
                "without approval. The Estate Manager issues a stop-work order. The tenant must remove the mezzanine within 30 days and pay a "
                "composition fee of S$500 (POL-001 cl. 8). If the tenant wants to keep it, they must submit a retrospective application with PE "
                "certification of the as-built structure. Approval is not guaranteed."),
          ("h1", "Annex 6 - Approval Process Flow"),
          ("numbered", ["Tenant submits form PLG-AA-01 with documents to the Estate Manager (email or HEB branch).",
                        "Leasing Officer checks completeness against the ALTERATION checklist within 3 working days; issues TPL-DOC-02 if anything is missing.",
                        "Estate Manager assesses impact on structure, services, fire safety and neighbours; consults Civil & Structural for Category C.",
                        "Approval letter issued with conditions, or rejection with reasons.",
                        "Tenant notifies start date at least 3 working days in advance; Estate Manager may inspect during works.",
                        "Tenant submits completion photos or, for Category C, the PE certificate of supervision; Estate Manager closes the case."]),
          ("pagebreak",),
          ("h1", "Annex 7 - Reinstatement Standards"),
          ("table", ["Element", "Standard on handover"], [("Walls", "Original layout restored; patched and painted in HEB standard white"),
                                                         ("Floor", "Original tiles or equivalent; no screed above original level"),
                                                         ("Ceiling", "False ceilings removed unless HEB agrees in writing to keep them"),
                                                         ("Services", "Tenant-installed services capped off safely; DB board labelled"),
                                                         ("Shopfront", "Original roller shutter in working condition"),
                                                         ("Signage", "All signage removed; wall made good")], [4, 13]),
          ("h1", "Annex 8 - Contacts"),
          ("table", ["Matter", "Contact"], [("A&A applications (East)", f"{sname('S04')}, Estate Manager (East)"),
                                           ("A&A applications (West)", f"{sname('S12')}, Estate Manager (West)"),
                                           ("Completeness checks", f"{sname('S05')}, Leasing Officer"),
                                           ("Policy questions", f"{sname('S02')}, Deputy Director")], [6, 11])]
    return b


def audit_report(M):
    ren = [a for a in M["applications"] if a["app_type"] == "RENEWAL" and a["tenancy_id"]]
    late = [a for a in ren if (tenancy(M, a["tenancy_id"])["end_date"] - a["submitted_date"]).days < 182]
    cutoff = D(2026, 6, 30)
    fu = [i for i in M["inspections"] if i["follow_up_due"] and i["follow_up_due"] <= cutoff]
    fu_late = [i for i in fu if i["closed_date"] is None or i["closed_date"] > i["follow_up_due"]]
    tks = [t for t in M["tickets"] if t["created_date"] <= cutoff]
    mis = [t for t in tks if t["status"] == "Rejected - Misrouted"]
    closed = [t for t in tks if t["sla_met"] is not None]
    sla = sum(1 for t in closed if t["sla_met"]) / max(1, len(closed))
    ha_t, ha_ta, ha_u = scripted(M, "Heng Ann Confectionery")
    findings = [
        ("IA-01", "Late renewal applications accepted without documented justification", "Medium",
         f"{len(late)} of {len(ren)} renewal applications ({len(late) / max(1, len(ren)):.0%}) in the review period were received less than 6 months "
         "before expiry. For 7 of the 15 sampled late cases, the file did not record why the late application was accepted under POL-002 cl. 4.4.",
         "Record the justification and approving officer for each late renewal in PLG Records.", sname("S03"), "31 Oct 2026"),
        ("IA-02", "Rent master data does not match the tenancy agreement", "High",
         f"In a sample of 60 tenancy agreements, 1 tenancy ({ha_ta['tenancy_id']}, {ha_t['name']}, {ha_u['unit_id']}) is recorded in PLG Records at "
         f"{money(ha_ta['monthly_rent'])}/month, but the signed agreement states S$4,580.00/month. The tenant has been over-billed S$270 a month "
         f"(before GST) since {fd(ha_ta['start_date'])}.",
         "Correct the record, refund the over-billed amount and introduce maker-checker for rent data entry.", sname("S07"), "30 Sep 2026"),
        ("IA-03", "Inspection follow-ups not completed on time", "Medium",
         f"{len(fu_late)} of {len(fu)} inspection follow-ups due by {fd(cutoff)} ({len(fu_late) / max(1, len(fu)):.0%}) were closed late or remained open, "
         "including a major breach (unauthorised subletting) in Rimba Heights that was still open at the time of audit.",
         "Estate Managers to review overdue follow-ups weekly; prioritise major breaches.", f"{sname('S04')} / {sname('S12')}", "31 Aug 2026"),
        ("IA-04", "Arrears SOP not aligned with revised policy", "High",
         "PLG-SOP-014 v1.2 still tells officers to refer cases for a Letter of Demand at day 45. PLG-POL-003 v2.0 (effective 1 Apr 2026) "
         "requires a hardship call first and the LOD at day 60. The SOP update due by 31 May 2026 (Management Meeting 4/2026, action 1) has not been done. "
         "Two LODs in the sample were issued at about day 46, before any hardship call.",
         "Update SOP-014 immediately; brief F&A officers; check LODs issued since 1 Apr 2026.", sname("S07"), "15 Aug 2026"),
        ("IA-05", "Tenant-facing FAQ shows the wrong security deposit amount", "Low",
         "The Tenant FAQ (2025 edition) on the HEB website says the security deposit is 2 months' rent. PLG-POL-002 cl. 6.1 sets it at 3 months. "
         "Two copies of the FAQ are on SharePoint with slightly different content.",
         "Withdraw the FAQ, correct it and keep a single controlled copy.", sname("S03"), "30 Sep 2026"),
        ("IA-06", "Misrouted i-EMS tickets", "Low",
         f"{len(mis)} of {len(tks)} i-EMS tickets ({len(mis) / max(1, len(tks)):.1%}) raised up to {fd(cutoff)} were rejected by contractors as misrouted. "
         f"Overall SLA attainment for closed tickets was {sla:.1%}.",
         "Refresher on the SOP-020 taxonomy; consider decision support for classification.", sname("S10"), "31 Dec 2026"),
    ]
    b = [("title", "INTERNAL AUDIT REPORT: TENANCY MANAGEMENT (PLG)"),
         ("kv", [("Report no.", "IA/2026/07"), ("Date", "28 July 2026"), ("Audit period", "1 October 2025 - 30 June 2026"),
                 ("Auditee", "Properties & Land Group - Tenancy Management, Finance & Arrears, Estate Management"),
                 ("Distribution", f"{sname('S01')}; {sname('S02')}; {sname('S03')}; {sname('S07')}; Audit Committee"),
                 ("Overall rating", "Needs Improvement")]),
         ("h1", "1. Executive Summary"),
         ("p", "Internal Audit reviewed the design and operating effectiveness of controls over tenancy renewals, rent master data, usage inspections, "
               "arrears recovery and defect routing. Six findings were raised: two High, two Medium and two Low. Management has agreed to the "
               "action plans. The most significant issues are rent master data integrity (IA-02) and the arrears SOP being out of step with policy (IA-04)."),
         ("table", ["Ref", "Finding", "Rating"], [(f[0], f[1], f[2]) for f in findings], [1.8, 12, 3.2]),
         ("h1", "2. Scope and Approach"),
         ("bullets", ["Sample testing of 60 tenancy agreements against PLG Records.", "Data analytics over all inspections, i-EMS tickets and renewal applications in the audit period.",
                      "Walk-through of the arrears recovery process with F&A officers.", "Review of policies, SOPs and tenant-facing publications for consistency."]),
         ("h1", "3. Detailed Findings")]
    for f in findings:
        b += [("h2", f"{f[0]} {f[1]}"), ("kv", [("Rating", f[2]), ("Observation", f[3]), ("Recommendation", f[4]), ("Management owner", f[5]), ("Target date", f[6])]),
              ("p", "Management response: Agreed. " + {"IA-01": "A mandatory 'late justification' field will be added in PLG Records.",
                                                         "IA-02": "Record corrected on 5 Aug 2026; refund being processed. Maker-checker to go live in Q4.",
                                                         "IA-03": "Weekly overdue list implemented from August.",
                                                         "IA-04": "SOP v1.3 is being drafted. Interim email instruction issued to F&A officers.",
                                                         "IA-05": "FAQ withdrawn from website on 1 Aug 2026; revision in progress.",
                                                         "IA-06": "Training scheduled; AI classification assistant to be explored in the super-librarian POC."}[f[0]])]
    b += [("h1", "4. Rating Definitions"),
          ("table", ["Rating", "Meaning"], [("High", "Significant control weakness; immediate action required"), ("Medium", "Control weakness needing timely action"),
                                            ("Low", "Improvement opportunity")], [3, 13]),
          ("h1", "Appendix A - Data Analytics Summary"),
          ("table", ["Test", "Population", "Exceptions"], [("Renewals received < 6 months before expiry", len(ren), len(late)),
                                                          ("Inspection follow-ups closed late / open", len(fu), len(fu_late)),
                                                          ("i-EMS tickets misrouted", len(tks), len(mis)),
                                                          ("Tenancy agreements vs PLG Records rent", 60, 1)], [9, 4, 4]),
          ("pagebreak",),
          ("h1", "Appendix B - Late Renewal Applications (IA-01)"),
          ("p", "Renewal applications received less than 182 days before tenancy expiry. 'Justification recorded' reflects the file review on the sampled cases."),
          ("table", ["Application", "Tenancy", "Submitted", "Expiry", "Days before expiry", "Justification recorded"],
           [(a["application_id"], a["tenancy_id"], fd(a["submitted_date"]), fd(tenancy(M, a["tenancy_id"])["end_date"]),
             (tenancy(M, a["tenancy_id"])["end_date"] - a["submitted_date"]).days, "No" if i % 2 else "Yes") for i, a in enumerate(late)], [2.8, 3, 2.6, 2.6, 2.8, 3.2]),
          ("pagebreak",),
          ("h1", "Appendix C - Inspection Follow-ups Closed Late or Open (IA-03)"),
          ("table", ["Inspection", "Unit", "Finding", "Outcome", "Follow-up due", "Closed"],
           [(i["inspection_id"], i["unit_id"], i["finding_code"], i["outcome"], fd(i["follow_up_due"]), fd(i["closed_date"]) if i["closed_date"] else "OPEN")
            for i in sorted(fu_late, key=lambda i: i["follow_up_due"])], [2.8, 3.2, 3.6, 2.6, 2.6, 2.2]),
          ("h1", "Appendix D - Misrouted i-EMS Tickets (IA-06)"),
          ("table", ["Ticket", "Feedback", "Created", "Defect code", "Routed to", "Correct team"],
           [(t["ticket_id"], t["feedback_id"], fd(t["created_date"]), t["category_code"], t["team"], TAX_BY_CODE[t["category_code"]]["team"]) for t in mis],
           [3, 3, 2.4, 2.2, 3.2, 3.2]),
          ("h1", "Appendix E - Sample Selection Method"),
          ("p", "The 60 tenancy agreements in IA-02 were selected by stratified random sampling across the six towns (10 per town), weighted towards tenancies "
                "that started in 2024-2025 when PLG Records data entry was decentralised to the estate offices. Each agreement was compared field by field "
                "(rent, deposit, term, approved trade, unit) against PLG Records. Data analytics tests ran over the full populations extracted from "
                "PLG Records, CRM and i-EMS on 7 July 2026.")]
    return b


def ops_report(M, month_end):
    month_start = D(month_end.year, month_end.month, 1)
    vac = vacancy_asof(M, month_end)
    rows = []
    tot = Counter()
    for t in TOWNS:
        c = t["code"]
        total = vac["total"][c]
        v, tn, nl = vac["vacant"][c], vac["tender"][c], vac["not_lettable"][c]
        ten = total - v - tn - nl
        occ = ten / (total - nl)
        rows.append((t["name"], total, ten, v, tn, nl, f"{occ:.1%}"))
        for kk, val in zip(["total", "ten", "v", "tn", "nl"], [total, ten, v, tn, nl]):
            tot[kk] += val
    rows.append(("TOTAL", tot["total"], tot["ten"], tot["v"], tot["tn"], tot["nl"], f"{tot['ten'] / (tot['total'] - tot['nl']):.1%}"))
    arr = arrears_asof(M, month_end)
    bk = Counter()
    bka = Counter()
    for r in arr:
        bk[r["bucket"]] += 1
        bka[r["bucket"]] += r["amount"]
    fb = [f for f in M["feedback"] if month_start <= f["received_date"] <= month_end]
    fbc = Counter(f["category"] for f in fb)
    tk = [t for t in M["tickets"] if month_start <= t["created_date"] <= month_end]
    tkc = [t for t in tk if t["sla_met"] is not None]
    ins = [i for i in M["inspections"] if month_start <= i["inspection_date"] <= month_end]
    insc = Counter(i["outcome"] for i in ins)
    apps = [a for a in M["applications"] if month_start <= a["submitted_date"] <= month_end]
    appc = Counter(APP_TYPE_LABEL[a["app_type"]] for a in apps)
    over3 = [r for r in arr if r["months_of_rent"] > 3]
    mname = f"{month_end:%B %Y}"
    b = [("title", f"PLG MONTHLY OPERATIONS REPORT - {mname.upper()}"),
         ("kv", [("Prepared by", f"{sname('S08')}, Ops Analytics"), ("Reporting date", fdl(month_end)), ("Issued", fdl(month_end + dt.timedelta(days=9))),
                 ("Distribution", "PLG Management")]),
         ("h1", "1. Highlights"),
         ("bullets", [f"Vacant units: {tot['v']} (excluding {tot['tn']} under tender and {tot['nl']} not lettable). Occupancy {tot['ten'] / (tot['total'] - tot['nl']):.1%}.",
                      f"Total arrears: {money(sum(bka.values()))} across {len(arr)} tenancies; {len(over3)} tenancies above the 3-month termination threshold.",
                      f"{len(fb)} public feedback cases received; {len(tk)} i-EMS tickets raised.",
                      f"{len(ins)} inspections completed ({insc['Major Breach']} major breaches).",
                      f"{len(apps)} applications received."]),
         ("h1", "2. Portfolio and Vacancy"),
         ("note", "Definition (wef Apr 2026): Vacant = lettable unit with no active or committed tenancy, excluding units under tender."),
         ("table", ["Town", "Total units", "Tenanted", "Vacant", "Under tender", "Not lettable", "Occupancy"], rows, [3.4, 2.2, 2.2, 2, 2.4, 2.4, 2.4]),
         ("h1", "3. Rental Arrears"),
         ("table", ["Ageing bucket", "Tenancies", "Amount"], [(b_, bk[b_], money(bka[b_])) for b_ in ["0-30", "31-60", "61-90", ">90"]]
          + [("Total", len(arr), money(sum(bka.values())))], [6, 4, 6]),
         ("p", "Top 5 arrears cases:"),
         ("table", ["Tenancy", "Tenant", "Unit", "Amount", "Days overdue"], [(r["tenancy_id"], tenant(M, r["tenant_id"])["name"], r["unit_id"], money(r["amount"]), r["days_overdue"])
                                                                             for r in arr[:5]], [3, 5, 3.2, 3, 2.8]),
         ("h1", "4. Public Feedback and Defects"),
         ("table", ["Category", "Cases"], sorted(fbc.items(), key=lambda x: -x[1]), [10, 6]),
         ("p", f"i-EMS: {len(tk)} tickets raised in {mname}; {len(tkc)} closed, of which {sum(1 for t in tkc if t['sla_met'])} met SLA "
               f"({(sum(1 for t in tkc if t['sla_met']) / max(1, len(tkc))):.0%}). Misrouted: {sum(1 for t in tk if t['status'] == 'Rejected - Misrouted')}."),
         ("h1", "5. Inspections"),
         ("table", ["Outcome", "Count"], [(o, insc[o]) for o in ["Compliant", "Minor Breach", "Major Breach"]], [10, 6]),
         ("h1", "6. Applications Received"),
         ("table", ["Type", "Count"], sorted(appc.items()), [10, 6]),
         ("h1", "7. Commentary"),
         ("p", "Vacancy remained stable. Units vacant for more than 6 months are concentrated in older void-deck blocks with low footfall. Estate "
               "Managers recommend combining them into the next tender with lower minimum bids. Arrears in the >90-day bucket are driven by a "
               "small number of large tenancies, which have been referred to Legal under PLG-POL-003 v2.0."),
         ("pagebreak",),
         ("h1", "Appendix A - Vacant Units"),
         ("table", ["Unit", "Address", "Type", "Area (sqm)", "Vacant since", "Days vacant"],
          [(u["unit_id"], f"Blk {u['blk']} {u['street']} {u['unit_no']}", u["unit_type"], u["floor_area_sqm"], fd(u["vacant_since"]), (month_end - u["vacant_since"]).days)
           for u in sorted((u for u in M["units"] if u["status"] == "Vacant" and u["vacant_since"] <= month_end), key=lambda u: u["vacant_since"])],
          [3, 5.6, 2.8, 1.8, 2.2, 1.8]),
         ("pagebreak",),
         ("h1", "Appendix B - Arrears Over 30 Days"),
         ("table", ["Tenancy", "Tenant", "Unit", "Amount", "Days", "Months of rent", "Bucket"],
          [(r["tenancy_id"], tenant(M, r["tenant_id"])["name"], r["unit_id"], money(r["amount"]), r["days_overdue"], r["months_of_rent"], r["bucket"])
           for r in arr if r["days_overdue"] > 30], [2.6, 4.4, 2.8, 2.4, 1.4, 1.8, 1.6]),
         ("h1", "Appendix C - Definitions"),
         ("table", ["Measure", "Definition"], [("Vacant", "Lettable unit, no active or committed tenancy, not under tender"),
                                               ("Occupancy", "Tenanted / (total - not lettable)"),
                                               ("Arrears", "Unpaid invoices past due date, incl. GST, excl. interest"),
                                               ("SLA met", "i-EMS completion within severity SLA; misrouted tickets excluded")], [4, 13])]
    return b, tot["v"]


def faq(variant):
    qs = [
        ("How is rent paid?", "Rent is payable monthly in advance by the 1st of each month. We encourage payment by GIRO."),
        ("What happens if I pay late?", "Late-payment interest of 8% per annum is charged on overdue amounts. You will receive reminders, and continued "
                                         "non-payment may lead to legal action and termination."),
        ("Can I change my trade?", "You may apply for a change of trade. Approval depends on the trade mix in the area, your payment and compliance "
                                   "record, and licensing requirements. A processing fee of S$300 applies."),
        ("Can I sublet part of my shop?", "No. Subletting or sharing any part of the premises without HEB's written approval is not allowed."),
        ("When should I apply to renew my tenancy?", "Please apply at least 6 months before your tenancy expires. We will send you an invitation about 8 "
                                                      "months before expiry if you are eligible."),
        ("How is my renewal rent determined?", "Renewal rent is based on the prevailing market rent assessed by an independent valuer."),
        ("How much is the security deposit?", "The security deposit is equivalent to two (2) months' rent and is refundable at the end of the tenancy, "
                                              "less any amounts owed."),
        ("Do I need approval for renovation?", "Yes, most works need approval. Please refer to the Guidelines on A&A Works for Commercial Tenants."),
        ("How far can I display goods outside my shop?", "Up to 0.6 m beyond your shopfront, keeping a 1.2 m clear walkway."),
        ("Who do I contact about building defects?", "Report defects through the CityFix App or our hotline. We will arrange for repairs."),
        ("Can I transfer my tenancy to someone else?", "You may apply for assignment after the first 12 months of your tenancy."),
        ("What are the permitted operating hours?", "Noisy activities are not allowed between 10.30 pm and 7.00 am." if variant == 0 else
                                                     "Noisy activities are not allowed between 10.30 pm and 7.00 am. Eating houses may operate 24 hours with approval."),
        ("How do I get my deposit back?", "Your deposit is refunded within 60 days after you return the premises in good condition."),
        ("What insurance do I need?", "Public liability insurance with a minimum cover of S$1,000,000."),
        ("How do I contact PLG?", "Hotline 1800-555-0123 (Mon-Fri, 8.30 am - 5.30 pm) or email plg_enquiry@heb.example.org." if variant == 0 else
                                  "Hotline 1800-555-0132 (Mon-Fri, 8.30 am - 5.30 pm) or email plg_enquiry@heb.example.org."),
    ]
    b = [("title", "FREQUENTLY ASKED QUESTIONS FOR COMMERCIAL TENANTS"), ("note", "2025 Edition. For general guidance only; the tenancy agreement prevails.")]
    for i, (q, a) in enumerate(qs, 1):
        b += [("h3", f"Q{i}. {q}"), ("p", a)]
    return b


def incident_report(M):
    t, ta, u = scripted(M, "Sin Hock Eating House")
    fk = M["key"]["fire"]
    return [
        ("title", "INCIDENT REPORT: FIRE AT EATING HOUSE"),
        ("kv", [("Incident ref", "PLG-INC-2026-011"), ("Date / time", "18 May 2026, approx. 06:40"), ("Premises", f"{t['name']}, {addr(u)} ({u['unit_id']})"),
                ("Tenancy", f"{ta['tenancy_id']} (rent {money(ta['monthly_rent'])}/month)"), ("Reported by", f"{sname('S04')}, Estate Manager (East)"),
                ("CRM case / i-EMS ticket", f"{fk['feedback']} / {fk['ticket']}"), ("CDA incident no.", "CDA/FI/2026/05/0447 (fictional)")]),
        ("h1", "1. Summary"),
        ("p", "A fire broke out in the kitchen exhaust hood of the drinks stall at the eating house at about 06:40. The Civil Defence Authority (CDA) "
              "put it out by 07:05. No injuries. Smoke damaged the ceiling boards and exhaust ducting. The eating house was closed by order of "
              "the Estate Manager until a structural check and CDA clearance were completed."),
        ("h1", "2. Timeline"),
        ("table", ["Time", "Event"], [("06:40", "Fire noticed by stall assistant; fire extinguisher used, unsuccessfully"), ("06:44", "CDA alerted by tenant"),
                                      ("06:52", "CDA on scene; residents of levels 2-4 evacuated as a precaution"), ("07:05", "Fire extinguished"),
                                      ("07:30", f"{sname('S04')} on site; premises cordoned"), ("09:15", f"i-EMS ticket {fk['ticket']} raised (Critical) by {sname('S10')}"),
                                      ("19 May 10:00", "Kemas Building Works structural inspection: no structural damage; ceiling and duct replacement needed"),
                                      ("05 Jun", "Repairs completed; CDA clearance obtained"), ("09 Jun", "Eating house reopened")], [3.5, 13.5]),
        ("h1", "3. Cause"),
        ("p", "CDA's preliminary assessment: grease build-up in the exhaust duct of the drinks stall caught fire. The duct cleaning record showed the last "
              "cleaning was in November 2025, more than 6 months earlier. Quarterly cleaning is required (Management Meeting 4/2026, AOB)."),
        ("h1", "4. Impact"),
        ("bullets", ["Closure: 22 days (18 May - 8 June 2026).", "Estimated repair cost: S$18,400 (ceiling, ducting, rewiring), to be recovered from tenant as tenant-caused.",
                     "12 stall-holders affected; 3 resident feedback cases on smoke smell."]),
        ("h1", "5. Recommendations"),
        ("numbered", ["No rent rebate: unlike precedent PC-2025-019 (where the fire was caused by an HEB electrical fault), this fire was caused by the tenant's "
                      "failure to maintain the duct.",
                      "Issue a warning and require quarterly duct-cleaning certificates for the remaining tenancy.",
                      "Recover repair costs from the tenant; the tenant may claim on their own insurance.",
                      "Estate Managers to audit duct-cleaning records of all eating houses by 31 July 2026."]),
        ("sig", ["Prepared by:", sname("S04"), "Estate Manager (East)", "Reviewed by:", sname("S03")]),
    ]


def scanned_ta_pages(M):
    t, ta, u = scripted(M, "Heng Ann Confectionery")
    return [
        ["# HOUSING & ESTATES BOARD", "# TENANCY AGREEMENT (COMMERCIAL)", "", f"Agreement No.: {ta['tenancy_id']}", f"Date: 20 June 2024", "",
         "BETWEEN", "  HOUSING & ESTATES BOARD ('the Landlord')", "AND", f"  {t['name'].upper()}", f"  (Registration No. {t['brn']}) ('the Tenant')", "",
         "1. PREMISES", f"  {addr(u)}", f"  Unit ID: {u['unit_id']}   Floor area: approx. {u['floor_area_sqm']} sqm", "",
         "2. TERM", f"  Three (3) years from {fdl(ta['start_date'])} to {fdl(ta['end_date'])}.", "",
         "3. RENT", "  The Tenant shall pay monthly rent of S$4,580.00", "  (Singapura Dollars Four Thousand Five Hundred and Eighty only)",
         "  exclusive of GST, payable in advance on the 1st day of each month.", "",
         "4. SECURITY DEPOSIT", "  S$13,740.00 being three (3) months' rent.", "", "5. APPROVED TRADE", "  Bakery & Confectionery (baking on premises permitted)."],
        ["6. TENANT'S COVENANTS", "  6.1 To pay rent and other charges on the due dates.", "  6.2 Not to use the premises other than for the approved trade.",
         "  6.3 Not to assign, sublet or part with possession of the", "      premises or any part without prior written consent.",
         "  6.4 Not to carry out alterations without written approval.", "  6.5 To keep the premises clean and in good repair.",
         "  6.6 To maintain public liability insurance of not less", "      than S$1,000,000.", "  6.7 To comply with all HEB policies as amended from time to time.", "",
         "7. LANDLORD'S RIGHTS", "  7.1 Late-payment interest at 8% per annum.", "  7.2 Re-entry if rent unpaid for 21 days after demand,",
         "      or upon breach of covenants.", "  7.3 Set-off of the security deposit against sums due.", "",
         "8. REINSTATEMENT", "  On expiry or termination the Tenant shall reinstate the", "  premises to original condition unless otherwise agreed."],
        ["IN WITNESS WHEREOF the parties have executed this Agreement.", "", "", "Signed for and on behalf of", "HOUSING & ESTATES BOARD", "",
         "  ______________________", f"  {sname('S03')}", "  Senior Manager, Tenancy Management", "", "",
         "Signed by the Tenant", "", "  ______________________", f"  {t['contact_person']}", "  Director", "", "",
         "Witness: ______________________", "", "", "[Stamp duty paid - Cert. No. SD-2024-0619-0081]"],
    ]


def tender_notice(M):
    rng = random.Random(M["seed"] + 11)
    units = [u for u in M["units"] if u["status"] == "Under Tender"]
    rows = []
    for u in units:
        trade = rng.choice(["Minimart", "GP Clinic", "Bakery & Confectionery", "Tuition Centre", "Any trade (subject to trade mix)"])
        base = int(u["floor_area_sqm"] * {"BV": 52, "CD": 48, "KR": 45, "RH": 40, "ST": 38, "PI": 44}[u["town"]] * 0.9 / 10) * 10
        if u["unit_type"] == "Kiosk":
            base *= 2
        rows.append((u["unit_id"], f"Blk {u['blk']} {u['street']} {u['unit_no']}", u["unit_type"], u["floor_area_sqm"], trade, money(base, False)))
    return [("title", "TENDER NOTICE: COMMERCIAL UNITS FOR RENT"),
            ("kv", [("Tender ref", "PLG/T/2026/09"), ("Published", "7 September 2026"), ("Closing", "5 October 2026, 4.00 pm"),
                    ("Tender briefing", "15 September 2026, 10.00 am, HEB Hub Auditorium")]),
            ("p", "The Housing & Estates Board invites tenders for the rental of the following commercial units for a term of 3 years. Tenderers "
                  "must bid at or above the minimum monthly rent shown (before GST)."),
            ("table", ["Unit ID", "Address", "Type", "Area (sqm)", "Approved trade", "Min. bid / month"], rows, [3, 5.2, 2.2, 1.8, 3, 2.3]),
            ("h2", "Conditions"),
            ("bullets", ["Successful tenderers must pay a security deposit of 3 months' rent and sign the tenancy agreement within 14 days of award.",
                         "Tenders are evaluated on price (70%) and trade proposal (30%).", "HEB is not bound to accept the highest or any tender.",
                         "Tenderers with arrears to HEB are not eligible."])]


def lod(M):
    t, ta, u = scripted(M, "Golden Leaf Minimart Pte Ltd")
    kk = M["key"]["Golden Leaf Minimart Pte Ltd"]
    d = kk["lod_date"]
    asof = d - dt.timedelta(days=1)
    invs = [i for i in M["invoices"] if i["tenancy_id"] == ta["tenancy_id"] and i["due_date"] <= asof and (i.get("paid_date") is None or i["paid_date"] > asof)]
    rows = []
    tot = 0
    interest = 0
    for i in invs:
        days = (asof - i["due_date"]).days
        it = late_interest(i["total_amount"], days)
        interest += it
        tot += i["total_amount"]
        rows.append((i["invoice_id"], i["period"], fd(i["due_date"]), money(i["total_amount"]), days, money(it)))
    rows.append(("", "", "Total", money(tot), "", money(interest)))
    return [("p", f"Our ref: {kk['lod']} / LEG/LOD/2026/{ta['tenancy_id'][-5:]}"), ("p", fdl(d)), ("p", "BY EMAIL AND REGISTERED POST"),
            ("p", f"{t['name']}\nAttn: {t['contact_person']}, Director\n{addr(u)}\nEmail: {t['email']}"),
            ("p", "Dear Sir/Madam,"),
            ("h3", f"LETTER OF DEMAND: ARREARS OF RENT FOR {addr(u).upper()} (TENANCY {ta['tenancy_id']})"),
            ("p", "1. We act for the Housing & Estates Board ('HEB'), your landlord under the above tenancy agreement."),
            ("p", f"2. Despite reminders dated {fd(D(2026, 6, 16))} and {fd(D(2026, 7, 2))}, and a phone call with your director on {fd(D(2026, 7, 9))}, "
                  f"the following sums remain outstanding as at {fdl(asof)}:"),
            ("table", ["Invoice", "Period", "Due date", "Amount (incl. GST)", "Days overdue", "Interest @ 8% p.a."], rows, [3.2, 2, 2.6, 3.4, 2.4, 3.4]),
            ("p", f"3. HEB hereby demands that you pay the total sum of {money(tot + interest)} within fourteen (14) days of the date of this letter, "
                  f"that is, by {fdl(d + dt.timedelta(days=14))}. Interest continues to accrue until full payment."),
            ("p", "4. If you fail to do so, HEB may, without further notice, exercise its rights under clause 7 of the tenancy agreement and PLG-POL-003 "
                  "Rental Arrears Management Policy. These include re-entering the premises, terminating the tenancy, setting off the security deposit "
                  "and starting legal proceedings to recover all sums due, with costs."),
            ("p", f"5. If you wish to propose an instalment plan, please contact {sname('S07')}, Manager, Finance & Arrears, at {M['idx']['staff']['S07']['phone']} "
                  "before the deadline above."),
            ("sig", ["Yours faithfully,", "", sname("S09"), "Legal Counsel", "for Housing & Estates Board", "", f"cc: {sname('S07')}; {sname('S03')}"])]


def inspection_report(M):
    rows = [i for i in M["inspections"] if i["unit_id"].startswith("U-RH") and D(2026, 6, 1) <= i["inspection_date"] <= D(2026, 6, 30)]
    ls = M["key"]["Lucky Star Hair Studio"]
    t, ta, u = scripted(M, "Lucky Star Hair Studio")
    oc = Counter(i["outcome"] for i in rows)
    return [("title", "INSPECTION REPORT: RIMBA HEIGHTS COMMERCIAL UNITS, JUNE 2026"),
            ("kv", [("Prepared by", f"{sname('S06')}, Property Officer"), ("Reviewed by", f"{sname('S12')}, Estate Manager (West)"), ("Date", "3 July 2026"),
                    ("Units inspected", len(rows)), ("Outcomes", f"Compliant {oc['Compliant']}, Minor {oc['Minor Breach']}, Major {oc['Major Breach']}")]),
            ("h1", "1. Summary"),
            ("p", "Inspections followed PLG-SOP-011 v1.1 and were recorded on the tablet app (Rimba Heights pilot). One significant case was found: "
                  f"unauthorised partial subletting at {t['name']} ({u['unit_id']}), inspection {ls['inspection']}."),
            ("h1", "2. Significant Case"),
            ("kv", [("Tenant", f"{t['name']} ({t['tenant_id']})"), ("Unit", addr(u)), ("Tenancy", ta["tenancy_id"]), ("Finding", "UNAUTH_SUBLET (Major Breach)"),
                    ("Details", "The rear third of the unit is partitioned and run as a nail salon, 'Glam Nails by Vivian', with its own cash register and "
                                "signage facing the side corridor. The tenant's director said it is a 'friend's business sharing rent'. No approval on record."),
                    ("Recommended action", "Composition fee S$500 and regularise within 14 days (first occurrence, POL-001 cl. 8; see precedent PC-2024-021)."),
                    ("Follow-up due", fd(D(2026, 6, 30)))]),
            ("h1", "3. All Inspections"),
            ("table", ["Inspection", "Date", "Unit", "Type", "Finding", "Outcome"], [(i["inspection_id"], fd(i["inspection_date"]), i["unit_id"], i["inspection_type"],
                                                                                  i["finding_code"], i["outcome"]) for i in rows], [2.8, 2.2, 3.2, 3, 3.4, 2.4])]


def register_pdfs(M):
    def r(id, fname, title, author, date, purpose, q, blocks_fn, flags="", entities=(), ref=None, letterhead=True, sub="pdfs"):
        path = f"{sub}/{fname}"

        def fn(root):
            pdf_render(f"{root}/{path}", blocks_fn(), title=title, author=sname(author), ref=ref, letterhead=letterhead)
        register(id, path, "pdf", title, sname(author), date, purpose, q, fn, flags=flags, entities=entities)

    gl_t, gl_ta, gl_u = scripted(M, "Golden Leaf Minimart Pte Ltd")
    r("PDF-001", "PLG_Circular_03-2026_Revised_Arrears_Policy.pdf", "PLG Circular 03/2026 - Revised Rental Arrears Management Policy", "S01", D(2026, 3, 16),
      "Announces POL-003 v2.0 changes", "What changed in the arrears policy in April 2026?", circular_03, flags="NEAR-DUPLICATE of OTH-008 (txt copy)",
      entities=("PLG-POL-003",), ref="Circular 03/2026")
    r("PDF-002", "PLG_Circular_07-2026_NC_Display_Area_Pilot.pdf", "PLG Circular 07/2026 - Display Area at NCs (Pilot)", "S01", D(2026, 7, 20),
      "Raises NC display limit to 1.0 m from 1 Aug 2026", "Can an NC shop display goods 0.9 m beyond the shopfront?", circular_07,
      flags="CONFLICT C5 (supersedes DOC-003 cl. 7.3 for NCs)", entities=("PLG-POL-001",), ref="Circular 07/2026")
    pc_blocks, pc_ids = precedents(M)
    r("PDF-003", "PLG_Precedent_Case_Compendium_2023-2026.pdf", "PLG Precedent Case Compendium 2023-2026", "S03", D(2026, 8, 28),
      "Long reference of 24 precedent decisions", "Are there precedents for changing a provision shop to bubble tea?; What did we decide on partial subletting to a nail salon?",
      lambda: pc_blocks, entities=tuple(pc_ids[:8]), ref="PLG-PC-2026")
    r("PDF-004", "Guidelines_AA_Works_Commercial_Tenants_2025.pdf", "Guidelines on A&A Works for Commercial Tenants (2025)", "S02", D(2025, 2, 3),
      "Long guideline: A&A categories, documents, conditions, fees", "Does a tenant need PE endorsement to hack a wall?; What is the fee for Category B works?", aa_guidelines,
      entities=("ALTERATION",))
    r("PDF-005", "Internal_Audit_Report_IA-2026-07_Tenancy_Management.pdf", "Internal Audit Report IA/2026/07 - Tenancy Management", "S09", D(2026, 7, 28),
      "Audit findings incl. rent data mismatch, SOP misalignment, FAQ error", "What did internal audit find about the arrears SOP?; Which tenancy has a rent mismatch?",
      lambda: audit_report(M), flags="References C1, C2, C6", entities=(scripted(M, "Heng Ann Confectionery")[1]["tenancy_id"], "PLG-SOP-014"), ref="IA/2026/07")
    aug_blocks, aug_v = ops_report(M, D(2026, 8, 31))
    jul_blocks, _ = ops_report(M, D(2026, 7, 31))
    r("PDF-006", "PLG_Monthly_Ops_Report_2026-08.pdf", "PLG Monthly Operations Report - August 2026", "S08", D(2026, 9, 9),
      f"Monthly KPIs as at 31 Aug 2026 (vacant = {aug_v})", "How many vacant units were there at end-August 2026?; What is total arrears at end-August?",
      lambda: aug_blocks, flags="CONFLICT C4 (vs DECK-001)", ref="OPS-2026-08")
    r("PDF-007", "PLG_Monthly_Ops_Report_2026-07.pdf", "PLG Monthly Operations Report - July 2026", "S08", D(2026, 8, 10),
      "Monthly KPIs as at 31 Jul 2026", "How did arrears change between July and August?", lambda: jul_blocks, ref="OPS-2026-07")
    r("PDF-008", "Tenant_FAQ_Commercial_2025.pdf", "FAQ for Commercial Tenants (2025 Edition)", "S03", D(2025, 2, 14),
      "Tenant-facing FAQ (deposit stated as 2 months - wrong)", "What does the FAQ say about the security deposit?", lambda: faq(0),
      flags="CONFLICT C2 (vs DOC-004); NEAR-DUPLICATE of PDF-009")
    r("PDF-009", "Tenant_FAQ_Commercial_2025_final(1).pdf", "FAQ for Commercial Tenants (2025 Edition) - copy", "S11", D(2025, 3, 2),
      "Near-duplicate FAQ with different hotline number and operating-hours line", "Which FAQ version has the correct hotline?", lambda: faq(1),
      flags="NEAR-DUPLICATE of PDF-008; CONFLICT C2")
    r("PDF-010", "Incident_Report_PLG-INC-2026-011_Fire_Sin_Hock.pdf", "Incident Report PLG-INC-2026-011 - Fire at Eating House", "S04", D(2026, 6, 12),
      "Fire incident, cause, closure, no rebate recommendation vs precedent PC-2025-019", "Should Sin Hock get a rent rebate for the fire closure?",
      lambda: incident_report(M), entities=(scripted(M, "Sin Hock Eating House")[1]["tenancy_id"], M["key"]["fire"]["ticket"]), ref="PLG-INC-2026-011")
    ha_t, ha_ta, ha_u = scripted(M, "Heng Ann Confectionery")

    def scan_fn(root):
        pdf_scanned(f"{root}/pdfs/Scan_TA_{ha_ta['tenancy_id']}_HengAnn.pdf", scanned_ta_pages(M), title="scan0047", seed=M["seed"] + 47, stamps={2: "HEB PLG"})
    register("PDF-011", f"pdfs/Scan_TA_{ha_ta['tenancy_id']}_HengAnn.pdf", "pdf", f"Tenancy Agreement {ha_ta['tenancy_id']} (scanned)", "Scanner", D(2024, 6, 20),
             "Image-only scanned tenancy agreement; rent S$4,580 differs from DB S$4,850", f"What is the contractual rent for {ha_ta['tenancy_id']}?", scan_fn,
             flags="SCANNED (image-only); CONFLICT C6", entities=(ha_ta["tenancy_id"], ha_u["unit_id"], ha_t["tenant_id"]))
    r("PDF-012", "Tender_Notice_PLG-T-2026-09.pdf", "Tender Notice PLG/T/2026/09", "S05", D(2026, 9, 7), "Units currently under tender (5)",
      "Which units are under tender and when does the tender close?", lambda: tender_notice(M), entities=tuple(u["unit_id"] for u in M["units"] if u["status"] == "Under Tender"))
    r("PDF-013", f"LOD_{gl_ta['tenancy_id']}_Golden_Leaf_Minimart.pdf", f"Letter of Demand - {gl_t['name']}", "S09", M["key"]["Golden Leaf Minimart Pte Ltd"]["lod_date"],
      "LOD issued at ~60 days under POL-003 v2.0", "How much did we demand from Golden Leaf Minimart and by when?", lambda: lod(M),
      entities=(gl_ta["tenancy_id"], gl_t["tenant_id"], M["key"]["Golden Leaf Minimart Pte Ltd"]["lod"]), ref=M["key"]["Golden Leaf Minimart Pte Ltd"]["lod"])
    r("PDF-014", "Inspection_Report_Rimba_Heights_2026-06.pdf", "Inspection Report - Rimba Heights, June 2026", "S06", D(2026, 7, 3),
      "Monthly inspection summary incl. unauthorised subletting at Lucky Star", "What was found at Lucky Star Hair Studio?", lambda: inspection_report(M),
      entities=(M["key"]["Lucky Star Hair Studio"]["inspection"],))
