"""Submission bundles for the document-completeness workflow (pdfs/submissions/<APP-ID>/...)."""
import datetime as dt
import random

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as rl_canvas

from common import D, addr, fd, fdl, money, register, tenancy, tenant, unit
from master import APP_TYPE_LABEL, CHECKLISTS
from render import pdf_render, pdf_scanned

INSURER = "Harbourline General Insurance Ltd"
CONTRACTORS = ["Trimax Renovation Pte Ltd", "BuildRight Interior Works", "Sterling Fit-Out Pte Ltd", "Hup Lee Construction"]


def _wrong_unit(u):
    n = int(u["unit_no"][-2:])
    return dict(u, unit_no=f"{u['unit_no'][:-2]}{(n % 30) + 1:02d}" if n != (n % 30) + 1 else u["unit_no"][:-2] + "40")


def doc_blocks(code, b, M, rng, problem):
    a = M["idx"]["app"][b["application_id"]]
    t = tenant(M, b["tenant_id"])
    u = unit(M, b["unit_id"])
    if problem == "wrong_unit":
        u = _wrong_unit(u)
    ta = tenancy(M, a["tenancy_id"]) if a["tenancy_id"] else next((x for x in M["tenancies"] if x["tenant_id"] == t["tenant_id"] and x["unit_id"] == b["unit_id"]), None)
    sub = b["submitted_date"]
    who = t["contact_person"]
    if code in ("BIZ", "BIZ2"):
        nm, brn = (t["name"], t["brn"]) if code == "BIZ" else (f"{rng.choice(['Sunrise', 'Vista', 'Meridian', 'Kian Seng'])} Holdings Pte Ltd", f"20{rng.randint(10, 24)}{rng.randint(10000, 99999)}K")
        ext = sub - dt.timedelta(days=rng.randint(3, 40)) if problem != "expired" else sub - dt.timedelta(days=rng.randint(130, 220))
        return [("title", "BUSINESS REGISTRY AUTHORITY - BUSINESS PROFILE"), ("note", "Fictional registry extract for POC purposes"),
                ("kv", [("Name", nm), ("Registration no.", brn), ("Entity type", "Private company limited by shares" if "Pte" in nm else "Sole proprietorship"),
                        ("Status", "Live"), ("Registered address", addr(unit(M, b["unit_id"]))), ("Principal activity", tenancy(M, a["tenancy_id"])["trade"] if a["tenancy_id"] else t["trade_primary"]),
                        ("Date of extract", fdl(ext)), ("Receipt no.", f"BRA-{rng.randint(10 ** 7, 10 ** 8 - 1)}")]),
                ("h3", "Officers"), ("table", ["Name", "ID (masked)", "Position", "Appointed"], [(who, f"SXXXX{rng.randint(100, 999)}{rng.choice('ABCDEFGHIZ')}", "Director",
                                                                                             fd(t["registered_since"]))], [5, 4, 4, 4])], ext
    if code == "INS":
        start = sub - dt.timedelta(days=rng.randint(30, 200))
        end = start + dt.timedelta(days=364)
        if problem == "expired" and a["app_type"] == "RENEWAL" and ta:
            end = min(end, ta["end_date"] - dt.timedelta(days=31))
        elif problem == "expired":
            end = sub - dt.timedelta(days=rng.randint(5, 40))
        insured = t["name"] if a["app_type"] != "ALTERATION" else rng.choice(CONTRACTORS)
        return [("title", "CERTIFICATE OF INSURANCE"), ("note", f"{INSURER} (fictional)"),
                ("kv", [("Policy no.", f"HGI/PL/{rng.randint(100000, 999999)}"), ("Insured", insured), ("Premises", addr(u)),
                        ("Cover", "Public Liability" if a["app_type"] != "ALTERATION" else "Contractor's All Risks incl. Third Party Liability"),
                        ("Limit of indemnity", "S$1,000,000 any one occurrence" if rng.random() > 0.1 else "S$2,000,000 any one occurrence"),
                        ("Period of insurance", f"{fdl(start)} to {fdl(end)}"), ("Date of issue", fdl(start - dt.timedelta(days=3)))]),
                ("p", "This certificate is issued as evidence of insurance and is subject to the terms of the policy.")], end
    if code == "NRIC":
        return "SCAN", [["# IDENTITY CARD (COPY) - MASKED", "", f"Name: {who.upper()}", f"ID No.: SXXXX{rng.randint(100, 999)}{rng.choice('ABCDEFGHIZ')}",
                         f"Date of birth: XX/XX/19{rng.randint(55, 95)}", "Sex: X", "", "[photo]", "", f"Certified true copy - {who}", f"Date: {fd(sub)}"]]
    if code == "DEP":
        ta2 = next((x for x in M["tenancies"] if x["tenant_id"] == t["tenant_id"]), None)
        amt = ta2["security_deposit"] if ta2 else 9000
        return [("title", "PAYMENT ADVICE - SECURITY DEPOSIT"), ("kv", [("Payer", t["name"]), ("Payee", "Housing & Estates Board"), ("Amount", money(amt)),
                                                                       ("Mode", rng.choice(["Cashier's order", "Interbank transfer (FAST)"])), ("Reference", f"{b['application_id']} DEPOSIT"),
                                                                       ("Value date", fdl(sub - dt.timedelta(days=1))), ("Bank ref", f"FT{rng.randint(10 ** 9, 10 ** 10 - 1)}")])], None
    if code == "GIRO":
        return [("title", "GIRO AUTHORISATION FORM (HEB RENT)"), ("note", "Form HEB-GIRO-3"), ("kv", [("Account holder", t["name"]), ("Bank", rng.choice(["Bank A", "Bank B", "Bank C"]) + " (fictional)"),
                                                                                                      ("Account no.", f"XXX-XXX{rng.randint(100, 999)}-X"), ("Billing org", "Housing & Estates Board - PLG"),
                                                                                                      ("Customer ref", ta["tenancy_id"] if ta else b["application_id"]), ("Limit", "No limit"),
                                                                                                      ("Signed", f"{who}, {fd(sub)}")])], None
    if code == "LIC":
        trade = a.get("proposed_trade") or (ta["trade"] if ta else t["trade_primary"])
        auth = "Environmental Health Authority" if trade in ("Bakery & Confectionery", "Bubble Tea", "Restaurant", "Coffeeshop", "Snack Kiosk") else "Health Services Licensing Office"
        return [("title", f"{auth.upper()} - LICENCE"), ("kv", [("Licensee", t["name"]), ("Premises", addr(u)), ("Licence type", f"{trade} premises licence"),
                                                                ("Licence no.", f"LIC-{rng.randint(100000, 999999)}"), ("Valid", f"{fd(sub - dt.timedelta(days=60))} to {fd(sub + dt.timedelta(days=305))}")])], None
    if code == "LOA":
        return [("p", fdl(sub)), ("p", "Housing & Estates Board\nProperties & Land Group"), ("h3", f"ACCEPTANCE OF LETTER OF OFFER - {addr(u)}"),
                ("p", f"We, {t['name']}, accept the offer of tenancy for the above premises on the terms set out in your letter of offer, including monthly rent of "
                      f"{money(ta['monthly_rent'] if ta else 0)} and a security deposit of three months' rent."), ("sig", ["Yours faithfully,", "", who, "Director", t["name"]])], None
    if code == "LAYOUT":
        return "DRAWING", None
    if code == "PLAN":
        trade = a.get("proposed_trade") or "proposed trade"
        return [("title", f"BUSINESS PLAN - {t['name'].upper()}"), ("h2", "1. Proposal"),
                ("p", f"We propose to convert our premises at {addr(u)} to a {trade.lower()} outlet. Our current business has seen declining sales of about 30% "
                      "over two years, which we attribute to competition from larger chains."),
                ("h2", "2. Market"), ("p", "Target customers are students and young families living in the surrounding blocks. We estimate daily footfall of "
                                            "400-600 based on our own observation of the walkway."),
                ("h2", "3. Financials"), ("table", ["Item", "Year 1", "Year 2"], [("Revenue", "S$312,000", "S$358,000"), ("Rent", "S$56,400", "S$56,400"),
                                                                                  ("Staff", "S$96,000", "S$101,000"), ("Net profit", "S$41,000", "S$63,000")], [6, 5, 5]),
                ("h2", "4. Fit-out"), ("p", "Fit-out works estimated at S$45,000, subject to A&A approval."), ("sig", [who, "Owner"])], None
    forms = {"REN": ("APPLICATION FOR RENEWAL OF TENANCY", "PLG-REN-01"), "ASG": ("APPLICATION FOR ASSIGNMENT OF TENANCY", "PLG-ASG-01"),
             "COT": ("APPLICATION FOR CHANGE / ADDITION OF TRADE", "PLG-COT-01"), "AA": ("APPLICATION FOR ALTERATION & ADDITION WORKS", "PLG-AA-01"),
             "FEE": ("PAYMENT RECEIPT - ASSIGNMENT FEE", "HEB-RCPT"), "CON": ("CONTRACTOR REGISTRATION CERTIFICATE", "BCA-like (fictional)"),
             "PE": ("PROFESSIONAL ENGINEER ENDORSEMENT", "PE-END"), "MS": ("METHOD STATEMENT & WORK SCHEDULE", "MS-01"), "DWG": ("LAYOUT & ELEVATION DRAWINGS", "DWG")}
    title, form = forms[code]
    kv = [("Applicant", t["name"]), ("Registration no.", t["brn"]), ("Contact person", who), ("Email", t["email"]), ("Premises", addr(u)),
          ("Unit ID", u["unit_id"] if problem != "wrong_unit" else f"U-{u['block_id']}-{u['unit_no'][1:3]}-{u['unit_no'][-2:]}"),
          ("Tenancy", ta["tenancy_id"] if ta else "(new)"), ("Date", fdl(sub))]
    extra = []
    if code == "REN":
        extra = [("Current expiry", fdl(ta["end_date"]) if ta else "-"), ("Requested term", "3 years"), ("Trade", ta["trade"] if ta else "-")]
    elif code == "COT":
        extra = [("Current trade", ta["trade"] if ta else "-"), ("Proposed trade", a.get("proposed_trade") or "-"), ("Reason", "Declining sales in current trade")]
    elif code == "AA":
        extra = [("Works description", rng.choice(["Replace shopfront glazing and signage", "New drywall partition and false ceiling", "Re-wiring and new lighting",
                                                    "Install grease trap and exhaust duct", "Hack internal wall to create opening"])),
                 ("Contractor", rng.choice(CONTRACTORS)), ("Est. duration", f"{rng.randint(2, 8)} weeks")]
    elif code == "FEE":
        extra = [("Amount", "S$1,090.00 (incl. GST)"), ("Receipt no.", f"R{rng.randint(10 ** 6, 10 ** 7 - 1)}")]
    elif code == "ASG":
        extra = [("Assignee", f"{rng.choice(['Sunrise', 'Vista', 'Meridian', 'Kian Seng'])} Holdings Pte Ltd"), ("Reason", "Retirement of owner")]
    elif code == "CON":
        extra = [("Contractor", rng.choice(CONTRACTORS)), ("Registration", f"CR-{rng.randint(1000, 9999)} Grade L{rng.randint(1, 3)}"), ("Valid until", fdl(sub + dt.timedelta(days=400)))]
    elif code == "PE":
        extra = [("PE", f"Er. {rng.choice(['Tan Boon Huat', 'Ravi Shankar', 'Lee Siew Lan'])} (PE Reg. {rng.randint(1000, 9999)})"), ("Statement", "Proposed opening does not affect structural integrity subject to lintel per drawing S-01.")]
    elif code == "MS":
        extra = [("Sequence", "1) hoarding 2) strip-out 3) services 4) partitions 5) finishes 6) clean-up"), ("Working hours", "Mon-Sat 9am-6pm; noisy works 10am-5pm")]
    elif code == "DWG":
        extra = [("Drawings", "A-01 Existing layout; A-02 Proposed layout; A-03 Shopfront elevation"), ("Scale", "1:50")]
    return [("title", title), ("note", f"Form {form} | Application {b['application_id']}"), ("kv", kv + extra),
            ("p", "I/We declare that the information given is true and complete."), ("sig", [f"Signature: {who}", f"Date: {fd(sub)}"])], None


