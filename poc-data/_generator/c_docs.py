"""Word documents: policies, SOPs, approved templates, minutes."""
from collections import Counter

from common import D, arrears_asof, fdl, money, register, sname
from master import CHECKLISTS, DEFECT_TAXONOMY, SEVERITY_SLA_DAYS, TRADES
from render import docx_render


def ctrl(doc_id, version, effective, owner, approver, review, status="In force", supersedes="-"):
    return [("Document ID", doc_id), ("Version", version), ("Effective date", fdl(effective)), ("Owner", owner), ("Approved by", approver),
            ("Next review", fdl(review)), ("Status", status), ("Supersedes", supersedes), ("Classification", "Restricted (fictional POC data)")]


def arrears_policy(v2):
    lod = 60 if v2 else 45
    term = "3 months'" if v2 else "2 months'"
    inst = 12 if v2 else 6
    cap = "S$30,000" if v2 else "S$20,000"
    b = [
        ("h1", "1. Purpose"),
        ("p", "This policy sets out how the Properties & Land Group (PLG) manages rental arrears for HEB commercial properties. It aims to recover "
              "rent promptly and keep treatment of tenants consistent, while giving viable businesses facing temporary difficulty a fair chance to recover."),
        ("h1", "2. Scope"),
        ("p", "This policy applies to all commercial tenancies managed by PLG, including shops, eating houses, kiosks, shops with living quarters and "
              "offices in HEB estates and neighbourhood centres (NCs). It does not apply to residential tenancies or to car park licences."),
        ("h1", "3. Definitions"),
        ("table", ["Term", "Definition"], [
            ("Rent", "Monthly rent payable in advance under the tenancy agreement, exclusive of GST."),
            ("Due date", "The 1st day of each calendar month."),
            ("Arrears", "Any rent, GST or late-payment interest that remains unpaid after the due date."),
            ("Days overdue", "Calendar days between the due date of the oldest unpaid invoice and the date of assessment."),
            ("Letter of Demand (LOD)", "A formal written demand issued by HEB Legal under template TPL-LOD-01."),
            ("Months of arrears", "Total arrears divided by one month's rent inclusive of GST."),
        ], [4, 12]),
        ("h1", "4. Policy Statements"),
        ("h2", "4.1 Payment of rent"),
        ("p", "Rent is payable monthly in advance on or before the 1st day of each month. Tenants are strongly encouraged to pay by GIRO. Where a GIRO "
              "deduction fails, the tenant must pay within 7 days of being notified."),
        ("h2", "4.2 Late-payment interest"),
        ("p", "Late-payment interest of 8% per annum, computed daily, is charged on overdue amounts from the day after the due date until full payment."),
        ("h2", "4.3 Reminders"),
        ("bullets", ["First reminder (TPL-REM-01) at 14 days overdue.", "Second reminder (TPL-REM-01, second-notice variant) and a phone call at 30 days overdue."]),
    ]
    if v2:
        b += [("h2", "4.4 Hardship assessment"),
              ("p", "Between 31 and 45 days overdue, the Finance & Arrears officer must call the tenant and record a hardship assessment "
                    "(form FA-07) covering the cause of arrears, business viability and proposed repayment. This step must be completed before a "
                    "Letter of Demand is issued.")]
    b += [
        ("h2", f"4.{5 if v2 else 4} Letter of Demand"),
        ("p", f"A Letter of Demand shall be issued by HEB Legal when any amount is {lod} days overdue and no approved instalment plan is in force. "
              "The LOD gives the tenant 14 days to pay the outstanding sum in full."),
        ("h2", f"4.{6 if v2 else 5} Termination"),
        ("p", f"Where arrears exceed {term} rent (inclusive of GST), the case shall be put to the Director, PLG with a recommendation on whether to "
              "terminate the tenancy, re-enter the premises and set off the security deposit against the arrears. A tenant with arrears above this "
              "threshold is not eligible for renewal, change of trade or assignment until the arrears are cleared."),
        ("h2", f"4.{7 if v2 else 6} Instalment plans"),
        ("p", f"Instalment plans of up to {inst} months may be approved. The Manager, Finance & Arrears may approve plans for total arrears up to {cap}; "
              f"plans above {cap} require the Director's approval. Missing two consecutive instalments cancels the plan, and the full amount becomes due."),
        ("h2", f"4.{8 if v2 else 7} Security deposit"),
        ("p", "The security deposit shall not be used to offset arrears during the tenancy, except on termination or expiry."),
        ("h1", "5. Roles and Responsibilities"),
        ("table", ["Role", "Responsibility"], [
            ("Finance & Arrears (F&A)", "Monitor the ageing report, issue reminders, conduct hardship calls, recommend instalment plans."),
            ("Leasing Officer", "Check arrears status before processing renewal, assignment or change-of-trade applications."),
            ("HEB Legal", "Issue Letters of Demand; advise on termination and recovery proceedings."),
            ("Director, PLG", "Approve termination and instalment plans above the delegated limit."),
        ], [5, 11]),
        ("h1", "6. Related Documents"),
        ("bullets", ["PLG-SOP-014 Rental Arrears Recovery SOP", "PLG-POL-002 Tenancy Renewal & Security Deposit Policy", "Templates TPL-REM-01, TPL-LOD-01"]
         + (["PLG Circular 03/2026 - Revised Rental Arrears Management Policy"] if v2 else [])),
    ]
    return b


