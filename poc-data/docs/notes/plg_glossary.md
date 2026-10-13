# PLG Glossary of Business Terms

_Team wiki page | Owner: Kelvin Goh (Ops Analytics) | Last edited 28 Apr 2026 | Source of truth for reporting definitions_

| Term | Definition | Notes / SQL hint |
|---|---|---|
| **Commercial unit** | A lettable premises managed by PLG (shop, eating house, kiosk, shop with living quarters, office). | `units` table |
| **Active tenancy** | A tenancy with `status = 'Active'` whose start_date <= reporting date <= end_date. | Pending Commencement tenancies are *committed*, not active |
| **Committed tenancy** | Tender awarded / offer accepted, not yet commenced (`status = 'Pending Commencement'`). | Unit counted as tenanted for vacancy |
| **Vacant unit** | Lettable unit with no active or committed tenancy, **excluding units under tender**. | `units.status = 'Vacant'`. Definition changed April 2026 (Mgmt Mtg 4/2026 item 3). Before April, vacancy included units under tender. |
| **Under tender** | Vacant unit currently advertised in an open tender. | Reported separately |
| **Not lettable** | Unit earmarked for upgrading/redevelopment; excluded from occupancy denominator. | |
| **Occupancy rate** | Tenanted units / (total units - not lettable). | |
| **Rent** | Monthly rent excl. GST as per tenancy agreement. | `tenancies.monthly_rent` |
| **Arrears** | Unpaid invoice amounts (incl. GST) whose due date has passed. Interest excluded unless stated. | `rent_invoices` LEFT JOIN `payments` |
| **Days overdue** | Days since due date of the oldest unpaid invoice. | |
| **Arrears > 3 months** | Arrears amount > 3 x monthly_rent x 1.09. Termination threshold under POL-003 v2.0. | Not "3 unpaid invoices" |
| **Ageing bucket** | 0-30, 31-60, 61-90, >90 days overdue. | |
| **NC** | Neighbourhood Centre as designated in the NC register. | `blocks.nc_id` |
| **Trade group** | Grouping of trades for trade-mix analysis (POL-001 Annex A). | `trades` table |
| **Concentration limit** | Max 2 active units of the same trade per NC (3 for minimarts in NCs > 40 units). | |
| **Major breach** | Inspection outcome for UNAUTH_TRADE, UNAUTH_SUBLET, FIRE_SAFETY, STRUCTURAL_DEFECT. | |
| **SLA met (i-EMS)** | completed_date - created_date <= sla_days. | Misrouted tickets excluded |
| **Late renewal** | Renewal application submitted < 6 months before tenancy end date. | POL-002 cl. 4.2 / 4.4 |