def draw_layout(path, b, M, rng):
    u = unit(M, b["unit_id"])
    c = rl_canvas.Canvas(path, pagesize=landscape(A4))
    W, H = landscape(A4)
    c.setTitle("layout plan")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, H - 2 * cm, f"PROPOSED FLOOR LAYOUT - {addr(u)}")
    c.setFont("Helvetica", 9)
    c.drawString(2 * cm, H - 2.6 * cm, f"Unit {u['unit_id']}  |  Area {u['floor_area_sqm']} sqm  |  Scale 1:50  |  Dwg A-02 rev B  |  Application {b['application_id']}")
    x0, y0, w, h = 3 * cm, 3 * cm, 18 * cm, 11 * cm
    c.setLineWidth(2)
    c.rect(x0, y0, w, h)
    c.setLineWidth(1)
    c.line(x0 + w * 0.65, y0, x0 + w * 0.65, y0 + h)
    c.drawString(x0 + 1 * cm, y0 + h - 1 * cm, "SERVICE / PREP AREA")
    c.drawString(x0 + w * 0.7, y0 + h - 1 * cm, "STORE")
    c.rect(x0 + 1 * cm, y0 + 1 * cm, 6 * cm, 1.2 * cm)
    c.drawString(x0 + 1.2 * cm, y0 + 1.4 * cm, "COUNTER")
    c.setDash(4, 3)
    c.line(x0, y0 - 1 * cm, x0 + w, y0 - 1 * cm)
    c.setDash()
    c.drawString(x0, y0 - 1.5 * cm, "Display line 1.0 m from shopfront (NC pilot)  |  Walkway clear width >= 1.2 m")
    c.setStrokeColor(colors.red)
    c.drawString(x0 + w + 0.5 * cm, y0 + h / 2, "REAR EXIT")
    c.save()