def trade_mix_policy(M):
    trade_rows = sorted({(v[2], t) for t, v in TRADES.items()})
    groups = {}
    for g, t in trade_rows:
        groups.setdefault(g, []).append(t)
    b = [
        ("h1", "1. Purpose"),
        ("p", "This policy guides how PLG plans the trade mix in HEB commercial premises and controls how those premises are used. HEB commercial "
              "premises exist primarily to meet residents' daily needs within walking distance and to keep neighbourhood centres vibrant. "
              "Trade mix decisions therefore balance resident needs, commercial viability and fair competition between tenants."),
        ("h1", "2. Objectives"),
        ("numbered", ["Ensure every NC and void-deck cluster offers essential daily needs (food, groceries, healthcare).",
                      "Avoid over-concentration of any single trade that would undermine tenant viability.",
                      "Support new trades that respond to changing resident demographics, such as eldercare, childcare and enrichment.",
                      "Keep common areas safe, clean and accessible."]),
        ("h1", "3. Definitions"),
        ("table", ["Term", "Definition"], [
            ("Neighbourhood Centre (NC)", "A cluster of commercial premises serving a neighbourhood of about 4,000 to 6,000 households, designated in PLG's NC register."),
            ("Void-deck shop", "A commercial unit at the ground floor of a residential block outside a designated NC."),
            ("Trade", "The approved business activity specified in the tenancy agreement (Annex A)."),
            ("Trade group", "A grouping of related trades used for trade-mix assessment (Annex A)."),
            ("Essential trade", "Minimart / provision shop, coffeeshop, GP clinic, pharmacy."),
            ("Shopfront line", "The line of the shop's front wall or roller shutter as shown in the approved layout plan."),
        ], [4.5, 11.5]),
        ("h1", "4. Essential Trades"),
        ("p", "Each NC shall have at least one minimart or provision shop, one coffeeshop and one GP clinic. When an essential trade unit falls vacant, "
              "it shall be re-tendered for the same trade unless the Deputy Director, Leasing Policy & Planning approves otherwise."),
        ("h1", "5. Trade Mix Rules"),
        ("h2", "5.1 Concentration limit"),
        ("p", "No more than two (2) units in the same NC may operate the same trade. For NCs with more than 40 units the limit for minimarts is three (3). "
              "Food & beverage trades other than coffeeshops shall not exceed 30% of units in an NC."),
        ("h2", "5.2 Void-deck clusters"),
        ("p", "Void-deck clusters of five or more units should include at least one essential trade."),
        ("h2", "5.3 Prohibited trades"),
        ("bullets", ["Massage establishments (other than licensed healthcare)", "Pawnbroking", "Gaming arcades and jackpot operations",
                     "Sale of e-vaporisers or other prohibited items", "Any trade requiring a licence the tenant is unable to obtain"]),
        ("h1", "6. Change or Addition of Trade"),
        ("h2", "6.1 Eligibility"),
        ("bullets", ["Tenancy has at least 12 months remaining.", "No arrears exceeding one month's rent.",
                     "No major breach in the past 12 months.", "The proposed trade complies with clause 5 and any licensing requirements."]),
        ("h2", "6.2 Evaluation criteria"),
        ("p", "Officers shall assess (a) impact on trade mix, using the Trade Mix Assessment Worksheet in Annex B; (b) resident feedback and demand indicators; "
              "(c) the tenant's compliance and payment record; and (d) relevant precedents in the PLG Precedent Case Compendium. Where the "
              "proposed trade would exceed the concentration limit in clause 5.1, the application should normally be rejected unless there is "
              "clear evidence of unmet demand. Examples include an NC serving more than 6,000 households, or an existing outlet that has given "
              "notice to terminate."),
        ("h2", "6.3 Fees and rent revision"),
        ("p", "A non-refundable processing fee of S$300 (before GST) applies. If approved, rent is revised to the market rent for the new trade, as "
              "assessed by PLG's appointed valuer, from the date the new trade starts."),
        ("h2", "6.4 Approval authority"),
        ("table", ["Case", "Approving officer"], [
            ("Within same trade group, within concentration limit", "Senior Manager, Tenancy Management"),
            ("Different trade group, within concentration limit", "Deputy Director, Leasing Policy & Planning"),
            ("Exceeds concentration limit / essential trade unit", "Director, PLG"),
        ], [10, 6]),
        ("h1", "7. Usage Rules"),
        ("h2", "7.1 Approved trade only"),
        ("p", "Tenants shall use the premises only for the approved trade. Selling incidental items up to 20% of display area is permitted if related to the "
              "approved trade."),
        ("h2", "7.2 Subletting and sharing"),
        ("p", "Subletting, licensing or sharing any part of the premises with another business is prohibited without PLG's prior written approval. "
              "Partial subletting (e.g. a partitioned corner operated by a third party) is treated as unauthorised subletting."),
        ("h2", "7.3 Display area beyond shopfront"),
        ("p", "Tenants may display goods up to 0.6 m beyond the shopfront line, provided a clear walkway of at least 1.2 m is maintained at all times "
              "and goods are removed outside operating hours. Tables and chairs may not be placed outside the shopfront line except at eating houses "
              "with an approved outdoor refreshment area (ORA)."),
        ("h2", "7.4 Operating hours"),
        ("p", "Premises below residential units shall not operate noisy activities between 10.30 pm and 7.00 am."),
        ("h1", "8. Enforcement"),
        ("table", ["Breach", "1st occurrence", "2nd occurrence (within 12 months)", "3rd occurrence"], [
            ("Display beyond permitted area", "Warning letter", "Composition fee S$200", "Composition fee S$500 and review of tenancy"),
            ("Unauthorised trade", "Warning; cease within 14 days", "Composition fee S$500", "Termination considered"),
            ("Unauthorised subletting", "Composition fee S$500; regularise within 14 days", "Termination considered", "-"),
            ("Unapproved A&A works", "Reinstate within 30 days", "Composition fee S$500 + reinstatement", "Termination considered"),
            ("Noise / hygiene", "Warning letter", "Composition fee S$200", "Composition fee S$500"),
        ], [4.2, 3.6, 4.4, 3.8]),
        ("h1", "9. Appeals"),
        ("p", "Tenants may appeal in writing within 14 days of a decision. Appeals are reviewed by an officer at least one grade above the original "
              "approving officer, and that officer was not involved in the original decision."),
        ("pagebreak",),
        ("h1", "Annex A - Trade Groups"),
        ("table", ["Trade group", "Trades"], [(g, ", ".join(ts)) for g, ts in groups.items()], [5, 11]),
        ("h1", "Annex B - Trade Mix Assessment Worksheet"),
        ("table", ["Step", "Check", "Source"], [
            ("1", "Count active units of the proposed trade in the NC / cluster", "PLG Records - tenancies; Trade_Mix_Analysis_by_NC.xlsx"),
            ("2", "Compare against the clause 5.1 limit", "This policy"),
            ("3", "Check F&B share if proposed trade is F&B", "PLG Records"),
            ("4", "Review resident feedback in past 12 months", "CRM feedback export"),
            ("5", "Check tenant arrears and breach history", "Arrears ageing report; inspections"),
            ("6", "Search precedents for similar trade / NC", "PLG Precedent Case Compendium"),
            ("7", "Recommend and route to approving officer per clause 6.4", "-"),
        ], [1.2, 9, 5.8]),
    ]
    return b


