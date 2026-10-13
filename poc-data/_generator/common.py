"""Registry and shared helpers used by every content module."""
import datetime as dt
from collections import Counter

from master import ASOF, GST, LATE_INTEREST_PA, STAFF_BY_ID, TOWN_BY_CODE

D = dt.date
ARTS = []


def register(id, path, type, title, author, date, purpose, questions, fn, recipients="", entities=(), flags=""):
    ARTS.append(dict(id=id, path=path, type=type, title=title, author=author, recipients=recipients, date=str(date),
                     entities_referenced=";".join(entities), purpose=purpose, test_questions=questions, flags=flags, fn=fn))


def staff(sid):
    return STAFF_BY_ID[sid]


def sname(sid):
    return STAFF_BY_ID[sid]["name"]


def money(x, cents=True):
    return f"S${x:,.2f}" if cents else f"S${x:,.0f}"


def fd(d):
    return f"{d.day} {d:%b %Y}"


def fdl(d):
    return f"{d.day} {d:%B %Y}"


def addr(u):
    return f"Blk {u['blk']} {u['street']} {u['unit_no']} Singapura {u['postal']}"


def town_name(code):
    return TOWN_BY_CODE[code]["name"]


def k(M, name):
    return M["key"][name]


def tenancy(M, tid):
    return M["idx"]["tenancy"][tid]


def tenant(M, tid):
    return M["idx"]["tenant"][tid]


def unit(M, uid):
    return M["idx"]["unit"][uid]


def scripted(M, name):
    """Return (tenant, tenancy, unit) for a scripted key tenant."""
    kk = M["key"][name]
    return tenant(M, kk["tenant"]), tenancy(M, kk["tenancy"]), unit(M, kk["unit"])


def arrears_asof(M, d):
    """Arrears per tenancy as at date d (invoices due on/before d, unpaid at d)."""
    out = {}
    for inv in M["invoices"]:
        if inv["due_date"] > d:
            continue
        pdate = inv.get("paid_date")
        if pdate is not None and pdate <= d:
            continue
        r = out.setdefault(inv["tenancy_id"], dict(tenancy_id=inv["tenancy_id"], tenant_id=inv["tenant_id"], amount=0.0, invoices=0, oldest_due=inv["due_date"]))
        r["amount"] += inv["total_amount"]
        r["invoices"] += 1
        r["oldest_due"] = min(r["oldest_due"], inv["due_date"])
    for r in out.values():
        r["amount"] = round(r["amount"], 2)
        r["days_overdue"] = (d - r["oldest_due"]).days
        days = r["days_overdue"]
        r["bucket"] = "0-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else ">90"
        ta = M["idx"]["tenancy"][r["tenancy_id"]]
        r["months_of_rent"] = round(r["amount"] / (ta["monthly_rent"] * (1 + GST)), 2)
        r["unit_id"] = ta["unit_id"]
    return sorted(out.values(), key=lambda r: -r["amount"])


def late_interest(amount, days):
    return round(amount * LATE_INTEREST_PA * days / 365, 2)


def vacancy_asof(M, d, include_tender=False):
    """Vacancy counts by town as at d. Units in a non-tenanted status since <= d."""
    c = Counter()
    tender = Counter()
    nl = Counter()
    total = Counter()
    for u in M["units"]:
        total[u["town"]] += 1
        since = u.get("vacant_since")
        if since is None or since > d:
            continue
        if u["status"] == "Vacant":
            c[u["town"]] += 1
        elif u["status"] == "Under Tender":
            tender[u["town"]] += 1
        elif u["status"] == "Not Lettable":
            nl[u["town"]] += 1
    if include_tender:
        c = c + tender
    return dict(vacant=c, tender=tender, not_lettable=nl, total=total)


def active_on(M, d):
    return [t for t in M["tenancies"] if t["start_date"] <= d <= t["end_date"] and t["status"] in ("Active", "Renewed", "Expired", "Terminated")
            and (t["status"] == "Active" or t["end_date"] >= d)]


def iso(o):
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    return o


def email_of(x):
    """'S03' -> 'Nurul Huda Rahman <nurul.huda@...>'; tuples pass through."""
    if isinstance(x, str) and x in STAFF_BY_ID:
        s = STAFF_BY_ID[x]
        return f"{s['name']} <{s['email']}>"
    if isinstance(x, tuple):
        return f"{x[0]} <{x[1]}>"
    return x


ASOF = ASOF
