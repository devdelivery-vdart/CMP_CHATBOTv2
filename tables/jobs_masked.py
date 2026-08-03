"""
Registration file for the `jobs_masked` view.

Covers open/closed job requirements (synced from Ceipal). This is
separate from `candidates_masked` -- jobs represent DEMAND (open roles),
candidates represent SUPPLY (people placed/available). A question like
"how many open positions do we have" needs this table; "how many
candidates does recruiter X have" needs candidates_masked instead.

NOTE: the `requirements` table was checked and found to be completely
EMPTY (0 rows) -- it's not used, don't register or query it. `jobs` is
the real, populated table for requirement/job data (4,997 rows).
"""

from tables.base import TableSpec, Example

TABLE = TableSpec(
    name="jobs_masked",
    description="""
Table: jobs_masked
(This is a curated view of the `jobs` table -- ATS integration/sync
bookkeeping columns and a raw payload dump have been excluded, since they
have no business insight value. No columns in this view are PII-masked;
none of the fields here are person-level contact info like phone/email --
this table is about job requirements, not candidates.)

Represents job requirements/openings (both open and closed/filled),
synced from the Ceipal ATS system. This is DEMAND-side data -- how many
roles clients need filled -- as opposed to candidates_masked, which is
SUPPLY-side data -- the people available/placed.

Columns:
- job_pk (int) - unique internal id
- external_id (text) - Ceipal's external reference id
- job_code (text), ceipal_ref (text) - internal reference codes
- job_title (text), public_job_title (text)
- job_status (text) -- VERIFIED distinct values: 'Active', 'Closed',
  'Draft', 'Filled', 'Hold by Client', 'Hold by Manager', 'Open', 'Re-Open'.
  For "how many open positions" style questions, "open" means status IN
  ('Open', 'Active', 'Re-Open') -- NOT simply "anything except Closed/
  Draft" (that would incorrectly include Filled and both Hold statuses).
  'Hold by Client' / 'Hold by Manager' are NOT open and NOT closed --
  if relevant, mention them as a separate "on hold" count rather than
  including or silently excluding them without saying so.
- job_type (text), type_of_job (text)
- client (text) - client company name (same client names as in
  candidates_masked.client, in theory -- but these are separate tables,
  never JOIN them directly on client name without checking for spelling
  consistency first, the same way recruiter_name had spelling variants)
- end_client (text)
- client_job_id (text) - client's own reference id for this job
- client_manager_external_id, sales_manager_external_id,
  recruitment_manager_external_id, account_manager, assigned_to,
  primary_recruiter (text) -- internal staff assigned to this job.
  These are text names/ids, not verified against a master list -- expect
  the same kind of spelling inconsistency found in candidates_masked's
  recruiter_name field.
- country (text), state (text), city (text), zip_code (text), location (text)
- job_start_date (date), job_end_date (date)
- respond_by (int), turnaround_time (text)
- required_hours_week (int)
- duration (text), notice_period (text)
- remote_job (enum: 'Yes'/'No')
- expenses_paid (boolean 0/1)
- priority (text)
- interview_mode (text)
- clearance (text) - security clearance requirement, if any
- degree (text), experience (text) - education/experience requirements
- primary_skills (text), secondary_skills (text) -- free text, use LIKE
  for matching, same as candidates_masked.primary_skills
- languages (text)
- work_authorization (text) - required work authorization type
- number_of_positions (int) -- how many openings for this single job row
  (a job with number_of_positions=3 represents 3 openings, not 1 -- sum
  this column rather than counting rows, for "how many open positions"
  style questions)
- maximum_allowed_submissions (int)
- client_bill_rate_salary (text), pay_rate_salary (text) -- stored as
  TEXT, not numeric -- may contain ranges or non-numeric formatting, so
  aggregate math (AVG/SUM) may not work directly without cleaning
- tax_terms (text)
- business_unit (int), business_unit_internal (text), department (text)
- industry (text)
- client_category (text), client_type (text), client_track (text)
- business_entity (text)
- actual_team_name (text)
- dal (text)
- created_at (datetime), updated_at (datetime)

Notes for writing SQL:
- Always use table name "jobs_masked" -- never "jobs" (off-limits, query
  will be rejected).
- Only SELECT statements, same rules as candidates_masked.
- The `requirements` table is EMPTY and unused -- never query or JOIN to
  it, it will always return zero rows.
- Do not JOIN jobs_masked to candidates_masked unless explicitly asked to
  cross-reference demand vs supply -- there is no verified, reliable join
  key between them yet (client name matching has known spelling
  inconsistencies, same issue found with recruiter_name).
""".strip(),
    examples=(
        Example(
            question="How many open positions do we have right now?",
            sql=(
                "SELECT SUM(number_of_positions) AS open_positions "
                "FROM jobs_masked WHERE job_status IN ('Open', 'Active', 'Re-Open')"
            ),
        ),
        Example(
            question="Which clients have the most open job requirements?",
            sql=(
                "SELECT client, COUNT(*) AS open_jobs, SUM(number_of_positions) AS open_positions "
                "FROM jobs_masked WHERE job_status IN ('Open', 'Active', 'Re-Open') "
                "AND client IS NOT NULL AND client != '' "
                "GROUP BY client ORDER BY open_positions DESC"
            ),
        ),
        Example(
            question="How many jobs require Java?",
            sql=(
                "SELECT COUNT(*) FROM jobs_masked "
                "WHERE primary_skills LIKE '%Java%' OR secondary_skills LIKE '%Java%'"
            ),
        ),
    ),
)