def renewal_policy():
    return [
        ("h1", "1. Purpose"),
        ("p", "This policy sets out the principles for renewing commercial tenancies and for collecting, topping up and refunding security deposits."),
        ("h1", "2. Scope"),
        ("p", "All PLG commercial tenancies with a fixed term of three (3) years."),
        ("h1", "3. Eligibility for Renewal"),
        ("bullets", ["No arrears exceeding one month's rent at the time of application and at the time of offer.",
                     "No major breach (unauthorised trade, subletting, fire safety or structural) in the preceding 12 months.",
                     "The trade continues to be consistent with PLG-POL-001 Trade Mix & Usage Policy.",
                     "The unit is not earmarked for redevelopment, upgrading or a change of use."]),
        ("h1", "4. Application"),
        ("h2", "4.1 Renewal invitation"),
        ("p", "PLG will send a renewal invitation to eligible tenants about 8 months before their tenancy expires."),
        ("h2", "4.2 Application lead time"),
        ("p", "Tenants must submit a complete renewal application at least six (6) months before the tenancy expires. This allows time for "
              "market rent valuation, an offer and acceptance, and, if renewal is not pursued, re-tendering of the unit without a vacancy gap."),
        ("h2", "4.3 Required documents"),
        ("p", "As listed in the PLG submission checklist for RENEWAL: renewal application form, current business profile, valid public liability "
              "insurance certificate covering the new term, and a GIRO form if the bank account has changed."),
        ("h2", "4.4 Late applications"),
        ("p", "Applications received less than six months before expiry may be considered case by case. The Senior Manager, Tenancy Management "
              "may accept a late application received three to six months before expiry if the tenant has a good payment and compliance record. Late "
              "applications received less than three months before expiry are normally rejected, and the unit is put to tender."),
        ("h1", "5. Renewal Rent"),
        ("p", "Renewal rent is set at the prevailing market rent, as assessed by PLG's appointed valuer (currently Lumina Valuers & Surveyors). Where "
              "the new rent exceeds the current rent by more than 20%, the increase is phased equally over the first two years of the new term."),
        ("h1", "6. Security Deposit"),
        ("h2", "6.1 Amount"),
        ("p", "The security deposit is equal to three (3) months' rent (exclusive of GST). It is payable before the tenancy starts, or before a renewed "
              "tenancy starts."),
        ("h2", "6.2 Top-up"),
        ("p", "When rent is revised on renewal, change of trade or assignment, the tenant shall top up the deposit to three months of the revised rent."),
        ("h2", "6.3 Refund"),
        ("p", "The deposit is refunded without interest within 60 days after the premises are handed back in the required condition, less any "
              "arrears, reinstatement costs and other sums due."),
        ("h2", "6.4 Bankers' guarantee"),
        ("p", "A bankers' guarantee from a bank acceptable to HEB may replace a cash deposit for deposits above S$15,000."),
        ("h1", "7. Term"),
        ("p", "Renewed tenancies are for three (3) years. Shorter terms may be offered where the unit is earmarked for upgrading."),
    ]


