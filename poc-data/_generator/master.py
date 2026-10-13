"""Shared master data for the HEB PLG corpus.

Every artifact is derived from the structure returned by build(seed). Nothing here
refers to real people or organisations; all domains are reserved example domains.
"""
import datetime as dt
import random
from collections import Counter, defaultdict

D = dt.date
START, END = D(2025, 10, 1), D(2026, 9, 30)
ASOF = END
GST = 0.09
LATE_INTEREST_PA = 0.08
ORG = "Housing & Estates Board"
ORG_SHORT = "HEB"
GROUP = "Properties & Land Group"
ORG_DOMAIN = "heb.example.org"
ORG_ADDRESS = "480 Lorong Merdeka, HEB Hub, Singapura 310480"

STAFF = [
    dict(id="S01", name="Tan Wei Ling", first="Wei Ling", title="Director, Properties & Land Group", dept="PLG Directorate", style="formal", email="tan.weiling@heb.example.org", phone="+65 6100 2001"),
    dict(id="S02", name="Rajesh Pillai", first="Rajesh", title="Deputy Director, Leasing Policy & Planning", dept="Leasing Policy & Planning", style="formal", email="rajesh.pillai@heb.example.org", phone="+65 6100 2014"),
    dict(id="S03", name="Nurul Huda Rahman", first="Nurul", title="Senior Manager, Tenancy Management", dept="Tenancy Management", style="chatty", email="nurul.huda@heb.example.org", phone="+65 6100 2032"),
    dict(id="S04", name="Marcus Lim", first="Marcus", title="Estate Manager (East)", dept="Estate Management", style="terse", email="marcus.lim@heb.example.org", phone="+65 6100 2047"),
    dict(id="S05", name="Siti Aishah Yusof", first="Siti", title="Leasing Officer", dept="Tenancy Management", style="chatty", email="siti.aishah@heb.example.org", phone="+65 6100 2058"),
    dict(id="S06", name="Daniel Ong", first="Daniel", title="Property Officer (Inspections)", dept="Estate Management", style="terse", email="daniel.ong@heb.example.org", phone="+65 6100 2063"),
    dict(id="S07", name="Priya Menon", first="Priya", title="Manager, Finance & Arrears", dept="Finance & Arrears", style="formal", email="priya.menon@heb.example.org", phone="+65 6100 2071"),
    dict(id="S08", name="Kelvin Goh", first="Kelvin", title="Data Analyst, Ops Analytics", dept="Ops Analytics", style="terse", email="kelvin.goh@heb.example.org", phone="+65 6100 2086"),
    dict(id="S09", name="Joanne Teo", first="Joanne", title="Legal Counsel", dept="Legal", style="formal", email="joanne.teo@heb.example.org", phone="+65 6100 2090"),
    dict(id="S10", name="Ahmad Faizal Ismail", first="Faizal", title="Maintenance Coordinator (i-EMS)", dept="Estate Management", style="terse", email="ahmad.faizal@heb.example.org", phone="+65 6100 2104"),
    dict(id="S11", name="Grace Chua", first="Grace", title="Customer Relations Officer", dept="Customer Relations", style="chatty", email="grace.chua@heb.example.org", phone="+65 6100 2112"),
    dict(id="S12", name="Benjamin Ho", first="Benjamin", title="Estate Manager (West)", dept="Estate Management", style="semi-formal", email="benjamin.ho@heb.example.org", phone="+65 6100 2125"),
]
STAFF_BY_ID = {s["id"]: s for s in STAFF}

TOWNS = [
    dict(code="BV", name="Bayshore Vale", region="East", blk_range=(201, 299), postal="46", rate=52, tc="Bayshore-Cendana Town Council", em="S04",
         streets=["Bayshore Vale Street 21", "Bayshore Vale Avenue 2", "Bayshore Vale Drive"],
         ncs=["Bayshore Vale Central NC", "Bayshore Vale North NC", "Vale Point NC"]),
    dict(code="CD", name="Cendana", region="East", blk_range=(101, 199), postal="47", rate=48, tc="Bayshore-Cendana Town Council", em="S04",
         streets=["Cendana Road", "Cendana Street 11", "Jalan Cendana Indah"],
         ncs=["Cendana Central NC", "Cendana Gardens NC", "Cendana Lake NC"]),
    dict(code="KR", name="Kebun Raya", region="West", blk_range=(301, 399), postal="65", rate=45, tc="Kebun Raya-Rimba Town Council", em="S12",
         streets=["Kebun Raya Avenue 3", "Kebun Raya Street 31", "Kebun Raya Crescent"],
         ncs=["Kebun Raya Central NC", "Raya Hill NC", "Kebun Raya West NC"]),
    dict(code="RH", name="Rimba Heights", region="West", blk_range=(401, 499), postal="67", rate=40, tc="Kebun Raya-Rimba Town Council", em="S12",
         streets=["Rimba Heights Road", "Rimba Heights Street 45", "Rimba Walk"],
         ncs=["Rimba Heights NC", "Rimba Green NC", "Rimba Park NC"]),
    dict(code="ST", name="Sungai Tinggi", region="West", blk_range=(501, 599), postal="73", rate=38, tc="Sungai Tinggi-Pasir Indah Town Council", em="S12",
         streets=["Sungai Tinggi Drive", "Sungai Tinggi Street 52", "Tinggi Link"],
         ncs=["Sungai Tinggi Central NC", "Tinggi Vista NC", "Sungai Tinggi East NC"]),
    dict(code="PI", name="Pasir Indah", region="East", blk_range=(601, 699), postal="51", rate=44, tc="Sungai Tinggi-Pasir Indah Town Council", em="S04",
         streets=["Pasir Indah Avenue 6", "Pasir Indah Street 62", "Jalan Pasir Indah"],
         ncs=["Pasir Indah Central NC", "Indah Bay NC", "Pasir Indah South NC"]),
]
TOWN_BY_CODE = {t["code"]: t for t in TOWNS}

# Scripted blocks that the narrative depends on: (town, blk, nc index, street index)
SCRIPTED_UNITS = {"U-BV214-01-32": "Shop", "U-CD118-01-01": "Eating House", "U-KR305-01-12": "Shop", "U-PI627-01-08": "Shop",
                  "U-RH455-01-20": "Shop", "U-ST512-01-05": "Shop", "U-BV214-01-07": "Shop", "U-ST512-01-33": "Shop"}
SCRIPTED_BLOCKS = {("BV", 214): (0, 0), ("CD", 118): (0, 0), ("KR", 305): (0, 0), ("PI", 627): (0, 1), ("RH", 455): (0, 1), ("ST", 512): (0, 0)}

UNIT_TYPES = {  # type: (weight, area range sqm, rate multiplier)
    "Shop": (60, (40, 120), 1.0),
    "Eating House": (0, (200, 340), 0.9),  # placed explicitly, one per NC
    "Kiosk": (8, (6, 15), 2.2),
    "Shop with Living Quarters": (8, (60, 110), 0.85),
    "Office": (12, (50, 150), 0.6),
}

TRADES = {  # trade: (weight, allowed unit types, trade group)
    "Minimart": (12, ["Shop", "Shop with Living Quarters"], "Daily Necessities"),
    "Provision Shop": (6, ["Shop", "Shop with Living Quarters"], "Daily Necessities"),
    "Hair Salon": (8, ["Shop"], "Personal Services"),
    "Bakery & Confectionery": (5, ["Shop"], "Food & Beverage"),
    "GP Clinic": (6, ["Shop", "Office"], "Healthcare"),
    "Dental Clinic": (3, ["Shop", "Office"], "Healthcare"),
    "TCM Clinic": (4, ["Shop", "Office"], "Healthcare"),
    "Pharmacy": (3, ["Shop"], "Healthcare"),
    "Tuition Centre": (7, ["Office", "Shop"], "Education"),
    "Laundry": (3, ["Shop"], "Personal Services"),
    "Florist": (2, ["Shop", "Kiosk"], "Retail"),
    "Optical": (3, ["Shop"], "Retail"),
    "Mobile Phone & Accessories": (4, ["Shop", "Kiosk"], "Retail"),
    "Hardware": (3, ["Shop", "Shop with Living Quarters"], "Retail"),
    "Stationery & Books": (2, ["Shop"], "Retail"),
    "Bubble Tea": (3, ["Shop", "Kiosk"], "Food & Beverage"),
    "Restaurant": (4, ["Shop"], "Food & Beverage"),
    "Childcare Centre": (2, ["Office"], "Education"),
    "Remittance & Money Changer": (2, ["Kiosk", "Shop"], "Financial Services"),
    "Pet Shop": (1, ["Shop"], "Retail"),
    "Key Cutting & Shoe Repair": (2, ["Kiosk"], "Personal Services"),
    "Snack Kiosk": (3, ["Kiosk"], "Food & Beverage"),
    "Professional Services Office": (4, ["Office"], "Professional Services"),
    "Fruit Shop": (2, ["Shop", "Kiosk"], "Daily Necessities"),
    "Coffeeshop": (0, ["Eating House"], "Food & Beverage"),
}