def register_submissions(M):
    rng = random.Random(M["seed"] + 61)
    name_styles = [lambda code, i: f"scan_{rng.randint(1, 99):04d}.pdf", lambda code, i: f"{code.lower()}.pdf", lambda code, i: f"IMG_{rng.randint(1000, 9999)}.pdf",
                   lambda code, i: f"{code}_{i}.pdf", lambda code, i: f"Document ({i}).pdf"]
    friendly = {"BIZ": "BizProfile", "INS": "insurance cert", "GIRO": "GIRO form", "NRIC": "IC copy", "LOA": "LOA signed", "REN": "Renewal form", "COT": "COT application",
                "PLAN": "business plan", "LAYOUT": "layout", "AA": "AA form", "DWG": "drawings", "MS": "method statement", "CON": "contractor cert",
                "PE": "PE letter", "DEP": "deposit payment", "FEE": "fee receipt", "ASG": "assignment form", "BIZ2": "assignee bizprofile", "LIC": "licence"}
    for b in M["bundles"]:
        folder = f"pdfs/submissions/{b['application_id']}"
        used = set()
        for i, code in enumerate(b["present"], 1):
            style = rng.random()
            if style < 0.45:
                fname = f"{friendly[code]}.pdf"
            else:
                fname = rng.choice(name_styles)(code, i)
            while fname in used:
                fname = fname.replace(".pdf", "_1.pdf")
            used.add(fname)
            problem = b["problems"].get(code)
            path = f"{folder}/{fname}"
            b["files"].append(dict(file=path, doc_code=code, problem=problem))
            seed = rng.randint(0, 10 ** 6)
            app_label = APP_TYPE_LABEL[b["app_type"]]

            def fn(root, code=code, b=b, problem=problem, path=path, seed=seed):
                import os
                os.makedirs(os.path.dirname(f"{root}/{path}"), exist_ok=True)
                r = random.Random(seed)
                res = doc_blocks(code, b, M, r, problem)
                if res[0] == "DRAWING":
                    draw_layout(f"{root}/{path}", b, M, r)
                    return
                if res[0] == "SCAN":
                    pdf_scanned(f"{root}/{path}", res[1], title="scan", seed=seed, heavy=(problem == "illegible_scan"))
                    return
                blocks, _ = res
                if problem == "illegible_scan":
                    lines = []
                    for bl in blocks:
                        if bl[0] in ("title", "p", "note"):
                            lines.append(("# " if bl[0] == "title" else "") + str(bl[1])[:70])
                        elif bl[0] == "kv":
                            lines += [f"{k}: {v}"[:70] for k, v in bl[1]]
                    pdf_scanned(f"{root}/{path}", [lines], title="scan", seed=seed, heavy=True)
                    return
                pdf_render(f"{root}/{path}", blocks, title=fname_title(code), author=tenant(M, b["tenant_id"])["contact_person"],
                           letterhead=code in ("REN", "COT", "AA", "ASG", "FEE", "GIRO"), ref=b["application_id"], classification="FICTIONAL POC DATA - SUBMITTED DOCUMENT")
            label = next(c[1] for c in CHECKLISTS[b["app_type"]] if c[0] == code)
            register(f"SUB-{b['application_id'][4:]}-{i:02d}", path, "pdf", f"{b['application_id']} submitted document ({label})", tenant(M, b["tenant_id"])["contact_person"],
                     b["submitted_date"], f"{app_label} submission bundle document; checklist code {code}",
                     f"Is application {b['application_id']} complete? What is missing?", fn,
                     entities=(b["application_id"], b["tenant_id"], b["unit_id"]),
                     flags=(f"PROBLEM: {problem}" if problem else "") + ("; SCANNED (image-only)" if code == "NRIC" or problem == "illegible_scan" else ""))


def fname_title(code):
    return {"BIZ": "Business Profile", "INS": "Insurance Certificate"}.get(code, code)