def inspection_sop(v11):
    fu_major = 7 if v11 else 14
    steps = [
        ("1", "Plan", "Each unit is inspected at least once a year (routine). The Estate Manager approves the monthly inspection roster by the 25th of the preceding month."),
        ("2", "Prepare", "Download the unit list, approved trades and open breaches from PLG Records. Check open feedback cases for the block."),
        ("3", "Inspect", "Complete checklist IC-01 for each unit." + (" Take at least three (3) photos for each breach (wide shot, close-up, shopfront line)." if v11 else " Take photos of any breach.")),
        ("4", "Record", "Enter results in PLG Records within 2 working days using the finding codes in section 6."),
        ("5", "Follow up", f"Minor breach: re-inspect within 14 days. Major breach: re-inspect within {fu_major} days and escalate to the Estate Manager."),
        ("6", "Close", "Close the inspection once the breach is rectified, or once enforcement action has been issued."),
    ]
    b = [
        ("h1", "1. Purpose"),
        ("p", "This SOP standardises inspections of HEB commercial units to check compliance with tenancy conditions and PLG-POL-001 Trade Mix & "
              "Usage Policy, and to detect building defects early."),
        ("h1", "2. Scope"),
        ("p", "Applies to Property Officers and Estate Managers in PLG Estate Management for all commercial units."),
        ("h1", "3. Inspection Types"),
        ("table", ["Type", "Trigger", "Frequency"], [("Routine", "Annual roster", "At least once per unit per year"),
                                                     ("Complaint-driven", "Public feedback / CRM case", "Within 3 working days of case assignment"),
                                                     ("Follow-up", "Open breach", "Per section 5 timelines")], [3.5, 7, 5.5]),
        ("h1", "4. Procedure"),
        ("table", ["Step", "Activity", "Details"], steps, [1.2, 2.6, 12.2]),
        ("h1", "5. Follow-up Timelines"),
        ("table", ["Outcome", "Re-inspection", "Escalation"], [("Minor Breach", "Within 14 days", "Warning letter if not rectified"),
                                                              ("Major Breach", f"Within {fu_major} days", "Estate Manager; enforcement per POL-001 cl. 8")], [4, 5, 7]),
        ("h1", "6. Finding Codes"),
        ("table", ["Code", "Description", "Outcome class"], [
            ("NONE", "No issues observed", "Compliant"), ("DISPLAY_ENCROACH", "Goods/furniture beyond permitted display area", "Minor Breach"),
            ("HYGIENE", "Refuse, grease or cleanliness issue", "Minor Breach"), ("UNAPPROVED_AA", "Alteration works without approval", "Minor Breach"),
            ("UNAUTH_TRADE", "Trade outside approved trade", "Major Breach"), ("UNAUTH_SUBLET", "Part/whole of unit used by another party", "Major Breach"),
            ("FIRE_SAFETY", "Blocked exits, expired extinguishers", "Major Breach"), ("STRUCTURAL_DEFECT", "Spalling, cracks - raise i-EMS ticket", "Major Breach"),
        ], [4, 8, 4]),
        ("h1", "7. Safety"),
        ("p", "Officers shall not enter areas that appear structurally unsafe. Report structural defects immediately to the Maintenance Coordinator "
              "so an i-EMS ticket can be raised (see PLG-SOP-020)."),
    ]
    if v11:
        b += [("h1", "8. Tablet App Pilot (Rimba Heights)"),
              ("p", "From 1 December 2025, Rimba Heights inspections are recorded on the PLG tablet app. The app uploads photos and findings directly "
                    "to PLG Records, which replaces step 4 for the pilot town.")]
    return b


def arrears_sop():
    return [
        ("h1", "1. Purpose"),
        ("p", "This SOP gives Finance & Arrears officers step-by-step instructions to recover rental arrears in line with PLG-POL-003."),
        ("h1", "2. Daily and Monthly Routines"),
        ("bullets", ["Daily: review GIRO rejection file; update PLG Records payment status.",
                     "Monthly (by 5th working day): generate the Arrears Ageing Report and circulate to Senior Manager, Tenancy Management."]),
        ("h1", "3. Recovery Timeline"),
        ("table", ["Days overdue", "Action", "Template / form", "Owner"], [
            ("Day 0", "Rent due (1st of month)", "-", "-"),
            ("Day 7", "GIRO failure check; SMS to tenant", "SMS-02", "F&A Officer"),
            ("Day 14", "First reminder letter", "TPL-REM-01", "F&A Officer"),
            ("Day 30", "Second reminder letter + phone call; log call in PLG Records", "TPL-REM-01 (2nd notice)", "F&A Officer"),
            ("Day 45", "Refer to HEB Legal to issue Letter of Demand", "TPL-LOD-01", "F&A Manager / Legal"),
            ("Day 75", "If unpaid after LOD expiry, recommend termination to Director", "Memo FA-11", "F&A Manager"),
        ], [2.4, 7, 3.6, 3]),
        ("h1", "4. Instalment Plans"),
        ("p", "Use form FA-08. Maximum 6 months. The F&A Manager approves plans up to S$20,000; the Director approves anything above."),
        ("h1", "5. Records"),
        ("p", "All calls, letters and plans must be logged in PLG Records against the tenancy ID within 1 working day."),
        ("h1", "6. Related Documents"),
        ("bullets", ["PLG-POL-003 Rental Arrears Management Policy", "TPL-REM-01 Arrears Reminder", "TPL-LOD-01 Letter of Demand"]),
    ]