NAME_PREFIX = ["Heng Ann", "Sin Hock", "Golden Leaf", "Ah Seng", "Mutiara", "Lucky Star", "Prima", "Evergreen", "Seri Murni", "Kim Hiap",
               "Wellcare", "Sunflower", "Jade Garden", "Hock Lee", "Sri Ganesh", "Barakah", "Tian Fu", "Bright Path", "Rainbow", "Harmony",
               "Kampung", "Orchid", "Lotus", "Phoenix", "Teck Guan", "Chop Wah", "Nanyang", "Bayu", "Cahaya", "Murugan",
               "Fortune", "Silver Moon", "Blue Pearl", "Little Sprouts", "Wisdom", "Happy Paws", "Fresh Valley", "Thye Hin", "Joo Chiat", "Peng Kee",
               "Hup Seng", "Swee Heng", "Amanah", "Sejahtera", "Ananda", "Lakshmi", "Green Leaf", "Red Lantern", "Unity", "Starlight",
               "Everbright", "Kian Huat", "Chin Lee", "Soon Hin", "Mei Ling", "Nur", "Al-Ameen", "Raja", "Kumar", "Suria",
               "Pinnacle", "Brilliant", "Smart Kids", "Bloom", "Cosy", "Daily Fresh", "Value", "Kopi Corner", "Hometown", "Old Town",
               "New Life", "Ever Joy", "Treasure", "Gold Coin", "Lim's", "Tan Brothers", "Wong's", "Ong & Sons", "Siva", "Hassan"]
TRADE_SUFFIX = {
    "Minimart": ["Minimart", "Mart", "Supermarket"], "Provision Shop": ["Provision Shop", "Trading", "Store"],
    "Hair Salon": ["Hair Studio", "Hair Salon", "Beauty & Hair"], "Bakery & Confectionery": ["Bakery", "Confectionery", "Cake House"],
    "GP Clinic": ["Family Clinic", "Medical Clinic", "Clinic & Surgery"], "Dental Clinic": ["Dental Care", "Dental Surgery"],
    "TCM Clinic": ["TCM Clinic", "Medical Hall"], "Pharmacy": ["Pharmacy", "Medical Supplies"],
    "Tuition Centre": ["Learning Centre", "Tuition Centre", "Education Hub"], "Laundry": ["Laundry", "Dry Cleaners"],
    "Florist": ["Florist", "Flowers & Gifts"], "Optical": ["Optical", "Eye Centre"], "Mobile Phone & Accessories": ["Mobile", "Telecom"],
    "Hardware": ["Hardware", "Hardware & Electrical"], "Stationery & Books": ["Bookstore", "Stationery"],
    "Bubble Tea": ["Tea House", "Bubble Tea", "Boba Bar"], "Restaurant": ["Restaurant", "Kitchen", "Eating Place"],
    "Childcare Centre": ["Childcare", "Kindergarten"], "Remittance & Money Changer": ["Remittance", "Money Changer"],
    "Pet Shop": ["Pet Shop", "Aquarium & Pets"], "Key Cutting & Shoe Repair": ["Key & Shoe Service", "Locksmith"],
    "Snack Kiosk": ["Snacks", "Kueh Corner"], "Professional Services Office": ["Accounting Services", "Agency", "Consultancy"],
    "Fruit Shop": ["Fruits", "Fruit Trading"], "Coffeeshop": ["Eating House", "Coffeeshop", "Kopitiam"],
}
SURNAMES_C = ["Tan", "Lim", "Lee", "Ng", "Ong", "Wong", "Goh", "Chua", "Chan", "Koh", "Teo", "Ang", "Yeo", "Tay", "Ho", "Low", "Toh", "Sim", "Chong", "Chia"]
GIVEN_C = ["Wei Ming", "Hui Ling", "Kok Leong", "Mei Fen", "Jun Jie", "Siew Lan", "Ah Hock", "Bee Choo", "Chee Keong", "Li Ting", "Boon Huat", "Shu Fen", "Kim Seng", "Pei Shan", "Teck Soon"]
NAMES_M = ["Ahmad bin Hassan", "Siti Rohani binte Salleh", "Muhammad Firdaus", "Nur Aisyah binte Kamal", "Rahim bin Osman", "Zainab binte Ali", "Iskandar bin Yusof", "Farah binte Ismail", "Hafiz bin Rahman", "Norhayati binte Said"]
NAMES_I = ["Suresh s/o Ramasamy", "Lakshmi d/o Krishnan", "Arun Kumar", "Meena Pillai", "Ravi Shankar", "Devi Nair", "Ganesh Murugan", "Kavitha Raj", "Vijay Menon", "Anand Subramaniam"]

DEFECT_TAXONOMY = [
    dict(code="STR", category="Structural", examples="spalling concrete, cracks in beams/columns/walls, falling plaster", team="Civil & Structural", vendor="Kemas Building Works Pte Ltd", default_severity="High", iems=True),
    dict(code="SEP", category="Water Seepage / Leak", examples="ceiling leak, wall seepage, leaking roof slab", team="Civil & Structural", vendor="Kemas Building Works Pte Ltd", default_severity="Medium", iems=True),
    dict(code="PLB", category="Plumbing & Sanitary", examples="choked floor trap, burst pipe, overflowing grease interceptor (common)", team="M&E", vendor="Sunrise M&E Services Pte Ltd", default_severity="Medium", iems=True),
    dict(code="ELE", category="Electrical", examples="power trip, exposed wiring, faulty common corridor lighting at shopfront", team="M&E", vendor="Sunrise M&E Services Pte Ltd", default_severity="High", iems=True),
    dict(code="FIR", category="Fire Safety", examples="blocked fire exit, fire incident, missing hose reel cover", team="Estate Compliance", vendor="", default_severity="Critical", iems=True),
    dict(code="PST", category="Pest", examples="rats, cockroach infestation, termites", team="Pest Control", vendor="PestAway Solutions", default_severity="Medium", iems=True),
    dict(code="HYG", category="Hygiene (Tenant)", examples="grease smell, refuse left outside shop, dirty shopfront", team="Estate Compliance", vendor="", default_severity="Low", iems=False),
    dict(code="ENC", category="Obstruction / Encroachment", examples="goods displayed beyond permitted area, tables blocking walkway", team="Estate Compliance", vendor="", default_severity="Low", iems=False),
    dict(code="NOI", category="Noise / Nuisance", examples="late-night operations, loud music, karaoke", team="Estate Compliance", vendor="", default_severity="Low", iems=False),
    dict(code="CMN", category="Common Area (Town Council)", examples="corridor lighting, common area cleanliness, lift lobby", team="Town Council Liaison", vendor="", default_severity="Low", iems=False),
    dict(code="OTH", category="General Enquiry / Non-defect", examples="rental enquiry, compliment, tender enquiry", team="Customer Relations", vendor="", default_severity="Low", iems=False),
]
TAX_BY_CODE = {t["code"]: t for t in DEFECT_TAXONOMY}
SEVERITY_SLA_DAYS = {"Critical": 1, "High": 3, "Medium": 7, "Low": 14}

