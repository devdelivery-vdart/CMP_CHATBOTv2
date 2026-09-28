"""
Registration file for `deployed_candidate_extension_scoped`.
Satellite table, RBAC-scoped via join to deployed_candidates (same
design as the lifecycle table -- see that file's docstring).
"""

from tables.base import TableSpec, Example

TABLE = TableSpec(
    name="deployed_candidate_extension_scoped",
    description="""
Table: deployed_candidate_extension_scoped
(RBAC-scoped via join to deployed_candidates internally.)

PURPOSE: tracks the extension REQUEST/APPROVAL workflow for a
candidate's engagement -- separate from deployed_candidate_lifecycle's
'extended' event type, which just records that an extension happened;
this table tracks the process around deciding whether to extend.

Columns:
- id (int, PK), deployed_candidate_id (int) -- JOIN KEY, same pattern
  as every satellite table: JOIN deployed_candidates_masked_scoped ON
  deployed_candidate_id = deployed_candidates_masked_scoped.id
- extension_requested (tinyint) -- THREE-STATE, NOT a boolean:
  0 = pending, 1 = yes/approved, 2 = no/declined. Never treat this as
  a simple true/false -- a query checking "extension requested" must
  account for all three states explicitly if the question is ambiguous
  about which one it means.
- extension_status (text) -- free-form status text.
- poc_name (text) -- point of contact for this extension.
- extension_date, extension_duration, extension_comments
- no_extension_reason, pending_extension_reason (text)
- last_working_date (date)
- looking_for_opportunity (text)
- is_active (tinyint) -- 1 means this is the CURRENT/active extension
  record for this candidate. Use `WHERE is_active = 1` for "what is the
  current extension status" style questions -- a candidate can have
  multiple historical extension records, only one of which is active
  at a time.
- approved_by (bigint) -- numeric ID only, not resolvable to a name
  (users table not part of this database) -- don't attempt to resolve it.
- approved_at, approval_comments, approval_status
- contacted_with (text)
- extended_count (int) -- total number of times extended.
- last_extension_cycle, extension_cycle_count
- extension_data_cleared_at, extension_data_cleared_by

Notes for writing SQL:
- Always use table name `deployed_candidate_extension_scoped`.
- For "current" extension status questions, filter `is_active = 1`.
- Never write SELECT *.
""".strip(),
    examples=(
        Example(
            question="How many candidates have a pending extension request?",
            sql=(
                "SELECT COUNT(*) FROM deployed_candidate_extension_scoped "
                "WHERE extension_requested = 0 AND is_active = 1"
            ),
        ),
        Example(
            question="Which of my candidates have been extended more than twice?",
            sql=(
                "SELECT dc.candidate_name, ext.extended_count "
                "FROM deployed_candidate_extension_scoped ext "
                "JOIN deployed_candidates_masked_scoped dc ON ext.deployed_candidate_id = dc.id "
                "WHERE dc.is_real_candidate = 1 AND ext.extended_count > 2 AND ext.is_active = 1"
            ),
        ),
    ),
)