def feedback_sop():
    return [
        ("h1", "1. Purpose"),
        ("p", "This SOP sets out how public feedback about HEB commercial premises is received, classified, routed and closed, including how "
              "building defects are referred to the integrated Estate Management System (i-EMS)."),
        ("h1", "2. Intake Channels"),
        ("bullets", ["CityFix App", "PLG hotline", "Email to plg_feedback@heb.example.org", "Walk-in at HEB Branch", "Letters from Members of Parliament (MP Letter)"]),
        ("h1", "3. Service Standards"),
        ("table", ["Milestone", "Standard"], [("Acknowledgement", "Within 3 working days"), ("Substantive reply", "Within 7 calendar days (TPL-FBK-03)"),
                                               ("MP letters", "Reply within 5 working days, cleared by Senior Manager")], [6, 10]),
        ("h1", "4. Classification Taxonomy"),
        ("p", "Classify every case into exactly one primary category. Where a case mentions several issues, choose the issue with the highest "
              "severity and note the secondary issue in remarks."),
        ("table", ["Code", "Category", "Examples", "Routed to", "i-EMS?"], [(t["code"], t["category"], t["examples"], t["team"], "Yes" if t["iems"] else "No")
                                                                       for t in DEFECT_TAXONOMY], [1.3, 3.2, 6, 3.3, 1.6]),
        ("h1", "5. Severity and SLA"),
        ("table", ["Severity", "Definition", "i-EMS completion SLA"], [
            ("Critical", "Immediate risk to life or property (fire, falling concrete in public area)", f"{SEVERITY_SLA_DAYS['Critical']} day"),
            ("High", "Safety risk or business stoppage", f"{SEVERITY_SLA_DAYS['High']} days"),
            ("Medium", "Affects use of premises but not safety", f"{SEVERITY_SLA_DAYS['Medium']} days"),
            ("Low", "Cosmetic, nuisance or compliance", f"{SEVERITY_SLA_DAYS['Low']} days")], [3, 9, 4]),
        ("h1", "6. Routing to i-EMS"),
        ("numbered", ["Customer Relations Officer classifies the case in CRM.", "For i-EMS categories, the Maintenance Coordinator raises an i-EMS ticket "
                                                                              "with: unit ID, category code, severity, description, photos.",
                      "i-EMS assigns to the term contractor for the routed team.", "If the contractor rejects the ticket as misrouted, the Maintenance "
                                                                                    "Coordinator re-classifies it within 1 working day.",
                      "On completion, Customer Relations sends the feedback provider an update using TPL-FBK-03."]),
        ("h1", "7. Non-i-EMS Categories"),
        ("p", "Hygiene, encroachment and noise cases are passed to Estate Management for a complaint-driven inspection (PLG-SOP-011). Common-area cases "
              "are referred to the relevant Town Council within 2 working days."),
    ]


TEMPLATES = {
    "TPL-REM-01": dict(title="Arrears Reminder Letter", purpose="First/second reminder for overdue rent", approver="Manager, Finance & Arrears",
                       slots=["letter_ref", "letter_date", "tenant_name", "tenant_address", "unit_address", "tenancy_id", "notice_level", "invoice_table",
                              "total_due", "pay_by_date", "officer_name", "officer_phone"]),
    "TPL-DOC-02": dict(title="Missing Documents Notice", purpose="Notify applicant of missing/invalid documents", approver="Senior Manager, Tenancy Management",
                       slots=["letter_ref", "letter_date", "tenant_name", "contact_person", "application_id", "application_type", "unit_address",
                              "missing_documents_list", "submit_by_date", "officer_name", "officer_email"]),
    "TPL-FBK-03": dict(title="Feedback Update Reply", purpose="Update to member of public on feedback case", approver="Senior Manager, Tenancy Management",
                       slots=["feedback_id", "reply_date", "provider_name", "received_date", "location", "issue_summary", "action_taken",
                              "ticket_reference", "next_steps", "officer_name"]),
}


