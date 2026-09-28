"""
Registration file for `deployed_candidate_lifecycle_masked_scoped`.
Satellite table -- has no account_managers/bu_head/recruiter_name
column of its own, so RBAC scoping happens by joining back to
deployed_candidates_scoped (confirmed design decision) rather than
independently. This view already has that join baked in (see the SQL
that defines it) -- from the LLM's point of view, this view ALREADY
only shows rows belonging to candidates the current login can see; no
additional join is needed for access control, only for combining data
with the main table's own columns when a question needs both.
"""

from tables.base import TableSpec, Example

TABLE = TableSpec(
    name="deployed_candidate_lifecycle_masked_scoped",
    description="""
Table: deployed_candidate_lifecycle_masked_scoped
(RBAC-scoped via join to deployed_candidates internally -- this view's
rows are already restricted to candidates the current login can see.)

PURPOSE: one row per LIFECYCLE EVENT for a candidate -- onboarding,
offboarding, extension, roll-off, sent-to-RD, redeployment -- each
carrying a snapshot of relevant values AS THEY WERE AT THAT MOMENT.
This is the right table for any "as of [past date/event]" or
historical-snapshot question -- unlike the main table (which only ever
holds CURRENT state), this table preserves what was true at each
individual event.

Columns:
- id (int, PK), deployed_candidate_id (int) -- JOIN KEY. To combine
  with the main table's current-state columns (e.g. candidate_name),
  JOIN deployed_candidates_masked_scoped ON
  deployed_candidate_id = deployed_candidates_masked_scoped.id
- event_type (text) -- one of: 'onboarded', 'offboarded', 'extended',
  'rolled_off', 'sent_to_rd', 'redeployed'. Filter on this exact set of
  values for any "how many were onboarded/offboarded/etc." question.
- event_date (date) -- when this event occurred.
- effective_from, effective_to (date) -- the start/end of the cycle
  this event record describes.
- onboard_date, onboard_plc_code, onboard_client, onboard_end_client,
  onboard_job_title (various) -- the candidate's situation AT
  ONBOARDING time -- use these, not the main table's current client/
  job_title, for any "what was X when they onboarded" question.
- onboard_pay_rate, onboard_client_rate (decimal, RESTRICTED) -- same
  restricted-column gating as the main table's pay_rate/client_rate.
  Rejected outright for a login without can_view_restricted.
- onboard_project_city, onboard_project_state, onboard_project_country
- offboard_date, offboard_reason (text), last_working_date
- extension_date, extension_duration, extension_cycle_number (which
  extension cycle this is -- 1st, 2nd, etc.), extension_comments
- rolloff_date, rolloff_reason (text)
- sow_end_date, extended_sow_date -- the planned end date at that
  point, and any extended version of it.
- sent_to_rd (tinyint), sent_to_rd_date -- whether/when sent to the
  redeployment/bench pool.
- status_at_event (text) -- the candidate's overall status AT THE TIME
  of this event -- use this, not the main table's current status, for
  "what was their status when X happened" questions.
- recruiter_name, dal_name, dm_name, bu_name (text) -- who was assigned
  AT THAT POINT IN TIME. NOTE: these may differ from the main table's
  CURRENT recruiter_name/bu_head if an assignment has changed since --
  that's expected, not a data inconsistency.
- remarks (text)

Notes for writing SQL:
- Always use table name `deployed_candidate_lifecycle_masked_scoped`.
- For "how many candidates were onboarded/rolled off in [period]"
  questions, filter event_type + event_date -- this is the correct
  table for that, not counting the main table's start_date/end_date.
- Never write SELECT *.
""".strip(),
    examples=(
        Example(
            question="How many candidates were onboarded this quarter?",
            sql=(
                "SELECT COUNT(*) FROM deployed_candidate_lifecycle_masked_scoped "
                "WHERE event_type = 'onboarded' "
                "AND event_date >= CONCAT(YEAR(CURDATE()), '-', LPAD(3*(QUARTER(CURDATE())-1)+1, 2, '0'), '-01') "
                "AND event_date <= CURDATE()"
            ),
        ),
        Example(
            question="Show me the lifecycle history for candidates ending in the next 30 days",
            sql=(
                "SELECT dc.candidate_name, lc.event_type, lc.event_date, lc.remarks "
                "FROM deployed_candidate_lifecycle_masked_scoped lc "
                "JOIN deployed_candidates_masked_scoped dc ON lc.deployed_candidate_id = dc.id "
                "WHERE dc.is_real_candidate = 1 "
                "AND dc.sow_end_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY) "
                "ORDER BY dc.candidate_name, lc.event_date"
            ),
        ),
    ),
)