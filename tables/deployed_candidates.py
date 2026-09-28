"""
Registration file for `deployed_candidates_masked_scoped` -- the
replacement for CMP's old `candidates_masked_scoped` (staffing_db_v2),
now pointing at the mdm_chatbot database's deployed_candidates table
cluster. This is a FULL CUTOVER, not a second parallel data source --
once this file (and its 5 satellite-table siblings) are registered,
the OLD candidates_masked_scoped.py registration file should be
REMOVED from tables/ entirely, so the LLM's schema prompt doesn't carry
two overlapping, confusing descriptions of "the candidates table."

CONFIRMED SCHEMA IMPROVEMENTS vs. the old CMP table (verified via
SHOW CREATE TABLE, not carried over as assumptions):
  - Real `id` INT UNSIGNED primary key -- the old table never had a
    clean PK, which made some joins/lookups awkward. Now: none of
    that hackery is needed, and every satellite table joins cleanly
    on `deployed_candidate_id = id`.
  - pay_rate/client_rate are DECIMAL(10,2) directly -- NOT messy TEXT.
    None of the old pay_rate_numeric cleanup, lakh-comma-parsing, or
    "X | Y" ambiguous-format issues apply here at all. Use pay_rate/
    client_rate directly in any SUM/AVG -- no derived _numeric column
    exists or is needed.
  - `is_real_candidate` (1=real, 0=test/import) exists specifically so
    test/import rows never accidentally get counted as real business
    data -- see the mandatory default filter below.
  - `candidate_added_source` records which system a row originated
    from ('CMP', 'PMT', 'MDM', 'IMPORT', 'API') -- useful context, but
    NOT itself something to filter on unless a question explicitly
    asks about data provenance/source system.

CARRIED FORWARD FROM THE OLD SCHEMA AS A STARTING HYPOTHESIS, NOT YET
RE-VERIFIED (this snapshot has only 2 real test rows -- real volume
doesn't exist yet to confirm or refute any of these against real data.
Treat every "real, verified bug" style callout below from the OLD
system as historical context for why the rule exists, not as a
confirmed fact about THIS table's real data. Re-verify each one once
real volume flows in):
  - recruiter_name may contain non-recruiter process codes (the old
    system's confirmed list was 'PT', 'PTR', 'TBD', 'NA', 'Vendor
    Change', 'Vendor consolidation', 'Redeployement', 'Redeployment')
    -- unconfirmed whether the SAME codes appear here; flag any
    recruiter breakdown as a caveat the same way, but don't assume
    this exact list is complete for this table until checked.
  - Fiscal quarter/year definitions (calendar Q1-Q4, "last year" means
    previous calendar year, never hardcode a literal year) -- same
    logic almost certainly applies, business calendar doesn't change
    per-system, but not separately reconfirmed here.
  - Margin calculation: compute live as (client_rate - pay_rate), never
    trust a stored margin_value blindly, group by currency + payment
    basis together, never blend across them -- SAME risk profile as
    before (this table also has an `is_real_candidate`-style provenance
    problem waiting to happen with margin_value specifically: its
    exact business definition here (percentage vs. dollar amount,
    decimal(5,2) suggests a percentage under 1000) is NOT YET
    CONFIRMED with the business for this new schema -- treat any
    direct use of the stored margin_value column with real caution
    until that's confirmed, same as the old system's "may be stale"
    caveat, but for a different underlying reason here.
"""

from tables.base import TableSpec, Example