def template_blocks(tid):
    t = TEMPLATES[tid]
    meta = [("Template ID", tid), ("Purpose", t["purpose"]), ("Approved by", t["approver"]), ("Required slots", ", ".join(t["slots"])),
            ("Rule", "Approved wording must not be changed. Only {{ slot }} values may be filled. Text in [square brackets] is guidance for officers "
                     "and must be deleted.")]
    b = [("h2", "Template metadata"), ("kv", meta), ("pagebreak",)]
    if tid == "TPL-REM-01":
        b += [("p", "Our ref: {{ letter_ref }}"), ("p", "{{ letter_date }}"), ("p", "{{ tenant_name }}\n{{ tenant_address }}"),
              ("p", "Dear Sir/Madam,"),
              ("h3", "{{ notice_level }} REMINDER: OVERDUE RENT FOR {{ unit_address }} (TENANCY {{ tenancy_id }})"),
              ("p", "Our records show that the following rent remains unpaid as at the date of this letter:"),
              ("p", "{{ invoice_table }}"),
              ("p", "The total amount due is {{ total_due }} (inclusive of GST). Late-payment interest at 8% per annum will continue to accrue until "
                    "full payment is received."),
              ("p", "Please pay the total amount due by {{ pay_by_date }}. You may pay by GIRO, PayNow (UEN reference on your invoice) or at any HEB "
                    "branch. If you have already paid, please ignore this reminder."),
              ("p", "If you are having difficulty paying, please call {{ officer_name }} at {{ officer_phone }} to discuss your situation."),
              ("p", "Failure to pay may result in further action under your tenancy agreement, including a Letter of Demand."),
              ("sig", ["Yours faithfully,", "", "{{ officer_name }}", "Finance & Arrears", "Properties & Land Group", "Housing & Estates Board"])]
    elif tid == "TPL-DOC-02":
        b += [("p", "Our ref: {{ letter_ref }}"), ("p", "{{ letter_date }}"), ("p", "{{ tenant_name }}\nAttn: {{ contact_person }}"),
              ("p", "Dear {{ contact_person }},"),
              ("h3", "{{ application_type }} APPLICATION {{ application_id }} - OUTSTANDING DOCUMENTS ({{ unit_address }})"),
              ("p", "Thank you for your application. We have reviewed the documents you submitted and need the following before we can continue:"),
              ("p", "{{ missing_documents_list }}"),
              ("p", "Please submit the documents by {{ submit_by_date }} (14 days from the date of this letter) via email to {{ officer_email }} or at "
                    "any HEB branch. Your application will be treated as withdrawn if we do not receive them by this date."),
              ("p", "[Officer: for each item, state whether it is missing, expired, illegible or for the wrong unit.]"),
              ("sig", ["Yours sincerely,", "", "{{ officer_name }}", "Tenancy Management", "Properties & Land Group"])]
    else:
        b += [("p", "Case: {{ feedback_id }}"), ("p", "{{ reply_date }}"), ("p", "Dear {{ provider_name }},"),
              ("p", "Thank you for your feedback received on {{ received_date }} regarding {{ issue_summary }} at {{ location }}."),
              ("p", "We have looked into the matter. {{ action_taken }}"), ("p", "Reference: {{ ticket_reference }}"),
              ("p", "{{ next_steps }}"),
              ("p", "We appreciate you taking the time to help us keep our estates safe and pleasant."),
              ("sig", ["Yours sincerely,", "", "{{ officer_name }}", "Customer Relations", "Properties & Land Group"])]
    return b


def minutes(M):
    v = Counter(u["town"] for u in M["units"] if u["status"] == "Vacant")
    return [
        ("kv", [("Meeting", "PLG Management Meeting No. 4/2026"), ("Date / time", "15 April 2026, 2.30 pm - 4.45 pm"), ("Venue", "HEB Hub, Meeting Room 7-02"),
                ("Chair", sname("S01")), ("Present", ", ".join(sname(s) for s in ["S02", "S03", "S04", "S07", "S08", "S09", "S12"])),
                ("Apologies", sname("S06")), ("Secretariat", sname("S05"))]),
        ("h1", "1. Confirmation of Minutes"),
        ("p", "The minutes of Meeting No. 3/2026 (18 March 2026) were confirmed without amendment."),
        ("h1", "2. Roll-out of Revised Arrears Policy (PLG-POL-003 v2.0)"),
        ("p", "Priya briefed the meeting on the revised policy, effective 1 April 2026. Main changes: a mandatory hardship call between 31 and 45 days, "
              "the Letter of Demand moving from 45 to 60 days, a termination threshold of more than 3 months of arrears, and instalment plans of up to 12 months. "
              "Joanne noted that Legal's LOD queue will move accordingly."),
        ("p", "Decision: PLG-SOP-014 to be updated to match the policy by 31 May 2026. Training for F&A officers was held on 8 April 2026."),
        ("h1", "3. Definition of Vacant Units in Management Reporting"),
        ("p", "Kelvin pointed out that the monthly reports and the QBR count vacancy differently. The Director decided that, from the April 2026 report, "
              "'vacant' means units with no active or committed tenancy that are lettable and NOT under tender. Units under tender and units "
              "not lettable (earmarked for upgrading or redevelopment) are reported separately. Historical figures are not restated."),
        ("p", "Action: Kelvin to update the vacancy report template and the PLG glossary. Rajesh to ensure the QBR deck follows the new definition."),
        ("h1", "4. Display Areas at Neighbourhood Centres"),
        ("p", "Benjamin and Marcus reported that NC tenants keep asking for more display space, and that enforcing the 0.6 m rule at wide NC "
              "walkways is producing a lot of feedback cases. Rajesh proposed piloting 1.0 m at NCs where the walkway is wide enough. Agreed in principle; "
              "Rajesh to draft a circular for the Director's approval, targeting 1 August 2026."),
        ("h1", "5. Arrears Position"),
        ("p", f"Priya reported total arrears of {money(sum(r['amount'] for r in arrears_asof(M, D(2026, 3, 31))), False)} "
              "as at 31 March 2026. The meeting noted that a few large minimarts and two eating houses make up a significant share."),
        ("h1", "6. Any Other Business"),
        ("bullets", ["Fire safety: Estate Managers to remind eating-house tenants to clean exhaust ducts quarterly.",
                     "Super-librarian AI POC: the Director supported a 4-week POC using synthetic data. Kelvin is the point of contact."]),
        ("h1", "Action Items"),
        ("table", ["#", "Action", "Owner", "Due"], [("1", "Update PLG-SOP-014 to align with POL-003 v2.0", sname("S07"), "31 May 2026"),
                                                   ("2", "Update vacancy report template and glossary", sname("S08"), "30 Apr 2026"),
                                                   ("3", "QBR to adopt new vacancy definition", sname("S02"), "Next QBR"),
                                                   ("4", "Draft circular on NC display area pilot", sname("S02"), "15 Jul 2026"),
                                                   ("5", "Exhaust duct cleaning reminder to eating houses", f"{sname('S04')} / {sname('S12')}", "30 Apr 2026")], [1, 8, 4, 3]),
        ("note", "Next meeting: 20 May 2026."),
    ]


