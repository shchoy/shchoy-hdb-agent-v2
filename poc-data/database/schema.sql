-- PLG Records (fictional) - relational schema for the POC database export
-- Engine: PostgreSQL-compatible DDL. CSV files in this folder are one per table.

CREATE TABLE staff (staff_id VARCHAR(4) PRIMARY KEY, name TEXT NOT NULL, title TEXT, dept TEXT, email TEXT UNIQUE, phone TEXT);
CREATE TABLE towns (town_code CHAR(2) PRIMARY KEY, town_name TEXT NOT NULL, region TEXT, town_council TEXT, estate_manager_id VARCHAR(4) REFERENCES staff);
CREATE TABLE neighbourhood_centres (nc_id VARCHAR(8) PRIMARY KEY, town_code CHAR(2) REFERENCES towns, nc_name TEXT);
CREATE TABLE blocks (block_id VARCHAR(8) PRIMARY KEY, town_code CHAR(2) REFERENCES towns, blk INT, street TEXT, nc_id VARCHAR(8) REFERENCES neighbourhood_centres,
                     postal_code CHAR(6), year_built INT);
CREATE TABLE trades (trade TEXT PRIMARY KEY, trade_group TEXT, allowed_unit_types TEXT);
CREATE TABLE units (unit_id VARCHAR(16) PRIMARY KEY, block_id VARCHAR(8) REFERENCES blocks, unit_no VARCHAR(8), unit_type TEXT, floor_area_sqm NUMERIC(6,1),
                    status TEXT CHECK (status IN ('Tenanted','Vacant','Under Tender','Not Lettable')), vacant_since DATE);
CREATE TABLE tenants (tenant_id VARCHAR(8) PRIMARY KEY, name TEXT NOT NULL, brn VARCHAR(12), entity_type TEXT, contact_person TEXT, email TEXT, phone TEXT,
                      registered_since DATE);
CREATE TABLE tenancies (tenancy_id VARCHAR(16) PRIMARY KEY, unit_id VARCHAR(16) REFERENCES units, tenant_id VARCHAR(8) REFERENCES tenants,
                        trade TEXT REFERENCES trades, start_date DATE, end_date DATE, monthly_rent NUMERIC(10,2), security_deposit NUMERIC(10,2),
                        status TEXT, rent_basis TEXT);
CREATE TABLE rent_invoices (invoice_id VARCHAR(16) PRIMARY KEY, tenancy_id VARCHAR(16) REFERENCES tenancies, period CHAR(7), invoice_date DATE, due_date DATE,
                            rent_amount NUMERIC(10,2), gst_amount NUMERIC(10,2), total_amount NUMERIC(10,2), status TEXT);
CREATE TABLE payments (payment_id VARCHAR(12) PRIMARY KEY, invoice_id VARCHAR(16) REFERENCES rent_invoices, tenancy_id VARCHAR(16) REFERENCES tenancies,
                       paid_date DATE, amount NUMERIC(10,2), method TEXT);
CREATE TABLE inspections (inspection_id VARCHAR(12) PRIMARY KEY, unit_id VARCHAR(16) REFERENCES units, tenancy_id VARCHAR(16) REFERENCES tenancies,
                          inspection_date DATE, officer_id VARCHAR(4) REFERENCES staff, inspection_type TEXT, finding_code TEXT, outcome TEXT,
                          follow_up_due DATE, closed_date DATE, remarks TEXT);
CREATE TABLE feedback_cases (feedback_id VARCHAR(14) PRIMARY KEY, received_date DATE, channel TEXT, unit_id VARCHAR(16) REFERENCES units, description TEXT,
                             category_code CHAR(3), severity TEXT, assigned_team TEXT, status TEXT, iems_ticket_id VARCHAR(16), officer_id VARCHAR(4) REFERENCES staff,
                             reply_due DATE, replied_date DATE);
CREATE TABLE iems_tickets (ticket_id VARCHAR(16) PRIMARY KEY, feedback_id VARCHAR(14) REFERENCES feedback_cases, created_date DATE, unit_id VARCHAR(16) REFERENCES units,
                           category_code CHAR(3), team TEXT, vendor TEXT, priority TEXT, sla_days INT, status TEXT, completed_date DATE, sla_met BOOLEAN);
CREATE TABLE applications (application_id VARCHAR(12) PRIMARY KEY, app_type TEXT, tenancy_id VARCHAR(16) REFERENCES tenancies, tenant_id VARCHAR(8) REFERENCES tenants,
                           unit_id VARCHAR(16) REFERENCES units, submitted_date DATE, status TEXT, officer_id VARCHAR(4) REFERENCES staff, decision_date DATE,
                           proposed_trade TEXT, remarks TEXT);
CREATE TABLE application_documents (application_id VARCHAR(12) REFERENCES applications, doc_code VARCHAR(8), doc_label TEXT, mandatory BOOLEAN, submitted BOOLEAN,
                                    received_date DATE, verified BOOLEAN, PRIMARY KEY (application_id, doc_code));
CREATE TABLE tasks (task_id VARCHAR(12) PRIMARY KEY, task_type TEXT, title TEXT, related_id VARCHAR(16), assignee_id VARCHAR(4) REFERENCES staff, created_date DATE,
                    due_date DATE, status TEXT, safety_flag BOOLEAN, revenue_at_risk NUMERIC(12,2), tenants_affected INT);
CREATE TABLE letters (letter_id VARCHAR(14) PRIMARY KEY, letter_date DATE, template_id VARCHAR(12), letter_type TEXT, reference_id VARCHAR(16),
                      tenant_id VARCHAR(8) REFERENCES tenants, author_id VARCHAR(4) REFERENCES staff, channel TEXT);

CREATE INDEX ix_units_block ON units(block_id);
CREATE INDEX ix_units_status ON units(status);
CREATE INDEX ix_tenancies_unit ON tenancies(unit_id);
CREATE INDEX ix_tenancies_tenant ON tenancies(tenant_id);
CREATE INDEX ix_tenancies_end ON tenancies(end_date);
CREATE INDEX ix_invoices_tenancy ON rent_invoices(tenancy_id, due_date);
CREATE INDEX ix_payments_invoice ON payments(invoice_id);
CREATE INDEX ix_inspections_unit ON inspections(unit_id, inspection_date);
CREATE INDEX ix_feedback_unit ON feedback_cases(unit_id, received_date);
CREATE INDEX ix_tickets_feedback ON iems_tickets(feedback_id);
CREATE INDEX ix_apps_tenant ON applications(tenant_id);
CREATE INDEX ix_tasks_assignee ON tasks(assignee_id, status, due_date);

-- NOTE: the export intentionally contains data-quality issues for testing (see _report.md):
--   duplicate tenant (same BRN), NULL emails/floor areas, an outlier rent, a far-future inspection date, a duplicated payment row.
--   The duplicated payment row violates the payments PK on purpose; load with a staging table or DuckDB read_csv.