CHECKLISTS = {
    "NEW_TENANCY": [
        ("LOA", "Signed acceptance of Letter of Offer", True), ("BIZ", "Business profile (company registry extract, < 3 months old)", True),
        ("NRIC", "Identity document of sole proprietor / director (masked copy)", True), ("DEP", "Proof of security deposit payment (3 months' rent)", True),
        ("GIRO", "GIRO authorisation form for monthly rent", True), ("INS", "Public liability insurance certificate (min S$1,000,000)", True),
        ("LIC", "Trade licence or licence application (food, healthcare, childcare trades)", False)],
    "RENEWAL": [
        ("REN", "Tenancy renewal application form", True), ("BIZ", "Business profile (company registry extract, < 3 months old)", True),
        ("INS", "Valid public liability insurance certificate covering the new term", True), ("GIRO", "GIRO authorisation form (only if bank account changed)", False)],
    "ASSIGNMENT": [
        ("ASG", "Application for assignment of tenancy", True), ("BIZ", "Business profile of assignor", True), ("BIZ2", "Business profile of assignee", True),
        ("NRIC", "Identity document of assignee director (masked copy)", True), ("FEE", "Proof of assignment fee payment", True), ("INS", "Assignee public liability insurance certificate", True)],
    "CHANGE_OF_TRADE": [
        ("COT", "Application for change / addition of trade", True), ("PLAN", "Business plan for proposed trade", True),
        ("LAYOUT", "Proposed floor layout plan", True), ("LIC", "Trade licence application or approval (if regulated trade)", False)],
    "ALTERATION": [
        ("AA", "Application for alteration & addition (A&A) works", True), ("DWG", "Layout and elevation drawings", True),
        ("CON", "Contractor's registration certificate", True), ("PE", "Professional Engineer endorsement (structural works only)", False),
        ("MS", "Method statement and work schedule", True), ("INS", "Contractor's all-risk insurance certificate", True)],
}
APP_TYPE_LABEL = {"NEW_TENANCY": "New Tenancy", "RENEWAL": "Tenancy Renewal", "ASSIGNMENT": "Assignment of Tenancy",
                  "CHANGE_OF_TRADE": "Change of Trade", "ALTERATION": "Alteration & Addition Works"}

# Planned conflicts: (id, topic, sources, values, resolution)
CONFLICTS = [
    dict(id="C1", topic="Letter of demand trigger for rental arrears",
         a="PLG-POL-003 Rental Arrears Management Policy v2.0 (effective 2026-04-01): LOD at 60 days overdue",
         b="PLG-SOP-014 Rental Arrears Recovery SOP v1.2 (2025-06-02): LOD at 45 days overdue",
         resolution="Policy v2.0 prevails; SOP v1.2 was not updated after the policy revision (flagged in Internal Audit finding IA-04)."),
    dict(id="C2", topic="Security deposit amount",
         a="PLG-POL-002 Tenancy Renewal & Security Deposit Policy v2.1: 3 months' rent",
         b="Tenant FAQ (Commercial Tenants) 2025 edition, Q7: 2 months' rent",
         resolution="Policy prevails (3 months). FAQ is outdated."),
    dict(id="C3", topic="Lead time to apply for tenancy renewal",
         a="PLG-POL-002 v2.1 cl. 4.2: at least 6 months before expiry",
         b="onboarding_guide_new_officers.md and Siti's email reply to Wellcare Family Clinic: 3 months",
         resolution="Policy prevails (6 months)."),
    dict(id="C4", topic="Number of vacant units as at 31 Aug 2026",
         a="Vacancy_Report_Aug2026.xlsx and Monthly Operations Report Aug 2026: 47 vacant units",
         b="PLG_QBR_Q3_2026.pptx slide 4: 52 vacant units",
         resolution="Both are arithmetically correct; the QBR uses the pre-April definition that counts units under tender (5). Current definition (minutes of 15 Apr 2026, glossary) excludes them, so 47."),
    dict(id="C5", topic="Permitted display area beyond shopfront",
         a="PLG-POL-001 Trade Mix & Usage Policy v3.0 cl. 7.3: 0.6 m",
         b="PLG Circular 07/2026 (effective 2026-08-01): 1.0 m (NCs only, max 50% of frontage)",
         resolution="Circular 07/2026 supersedes cl. 7.3 for NC units from 1 Aug 2026; 0.6 m still applies to void-deck shops."),
    dict(id="C6", topic="Monthly rent of Heng Ann Confectionery tenancy",
         a="Scanned tenancy agreement (PDF): S$4,580 per month",
         b="PLG Records database tenancies table and rent roll: S$4,850 per month",
         resolution="Data-entry transposition in PLG Records; agreement is the legal source. Invoices have been over-billed by S$270/month."),
]


def _wchoice(rng, d):
    keys = list(d.keys())
    return rng.choices(keys, weights=[d[k][0] for k in keys])[0]


