"""
Registration file for `deployed_candidate_coi_masked_scoped`.
Satellite table, RBAC-scoped via join to deployed_candidates. Per the
confirmed design decision: no separate access gate beyond ordinary row
scope, but masked the same way every other contact field in this
schema is (partial email, truncated phone, full LinkedIn redaction).
"""

from tables.base import TableSpec, Example

TABLE = TableSpec(
    name="deployed_candidate_coi_masked_scoped",
    description="""
Table: deployed_candidate_coi_masked_scoped
(RBAC-scoped via join to deployed_candidates internally. Masked:
reporting_manager_email/client_tag_poc_email to first-2-chars+****@domain,
reporting_manager_phone/client_tag_poc_phone to first-3-digits+XXXXX,
reporting_manager_linkedin/client_tag_poc_linkedin fully redacted (NULL).)

PURPOSE: "Circle of Influence" -- contacts on the CLIENT SIDE connected
to this candidate's placement. IMPORTANT DISTINCTION: every person in
this table works for the CLIENT COMPANY, not for VDart -- this is NOT
the candidate's own contact info (that's in deployed_candidates_masked_scoped)
and NOT a VDart recruiter/account manager/BU head (those are also on
the main table). Two distinct client-side contacts are tracked:
  - reporting_manager_* -- the candidate's actual day-to-day manager
    at the client.
  - client_tag_poc_* -- the client's own designated point of contact
    for this engagement (may or may not be the same person as the
    reporting manager).

Columns:
- id (int, PK), deployed_candidate_id (int) -- JOIN KEY:
  JOIN deployed_candidates_masked_scoped ON
  deployed_candidate_id = deployed_candidates_masked_scoped.id
- candidate_connected_date, candidate_connected_comments -- when/how
  VDart connected with the candidate about this COI relationship.
- reporting_manager_name, reporting_manager_email (MASKED),
  reporting_manager_phone (MASKED), reporting_manager_location,
  reporting_manager_linkedin (always NULL, fully redacted)
- reporting_comments, reporting_manager_connected_date
- client_tag_poc_name, client_tag_poc_email (MASKED),
  client_tag_poc_phone (MASKED), client_tag_poc_location,
  client_tag_poc_linkedin (always NULL, fully redacted)
- client_tag_poc_connected_date, client_tag_poc_comments

Notes for writing SQL:
- Always use table name `deployed_candidate_coi_masked_scoped`.
- Never confuse reporting_manager_name / client_tag_poc_name with
  recruiter_name, bu_head, or any other VDart-internal person on the
  main table -- these are always client-side people.
- Never write SELECT *.
""".strip(),
    examples=(
        Example(
            question="Who is the reporting manager for candidates at Accenture?",
            sql=(
                "SELECT dc.candidate_name, coi.reporting_manager_name, coi.reporting_manager_email "
                "FROM deployed_candidate_coi_masked_scoped coi "
                "JOIN deployed_candidates_masked_scoped dc ON coi.deployed_candidate_id = dc.id "
                "WHERE dc.is_real_candidate = 1 AND dc.client = 'Accenture'"
            ),
        ),
    ),
)