TABLE = TableSpec(
    name="deployed_candidates_masked_scoped",
    description="""
Table: deployed_candidates_masked_scoped
(Masked, RBAC-scoped view. candidate_phone/vendor_contact_number are
masked to first-3-digits+XXXXX. candidate_email/vendor_contact_email/
bu_head_emailid are masked to first-2-chars+****@domain.
account_managers is a comma-separated list, each entry masked the same
way. dob and linkedin_url are FULLY redacted (NULL) -- no partial-mask
form exists for either that doesn't remain identifying.)

MANDATORY DEFAULT FILTER -- READ THIS FIRST: unless a question
EXPLICITLY asks about test data, import data, or "non-real" candidates,
every query against this table MUST include
`AND is_real_candidate = 1` in its WHERE clause. This column exists
specifically to keep test/import rows out of real business counts --
omitting this filter risks silently inflating/deflating a real count
with test rows. Only drop this filter if the question explicitly asks
about test/import/non-real records.

Columns:
- id (int, PK) -- the join key every satellite table
  (deployed_candidate_lifecycle_masked_scoped,
  deployed_candidate_extension_scoped,
  deployed_candidate_feedback_scoped,
  deployed_candidate_project_scoped,
  deployed_candidate_coi_masked_scoped) references via
  `deployed_candidate_id = id`. See each satellite table's own
  registration for its specific join guidance and what it adds.
- is_real_candidate (tinyint) -- see MANDATORY DEFAULT FILTER above.
- candidate_added_source (text) -- 'CMP' | 'PMT' | 'MDM' | 'IMPORT' | 'API'.
  Only filter on this if a question explicitly asks about data
  provenance/source system -- never filter on it for an ordinary
  candidate-count/breakdown question.
- status (text) -- 'Active'/'Inactive' equivalent; confirm exact values
  present once real data exists (this snapshot's 2 test rows may not
  cover the full real value set).
- plc_code, sap_id (text) -- internal reference codes.
- candidate_name (text) -- use LIKE '%<name>%' fuzzy matching, never
  exact `=`, and always include candidate_name in the SELECT so the
  matched value is visible -- same name-formatting-variance risk as
  any real personnel data. If a LIKE search returns more than one
  distinct name, list them and ask which one was meant rather than
  guessing or combining.
- candidate_phone, candidate_email (MASKED, see above)
- dob (always NULL, fully redacted)
- linkedin_url (always NULL, fully redacted)
- certifications (text)
- client, client_track, end_client (text) -- "candidates with <company>"
  means WHERE client = '<company>', never a skills-column search.
- job_title (text)
- primary_skills, secondary_skills (text) -- LIKE-match for
  technology/tool names only, never a company name.
- start_date, end_date (date) -- end_date NULL for active candidates
  (no end date yet). A plain "rolloff" question (no qualifying word)
  means end_date <= CURDATE(), and is a SIMPLE fact question
  (is_insight should be false for it).
- sow_end_date (date) -- the PLANNED end date. Use this, not end_date,
  for any FORWARD-LOOKING "ending soon"/"upcoming rolloff" question --
  end_date is NULL for active candidates, so filtering by end_date for
  a future window always incorrectly returns zero.
- sow_end_month (datetime) -- despite the name, stores a full
  datetime, not a month label (e.g. '2027-01-01 00:00:00') -- appears
  to represent sow_end_date rounded/truncated to the start of its
  month. Not yet confirmed with the business exactly how this differs
  in meaning from sow_end_date itself -- prefer sow_end_date for any
  precise date question; only use sow_end_month if a question
  specifically asks about month-level grouping and sow_end_date proves
  insufficient.
- extended_sow_date (date) -- the SOW end date after an extension was
  applied, when one exists. If a candidate has been extended, this is
  the new planned end date superseding the original sow_end_date --
  prefer this over sow_end_date for "when is this candidate now
  scheduled to end" if extended_sow_date is not NULL.
- "UNEXPECTED rolloff" -- a candidate whose end_date is earlier than
  sow_end_date (early exit vs. plan):
  end_date IS NOT NULL AND sow_end_date IS NOT NULL AND end_date < sow_end_date
  The word "unexpected" must be explicitly present (or clearly implied
  by history) for this definition to apply -- a plain "rolloff" with no
  qualifying word always means the plain end_date <= CURDATE() definition.
- contractor_status (text) -- e.g. 'C2C'.
- contractor_vendor_name, vendor_contact_person (text)
- vendor_contact_number, vendor_contact_email (MASKED, see above)
- project_city, project_state (text) -- project_state likely stores
  2-letter US state abbreviations, same convention as the old system
  (e.g. 'TX' not 'Texas') -- convert a full state name to its
  abbreviation before filtering, but confirm this convention holds
  once real data exists (only 2 test rows currently).
- project_country (text)
- pay_rate_currency, pay_rate, pay_rate_payment_basis -- pay_rate is a
  CLEAN DECIMAL(10,2), use directly, no _numeric cleanup needed (see
  module docstring's "CONFIRMED SCHEMA IMPROVEMENTS").
  CRITICAL: never AVG/SUM pay_rate without GROUP BY pay_rate_currency
  AND pay_rate_payment_basis together -- blending hourly and
  monthly/annual figures, or blending currencies, produces a
  meaningless number regardless of how clean the underlying values are.
- client_rate_currency, client_rate, client_rate_payment_basis -- same
  rules as pay_rate. RESTRICTED: NULL for any login without
  can_view_restricted -- if a question needs these, expect the query
  to be rejected outright for a scoped login (this is expected,
  correct behavior, not a bug to work around).
- margin_value (decimal(5,2), RESTRICTED) -- see module docstring's
  caution on this column's definition not yet being confirmed for this
  new schema. For ANY margin question, calculate live as
  (client_rate - pay_rate) rather than trusting this stored column,
  and only where pay_rate_currency = client_rate_currency AND
  pay_rate_payment_basis = client_rate_payment_basis.
- dal_name, dm_name, add_name, bu_head, cal_name, passthrough_owner,
  passthrough_support, lead_recruiter, team_lead_name (text)
- bu_head_emailid (MASKED, see above)
- recruiter_name (text) -- use LIKE '%<name>%' fuzzy matching (never
  exact `=`), always include recruiter_name in the SELECT/GROUP BY so
  the matched value is visible. May contain non-recruiter process
  codes -- see module docstring; flag any recruiter breakdown that
  includes obviously-non-name values as a data-quality caveat rather
  than presenting them as ordinary recruiters.
- recruiter_emp_id, deal_pt_ptr (text)
- client_project_manager, client_resource_manager (text)
- account_managers (text, MASKED per-entry) -- comma-separated list of
  account manager emails. "My candidates"/"my clients" for an
  account_manager-scoped login means this column already filtered
  their access invisibly at the database level -- NEVER add a WHERE
  filter for "my"/"our", and NEVER invent a placeholder value like
  WHERE client = 'YourClientName' for it. See the general "my/our"
  rule in the system prompt -- it applies identically here.
- created_at, updated_at, created_by, updated_by -- created_by/
  updated_by are bare numeric IDs with no resolvable name (the users
  table is deliberately not part of this chatbot's database at all) --
  don't attempt to resolve them to a name, and don't treat them as
  meaningful without an explicit reason to.

Notes for writing SQL:
- Always use table name `deployed_candidates_masked_scoped` -- never
  `deployed_candidates` (the raw table) or `deployed_candidates_scoped`
  (the unmasked intermediate layer) -- neither is on the allow-list.
- Never write SELECT * -- name specific relevant columns (see the
  general column-selection rule in the system prompt).
- Only SELECT statements.
""".strip(),
    examples=(
        Example(
            question="How many candidates do we have in total?",
            sql="SELECT COUNT(*) FROM deployed_candidates_masked_scoped WHERE is_real_candidate = 1",
        ),
        Example(
            question="How many candidates do we have with Accenture?",
            sql="SELECT COUNT(*) FROM deployed_candidates_masked_scoped WHERE is_real_candidate = 1 AND client = 'Accenture'",
        ),
        Example(
            question="How many roll offs does HCL have?",
            sql=(
                "SELECT COUNT(*) FROM deployed_candidates_masked_scoped "
                "WHERE is_real_candidate = 1 AND client = 'HCL' "
                "AND end_date IS NOT NULL AND end_date <= CURDATE()"
            ),
        ),
        Example(
            question="Which clients give us the best margins?",
            sql=(
                "SELECT client, pay_rate_currency, pay_rate_payment_basis, "
                "AVG(client_rate - pay_rate) AS avg_margin, COUNT(*) AS candidate_count "
                "FROM deployed_candidates_masked_scoped "
                "WHERE is_real_candidate = 1 "
                "AND pay_rate_currency = client_rate_currency "
                "AND pay_rate_payment_basis = client_rate_payment_basis "
                "AND client IS NOT NULL AND client != '' "
                "GROUP BY client, pay_rate_currency, pay_rate_payment_basis "
                "HAVING COUNT(*) >= 3 "
                "ORDER BY avg_margin DESC"
            ),
        ),
        Example(
            question="How many candidates does each recruiter have?",
            sql=(
                "SELECT COALESCE(recruiter_name, 'Unassigned') AS recruiter, "
                "COUNT(*) AS candidate_count FROM deployed_candidates_masked_scoped "
                "WHERE is_real_candidate = 1 "
                "GROUP BY recruiter_name ORDER BY candidate_count DESC"
            ),
        ),
        Example(
            question="How many candidates in Vinay's BU are ending in the next 60 days?",
            sql=(
                "SELECT COUNT(*) FROM deployed_candidates_masked_scoped "
                "WHERE is_real_candidate = 1 AND bu_head = 'Vinay' "
                "AND sow_end_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 60 DAY)"
            ),
        ),
        Example(
            question="How many candidates do we have in total, broken down by BU?",
            sql=(
                "SELECT COALESCE(bu_head, 'Unassigned') AS bu, COUNT(*) AS candidate_count "
                "FROM deployed_candidates_masked_scoped "
                "WHERE is_real_candidate = 1 "
                "GROUP BY bu_head ORDER BY candidate_count DESC"
            ),
        ),
        Example(
            question="How many roll offs do we have, broken down by BU?",
            sql=(
                "SELECT COALESCE(bu_head, 'Unassigned') AS bu, COUNT(*) AS candidate_count "
                "FROM deployed_candidates_masked_scoped "
                "WHERE is_real_candidate = 1 "
                "AND end_date IS NOT NULL AND end_date <= CURDATE() "
                "GROUP BY bu_head ORDER BY candidate_count DESC"
            ),
        ),
    ),
)