def register_docs(M):
    out = "docs"

    def r(id, fname, title, author, date, purpose, q, blocks_fn, flags="", entities=(), **kw):
        def fn(root):
            docx_render(f"{root}/{out}/{fname}", blocks_fn(), title=title, author=sname(author) if author.startswith("S") else author, date=date, **kw)
        register(id, f"{out}/{fname}", "docx", title, sname(author), date, purpose, q, fn, flags=flags, entities=entities)

    r("DOC-001", "PLG-POL-003_Rental_Arrears_Management_Policy_v1.0.docx", "PLG-POL-003 Rental Arrears Management Policy (v1.0)", "S02", D(2024, 2, 20),
      "Superseded arrears policy (LOD at 45 days, termination at 2 months)", "What was the LOD trigger before April 2026?",
      lambda: arrears_policy(False), flags="SUPERSEDED by DOC-002", entities=("PLG-POL-003",),
      doc_id="PLG-POL-003", watermark="SUPERSEDED w.e.f. 1 Apr 2026", control=ctrl("PLG-POL-003", "1.0", D(2024, 3, 1), "Leasing Policy & Planning", sname("S01"), D(2026, 3, 1), "Superseded", "PLG-POL-003 v0.9 (2021)"),
      revisions=[("0.9", "2021-05-03", "PLG Policy", "Initial"), ("1.0", "2024-02-20", sname("S02"), "Added instalment plan limits; LOD at 45 days")])
    r("DOC-002", "PLG-POL-003_Rental_Arrears_Management_Policy_v2.0.docx", "PLG-POL-003 Rental Arrears Management Policy (v2.0)", "S02", D(2026, 3, 16),
      "Current arrears policy: hardship call, LOD at 60 days, termination >3 months, instalments up to 12 months",
      "When does PLG issue a Letter of Demand?; What is the termination threshold for arrears?", lambda: arrears_policy(True),
      flags="CONFLICT C1 (vs DOC-007)", entities=("PLG-POL-003", "PLG Circular 03/2026"), doc_id="PLG-POL-003",
      control=ctrl("PLG-POL-003", "2.0", D(2026, 4, 1), "Leasing Policy & Planning", sname("S01"), D(2028, 4, 1), "In force", "v1.0 (1 Mar 2024)"),
      revisions=[("1.0", "2024-02-20", sname("S02"), "Instalment plan limits; LOD at 45 days"),
                 ("2.0", "2026-03-16", sname("S02"), "Hardship call 31-45 days; LOD moved to 60 days; termination threshold >3 months; instalments up to 12 months; Director limit S$30,000")])
    r("DOC-003", "PLG-POL-001_Trade_Mix_and_Usage_Policy_v3.0.docx", "PLG-POL-001 Trade Mix & Usage Policy (v3.0)", "S02", D(2025, 6, 10),
      "Long policy: trade mix limits, change of trade, usage rules incl. display area 0.6 m", "How many units of the same trade are allowed in an NC?; What is the display-area limit?",
      lambda: trade_mix_policy(M), flags="CONFLICT C5 (cl. 7.3 superseded for NCs by PDF-002)", entities=("PLG-POL-001",), doc_id="PLG-POL-001",
      control=ctrl("PLG-POL-001", "3.0", D(2025, 7, 1), "Leasing Policy & Planning", sname("S01"), D(2027, 7, 1), "In force", "v2.2 (2022)"),
      revisions=[("2.2", "2022-08-01", "PLG Policy", "Added eldercare trades"), ("3.0", "2025-06-10", sname("S02"), "Concentration limit 2 per NC (3 minimarts in large NCs); enforcement table; appeals")])
    r("DOC-004", "PLG-POL-002_Tenancy_Renewal_and_Security_Deposit_Policy_v2.1.docx", "PLG-POL-002 Tenancy Renewal & Security Deposit Policy (v2.1)", "S02", D(2025, 1, 6),
      "Renewal eligibility, 6-month lead time, market rent, 3-month deposit", "How early must a tenant apply to renew?; How much is the security deposit?",
      renewal_policy, flags="CONFLICT C2 (vs PDF-008), C3 (vs OTH-005, EML)", entities=("PLG-POL-002",), doc_id="PLG-POL-002",
      control=ctrl("PLG-POL-002", "2.1", D(2025, 1, 15), "Tenancy Management", sname("S01"), D(2027, 1, 15), "In force", "v2.0 (2023)"),
      revisions=[("2.0", "2023-04-01", "PLG Policy", "Phasing of rent increases > 20%"), ("2.1", "2025-01-06", sname("S03"), "Bankers' guarantee threshold S$15,000; clarified late applications")])
    r("DOC-005", "PLG-SOP-011_Commercial_Unit_Inspection_SOP_v1.0.docx", "PLG-SOP-011 Commercial Unit Inspection SOP (v1.0)", "S06", D(2025, 3, 3),
      "Inspection SOP (older version)", "How soon must a major breach be re-inspected (v1.0)?", lambda: inspection_sop(False),
      flags="NEAR-DUPLICATE of DOC-006; SUPERSEDED", entities=("PLG-SOP-011",), doc_id="PLG-SOP-011",
      control=ctrl("PLG-SOP-011", "1.0", D(2025, 3, 3), "Estate Management", sname("S04"), D(2026, 3, 3), "Superseded"),
      revisions=[("1.0", "2025-03-03", sname("S06"), "First issue")])
    r("DOC-006", "PLG-SOP-011_Commercial_Unit_Inspection_SOP_v1.1.docx", "PLG-SOP-011 Commercial Unit Inspection SOP (v1.1)", "S06", D(2025, 11, 10),
      "Current inspection SOP: 3 photos per breach, major breach follow-up 7 days, tablet pilot", "What are the inspection finding codes?; What changed in SOP-011 v1.1?",
      lambda: inspection_sop(True), flags="NEAR-DUPLICATE of DOC-005", entities=("PLG-SOP-011",), doc_id="PLG-SOP-011",
      control=ctrl("PLG-SOP-011", "1.1", D(2025, 12, 1), "Estate Management", sname("S04"), D(2026, 12, 1), "In force", "v1.0"),
      revisions=[("1.0", "2025-03-03", sname("S06"), "First issue"), ("1.1", "2025-11-10", sname("S06"), "Min. 3 photos per breach; major breach re-inspection 7 days; Rimba Heights tablet pilot")])
    r("DOC-007", "PLG-SOP-014_Rental_Arrears_Recovery_SOP_v1.2.docx", "PLG-SOP-014 Rental Arrears Recovery SOP (v1.2)", "S07", D(2025, 6, 2),
      "Arrears SOP NOT updated after policy v2.0 (still LOD at day 45)", "What does the arrears SOP say about LOD timing? Is it consistent with policy?",
      arrears_sop, flags="CONFLICT C1 (vs DOC-002); outdated", entities=("PLG-SOP-014", "PLG-POL-003"), doc_id="PLG-SOP-014",
      control=ctrl("PLG-SOP-014", "1.2", D(2025, 6, 2), "Finance & Arrears", sname("S03"), D(2026, 6, 2), "In force (review overdue)", "v1.1"),
      revisions=[("1.1", "2024-03-01", sname("S07"), "Aligned with POL-003 v1.0"), ("1.2", "2025-06-02", sname("S07"), "Added SMS-02 at day 7")])
    r("DOC-008", "PLG-SOP-020_Public_Feedback_and_Defect_Routing_SOP_v2.0.docx", "PLG-SOP-020 Public Feedback & Defect Routing SOP (v2.0)", "S03", D(2025, 11, 24),
      "Feedback classification taxonomy, severity SLAs, i-EMS routing", "Which team handles water seepage?; What is the SLA for a Critical defect?",
      feedback_sop, entities=("PLG-SOP-020", "i-EMS"), doc_id="PLG-SOP-020",
      control=ctrl("PLG-SOP-020", "2.0", D(2025, 12, 1), "Customer Relations", sname("S01"), D(2027, 12, 1)),
      revisions=[("1.0", "2023-09-01", sname("S11"), "First issue"), ("2.0", "2025-11-24", sname("S03"), "Added taxonomy codes; misrouted ticket handling")])
    for i, tid in enumerate(TEMPLATES, 9):
        t = TEMPLATES[tid]
        r(f"DOC-{i:03d}", f"{tid}_{t['title'].replace(' ', '_')}.docx", f"{tid} {t['title']} (Approved Template)", "S03", D(2025, 9, 1) if i < 11 else D(2025, 12, 1),
          f"Approved template for drafting agent: {t['purpose']}", f"Draft a {t['title'].lower()} using the approved template",
          (lambda tid=tid: template_blocks(tid)), entities=(tid,), doc_id=tid,
          control=[("Template ID", tid), ("Version", "1.3"), ("Approved by", t["approver"]), ("Status", "Approved for use")])
    r("DOC-012", "Minutes_PLG_Management_Meeting_2026-04-15.docx", "Minutes of PLG Management Meeting No. 4/2026", "S05", D(2026, 4, 17),
      "Decisions: arrears policy roll-out, new vacancy definition, NC display-area pilot", "How is a vacant unit defined for reporting since April 2026?; Who owns the SOP-014 update?",
      lambda: minutes(M), flags="Explains C4 and C5", entities=("PLG-POL-003", "PLG-SOP-014"), doc_id="PLG-MIN-04/2026")
    return CHECKLISTS