def add_months(d, n):
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    import calendar
    return D(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def month_starts(a=START, b=END):
    d = D(a.year, a.month, 1)
    while d <= b:
        yield d
        d = add_months(d, 1)


def rand_date(rng, a, b):
    return a + dt.timedelta(days=rng.randint(0, (b - a).days))


def person_name(rng):
    r = rng.random()
    if r < 0.6:
        return f"{rng.choice(SURNAMES_C)} {rng.choice(GIVEN_C)}"
    if r < 0.8:
        return rng.choice(NAMES_M)
    return rng.choice(NAMES_I)


def fake_brn(rng, year):
    return f"{year}{rng.randint(10000, 99999)}{rng.choice('ABCDEGHKMNRZ')}"


def build(seed=42):
    rng = random.Random(seed)
    M = dict(seed=seed, start=START, end=END, staff=STAFF, towns=TOWNS, taxonomy=DEFECT_TAXONOMY, checklists=CHECKLISTS,
             conflicts=CONFLICTS)

    # ---------------- blocks, NCs and units ----------------
    blocks, units = [], []
    ncs = []
    for t in TOWNS:
        for i, nc in enumerate(t["ncs"]):
            ncs.append(dict(nc_id=f"NC-{t['code']}-{i+1}", town=t["code"], name=nc))
        lo, hi = t["blk_range"]
        scripted = [b for (tc, b) in SCRIPTED_BLOCKS if tc == t["code"]]
        pool = [b for b in range(lo, hi + 1) if b not in scripted]
        nums = sorted(scripted + rng.sample(pool, 25 - len(scripted)))
        for b in nums:
            if (t["code"], b) in SCRIPTED_BLOCKS:
                nci, sti = SCRIPTED_BLOCKS[(t["code"], b)]
            else:
                nci, sti = rng.randrange(3), rng.randrange(3)
            blocks.append(dict(block_id=f"{t['code']}{b}", town=t["code"], blk=b, street=t["streets"][sti],
                               nc_id=f"NC-{t['code']}-{nci+1}", postal=f"{t['postal']}{b:04d}", year_built=rng.randint(1978, 2012)))
    # units per block; one eating house per NC on the first block of that NC
    eh_done = set()
    for blk in blocks:
        n = rng.randint(6, 14)
        if (blk["town"], blk["blk"]) in SCRIPTED_BLOCKS:
            n = max(n, 34)  # scripted blocks need e.g. #01-32
        for k in range(1, n + 1):
            sid = f"U-{blk['block_id']}-01-{k:02d}"
            if sid in SCRIPTED_UNITS:
                utype = SCRIPTED_UNITS[sid]
                eh_done.add(blk["nc_id"]) if utype == "Eating House" else None
            elif blk["nc_id"] not in eh_done and k == 1 and (blk["town"], blk["blk"]) not in SCRIPTED_BLOCKS:
                utype = "Eating House"
                eh_done.add(blk["nc_id"])
            else:
                utype = _wchoice(rng, {u: v for u, v in UNIT_TYPES.items() if v[0] > 0})
            floor = 2 if utype == "Office" and rng.random() < 0.7 and sid not in SCRIPTED_UNITS else 1
            unit_no = f"#{floor:02d}-{k:02d}"
            amin, amax = UNIT_TYPES[utype][1]
            area = round(rng.uniform(amin, amax), 1)
            units.append(dict(unit_id=f"U-{blk['block_id']}-{floor:02d}-{k:02d}", block_id=blk["block_id"], town=blk["town"],
                              blk=blk["blk"], street=blk["street"], unit_no=unit_no, postal=blk["postal"], nc_id=blk["nc_id"],
                              unit_type=utype, floor_area_sqm=area, status=None))
    unit_by_id = {u["unit_id"]: u for u in units}

    # ---------------- unit status: exactly 47 vacant, 5 under tender, 6 not lettable ----------------
    sc_units = set(SCRIPTED_UNITS)
    free = [u for u in units if u["unit_id"] not in sc_units and u["unit_type"] != "Eating House"]
    rng.shuffle(free)
    for u in free[:47]:
        u["status"] = "Vacant"
        u["vacant_since"] = rand_date(rng, D(2025, 3, 1), D(2026, 8, 20))
    for u in free[47:52]:
        u["status"] = "Under Tender"
        u["vacant_since"] = rand_date(rng, D(2026, 2, 1), D(2026, 6, 30))
    for u in free[52:58]:
        u["status"] = "Not Lettable"
        u["vacant_since"] = rand_date(rng, D(2024, 6, 1), D(2025, 12, 31))
    for u in units:
        if u["status"] is None:
            u["status"] = "Tenanted"
    # Prima Dental's unit: tenanted from 1 Oct 2026 (offer accepted); counts as Tenanted (committed) at 30 Sep? keep Vacant-committed

    # ---------------- tenants and tenancies ----------------
    tenants, tenancies = [], []
    used_names = set()
    tid = [10000]
    taid = Counter()

    def new_tenant(trade, name=None, town=None):
        tid[0] += rng.randint(1, 3)
        if name is None:
            for _ in range(50):
                nm = f"{rng.choice(NAME_PREFIX)} {rng.choice(TRADE_SUFFIX[trade])}"
                if rng.random() < 0.45:
                    nm += " Pte Ltd"
                if nm not in used_names:
                    break
            name = nm
        used_names.add(name)
        yr = rng.randint(1995, 2025)
        contact = person_name(rng)
        slug = "".join(ch for ch in name.lower().replace("pte ltd", "") if ch.isalnum())[:18]
        t = dict(tenant_id=f"T-{tid[0]}", name=name, brn=fake_brn(rng, yr), entity_type="Company" if "Pte Ltd" in name else "Sole Proprietorship",
                 contact_person=contact, email=f"admin@{slug}.example.com", phone=f"+65 9{rng.randint(100, 999)} {rng.randint(1000, 9999)}",
                 trade_primary=trade, registered_since=D(yr, rng.randint(1, 12), rng.randint(1, 28)), payment_profile="good")
        tenants.append(t)
        return t

    def new_tenancy(unit, tenant, trade, start, rent, status):
        taid[start.year] += rng.randint(1, 2)
        end = add_months(start, 36) - dt.timedelta(days=1)
        ta = dict(tenancy_id=f"TA-{start.year}-{taid[start.year]:05d}", unit_id=unit["unit_id"], tenant_id=tenant["tenant_id"], trade=trade,
                  start_date=start, end_date=end, monthly_rent=rent, security_deposit=rent * 3, term_months=36, status=status,
                  rent_basis="Market (tender)" if rng.random() < 0.6 else "Market (renewal valuation)")
        tenancies.append(ta)
        return ta

    def rent_for(u, mult=1.0):
        t = TOWN_BY_CODE[u["town"]]
        base = u["floor_area_sqm"] * t["rate"] * UNIT_TYPES[u["unit_type"]][2] * rng.uniform(0.85, 1.2) * mult
        return int(round(max(base, 900) / 10.0) * 10)

    scripted_tenants = {
        "U-BV214-01-32": ("Golden Leaf Minimart Pte Ltd", "Minimart", D(2024, 9, 1), 5200),
        "U-CD118-01-01": ("Sin Hock Eating House", "Coffeeshop", D(2024, 4, 1), 11800),
        "U-KR305-01-12": ("Wellcare Family Clinic", "GP Clinic", D(2024, 1, 1), 6350),
        "U-PI627-01-08": ("Mutiara Provision Shop", "Provision Shop", D(2024, 10, 1), 3900),
        "U-RH455-01-20": ("Lucky Star Hair Studio", "Hair Salon", D(2025, 2, 1), 3450),
        "U-ST512-01-05": ("Heng Ann Confectionery", "Bakery & Confectionery", D(2024, 7, 1), 4850),
        "U-BV214-01-07": ("Kim Hiap Trading", "Hardware", D(2024, 3, 1), 4100),
    }
    # pre-order: sort units so tenancy numbering is chronological-ish
    plan = []
    for u in units:
        if u["status"] != "Tenanted":
            continue
        if u["unit_id"] in scripted_tenants:
            nm, trade, start, rent = scripted_tenants[u["unit_id"]]
            plan.append((start, u, trade, nm, rent))
            continue
        allowed = {k: v for k, v in TRADES.items() if u["unit_type"] in v[1] and v[0] > 0}
        trade = "Coffeeshop" if u["unit_type"] == "Eating House" else _wchoice(rng, allowed)
        start = D(rng.randint(2023, 2026), rng.randint(1, 12), 1)
        while not (D(2023, 10, 1) <= start <= D(2026, 9, 1)):
            start = D(rng.randint(2023, 2026), rng.randint(1, 12), 1)
        plan.append((start, u, trade, None, None))
    # previous tenancies (history) for units whose current tenancy started within the corpus window or recently
    plan.sort(key=lambda x: (x[0], x[1]["unit_id"]))
    chain_tenant = None
    for start, u, trade, nm, rent in plan:
        if nm is None and trade == "Minimart" and rng.random() < 0.25:
            if chain_tenant is None:
                chain_tenant = new_tenant("Minimart", name="PrimeValue Mart Pte Ltd")
            ten = chain_tenant
        else:
            ten = new_tenant(trade, name=nm)
        if rent is None:
            rent = rent_for(u)
        # history: earlier tenancy on the same unit
        if start >= D(2024, 1, 1) and rng.random() < 0.55:
            pstart = add_months(start, -36)
            if rng.random() < 0.6 and nm is None:
                prev_t, pstatus = ten, "Renewed"
            else:
                prev_t, pstatus = new_tenant(trade), rng.choice(["Expired", "Terminated"])
            prev = new_tenancy(u, prev_t, trade, pstart, int(round(rent * rng.uniform(0.88, 0.97) / 10) * 10), pstatus)
            if pstatus == "Terminated":
                prev["end_date"] = add_months(start, -rng.randint(1, 8)) - dt.timedelta(days=1)
        ta = new_tenancy(u, ten, trade, start, rent, "Active")
        u["current_tenancy"] = ta["tenancy_id"]
    # Prima Dental: new tenancy starting 1 Oct 2026 on a vacant-committed unit
    pd_unit = unit_by_id["U-ST512-01-33"]
    pd_ten = new_tenant("Dental Clinic", name="Prima Dental Care Pte Ltd")
    taid[2026] += 1
    pd_ta = dict(tenancy_id=f"TA-2026-{taid[2026]:05d}", unit_id=pd_unit["unit_id"], tenant_id=pd_ten["tenant_id"], trade="Dental Clinic",
                 start_date=D(2026, 10, 1), end_date=D(2029, 9, 30), monthly_rent=4650, security_deposit=4650 * 3, term_months=36,
                 status="Pending Commencement", rent_basis="Market (tender)")
    tenancies.append(pd_ta)
    pd_unit["status"] = "Tenanted"  # committed tenancy; was Vacant till Aug, tender awarded in July
    pd_unit["current_tenancy"] = pd_ta["tenancy_id"]
    tenancy_by_id = {t["tenancy_id"]: t for t in tenancies}
    tenant_by_id = {t["tenant_id"]: t for t in tenants}
    # Trade-mix narrative: Mutiara's NC has exactly 2 active Bubble Tea outlets (and Mutiara wants to be the 3rd)
    mut_nc = unit_by_id["U-PI627-01-08"]["nc_id"]
    act_nc = [t for t in tenancies if t["status"] == "Active" and unit_by_id[t["unit_id"]]["nc_id"] == mut_nc and t["unit_id"] not in SCRIPTED_UNITS]
    bt = [t for t in act_nc if t["trade"] == "Bubble Tea"]
    cands = [t for t in act_nc if t["trade"] not in ("Bubble Tea", "Coffeeshop") and unit_by_id[t["unit_id"]]["unit_type"] in ("Shop", "Kiosk")
             and t["tenant_id"] != (chain_tenant or {}).get("tenant_id")]
    while len(bt) > 2:
        t = bt.pop()
        t["trade"] = "Snack Kiosk" if unit_by_id[t["unit_id"]]["unit_type"] == "Kiosk" else "Bakery & Confectionery"
        tenant_by_id[t["tenant_id"]]["trade_primary"] = t["trade"]
    for nm in ["Boba Bliss Tea House", "Cahaya Bubble Tea"][:2 - len(bt)]:
        t = cands.pop(0)
        t["trade"] = "Bubble Tea"
        tenant_by_id[t["tenant_id"]].update(name=nm, trade_primary="Bubble Tea")
        bt.append(t)
    active = [t for t in tenancies if t["status"] == "Active"]

    # payment profiles
    for t in tenants:
        r = rng.random()
        t["payment_profile"] = "good" if r < 0.86 else "late" if r < 0.955 else "arrears" if r < 0.985 else "chronic"
    key = {}
    for uid, (nm, *_rest) in scripted_tenants.items():
        ta = tenancy_by_id[unit_by_id[uid]["current_tenancy"]]
        key[nm] = dict(unit=uid, tenancy=ta["tenancy_id"], tenant=ta["tenant_id"])
        tenant_by_id[ta["tenant_id"]]["payment_profile"] = "good"
    key["Prima Dental Care Pte Ltd"] = dict(unit=pd_unit["unit_id"], tenancy=pd_ta["tenancy_id"], tenant=pd_ten["tenant_id"])
    gl_tenant = tenant_by_id[key["Golden Leaf Minimart Pte Ltd"]["tenant"]]
    gl_tenant["payment_profile"] = "scripted_arrears"
    tenant_by_id[key["Wellcare Family Clinic"]["tenant"]]["contact_person"] = "Dr Lim Kok Leong"
    tenant_by_id[key["Golden Leaf Minimart Pte Ltd"]["tenant"]]["contact_person"] = "Ong Bee Choo"
    tenant_by_id[key["Mutiara Provision Shop"]["tenant"]]["contact_person"] = "Rahim bin Osman"
    tenant_by_id[key["Lucky Star Hair Studio"]["tenant"]]["contact_person"] = "Chan Siew Lan"
    tenant_by_id[key["Prima Dental Care Pte Ltd"]["tenant"]]["contact_person"] = "Dr Kavitha Raj"
    tenant_by_id[key["Sin Hock Eating House"]["tenant"]]["contact_person"] = "Teo Ah Hock"
    tenant_by_id[key["Heng Ann Confectionery"]["tenant"]]["contact_person"] = "Lee Mei Fen"
    for nm in ["Golden Leaf Minimart Pte Ltd", "Wellcare Family Clinic", "Mutiara Provision Shop", "Lucky Star Hair Studio", "Prima Dental Care Pte Ltd",
               "Sin Hock Eating House", "Heng Ann Confectionery"]:
        t = tenant_by_id[key[nm]["tenant"]]
        t["email"] = {"Golden Leaf Minimart Pte Ltd": "accounts@goldenleafmart.example.com", "Wellcare Family Clinic": "admin@wellcareclinic.example.com",
                      "Mutiara Provision Shop": "mutiara.provision@example.com", "Lucky Star Hair Studio": "luckystarhair@example.com",
                      "Prima Dental Care Pte Ltd": "hello@primadental.example.com", "Sin Hock Eating House": "sinhock.eatinghouse@example.com",
                      "Heng Ann Confectionery": "hengann.bakery@example.com"}[nm]

    # ---------------- rent invoices and payments ----------------
    invoices, payments = [], []
    inv_seq, pay_seq = Counter(), [0]
    gl_ta = key["Golden Leaf Minimart Pte Ltd"]["tenancy"]
    for ms in month_starts():
        for ta in tenancies:
            if not (ta["start_date"] <= ms <= ta["end_date"]) or ta["status"] == "Pending Commencement":
                continue
            yymm = ms.strftime("%y%m")
            inv_seq[yymm] += 1
            amt = ta["monthly_rent"]
            inv = dict(invoice_id=f"INV-{yymm}-{inv_seq[yymm]:06d}", tenancy_id=ta["tenancy_id"], tenant_id=ta["tenant_id"],
                       period=ms.strftime("%Y-%m"), invoice_date=ms - dt.timedelta(days=10), due_date=ms, rent_amount=amt,
                       gst_amount=round(amt * GST, 2), total_amount=round(amt * (1 + GST), 2), status="Unpaid")
            invoices.append(inv)
            prof = tenant_by_id[ta["tenant_id"]]["payment_profile"]
            if ta["tenancy_id"] == gl_ta:
                lag = rng.randint(0, 6) if ms < D(2026, 6, 1) else None
            elif prof == "good":
                lag = rng.choice([0, 0, 0, 1, 2, 3, 5, 7])
            elif prof == "late":
                lag = rng.randint(10, 45)
            elif prof == "chronic":
                lag = rng.randint(45, 95)
            else:  # arrears: stop paying from a random month
                stop = getattr(ta, "_stop", None) or ta.setdefault("_stop", rand_date(rng, D(2026, 2, 1), D(2026, 8, 1)))
                lag = rng.randint(5, 30) if ms < stop else None
            if lag is not None:
                pd_ = ms + dt.timedelta(days=lag)
                if pd_ <= ASOF:
                    pay_seq[0] += 1
                    payments.append(dict(payment_id=f"PAY-{pay_seq[0]:08d}", invoice_id=inv["invoice_id"], tenancy_id=ta["tenancy_id"],
                                         paid_date=pd_, amount=inv["total_amount"], method="GIRO" if lag <= 3 else rng.choice(["PayNow", "Cheque", "Bank Transfer"])))
                    inv["status"] = "Paid"
                    inv["paid_date"] = pd_
    for ta in tenancies:
        ta.pop("_stop", None)

    # arrears snapshot
    arrears = defaultdict(lambda: dict(amount=0.0, oldest_due=None, invoices=0))
    for inv in invoices:
        if inv["status"] == "Unpaid" and inv["due_date"] <= ASOF:
            a = arrears[inv["tenancy_id"]]
            a["amount"] += inv["total_amount"]
            a["invoices"] += 1
            if a["oldest_due"] is None or inv["due_date"] < a["oldest_due"]:
                a["oldest_due"] = inv["due_date"]
    arrears_rows = []
    for tid_, a in arrears.items():
        ta = tenancy_by_id[tid_]
        days = (ASOF - a["oldest_due"]).days
        arrears_rows.append(dict(tenancy_id=tid_, tenant_id=ta["tenant_id"], unit_id=ta["unit_id"], amount=round(a["amount"], 2),
                                 unpaid_invoices=a["invoices"], oldest_due=a["oldest_due"], days_overdue=days,
                                 months_of_rent=round(a["amount"] / (ta["monthly_rent"] * (1 + GST)), 2),
                                 bucket="0-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else ">90"))
    arrears_rows.sort(key=lambda r: -r["amount"])

    # ---------------- inspections ----------------
    inspections = []
    iseq = Counter()
    findings = ["NONE"] * 70 + ["DISPLAY_ENCROACH"] * 10 + ["HYGIENE"] * 6 + ["UNAPPROVED_AA"] * 4 + ["UNAUTH_TRADE"] * 3 + ["FIRE_SAFETY"] * 3 + ["UNAUTH_SUBLET"] * 2 + ["STRUCTURAL_DEFECT"] * 2
    ins_plan = []
    for ta in active:
        for _ in range(rng.choice([1, 1, 2, 2, 2])):
            ins_plan.append((rand_date(rng, START, END), ta))
    ins_plan.sort(key=lambda x: x[0])
    lucky = key["Lucky Star Hair Studio"]["tenancy"]
    for d, ta in ins_plan:
        iseq[d.year] += 1
        u = unit_by_id[ta["unit_id"]]
        officer = "S06" if rng.random() < 0.6 else TOWN_BY_CODE[u["town"]]["em"]
        f = rng.choice(findings)
        outcome = "Compliant" if f == "NONE" else ("Major Breach" if f in ("UNAUTH_SUBLET", "UNAUTH_TRADE", "FIRE_SAFETY", "STRUCTURAL_DEFECT") else "Minor Breach")
        due = d + dt.timedelta(days=14 if outcome == "Minor Breach" else 7) if f != "NONE" else None
        closed = None
        if due and rng.random() < 0.8 and due + dt.timedelta(days=10) <= ASOF:
            closed = due + dt.timedelta(days=rng.randint(-5, 10))
        inspections.append(dict(inspection_id=f"INSP-{d.year}-{iseq[d.year]:04d}", unit_id=ta["unit_id"], tenancy_id=ta["tenancy_id"],
                                inspection_date=d, officer_id=officer, inspection_type=rng.choice(["Routine"] * 5 + ["Complaint-driven", "Follow-up"]),
                                finding_code=f, outcome=outcome, follow_up_due=due, closed_date=closed, remarks=""))
    # scripted: Lucky Star subletting found 2026-06-16
    target = [i for i in inspections if i["inspection_date"] >= D(2026, 6, 16)][0]
    target.update(unit_id=key["Lucky Star Hair Studio"]["unit"], tenancy_id=lucky, inspection_date=D(2026, 6, 16), officer_id="S06",
                  inspection_type="Complaint-driven", finding_code="UNAUTH_SUBLET", outcome="Major Breach", follow_up_due=D(2026, 6, 30), closed_date=None,
                  remarks="Rear 1/3 of unit partitioned and operated as nail salon 'Glam Nails by Vivian'; separate cash register; no approval on record.")
    key["Lucky Star Hair Studio"]["inspection"] = target["inspection_id"]
    remarks_map = {"DISPLAY_ENCROACH": "Goods displayed ~{x} m beyond shopfront line; obstructs walkway.", "HYGIENE": "Refuse bags left at rear service corridor; grease stains.",
                   "UNAPPROVED_AA": "Partition wall / signage installed without A&A approval.", "UNAUTH_TRADE": "Selling items outside approved trade ({t}).",
                   "FIRE_SAFETY": "Rear exit partially blocked by stock; extinguisher service tag expired.", "STRUCTURAL_DEFECT": "Spalling concrete observed at ceiling near entrance.",
                   "UNAUTH_SUBLET": "Part of unit appears to be operated by a third party; tenant unable to show approval.", "NONE": "No issues observed."}
    for i in inspections:
        if not i["remarks"]:
            i["remarks"] = remarks_map[i["finding_code"]].format(x=round(rng.uniform(0.8, 2.5), 1), t=tenancy_by_id[i["tenancy_id"]]["trade"])

    # ---------------- public feedback and i-EMS tickets ----------------
    feedback, tickets = [], []
    fseq, tseq = Counter(), Counter()
    fb_dates = sorted(rand_date(rng, START, END) for _ in range(1180))
    cat_w = {"STR": 7, "SEP": 14, "PLB": 12, "ELE": 9, "FIR": 3, "PST": 10, "HYG": 12, "ENC": 11, "NOI": 7, "CMN": 8, "OTH": 7}
    tenanted_units = [u for u in units if u["status"] == "Tenanted" and u.get("current_tenancy")]
    for d in fb_dates:
        fseq[d.year] += 1
        code = rng.choices(list(cat_w), weights=list(cat_w.values()))[0]
        u = rng.choice(tenanted_units)
        ta = tenancy_by_id[u["current_tenancy"]]
        tx = TAX_BY_CODE[code]
        sev = tx["default_severity"]
        if rng.random() < 0.2:
            sev = rng.choice(["Low", "Medium", "High"])
        ambiguous = rng.random() < 0.08
        text = feedback_text(rng, code, u, tenant_by_id[ta["tenant_id"]]["name"], ambiguous)
        fb = dict(feedback_id=f"FB-{d.year}-{fseq[d.year]:05d}", received_date=d, channel=rng.choice(["Hotline", "Email", "CityFix App", "CityFix App", "Walk-in", "MP Letter"]),
                  unit_id=u["unit_id"], block_id=u["block_id"], description=text, category_code=code, category=tx["category"], severity=sev,
                  assigned_team=tx["team"], label_confidence="ambiguous" if ambiguous else "clear", status="Closed", iems_ticket_id=None,
                  reply_due=d + dt.timedelta(days=7), replied_date=None, officer_id="S11" if rng.random() < 0.7 else "S03")
        if d + dt.timedelta(days=7) <= ASOF:
            fb["replied_date"] = d + dt.timedelta(days=rng.choice([1, 2, 3, 4, 5, 6, 8, 12]))
        else:
            fb["status"] = rng.choice(["Open", "In Progress"])
        if tx["iems"] and not (ambiguous and rng.random() < 0.5):
            created = d + dt.timedelta(days=rng.choice([0, 0, 1, 1, 2]))
            ym = created.strftime("%y%m")
            tseq[ym] += 1
            sla = SEVERITY_SLA_DAYS[sev]
            done = created + dt.timedelta(days=max(0, int(rng.gauss(sla * 0.9, sla * 0.6))))
            st = "Closed" if done <= ASOF - dt.timedelta(days=3) else rng.choice(["Assigned", "In Progress"])
            misrouted = rng.random() < 0.04
            tk = dict(ticket_id=f"IEMS-{ym}-{tseq[ym]:04d}", feedback_id=fb["feedback_id"], created_date=created, unit_id=u["unit_id"],
                      category_code=code, team=tx["team"] if not misrouted else rng.choice(["M&E", "Civil & Structural"]), vendor=tx["vendor"], priority=sev,
                      sla_days=sla, status="Rejected - Misrouted" if misrouted else st, completed_date=done if st == "Closed" and not misrouted else None,
                      sla_met=(done - created).days <= sla if st == "Closed" and not misrouted else None, raised_by="S10")
            tickets.append(tk)
            fb["iems_ticket_id"] = tk["ticket_id"]
        feedback.append(fb)

    def pick_fb(code, near, uid):
        cand = min((f for f in feedback if f["category_code"] == code and f["iems_ticket_id"]), key=lambda f: abs((f["received_date"] - near).days))
        cand["unit_id"] = uid
        cand["block_id"] = unit_by_id[uid]["block_id"]
        t = next(t for t in tickets if t["ticket_id"] == cand["iems_ticket_id"])
        t["unit_id"] = uid
        return cand, t
    fb_seep, tk_seep = pick_fb("SEP", D(2026, 8, 11), "U-BV214-01-07")
    fb_seep.update(received_date=D(2026, 8, 11), channel="Email", severity="High",
                   description="Water dripping from ceiling of Kim Hiap Trading at Blk 214 Bayshore Vale St 21 #01-07 since last night's rain. "
                                "Stain spreading to next unit, shopkeeper put pails. Pls send someone urgently, stock getting wet.")
    tk_seep.update(created_date=D(2026, 8, 12), priority="High", sla_days=3, status="Closed", completed_date=D(2026, 8, 14), sla_met=True,
                   vendor="Kemas Building Works Pte Ltd", team="Civil & Structural")
    fb_fire, tk_fire = pick_fb("FIR", D(2026, 5, 18), "U-CD118-01-01")
    fb_fire.update(received_date=D(2026, 5, 18), channel="Hotline", severity="Critical",
                   description="Fire at Sin Hock Eating House Blk 118 Cendana Road #01-01 kitchen area around 6.40am. CDA attended. Smoke damage to ceiling and "
                                "exhaust duct; drinks stall closed. Need structural check before reopening.")
    tk_fire.update(created_date=D(2026, 5, 18), priority="Critical", sla_days=1, status="Closed", completed_date=D(2026, 5, 19), sla_met=True,
                   team="Estate Compliance", vendor="Kemas Building Works Pte Ltd")
    key["seepage"] = dict(feedback=fb_seep["feedback_id"], ticket=tk_seep["ticket_id"])
    key["fire"] = dict(feedback=fb_fire["feedback_id"], ticket=tk_fire["ticket_id"])
    feedback.sort(key=lambda f: f["feedback_id"])

    # ---------------- applications and submitted documents ----------------
    applications, app_docs = [], []
    aseq = Counter()
    app_dates = sorted(rand_date(rng, START, END) for _ in range(410))
    type_w = {"NEW_TENANCY": 22, "RENEWAL": 34, "ASSIGNMENT": 8, "CHANGE_OF_TRADE": 14, "ALTERATION": 22}
    for d in app_dates:
        aseq[d.year] += 1
        atype = rng.choices(list(type_w), weights=list(type_w.values()))[0]
        ta = rng.choice(active)
        age = (ASOF - d).days
        if age > 60:
            status = rng.choices(["Approved", "Rejected", "Withdrawn"], weights=[80, 12, 8])[0]
        elif age > 20:
            status = rng.choices(["Approved", "Under Review", "Pending Documents", "Rejected"], weights=[50, 25, 20, 5])[0]
        else:
            status = rng.choices(["Under Review", "Pending Documents"], weights=[50, 50])[0]
        applications.append(dict(application_id=f"APP-{d.year}-{aseq[d.year]:04d}", app_type=atype, tenancy_id=ta["tenancy_id"] if atype != "NEW_TENANCY" else None,
                                 tenant_id=ta["tenant_id"], unit_id=ta["unit_id"], submitted_date=d, status=status,
                                 officer_id=rng.choice(["S05", "S05", "S03", "S04", "S12"]), decision_date=d + dt.timedelta(days=rng.randint(10, 40)) if status in ("Approved", "Rejected") else None,
                                 proposed_trade=None, remarks=""))
    for a in applications:
        if a["app_type"] == "CHANGE_OF_TRADE":
            a["proposed_trade"] = rng.choice([t for t in TRADES if t != "Coffeeshop"])

    def claim_app(near, atype, tenancy_id, tenant_id, unit_id, status, **kw):
        cand = min((a for a in applications if a.get("_claimed") is None and a["status"] in ("Under Review", "Pending Documents")),
                   key=lambda a: abs((a["submitted_date"] - near).days))
        cand.update(app_type=atype, tenancy_id=tenancy_id, tenant_id=tenant_id, unit_id=unit_id, status=status, submitted_date=near, _claimed=True, **kw)
        return cand
    k = key
    a_mut = claim_app(D(2026, 8, 24), "CHANGE_OF_TRADE", k["Mutiara Provision Shop"]["tenancy"], k["Mutiara Provision Shop"]["tenant"], k["Mutiara Provision Shop"]["unit"],
                      "Pending Documents", proposed_trade="Bubble Tea", officer_id="S05", remarks="Convert provision shop to bubble tea outlet 'Boba Bliss'. 2 bubble tea outlets already in NC.")
    a_well = claim_app(D(2026, 9, 21), "RENEWAL", k["Wellcare Family Clinic"]["tenancy"], k["Wellcare Family Clinic"]["tenant"], k["Wellcare Family Clinic"]["unit"],
                       "Under Review", officer_id="S05", remarks="Late renewal: tenancy expires 2026-12-31; policy requires 6 months' notice.")
    a_prima = claim_app(D(2026, 8, 3), "NEW_TENANCY", None, k["Prima Dental Care Pte Ltd"]["tenant"], k["Prima Dental Care Pte Ltd"]["unit"],
                        "Pending Documents", officer_id="S05", remarks="Tender award 2026-07-20; commencement 2026-10-01.")
    k["Mutiara Provision Shop"]["application"] = a_mut["application_id"]
    k["Wellcare Family Clinic"]["application"] = a_well["application_id"]
    k["Prima Dental Care Pte Ltd"]["application"] = a_prima["application_id"]
    # submission bundles: 20 pending/under-review applications get real files
    pending = [a for a in applications if a["status"] in ("Under Review", "Pending Documents")]
    others = [a for a in pending if not a.get("_claimed")]
    rng.shuffle(others)
    bundle_apps = [a_mut, a_well, a_prima] + others[:17]
    issue_cycle = ["complete", "missing1", "missing2", "missing1", "expired", "complete", "wrong_unit", "missing1", "illegible", "complete",
                   "missing2", "missing1", "complete", "missing1", "expired", "complete", "missing1", "wrong_unit", "missing2", "complete"]
    bundles = []
    for idx, a in enumerate(applications):
        cl = CHECKLISTS[a["app_type"]]
        for code, label, mandatory in cl:
            submitted = True if a["status"] in ("Approved",) else (rng.random() > 0.12)
            if not mandatory and rng.random() < 0.5:
                submitted = False
            a_doc = dict(application_id=a["application_id"], doc_code=code, doc_label=label, mandatory=mandatory, submitted=submitted,
                         received_date=a["submitted_date"] if submitted else None, verified=None)
            app_docs.append(a_doc)
    for bi, a in enumerate(bundle_apps):
        issue = issue_cycle[bi]
        if a is a_mut:
            issue = "missing1"
        if a is a_well:
            issue = "expired"
        if a is a_prima:
            issue = "missing2"
        cl = [c for c in CHECKLISTS[a["app_type"]] if c[2] or rng.random() < 0.5]
        mand = [c for c in cl if c[2]]
        missing = []
        if issue == "missing1":
            missing = [rng.choice(mand[1:])[0]]
        elif issue == "missing2":
            missing = [c[0] for c in rng.sample(mand[1:], 2)]
        if a is a_mut:
            missing = ["LAYOUT"]
        if a is a_prima:
            missing = ["INS", "GIRO"]
        problem = {}
        present = [c for c in cl if c[0] not in missing]
        if issue == "expired":
            problem = {"INS" if any(c[0] == "INS" for c in present) else "BIZ": "expired"}
        if issue == "wrong_unit":
            problem = {present[0][0]: "wrong_unit"}
        if issue == "illegible":
            problem = {present[-1][0]: "illegible_scan"}
        a["status"] = "Pending Documents" if (missing or problem) else "Under Review"
        for d_ in app_docs:
            if d_["application_id"] == a["application_id"]:
                d_["submitted"] = d_["doc_code"] in [c[0] for c in present]
                d_["received_date"] = a["submitted_date"] if d_["submitted"] else None
                d_["verified"] = False if d_["doc_code"] in problem else (True if d_["submitted"] else None)
        bundles.append(dict(application_id=a["application_id"], app_type=a["app_type"], tenant_id=a["tenant_id"], unit_id=a["unit_id"],
                            submitted_date=a["submitted_date"], expected=[c[0] for c in CHECKLISTS[a["app_type"]] if c[2]],
                            optional=[c[0] for c in CHECKLISTS[a["app_type"]] if not c[2]], present=[c[0] for c in present],
                            missing_mandatory=missing, problems=problem, scenario=issue, files=[]))
    for a in applications:
        a.pop("_claimed", None)

    # ---------------- officer tasks ----------------
    tasks = []
    tkseq = Counter()

    def add_task(created, ttype, title, related, assignee, due, safety=False, revenue=0.0, affected=1, status=None):
        tkseq[created.year] += 1
        if status is None:
            status = "Done" if due < ASOF - dt.timedelta(days=20) and rng.random() < 0.9 else ("Overdue" if due < ASOF else rng.choice(["Open", "Open", "In Progress"]))
        tasks.append(dict(task_id=f"TSK-{created.year}-{tkseq[created.year]:04d}", task_type=ttype, title=title, related_id=related, assignee_id=assignee,
                          created_date=created, due_date=due, status=status, safety_flag=safety, revenue_at_risk=round(revenue, 2),
                          tenants_affected=affected))
    task_events = []
    for ta in active:
        if START + dt.timedelta(days=180) <= ta["end_date"] <= ASOF + dt.timedelta(days=270):
            task_events.append((ta["end_date"] - dt.timedelta(days=180), "Renewal", f"Renewal due: {ta['tenancy_id']} expires {ta['end_date']:%d %b %Y}",
                                ta["tenancy_id"], "S05", ta["end_date"] - dt.timedelta(days=120), False, ta["monthly_rent"] * 12, 1))
    for r in arrears_rows:
        if r["days_overdue"] > 14:
            task_events.append((r["oldest_due"] + dt.timedelta(days=14), "Arrears Follow-up", f"Arrears S${r['amount']:,.2f} ({r['days_overdue']} days) - {r['tenancy_id']}",
                                r["tenancy_id"], "S07", r["oldest_due"] + dt.timedelta(days=60), False, r["amount"], 1))
    for i in inspections:
        if i["follow_up_due"]:
            task_events.append((i["inspection_date"], "Inspection Follow-up", f"Follow up {i['finding_code'].replace('_', ' ').title()} at {i['unit_id']}", i["inspection_id"],
                                i["officer_id"], i["follow_up_due"], i["finding_code"] in ("FIRE_SAFETY", "STRUCTURAL_DEFECT"), 0, 1))
    for t in tickets:
        if t["status"] in ("Assigned", "In Progress"):
            task_events.append((t["created_date"], "Defect Follow-up", f"Chase {t['ticket_id']} ({TAX_BY_CODE[t['category_code']]['category']})", t["ticket_id"], "S10",
                                t["created_date"] + dt.timedelta(days=t["sla_days"]), t["category_code"] in ("STR", "FIR", "ELE"), 0, rng.randint(1, 12)))
    for a in applications:
        if a["status"] in ("Under Review", "Pending Documents"):
            task_events.append((a["submitted_date"], "Application Review", f"Review {APP_TYPE_LABEL[a['app_type']]} {a['application_id']}", a["application_id"],
                                a["officer_id"], a["submitted_date"] + dt.timedelta(days=14), False, 0, 1))
    task_events.sort(key=lambda e: (e[0], e[3]))
    for e in task_events:
        if e[0] < START:
            continue
        add_task(*e)
    for t in tasks:
        if t["related_id"] == key["Lucky Star Hair Studio"]["inspection"]:
            t["status"] = "Overdue"
            key["Lucky Star Hair Studio"]["task"] = t["task_id"]

    # ---------------- letters log ----------------
    letters = []
    lseq = Counter()

    def add_letter(d, tpl, ttype, ref, tenant_id, author):
        lseq[d.year] += 1
        letters.append(dict(letter_id=f"LTR-{d.year}-{lseq[d.year]:05d}", letter_date=d, template_id=tpl, letter_type=ttype, reference_id=ref,
                            tenant_id=tenant_id, author_id=author, channel=rng.choice(["Email", "Email", "Post", "Email + Post"])))
    events = []
    for inv in invoices:
        if inv["status"] == "Unpaid" or (inv.get("paid_date") and (inv["paid_date"] - inv["due_date"]).days > 14):
            lag = ((inv.get("paid_date") or ASOF) - inv["due_date"]).days
            if lag > 14:
                events.append((inv["due_date"] + dt.timedelta(days=15), "TPL-REM-01", "Arrears Reminder (1st)", inv["invoice_id"], inv["tenant_id"], "S07"))
            if lag > 30:
                events.append((inv["due_date"] + dt.timedelta(days=31), "TPL-REM-01", "Arrears Reminder (2nd)", inv["invoice_id"], inv["tenant_id"], "S07"))
            if lag > 60 and inv["due_date"] >= D(2026, 2, 1):
                events.append((inv["due_date"] + dt.timedelta(days=61), "TPL-LOD-01", "Letter of Demand", inv["invoice_id"], inv["tenant_id"], "S09"))
    for f in feedback:
        if f["replied_date"]:
            events.append((f["replied_date"], "TPL-FBK-03", "Feedback Update", f["feedback_id"], None, f["officer_id"]))
    for b in bundles:
        if b["missing_mandatory"] or b["problems"]:
            events.append((b["submitted_date"] + dt.timedelta(days=3), "TPL-DOC-02", "Missing Documents Notice", b["application_id"], b["tenant_id"], "S05"))
    events = [e for e in events if START <= e[0] <= ASOF]
    events.sort(key=lambda e: (e[0], e[3]))
    for e in events:
        add_letter(*e)
    gl_lod = next(l for l in letters if l["letter_type"] == "Letter of Demand" and l["tenant_id"] == key["Golden Leaf Minimart Pte Ltd"]["tenant"])
    key["Golden Leaf Minimart Pte Ltd"]["lod"] = gl_lod["letter_id"]
    key["Golden Leaf Minimart Pte Ltd"]["lod_date"] = gl_lod["letter_date"]

    key["bubble_tea_nc"] = dict(nc_id=mut_nc, tenancies=[t["tenancy_id"] for t in bt])
    M.update(ncs=ncs, blocks=blocks, units=units, tenants=tenants, tenancies=tenancies, invoices=invoices, payments=payments, arrears=arrears_rows,
             inspections=inspections, feedback=feedback, tickets=tickets, applications=applications, app_docs=app_docs, bundles=bundles, tasks=tasks,
             letters=letters, key=key)
    M["idx"] = dict(unit=unit_by_id, tenancy=tenancy_by_id, tenant=tenant_by_id, staff=STAFF_BY_ID,
                    app={a["application_id"]: a for a in applications})
    return M


FB_TEMPLATES = {
    "STR": ["Concrete spalling from ceiling outside {shop} at Blk {blk} {street} {unit}. Pieces fell near the walkway this morning, very dangerous for elderly.",
            "There is a long crack on the column beside {unit} Blk {blk}. Getting bigger over the past month. Please check if structure is safe.",
            "Plaster falling off the beam above the shop {shop}, {street}. Shop owner already cordoned off with chairs."],
    "SEP": ["Ceiling leaking inside {shop} ({unit}) whenever it rains. Water stains and some stock damaged.",
            "Water seepage from the wall between {unit} and next unit at Blk {blk}. Wall paint peeling, smells musty.",
            "Roof slab above Blk {blk} {unit} leaking into shop. Have reported twice before!!"],
    "PLB": ["Floor trap at the back of {shop} choked, dirty water overflowing to common corridor Blk {blk}.",
            "Burst pipe near {unit} {street}, water gushing out. Please send plumber asap.",
            "Toilet at rear of Blk {blk} shops (near {unit}) cannot flush, pipe leaking."],
    "ELE": ["Power keeps tripping for the row of shops at Blk {blk} incl {shop}. Fridges affected, food spoiling.",
            "Exposed wiring hanging from ceiling outside {unit} Blk {blk} {street}. Children walk past here.",
            "Corridor lights in front of {shop} not working for a week, very dark at night, unsafe."],
    "FIR": ["Fire exit at rear of Blk {blk} near {unit} blocked by boxes from {shop}.",
            "Smell of burning and smoke from {shop} {unit}, Blk {blk}. Fire engine came.",
            "Hose reel cabinet near {unit} missing cover and hose damaged."],
    "PST": ["Many rats running around the bin area behind {shop}, Blk {blk}.", "Cockroach infestation along the drains in front of {unit} {street}.",
            "Termites found eating the door frame of {shop} ({unit})."],
    "HYG": ["{shop} leaves rubbish bags outside the shop overnight, smelly and attracts flies. Blk {blk}.",
            "Strong grease smell from {shop} kitchen exhaust, residents above complaining.", "Shopfront of {unit} Blk {blk} very dirty, oil stains on the floor."],
    "ENC": ["{shop} displaying goods all the way into the walkway at Blk {blk}, wheelchair cannot pass.",
            "Tables and chairs of {shop} occupying the corridor, {street}.", "Racks of {shop} ({unit}) placed beyond the yellow line, blocking pedestrians."],
    "NOI": ["{shop} at Blk {blk} operating till 2am with loud music. Residents cannot sleep.", "Karaoke noise from {unit} {street} every night.",
            "Delivery lorry unloading at 5am for {shop}, very noisy."],
    "CMN": ["Common corridor at Blk {blk} near {unit} not cleaned for days.", "Lift lobby lights near the shops at Blk {blk} faulty.",
            "Litter and stains along the 5-foot way at {street} Blk {blk}."],
    "OTH": ["How do I apply to rent a shop at Blk {blk} {street}? Saw a unit vacant.", "Would like to compliment the staff of {shop} for being helpful.",
            "When is the next tender for shops in this estate? Interested in {street}."],
}
AMBIGUOUS = [
    "Something wrong with {shop} at Blk {blk}, water and smell all over the back lane. Please look into it.",
    "The area near {unit} {street} is in bad condition. Lights, dirt, everything. Fix pls.",
    "Ceiling near {shop} wet and lights flickering, scared got short circuit.",
    "{shop} renovation very noisy and dust everywhere, also something cracked on the wall??",
]
TYPOS = [("please", "pls"), ("the ", "teh "), ("leaking", "leakng"), ("because", "bcos"), ("very", "v"), ("water", "watr")]


def feedback_text(rng, code, u, shop, ambiguous):
    tpl = rng.choice(AMBIGUOUS if ambiguous else FB_TEMPLATES[code])
    s = tpl.format(shop=shop, blk=u["blk"], street=u["street"], unit=u["unit_no"])
    if rng.random() < 0.15:
        a, b = rng.choice(TYPOS)
        s = s.replace(a, b, 1)
    if rng.random() < 0.1:
        s = s.upper()
    return s
